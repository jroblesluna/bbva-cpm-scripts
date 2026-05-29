"""
Property tests para el cálculo de uptime de servicios.

Verifica que para cualquier secuencia de resultados de health check de un
servicio en un período de tiempo, el porcentaje de uptime sea igual a
(count de resultados disponibles / total de resultados) * 100, redondeado
a 2 decimales.

**Validates: Requirements 7.5**

Feature: system-status-monitoring, Property 15: Service uptime calculation
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import Integer, create_engine, event, func
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base

# Importar todos los modelos para que Base.metadata conozca todas las tablas
import app.models  # noqa: F401

from app.models.system_status import (
    HealthCheckResult,
    OverallStatus,
    StatusSnapshot,
)


# === CONFIGURACIÓN DE BD EN MEMORIA ===


@contextmanager
def create_test_session():
    """
    Context manager que crea una sesión SQLite en memoria aislada.

    Crea todas las tablas, habilita foreign keys para CASCADE,
    proporciona una sesión limpia y limpia los recursos al finalizar.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Habilitar foreign keys en SQLite para que CASCADE funcione
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
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

# Nombres de servicios posibles (simula los servicios reales monitoreados)
_service_names = st.sampled_from([
    "backend",
    "frontend",
    "nginx",
    "redis",
    "rds",
    "ssl_certificate",
])

# Resultado de disponibilidad de un health check (True/False)
_is_available = st.booleans()

# Secuencia de resultados de health check para un servicio (1 a 50 checks)
_health_check_sequence = st.lists(
    _is_available,
    min_size=1,
    max_size=50,
)

# Múltiples servicios con sus secuencias de checks
_multi_service_checks = st.dictionaries(
    keys=_service_names,
    values=_health_check_sequence,
    min_size=1,
    max_size=6,
)


