"""
Property test para atomicidad transaccional en fallos de escritura.

Verifica que para cualquier operación de escritura de StatusSnapshot que falla
en cualquier punto durante la inserción (snapshot, metrics, health checks, o
container metrics), la base de datos NO contenga datos parciales de esa
operación fallida (rollback completo).

- Property 11: Transaction atomicity on failure

**Validates: Requirements 4.7**

Tag: Feature: system-status-monitoring, Property 11: Transaction atomicity on failure
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from enum import IntEnum
from unittest.mock import patch

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base

# Importar todos los modelos para que Base.metadata conozca todas las tablas
import app.models  # noqa: F401

from app.models.system_status import (
    ContainerMetric,
    HealthCheckResult,
    MetricRecord,
    StatusSnapshot,
)
from app.schemas.system_status import (
    AlertResponse,
    ContainerMetricsResponse,
    HealthCheckResponse,
    OsMetricsResponse,
)
from app.services.system_status import SystemStatusCollector


# === ENUMERACIÓN DE PUNTOS DE FALLO ===


class PuntoFallo(IntEnum):
    """Puntos donde se puede inyectar un fallo durante la persistencia."""
    SNAPSHOT_INSERT = 0       # Fallo al insertar el snapshot principal
    METRIC_RECORDS_INSERT = 1  # Fallo al insertar metric_records
    HEALTH_CHECKS_INSERT = 2   # Fallo al insertar health_check_results
    CONTAINER_METRICS_INSERT = 3  # Fallo al insertar container_metrics
    COMMIT = 4                 # Fallo durante el commit


# === CONFIGURACIÓN DE BD EN MEMORIA ===


@contextmanager
def crear_sesion_test():
    """
    Context manager que crea una sesión SQLite en memoria aislada.

    Crea todas las tablas, proporciona una sesión limpia y
    limpia los recursos al finalizar.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Deshabilitar foreign keys para simplificar el test
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# === ESTRATEGIAS DE GENERACIÓN ===


# Estrategia para métricas del sistema operativo con valores válidos
os_metrics_strategy = st.builds(
    OsMetricsResponse,
    memory_total_mb=st.floats(min_value=512.0, max_value=65536.0, allow_nan=False, allow_infinity=False),
    memory_used_mb=st.floats(min_value=0.1, max_value=65536.0, allow_nan=False, allow_infinity=False),
    memory_available_mb=st.floats(min_value=0.1, max_value=65536.0, allow_nan=False, allow_infinity=False),
    memory_percent=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    disk_total_mb=st.floats(min_value=1024.0, max_value=1048576.0, allow_nan=False, allow_infinity=False),
    disk_used_mb=st.floats(min_value=0.1, max_value=1048576.0, allow_nan=False, allow_infinity=False),
    disk_available_mb=st.floats(min_value=0.1, max_value=1048576.0, allow_nan=False, allow_infinity=False),
    disk_percent=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    cpu_percent=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    swap_total_mb=st.floats(min_value=0.0, max_value=32768.0, allow_nan=False, allow_infinity=False),
    swap_used_mb=st.floats(min_value=0.0, max_value=32768.0, allow_nan=False, allow_infinity=False),
    swap_available_mb=st.floats(min_value=0.0, max_value=32768.0, allow_nan=False, allow_infinity=False),
    uptime_seconds=st.integers(min_value=0, max_value=31536000),
)

# Estrategia para métricas de contenedores Docker
container_metrics_strategy = st.lists(
    st.builds(
        ContainerMetricsResponse,
        name=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
            min_size=1,
            max_size=30,
        ),
        status=st.sampled_from(["running", "stopped", "restarting"]),
        cpu_percent=st.floats(min_value=0.0, max_value=400.0, allow_nan=False, allow_infinity=False),
        memory_used_mb=st.floats(min_value=0.0, max_value=16384.0, allow_nan=False, allow_infinity=False),
        memory_limit_mb=st.floats(min_value=1.0, max_value=16384.0, allow_nan=False, allow_infinity=False),
        network_rx_bytes=st.integers(min_value=0, max_value=10**12),
        network_tx_bytes=st.integers(min_value=0, max_value=10**12),
        uptime_seconds=st.integers(min_value=0, max_value=31536000),
    ),
    min_size=0,
    max_size=5,
)

# Estrategia para resultados de health checks
health_checks_strategy = st.lists(
    st.builds(
        HealthCheckResponse,
        service_name=st.sampled_from(["backend", "frontend", "nginx", "redis", "rds", "ssl"]),
        is_available=st.booleans(),
        latency_ms=st.one_of(
            st.none(),
            st.floats(min_value=0.1, max_value=10000.0, allow_nan=False, allow_infinity=False),
        ),
        error_message=st.one_of(st.none(), st.text(min_size=1, max_size=100)),
        details=st.one_of(st.none(), st.just({"days_remaining": 10, "classification": "warning"})),
    ),
    min_size=1,
    max_size=6,
)

# Estrategia para el punto de fallo
punto_fallo_strategy = st.sampled_from(list(PuntoFallo))


# === CLASE AUXILIAR PARA INYECTAR FALLOS ===


