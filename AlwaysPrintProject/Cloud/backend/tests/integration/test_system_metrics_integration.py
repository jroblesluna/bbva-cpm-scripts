"""
Tests de integración del endpoint de métricas de escalabilidad.

Verifica el flujo completo del pipeline: HTTP request → colector → response,
incluyendo la integración con el scheduler y la persistencia en snapshots.

Los tests mockean las lecturas de /proc y la sesión de BD, pero validan
que toda la cadena funcione correctamente de extremo a extremo.

**Validates: Requirements 1.1, 7.1, 7.2, 6.2**
"""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints.system_metrics import router
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User, UserRole
from app.schemas.scalability_metrics import (
    DbPoolResponse,
    FileDescriptorResponse,
    NetworkTrafficResponse,
    PythonMemoryResponse,
    ScalabilityMetricsResponse,
    WebSocketMetricsResponse,
)
from app.services.scalability_metrics import ScalabilityMetricsCollector


# === DATOS DE FIXTURE PARA /proc ===

# Contenido realista de /proc/self/status
PROC_SELF_STATUS_CONTENT = """\
Name:\tpython3
Umask:\t0022
State:\tS (sleeping)
Tgid:\t1
Ngid:\t0
Pid:\t1
PPid:\t0
TracerPid:\t0
Uid:\t0\t0\t0\t0
Gid:\t0\t0\t0\t0
FDSize:\t256
Groups:\t0
VmPeak:\t  524288 kB
VmSize:\t  450000 kB
VmLck:\t       0 kB
VmPin:\t       0 kB
VmHWM:\t  262144 kB
VmRSS:\t  131072 kB
VmData:\t  200000 kB
VmStk:\t     136 kB
VmExe:\t    2048 kB
VmLib:\t   25000 kB
VmPTE:\t     500 kB
VmSwap:\t       0 kB
Threads:\t8
"""

# Contenido realista de /proc/net/dev
PROC_NET_DEV_CONTENT = """\
Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: 1234567   12345    0    0    0     0          0         0  1234567   12345    0    0    0     0       0          0
  eth0: 98765432  654321    0    0    0     0          0         0 45678901  321654    0    0    0     0       0          0
"""

# Contenido de /proc/self/fd simulado (lista de descriptores)
PROC_SELF_FD_ENTRIES = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]


# === FIXTURES ===