def _crear_snapshot_minimo(session: Session) -> StatusSnapshot:
    """
    Crea un StatusSnapshot mínimo necesario como padre de los HealthCheckResults.

    Retorna el snapshot creado y persistido en la sesión.
    """
    snapshot = StatusSnapshot(
        id=uuid.uuid4(),
        timestamp=datetime.now(timezone.utc) - timedelta(hours=1),
        overall_status=OverallStatus.HEALTHY,
        memory_percent=45.0,
        memory_total_mb=8192.0,
        memory_used_mb=3686.0,
        memory_available_mb=4506.0,
        disk_percent=60.0,
        disk_total_mb=51200.0,
        disk_used_mb=30720.0,
        disk_available_mb=20480.0,
        cpu_percent=25.0,
        swap_used_mb=256.0,
        swap_total_mb=2048.0,
        swap_available_mb=1792.0,
        uptime_seconds=86400,
        docker_available=True,
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def _insertar_health_checks(
    session: Session,
    snapshot: StatusSnapshot,
    service_name: str,
    results: list,
) -> None:
    """
    Inserta una secuencia de HealthCheckResults para un servicio dado.

    Cada resultado se asocia al snapshot proporcionado con timestamps
    espaciados 6 horas entre sí (simulando recolecciones periódicas).
    """
    base_time = datetime.now(timezone.utc) - timedelta(days=15)
    for i, is_available in enumerate(results):
        health_check = HealthCheckResult(
            id=uuid.uuid4(),
            snapshot_id=snapshot.id,
            service_name=service_name,
            is_available=is_available,
            latency_ms=50.0 if is_available else None,
            error_message=None if is_available else "Servicio no disponible",
            details_json=None,
            timestamp=base_time + timedelta(hours=6 * i),
        )
        session.add(health_check)
    session.flush()


def _calcular_uptime_esperado(results: list) -> tuple:
    """
    Calcula el uptime esperado a partir de una lista de resultados booleanos.

    Retorna:
        Tupla (uptime_percent, total_checks, successful_checks)
    """
    total = len(results)
    successful = sum(1 for r in results if r)
    uptime_percent = round((successful / total) * 100, 2) if total > 0 else 0.0
    return uptime_percent, total, successful


def _query_uptime_from_db(session: Session, service_name: str) -> tuple:
    """
    Ejecuta la misma query que el endpoint get_services_uptime para un servicio.

    Replica la lógica de GROUP BY service_name, SUM(is_available), COUNT(*)
    del endpoint real.

    Retorna:
        Tupla (uptime_percent, total_checks, successful_checks)
    """
    result = (
        session.query(
            HealthCheckResult.service_name,
            func.count(HealthCheckResult.id).label("total_checks"),
            func.sum(
                func.cast(HealthCheckResult.is_available, Integer)
            ).label("successful_checks"),
        )
        .filter(HealthCheckResult.service_name == service_name)
        .group_by(HealthCheckResult.service_name)
        .first()
    )

    if result is None:
        return 0.0, 0, 0

    total = result.total_checks
    successful = result.successful_checks or 0
    uptime_percent = round((successful / total) * 100, 2) if total > 0 else 0.0
    return uptime_percent, total, successful


# === PROPERTY 15: SERVICE UPTIME CALCULATION ===


class TestServiceUptimeCalculation:
    """
    Property 15: Service uptime calculation.

    Para cualquier secuencia de resultados de health check de un servicio
    en un período de tiempo, el porcentaje de uptime SHALL ser igual a
    (count de resultados disponibles / total de resultados) * 100,
    redondeado a 2 decimales.

    **Validates: Requirements 7.5**
    """

    @given(results=_health_check_sequence, service_name=_service_names)
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_uptime_percent_equals_available_over_total(
        self, results: list, service_name: str
    ):
        """
        El uptime_percent calculado desde la BD coincide con la fórmula
        (successful / total) * 100 redondeado a 2 decimales.

        **Validates: Requirements 7.5**
        """
        with create_test_session() as session:
            # Crear snapshot padre e insertar health checks
            snapshot = _crear_snapshot_minimo(session)
            _insertar_health_checks(session, snapshot, service_name, results)
            session.commit()

            # Calcular uptime desde la BD (misma lógica que el endpoint)
            db_uptime, db_total, db_successful = _query_uptime_from_db(
                session, service_name
            )

            # Calcular uptime esperado directamente de los datos generados
            expected_uptime, expected_total, expected_successful = (
                _calcular_uptime_esperado(results)
            )

            # Verificar que total_checks coincide con el número de registros
            assert db_total == expected_total, (
                f"total_checks no coincide: BD={db_total}, "
                f"esperado={expected_total} para {len(results)} resultados"
            )

            # Verificar que successful_checks coincide con los True en la lista
            assert db_successful == expected_successful, (
                f"successful_checks no coincide: BD={db_successful}, "
                f"esperado={expected_successful} para servicio '{service_name}'"
            )

            # Verificar que uptime_percent es correcto
            assert db_uptime == expected_uptime, (
                f"uptime_percent no coincide: BD={db_uptime}, "
                f"esperado={expected_uptime}. "
                f"Fórmula: ({expected_successful}/{expected_total})*100 "
                f"= {expected_uptime}"
            )

    @given(results=_health_check_sequence)
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_uptime_todos_disponibles_es_100(self, results: list):
        """
        Si todos los checks son disponibles, el uptime debe ser 100.00%.

        **Validates: Requirements 7.5**
        """
        # Forzar todos los resultados a True
        all_available = [True] * len(results)

        with create_test_session() as session:
            snapshot = _crear_snapshot_minimo(session)
            _insertar_health_checks(session, snapshot, "test_service", all_available)
            session.commit()

            uptime, total, successful = _query_uptime_from_db(
                session, "test_service"
            )

            assert uptime == 100.0, (
                f"Con todos los checks disponibles, uptime debería ser 100.0, "
                f"pero es {uptime}"
            )
            assert successful == total, (
                f"successful_checks ({successful}) debería ser igual a "
                f"total_checks ({total}) cuando todos están disponibles"
            )

    @given(results=_health_check_sequence)
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_uptime_ninguno_disponible_es_0(self, results: list):
        """
        Si ningún check es disponible, el uptime debe ser 0.00%.

        **Validates: Requirements 7.5**
        """
        # Forzar todos los resultados a False
        none_available = [False] * len(results)

        with create_test_session() as session:
            snapshot = _crear_snapshot_minimo(session)
            _insertar_health_checks(session, snapshot, "test_service", none_available)
            session.commit()

            uptime, total, successful = _query_uptime_from_db(
                session, "test_service"
            )

            assert uptime == 0.0, (
                f"Con ningún check disponible, uptime debería ser 0.0, "
                f"pero es {uptime}"
            )
            assert successful == 0, (
                f"successful_checks debería ser 0 cuando ninguno está "
                f"disponible, pero es {successful}"
            )

    @given(service_checks=_multi_service_checks)
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_uptime_multiples_servicios_independientes(
        self, service_checks: dict
    ):
        """
        El cálculo de uptime de cada servicio es independiente de los demás.
        Cada servicio tiene su propio conteo de checks y porcentaje.

        **Validates: Requirements 7.5**
        """
        with create_test_session() as session:
            snapshot = _crear_snapshot_minimo(session)

            # Insertar checks para cada servicio
            for service_name, results in service_checks.items():
                _insertar_health_checks(session, snapshot, service_name, results)
            session.commit()

            # Verificar uptime de cada servicio independientemente
            for service_name, results in service_checks.items():
                db_uptime, db_total, db_successful = _query_uptime_from_db(
                    session, service_name
                )
                expected_uptime, expected_total, expected_successful = (
                    _calcular_uptime_esperado(results)
                )

                assert db_total == expected_total, (
                    f"Servicio '{service_name}': total_checks no coincide. "
                    f"BD={db_total}, esperado={expected_total}"
                )
                assert db_successful == expected_successful, (
                    f"Servicio '{service_name}': successful_checks no coincide. "
                    f"BD={db_successful}, esperado={expected_successful}"
                )
                assert db_uptime == expected_uptime, (
                    f"Servicio '{service_name}': uptime_percent no coincide. "
                    f"BD={db_uptime}, esperado={expected_uptime}"
                )

    @given(results=_health_check_sequence)
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_uptime_rango_valido_0_a_100(self, results: list):
        """
        El porcentaje de uptime siempre está en el rango [0.0, 100.0].

        **Validates: Requirements 7.5**
        """
        with create_test_session() as session:
            snapshot = _crear_snapshot_minimo(session)
            _insertar_health_checks(session, snapshot, "test_service", results)
            session.commit()

            uptime, _, _ = _query_uptime_from_db(session, "test_service")

            assert 0.0 <= uptime <= 100.0, (
                f"uptime_percent ({uptime}) está fuera del rango válido "
                f"[0.0, 100.0]"
            )