class SesionConFalloInyectado:
    """
    Wrapper de sesión SQLAlchemy que inyecta un fallo en un punto específico.

    Cuenta las llamadas a add() y flush()/commit() para determinar cuándo
    lanzar la excepción según el punto de fallo configurado.
    """

    def __init__(self, session_real: Session, punto_fallo: PuntoFallo):
        """
        Inicializa el wrapper con la sesión real y el punto de fallo.

        Args:
            session_real: Sesión SQLAlchemy real
            punto_fallo: Punto donde se inyectará el fallo
        """
        self._session = session_real
        self._punto_fallo = punto_fallo
        self._add_count = 0
        self._flush_called = False

    def add(self, instance):
        """Intercepta add() para contar inserciones y fallar en el punto correcto."""
        # Determinar qué tipo de objeto se está insertando
        if isinstance(instance, StatusSnapshot):
            if self._punto_fallo == PuntoFallo.SNAPSHOT_INSERT:
                raise Exception("Error simulado: fallo al insertar snapshot")
        elif isinstance(instance, MetricRecord):
            if self._punto_fallo == PuntoFallo.METRIC_RECORDS_INSERT:
                raise Exception("Error simulado: fallo al insertar metric_record")
        elif isinstance(instance, HealthCheckResult):
            if self._punto_fallo == PuntoFallo.HEALTH_CHECKS_INSERT:
                raise Exception("Error simulado: fallo al insertar health_check_result")
        elif isinstance(instance, ContainerMetric):
            if self._punto_fallo == PuntoFallo.CONTAINER_METRICS_INSERT:
                raise Exception("Error simulado: fallo al insertar container_metric")

        self._session.add(instance)

    def flush(self):
        """Delega flush() a la sesión real."""
        self._session.flush()

    def commit(self):
        """Intercepta commit() para fallar si el punto de fallo es COMMIT."""
        if self._punto_fallo == PuntoFallo.COMMIT:
            raise Exception("Error simulado: fallo durante el commit")
        self._session.commit()

    def rollback(self):
        """Delega rollback() a la sesión real."""
        self._session.rollback()

    def refresh(self, instance):
        """Delega refresh() a la sesión real."""
        self._session.refresh(instance)

    def query(self, *args, **kwargs):
        """Delega query() a la sesión real."""
        return self._session.query(*args, **kwargs)


# === PROPERTY TEST ===


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    deadline=None,
)
@given(
    os_metrics=os_metrics_strategy,
    docker_metrics=container_metrics_strategy,
    health_checks=health_checks_strategy,
    punto_fallo=punto_fallo_strategy,
)
def test_transaction_atomicity_on_failure(
    os_metrics: OsMetricsResponse,
    docker_metrics: list,
    health_checks: list,
    punto_fallo: PuntoFallo,
):
    """
    Property 11: Atomicidad transaccional en fallos.

    Para cualquier operación de escritura de StatusSnapshot que falla en
    cualquier punto durante la inserción (snapshot, metrics, health checks,
    o container metrics), la base de datos NO debe contener datos parciales
    de esa operación fallida (rollback completo).

    Estrategia:
    1. Generar datos aleatorios válidos para un snapshot
    2. Inyectar un fallo en un punto específico de la operación
    3. Hacer que TODOS los reintentos fallen (3 intentos)
    4. Verificar que la BD no contiene datos parciales
    5. Verificar que save_snapshot() retorna None

    **Validates: Requirements 4.7**
    """
    # Para el caso CONTAINER_METRICS_INSERT, necesitamos al menos un contenedor
    if punto_fallo == PuntoFallo.CONTAINER_METRICS_INSERT and len(docker_metrics) == 0:
        return  # No se puede probar fallo en container_metrics sin contenedores

    # Para el caso HEALTH_CHECKS_INSERT, necesitamos al menos un health check
    if punto_fallo == PuntoFallo.HEALTH_CHECKS_INSERT and len(health_checks) == 0:
        return  # No se puede probar fallo en health_checks sin checks

    with crear_sesion_test() as session:
        collector = SystemStatusCollector()
        timestamp = datetime.now(timezone.utc)

        # Crear sesión con fallo inyectado
        sesion_con_fallo = SesionConFalloInyectado(session, punto_fallo)

        # Ejecutar save_snapshot con la sesión que fallará en TODOS los intentos
        # Mock time.sleep para evitar esperas de 5 segundos entre reintentos
        with patch("app.services.system_status.time.sleep"):
            resultado = collector.save_snapshot(
                db=sesion_con_fallo,
                os_metrics=os_metrics,
                docker_available=len(docker_metrics) > 0,
                docker_metrics=docker_metrics,
                health_checks=health_checks,
                overall_status="healthy",
                alerts=[],
                timestamp=timestamp,
            )

        # Verificar que save_snapshot retorna None (indica fallo)
        assert resultado is None, (
            f"save_snapshot() debería retornar None tras fallo en {punto_fallo.name}, "
            f"pero retornó {resultado}"
        )

        # Verificar que la BD NO contiene datos parciales del snapshot fallido
        # Usar la sesión real para consultar la BD
        snapshots_count = session.query(StatusSnapshot).count()
        assert snapshots_count == 0, (
            f"La BD contiene {snapshots_count} snapshots después de un fallo en "
            f"{punto_fallo.name}. Debería contener 0 (rollback completo)."
        )

        metric_records_count = session.query(MetricRecord).count()
        assert metric_records_count == 0, (
            f"La BD contiene {metric_records_count} metric_records después de un fallo en "
            f"{punto_fallo.name}. Debería contener 0 (rollback completo)."
        )

        health_checks_count = session.query(HealthCheckResult).count()
        assert health_checks_count == 0, (
            f"La BD contiene {health_checks_count} health_check_results después de un fallo en "
            f"{punto_fallo.name}. Debería contener 0 (rollback completo)."
        )

        container_metrics_count = session.query(ContainerMetric).count()
        assert container_metrics_count == 0, (
            f"La BD contiene {container_metrics_count} container_metrics después de un fallo en "
            f"{punto_fallo.name}. Debería contener 0 (rollback completo)."
        )