@pytest.fixture
def admin_user():
    """Usuario admin para los tests de integración."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "admin@system.com"
    user.role = UserRole.ADMIN
    user.organization_id = None
    return user


@pytest.fixture
def mock_db_session():
    """Sesión de BD mock con pool simulado."""
    session = MagicMock()
    return session


@pytest.fixture
def app_with_admin(admin_user, mock_db_session):
    """Aplicación FastAPI configurada con usuario admin y BD mock."""
    test_app = FastAPI()
    test_app.include_router(router, prefix="/system")
    test_app.dependency_overrides[get_current_user] = lambda: admin_user
    test_app.dependency_overrides[get_db] = lambda: mock_db_session
    yield test_app
    test_app.dependency_overrides.clear()


@pytest.fixture
def mock_connection_manager():
    """ConnectionManager mock con conteos realistas."""
    mock_cm = MagicMock()
    mock_cm.get_connection_count.return_value = {
        "workstations": 150,
        "operators": 5,
    }
    return mock_cm


@pytest.fixture
def mock_pool():
    """Pool SQLAlchemy mock con estado realista."""
    pool = MagicMock()
    pool.checkedout.return_value = 3
    pool.checkedin.return_value = 7
    pool.size.return_value = 10
    pool.overflow.return_value = 0
    pool._max_overflow = 5
    return pool


@pytest.fixture
def mock_engine(mock_pool):
    """Engine SQLAlchemy mock."""
    engine = MagicMock()
    engine.pool = mock_pool
    return engine


# === TEST 1: ENDPOINT COMPLETO CON PIPELINE FULL ===


class TestEndpointIntegrationCompleto:
    """
    Test de integración del endpoint completo.
    Mockea /proc pero ejecuta el pipeline real: HTTP → colector → response.
    Validates: Requirement 1.1
    """

    async def test_endpoint_retorna_200_con_estructura_correcta(
        self, app_with_admin, mock_connection_manager, mock_engine
    ):
        """
        WHEN un admin realiza GET /system/metrics con todos los colectores funcionales,
        THEN retorna HTTP 200 con las 5 métricas en la estructura esperada.
        """
        # Parchear dependencias donde se importan dentro de los métodos
        with patch("builtins.open", side_effect=self._mock_open_proc), \
             patch("os.listdir", return_value=PROC_SELF_FD_ENTRIES), \
             patch("resource.getrlimit", return_value=(1024, 1048576)), \
             patch("app.services.websocket_manager.connection_manager", mock_connection_manager), \
             patch("app.core.database.engine", mock_engine), \
             patch("app.core.config.settings", self._mock_settings()):

            # Configurar resultado de pg_stat_activity en la sesión mock
            mock_db = app_with_admin.dependency_overrides[get_db]()
            mock_result = MagicMock()
            mock_result.scalar.return_value = 2
            mock_db.execute.return_value = mock_result

            async with AsyncClient(
                transport=ASGITransport(app=app_with_admin),
                base_url="http://test",
            ) as client:
                response = await client.get(
                    "/system/metrics",
                    headers={"Authorization": "Bearer token_admin"},
                )

        # Verificar respuesta exitosa
        assert response.status_code == 200
        data = response.json()

        # Verificar estructura completa con las 5 métricas
        assert "websocket" in data
        assert "python_memory" in data
        assert "file_descriptors" in data
        assert "network" in data
        assert "db_pool" in data
        assert "collected_at" in data

        # Verificar que collected_at es un ISO datetime válido
        collected_at = datetime.fromisoformat(data["collected_at"])
        assert collected_at is not None

    async def test_endpoint_websocket_tiene_campos_correctos(
        self, app_with_admin, mock_connection_manager, mock_engine
    ):
        """
        WHEN el colector de WebSocket funciona correctamente,
        THEN la respuesta incluye workstation_count, operator_count, total y data_available.
        """
        with patch("builtins.open", side_effect=self._mock_open_proc), \
             patch("os.listdir", return_value=PROC_SELF_FD_ENTRIES), \
             patch("resource.getrlimit", return_value=(1024, 1048576)), \
             patch("app.services.websocket_manager.connection_manager", mock_connection_manager), \
             patch("app.core.database.engine", mock_engine), \
             patch("app.core.config.settings", self._mock_settings()):

            mock_db = app_with_admin.dependency_overrides[get_db]()
            mock_result = MagicMock()
            mock_result.scalar.return_value = 2
            mock_db.execute.return_value = mock_result

            async with AsyncClient(
                transport=ASGITransport(app=app_with_admin),
                base_url="http://test",
            ) as client:
                response = await client.get(
                    "/system/metrics",
                    headers={"Authorization": "Bearer token_admin"},
                )

        data = response.json()
        ws = data["websocket"]
        assert ws is not None
        assert ws["workstation_count"] == 150
        assert ws["operator_count"] == 5
        assert ws["total"] == 155
        assert ws["data_available"] is True

    async def test_endpoint_metricas_parciales_cuando_colector_falla(
        self, app_with_admin
    ):
        """
        WHEN un colector individual falla,
        THEN retorna HTTP 200 con null para la métrica fallida y las demás intactas.
        Validates: Requirement 1.5 (degradación parcial)
        """
        # Crear un colector que falle en python_memory pero funcione en los demás
        mock_response = ScalabilityMetricsResponse(
            websocket=WebSocketMetricsResponse(
                workstation_count=100,
                operator_count=3,
                total=103,
                data_available=True,
            ),
            python_memory=None,  # Simulamos fallo en este colector
            file_descriptors=FileDescriptorResponse(
                open_count=10, limit=1024, usage_percent=1.0
            ),
            network=None,  # Simulamos fallo en red
            db_pool=None,
            collected_at=datetime.now(timezone.utc),
        )

        with patch(
            "app.api.v1.endpoints.system_metrics.scalability_collector"
        ) as mock_collector:
            mock_collector.collect_all_metrics = AsyncMock(return_value=mock_response)

            async with AsyncClient(
                transport=ASGITransport(app=app_with_admin),
                base_url="http://test",
            ) as client:
                response = await client.get(
                    "/system/metrics",
                    headers={"Authorization": "Bearer token_admin"},
                )

        assert response.status_code == 200
        data = response.json()
        # Métricas que funcionan no son null
        assert data["websocket"] is not None
        assert data["file_descriptors"] is not None
        # Métricas que fallaron son null
        assert data["python_memory"] is None
        assert data["network"] is None

    # --- Helpers ---

    @staticmethod
    def _mock_open_proc(path, *args, **kwargs):
        """Simula la apertura de archivos /proc con datos realistas."""
        from io import StringIO

        if path == "/proc/self/status":
            return StringIO(PROC_SELF_STATUS_CONTENT)
        elif path == "/proc/net/dev":
            return StringIO(PROC_NET_DEV_CONTENT)
        elif path == "/sys/fs/cgroup/memory/memory.limit_in_bytes":
            return StringIO("2147483648")  # 2 GB
        elif path == "/sys/fs/cgroup/memory.max":
            return StringIO("2147483648")
        else:
            raise FileNotFoundError(f"Mock: archivo no encontrado {path}")

    @staticmethod
    def _mock_settings():
        """Crea un mock de settings con configuración PostgreSQL."""
        settings_mock = MagicMock()
        settings_mock.DATABASE_URL = "postgresql://appuser:password@localhost:5432/alwaysprint"
        settings_mock.is_postgresql = True
        return settings_mock


# === TEST 2: COLLECT_ALL DEL SCHEDULER INCLUYE SCALABILITY_METRICS ===


class TestSchedulerCollectAllIntegration:
    """
    Test de integración de SystemStatusCollector.collect_all().
    Verifica que el resultado incluye la clave scalability_metrics.
    Validates: Requirements 7.1, 7.2
    """

    async def test_collect_all_incluye_scalability_metrics(self):
        """
        WHEN el scheduler ejecuta collect_all(),
        THEN el resultado contiene la clave 'scalability_metrics' con un valor válido.
        """
        from app.services.system_status import SystemStatusCollector

        collector = SystemStatusCollector()

        # Mock de las dependencias del collector
        mock_db = MagicMock()

        # Mockear todas las sub-funciones del collector para aislar la integración
        with patch.object(collector, "collect_os_metrics", return_value=MagicMock()), \
             patch.object(collector, "collect_docker_metrics", new_callable=AsyncMock, return_value=(True, [])), \
             patch.object(collector, "collect_health_checks", new_callable=AsyncMock, return_value=([], {"ok_count": 0, "warning_count": 0, "failed_count": 0})), \
             patch.object(collector, "calculate_overall_status", return_value=("healthy", [])), \
             patch("app.services.system_status.scalability_collector") as mock_scalability:

            # Configurar el colector de escalabilidad para retornar métricas válidas
            mock_metrics = ScalabilityMetricsResponse(
                websocket=WebSocketMetricsResponse(
                    workstation_count=50,
                    operator_count=2,
                    total=52,
                    data_available=True,
                ),
                python_memory=PythonMemoryResponse(
                    rss_mb=128.5,
                    container_total_mb=2048.0,
                    avg_per_workstation_mb=2.57,
                ),
                file_descriptors=FileDescriptorResponse(
                    open_count=25, limit=1024, usage_percent=2.4
                ),
                network=NetworkTrafficResponse(
                    rx_bytes=98765432,
                    tx_bytes=45678901,
                    rx_rate_bps=None,
                    tx_rate_bps=None,
                ),
                db_pool=DbPoolResponse(
                    checked_out=3,
                    idle=7,
                    pool_size=10,
                    overflow=0,
                    max_overflow=5,
                    pg_active_connections=2,
                    usage_percent=30.0,
                ),
                collected_at=datetime.now(timezone.utc),
            )
            mock_scalability.collect_all_metrics = AsyncMock(return_value=mock_metrics)

            result = await collector.collect_all(db=mock_db)

        # Verificar que scalability_metrics está presente en el resultado
        assert "scalability_metrics" in result
        assert result["scalability_metrics"] is not None
        assert isinstance(result["scalability_metrics"], ScalabilityMetricsResponse)

    async def test_collect_all_incluye_scalability_metrics_json(self):
        """
        WHEN el scheduler ejecuta collect_all() exitosamente,
        THEN el resultado contiene 'scalability_metrics_json' como string JSON válido.
        """
        from app.services.system_status import SystemStatusCollector

        collector = SystemStatusCollector()
        mock_db = MagicMock()

        with patch.object(collector, "collect_os_metrics", return_value=MagicMock()), \
             patch.object(collector, "collect_docker_metrics", new_callable=AsyncMock, return_value=(True, [])), \
             patch.object(collector, "collect_health_checks", new_callable=AsyncMock, return_value=([], {"ok_count": 0, "warning_count": 0, "failed_count": 0})), \
             patch.object(collector, "calculate_overall_status", return_value=("healthy", [])), \
             patch("app.services.system_status.scalability_collector") as mock_scalability:

            mock_metrics = ScalabilityMetricsResponse(
                websocket=WebSocketMetricsResponse(
                    workstation_count=10,
                    operator_count=1,
                    total=11,
                    data_available=True,
                ),
                python_memory=None,
                file_descriptors=None,
                network=None,
                db_pool=None,
                collected_at=datetime.now(timezone.utc),
            )
            mock_scalability.collect_all_metrics = AsyncMock(return_value=mock_metrics)

            result = await collector.collect_all(db=mock_db)

        # Verificar que scalability_metrics_json es un JSON válido no-null
        assert "scalability_metrics_json" in result
        assert result["scalability_metrics_json"] is not None

        # Parsear el JSON y verificar estructura
        parsed = json.loads(result["scalability_metrics_json"])
        assert "websocket" in parsed
        assert "collected_at" in parsed

    async def test_collect_all_scalability_metrics_none_si_colector_falla(self):
        """
        WHEN el colector de escalabilidad lanza una excepción,
        THEN collect_all() retorna scalability_metrics=None sin interrumpir el proceso.
        Validates: Requirement 7.3
        """
        from app.services.system_status import SystemStatusCollector

        collector = SystemStatusCollector()
        mock_db = MagicMock()

        with patch.object(collector, "collect_os_metrics", return_value=MagicMock()), \
             patch.object(collector, "collect_docker_metrics", new_callable=AsyncMock, return_value=(True, [])), \
             patch.object(collector, "collect_health_checks", new_callable=AsyncMock, return_value=([], {"ok_count": 0, "warning_count": 0, "failed_count": 0})), \
             patch.object(collector, "calculate_overall_status", return_value=("healthy", [])), \
             patch("app.services.system_status.scalability_collector") as mock_scalability:

            # Simular fallo catastrófico del colector de escalabilidad
            mock_scalability.collect_all_metrics = AsyncMock(
                side_effect=RuntimeError("Error crítico en colector")
            )

            result = await collector.collect_all(db=mock_db)

        # El resultado debe existir sin error (las demás métricas siguen funcionando)
        assert "scalability_metrics" in result
        assert result["scalability_metrics"] is None
        assert result["scalability_metrics_json"] is None
        # Las demás métricas no se afectan
        assert "os_metrics" in result
        assert "overall_status" in result


# === TEST 3: PERSISTENCIA — SNAPSHOT CON SCALABILITY_METRICS_JSON NO-NULL ===


class TestPersistenciaScalabilityMetrics:
    """
    Test de integración para verificar que el JSON de métricas es
    no-null y válido después de una recolección exitosa.
    Validates: Requirement 7.2
    """

    async def test_scalability_metrics_json_valido_despues_de_recoleccion(self):
        """
        WHEN collect_all() completa exitosamente con métricas de escalabilidad,
        THEN scalability_metrics_json es un JSON string válido con las 5 claves de métricas.
        """
        from app.services.system_status import SystemStatusCollector

        collector = SystemStatusCollector()
        mock_db = MagicMock()

        # Métricas completas simuladas
        full_metrics = ScalabilityMetricsResponse(
            websocket=WebSocketMetricsResponse(
                workstation_count=200,
                operator_count=8,
                total=208,
                data_available=True,
            ),
            python_memory=PythonMemoryResponse(
                rss_mb=256.45,
                container_total_mb=4096.0,
                avg_per_workstation_mb=1.28,
            ),
            file_descriptors=FileDescriptorResponse(
                open_count=45, limit=65536, usage_percent=0.1
            ),
            network=NetworkTrafficResponse(
                rx_bytes=500000000,
                tx_bytes=200000000,
                rx_rate_bps=1250000.0,
                tx_rate_bps=500000.0,
            ),
            db_pool=DbPoolResponse(
                checked_out=5,
                idle=15,
                pool_size=20,
                overflow=0,
                max_overflow=10,
                pg_active_connections=3,
                usage_percent=25.0,
            ),
            collected_at=datetime.now(timezone.utc),
        )

        with patch.object(collector, "collect_os_metrics", return_value=MagicMock()), \
             patch.object(collector, "collect_docker_metrics", new_callable=AsyncMock, return_value=(True, [])), \
             patch.object(collector, "collect_health_checks", new_callable=AsyncMock, return_value=([], {"ok_count": 0, "warning_count": 0, "failed_count": 0})), \
             patch.object(collector, "calculate_overall_status", return_value=("healthy", [])), \
             patch("app.services.system_status.scalability_collector") as mock_scalability:

            mock_scalability.collect_all_metrics = AsyncMock(return_value=full_metrics)

            result = await collector.collect_all(db=mock_db)

        # Verificar que el JSON no es None
        json_str = result["scalability_metrics_json"]
        assert json_str is not None
        assert isinstance(json_str, str)
        assert len(json_str) > 0

        # Parsear y verificar estructura completa
        parsed = json.loads(json_str)
        assert parsed["websocket"]["workstation_count"] == 200
        assert parsed["websocket"]["operator_count"] == 8
        assert parsed["websocket"]["total"] == 208
        assert parsed["python_memory"]["rss_mb"] == 256.45
        assert parsed["file_descriptors"]["open_count"] == 45
        assert parsed["network"]["rx_bytes"] == 500000000
        assert parsed["db_pool"]["checked_out"] == 5
        assert parsed["db_pool"]["pg_active_connections"] == 3
        assert "collected_at" in parsed

    async def test_scalability_metrics_json_parcial_con_metricas_null(self):
        """
        WHEN algunas métricas individuales son null (colectores fallaron),
        THEN scalability_metrics_json aún es un JSON válido con campos null.
        """
        from app.services.system_status import SystemStatusCollector

        collector = SystemStatusCollector()
        mock_db = MagicMock()

        # Métricas parciales (algunos colectores fallaron)
        partial_metrics = ScalabilityMetricsResponse(
            websocket=WebSocketMetricsResponse(
                workstation_count=0,
                operator_count=0,
                total=0,
                data_available=False,
            ),
            python_memory=None,  # Colector falló
            file_descriptors=None,  # Colector falló
            network=None,  # Colector falló
            db_pool=None,  # Colector falló
            collected_at=datetime.now(timezone.utc),
        )

        with patch.object(collector, "collect_os_metrics", return_value=MagicMock()), \
             patch.object(collector, "collect_docker_metrics", new_callable=AsyncMock, return_value=(True, [])), \
             patch.object(collector, "collect_health_checks", new_callable=AsyncMock, return_value=([], {"ok_count": 0, "warning_count": 0, "failed_count": 0})), \
             patch.object(collector, "calculate_overall_status", return_value=("healthy", [])), \
             patch("app.services.system_status.scalability_collector") as mock_scalability:

            mock_scalability.collect_all_metrics = AsyncMock(return_value=partial_metrics)

            result = await collector.collect_all(db=mock_db)

        # Aún debe ser un JSON válido
        json_str = result["scalability_metrics_json"]
        assert json_str is not None
        parsed = json.loads(json_str)
        assert parsed["websocket"] is not None
        assert parsed["python_memory"] is None
        assert parsed["file_descriptors"] is None
        assert parsed["network"] is None
        assert parsed["db_pool"] is None


# === TEST 4: QUERY PG_STAT_ACTIVITY RETORNA CONTEO >= 0 ===


class TestDbPoolPgStatActivity:
    """
    Test de integración del colector de pool de BD con pg_stat_activity.
    Verifica que la query retorna un conteo válido (>= 0).
    Validates: Requirement 6.2
    """

    def test_collect_db_pool_metrics_retorna_pg_active_connections_valido(self):
        """
        WHEN collect_db_pool_metrics() ejecuta la query a pg_stat_activity,
        THEN pg_active_connections es un entero >= 0.
        """
        collector = ScalabilityMetricsCollector()

        # Configurar mock de la sesión de BD
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5  # 5 conexiones activas
        mock_db.execute.return_value = mock_result

        # Mock del engine y settings
        mock_pool = MagicMock()
        mock_pool.checkedout.return_value = 2
        mock_pool.checkedin.return_value = 8
        mock_pool.size.return_value = 10
        mock_pool.overflow.return_value = 0
        mock_pool._max_overflow = 5

        mock_engine = MagicMock()
        mock_engine.pool = mock_pool

        mock_settings = MagicMock()
        mock_settings.DATABASE_URL = "postgresql://appuser:pwd@db:5432/alwaysprint"
        mock_settings.is_postgresql = True

        with patch("app.core.database.engine", mock_engine), \
             patch("app.core.config.settings", mock_settings):
            result = collector.collect_db_pool_metrics(mock_db)

        # Verificar que pg_active_connections es un entero >= 0
        assert result.pg_active_connections is not None
        assert result.pg_active_connections >= 0
        assert result.pg_active_connections == 5

    def test_collect_db_pool_metrics_con_cero_conexiones_activas(self):
        """
        WHEN pg_stat_activity retorna 0 conexiones activas,
        THEN pg_active_connections es 0 (no None).
        """
        collector = ScalabilityMetricsCollector()

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0  # Cero conexiones activas
        mock_db.execute.return_value = mock_result

        mock_pool = MagicMock()
        mock_pool.checkedout.return_value = 1
        mock_pool.checkedin.return_value = 9
        mock_pool.size.return_value = 10
        mock_pool.overflow.return_value = 0
        mock_pool._max_overflow = 5

        mock_engine = MagicMock()
        mock_engine.pool = mock_pool

        mock_settings = MagicMock()
        mock_settings.DATABASE_URL = "postgresql://appuser:pwd@db:5432/alwaysprint"
        mock_settings.is_postgresql = True

        with patch("app.core.database.engine", mock_engine), \
             patch("app.core.config.settings", mock_settings):
            result = collector.collect_db_pool_metrics(mock_db)

        assert result.pg_active_connections == 0
        assert result.pg_active_connections >= 0

    def test_collect_db_pool_metrics_pg_stat_activity_falla_retorna_null(self):
        """
        WHEN la query a pg_stat_activity lanza una excepción,
        THEN pg_active_connections es None pero las métricas del pool local funcionan.
        Validates: Requirement 6.4
        """
        collector = ScalabilityMetricsCollector()

        mock_db = MagicMock()
        # Simular fallo en la query a pg_stat_activity
        mock_db.execute.side_effect = Exception("connection timeout")

        mock_pool = MagicMock()
        mock_pool.checkedout.return_value = 4
        mock_pool.checkedin.return_value = 6
        mock_pool.size.return_value = 10
        mock_pool.overflow.return_value = 1
        mock_pool._max_overflow = 5

        mock_engine = MagicMock()
        mock_engine.pool = mock_pool

        mock_settings = MagicMock()
        mock_settings.DATABASE_URL = "postgresql://appuser:pwd@db:5432/alwaysprint"
        mock_settings.is_postgresql = True

        with patch("app.core.database.engine", mock_engine), \
             patch("app.core.config.settings", mock_settings):
            result = collector.collect_db_pool_metrics(mock_db)

        # pg_stat_activity falló → null
        assert result.pg_active_connections is None
        # Las métricas del pool local siguen disponibles
        assert result.checked_out == 4
        assert result.idle == 6
        assert result.pool_size == 10
        assert result.overflow == 1
        assert result.max_overflow == 5
        assert result.usage_percent is not None

    def test_collect_db_pool_metrics_usage_percent_correcto(self):
        """
        WHEN el pool tiene conexiones checked_out,
        THEN usage_percent se calcula correctamente como (checked_out / pool_size * 100).
        """
        collector = ScalabilityMetricsCollector()

        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 3
        mock_db.execute.return_value = mock_result

        mock_pool = MagicMock()
        mock_pool.checkedout.return_value = 3
        mock_pool.checkedin.return_value = 7
        mock_pool.size.return_value = 10
        mock_pool.overflow.return_value = 0
        mock_pool._max_overflow = 5

        mock_engine = MagicMock()
        mock_engine.pool = mock_pool

        mock_settings = MagicMock()
        mock_settings.DATABASE_URL = "postgresql://appuser:pwd@db:5432/alwaysprint"
        mock_settings.is_postgresql = True

        with patch("app.core.database.engine", mock_engine), \
             patch("app.core.config.settings", mock_settings):
            result = collector.collect_db_pool_metrics(mock_db)

        # 3 / 10 * 100 = 30.0
        assert result.usage_percent == 30.0
