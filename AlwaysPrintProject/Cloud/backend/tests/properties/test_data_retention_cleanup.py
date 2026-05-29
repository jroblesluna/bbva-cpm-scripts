"""
Property tests para la limpieza de datos por retención temporal.

Verifica que el proceso de cleanup elimina todos los snapshots (y sus
registros asociados MetricRecords, HealthCheckResults, ContainerMetrics
via CASCADE) cuyo timestamp es anterior a 90 días desde el momento actual,
y preserva todos los snapshots dentro de la ventana de 90 días.

**Validates: Requirements 4.3, 4.4**

Feature: system-status-monitoring, Property 10: Data retention cleanup
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
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
    OverallStatus,
    StatusSnapshot,
)
from app.services.system_status import SystemStatusCollector


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

# Días de antigüedad del snapshot (0 a 180 días atrás)
# Evitamos exactamente 90 días para no tener problemas de boundary
# (el tiempo que pasa entre crear el snapshot y ejecutar cleanup
# puede hacer que un snapshot de exactamente 90 días cruce el límite)
_days_ago = st.integers(min_value=0, max_value=180).filter(lambda d: d != 90)

# Lista de snapshots con timestamps variados (entre 1 y 15 snapshots)
_snapshot_days_list = st.lists(
    _days_ago,
    min_size=1,
    max_size=15,
)

# Número de registros hijos por snapshot (0 a 3 para mantener tests rápidos)
_num_children = st.integers(min_value=0, max_value=3)


def _crear_snapshot(
    session: Session, days_ago: int, num_metrics: int = 1,
    num_health_checks: int = 1, num_containers: int = 1
) -> StatusSnapshot:
    """
    Crea un StatusSnapshot con registros hijos en la BD de test.

    Parámetros:
        session: Sesión SQLAlchemy
        days_ago: Días de antigüedad del snapshot respecto a ahora
        num_metrics: Número de MetricRecords a crear
        num_health_checks: Número de HealthCheckResults a crear
        num_containers: Número de ContainerMetrics a crear

    Retorna:
        StatusSnapshot creado y persistido
    """
    timestamp = datetime.now(timezone.utc) - timedelta(days=days_ago)

    snapshot = StatusSnapshot(
        id=uuid.uuid4(),
        timestamp=timestamp,
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

    # Crear MetricRecords asociados
    for i in range(num_metrics):
        metric = MetricRecord(
            id=uuid.uuid4(),
            snapshot_id=snapshot.id,
            metric_name=f"test_metric_{i}",
            value=float(i * 10),
            unit="percent",
            timestamp=timestamp,
        )
        session.add(metric)

    # Crear HealthCheckResults asociados
    for i in range(num_health_checks):
        health = HealthCheckResult(
            id=uuid.uuid4(),
            snapshot_id=snapshot.id,
            service_name=f"service_{i}",
            is_available=True,
            latency_ms=50.0,
            error_message=None,
            details_json=None,
            timestamp=timestamp,
        )
        session.add(health)

    # Crear ContainerMetrics asociados
    for i in range(num_containers):
        container = ContainerMetric(
            id=uuid.uuid4(),
            snapshot_id=snapshot.id,
            container_name=f"container_{i}",
            status="running",
            cpu_percent=5.0,
            memory_used_mb=128.0,
            memory_limit_mb=512.0,
            network_rx_bytes=1000,
            network_tx_bytes=2000,
            uptime_seconds=3600,
        )
        session.add(container)

    session.flush()
    return snapshot


# === PROPERTY 10: DATA RETENTION CLEANUP ===


class TestDataRetentionCleanup:
    """
    Property 10: Data retention cleanup.

    Para cualquier conjunto de StatusSnapshots con timestamps variados,
    el proceso de cleanup SHALL eliminar todos los snapshots (y sus
    MetricRecords, HealthCheckResults, ContainerMetrics asociados via
    CASCADE) cuyo timestamp es anterior a 90 días desde el momento actual,
    y SHALL preservar todos los snapshots dentro de la ventana de 90 días.

    **Validates: Requirements 4.3, 4.4**
    """

    @given(snapshot_days=_snapshot_days_list)
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_cleanup_elimina_snapshots_mayores_a_90_dias(
        self, snapshot_days: list
    ):
        """
        Todos los snapshots con timestamp > 90 días son eliminados por cleanup.

        **Validates: Requirements 4.3, 4.4**
        """
        with create_test_session() as session:
            # Crear snapshots con los días de antigüedad generados
            for days in snapshot_days:
                _crear_snapshot(session, days_ago=days)
            session.commit()

            # Verificar que se crearon todos los snapshots
            total_antes = session.query(StatusSnapshot).count()
            assert total_antes == len(snapshot_days)

            # Ejecutar cleanup
            collector = SystemStatusCollector()
            collector.cleanup_old_snapshots(session)

            # Verificar resultados
            snapshots_restantes = session.query(StatusSnapshot).all()

            # Contar cuántos deberían sobrevivir (<90 días, ya que
            # filtramos days_ago=90 en la estrategia)
            esperados_preservados = sum(1 for d in snapshot_days if d < 90)
            esperados_eliminados = sum(1 for d in snapshot_days if d > 90)

            assert len(snapshots_restantes) == esperados_preservados, (
                f"Se esperaban {esperados_preservados} snapshots preservados "
                f"(<90 días), pero quedan {len(snapshots_restantes)}. "
                f"Días generados: {snapshot_days}"
            )

            # Verificar que todos los restantes están dentro de la ventana
            # Nota: SQLite no almacena timezone, así que comparamos sin tz
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)
            cutoff_naive = cutoff.replace(tzinfo=None)
            for snap in snapshots_restantes:
                # SQLite devuelve timestamps naive, comparar apropiadamente
                snap_ts = snap.timestamp
                if snap_ts.tzinfo is not None:
                    snap_ts = snap_ts.replace(tzinfo=None)
                assert snap_ts >= cutoff_naive, (
                    f"Snapshot con timestamp {snap.timestamp} debería haber "
                    f"sido eliminado (anterior a cutoff {cutoff})"
                )

    @given(snapshot_days=_snapshot_days_list)
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_cleanup_preserva_snapshots_dentro_de_ventana_90_dias(
        self, snapshot_days: list
    ):
        """
        Todos los snapshots con timestamp < 90 días son preservados por cleanup.

        **Validates: Requirements 4.3**
        """
        with create_test_session() as session:
            # Crear snapshots y guardar IDs de los que deben sobrevivir
            ids_dentro_ventana = []
            for days in snapshot_days:
                snap = _crear_snapshot(session, days_ago=days)
                if days < 90:
                    ids_dentro_ventana.append(snap.id)
            session.commit()

            # Ejecutar cleanup
            collector = SystemStatusCollector()
            collector.cleanup_old_snapshots(session)

            # Verificar que todos los IDs dentro de ventana siguen existiendo
            for snap_id in ids_dentro_ventana:
                snap = session.query(StatusSnapshot).filter_by(id=snap_id).first()
                assert snap is not None, (
                    f"Snapshot {snap_id} dentro de la ventana de 90 días "
                    f"fue eliminado incorrectamente"
                )

    @given(
        snapshot_days=st.lists(
            st.integers(min_value=91, max_value=180),
            min_size=1,
            max_size=10,
        ),
        num_metrics=_num_children,
        num_health_checks=_num_children,
        num_containers=_num_children,
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_cleanup_cascade_elimina_registros_asociados(
        self,
        snapshot_days: list,
        num_metrics: int,
        num_health_checks: int,
        num_containers: int,
    ):
        """
        Al eliminar snapshots antiguos, los MetricRecords, HealthCheckResults
        y ContainerMetrics asociados se eliminan via CASCADE.

        **Validates: Requirements 4.4**
        """
        with create_test_session() as session:
            # Crear snapshots antiguos (>90 días) con registros hijos
            for days in snapshot_days:
                _crear_snapshot(
                    session,
                    days_ago=days,
                    num_metrics=num_metrics,
                    num_health_checks=num_health_checks,
                    num_containers=num_containers,
                )
            session.commit()

            # Verificar que se crearon registros hijos
            total_metrics_antes = session.query(MetricRecord).count()
            total_health_antes = session.query(HealthCheckResult).count()
            total_containers_antes = session.query(ContainerMetric).count()

            expected_metrics = len(snapshot_days) * num_metrics
            expected_health = len(snapshot_days) * num_health_checks
            expected_containers = len(snapshot_days) * num_containers

            assert total_metrics_antes == expected_metrics
            assert total_health_antes == expected_health
            assert total_containers_antes == expected_containers

            # Ejecutar cleanup
            collector = SystemStatusCollector()
            collector.cleanup_old_snapshots(session)

            # Verificar que todos los registros hijos fueron eliminados
            assert session.query(StatusSnapshot).count() == 0, (
                "Todos los snapshots (>90 días) deberían haber sido eliminados"
            )
            assert session.query(MetricRecord).count() == 0, (
                "Todos los MetricRecords asociados deberían haber sido "
                "eliminados via CASCADE"
            )
            assert session.query(HealthCheckResult).count() == 0, (
                "Todos los HealthCheckResults asociados deberían haber sido "
                "eliminados via CASCADE"
            )
            assert session.query(ContainerMetric).count() == 0, (
                "Todos los ContainerMetrics asociados deberían haber sido "
                "eliminados via CASCADE"
            )

    @given(
        old_days=st.lists(
            st.integers(min_value=91, max_value=180),
            min_size=1,
            max_size=5,
        ),
        recent_days=st.lists(
            st.integers(min_value=0, max_value=89),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_cleanup_cascade_no_afecta_registros_de_snapshots_recientes(
        self, old_days: list, recent_days: list
    ):
        """
        El CASCADE solo elimina registros hijos de snapshots antiguos,
        preservando los registros de snapshots recientes intactos.

        **Validates: Requirements 4.3, 4.4**
        """
        with create_test_session() as session:
            # Crear snapshots antiguos con hijos
            for days in old_days:
                _crear_snapshot(
                    session, days_ago=days,
                    num_metrics=2, num_health_checks=2, num_containers=2
                )

            # Crear snapshots recientes con hijos
            recent_ids = []
            for days in recent_days:
                snap = _crear_snapshot(
                    session, days_ago=days,
                    num_metrics=2, num_health_checks=2, num_containers=2
                )
                recent_ids.append(snap.id)
            session.commit()

            # Contar registros hijos de snapshots recientes antes del cleanup
            metrics_recientes_antes = session.query(MetricRecord).filter(
                MetricRecord.snapshot_id.in_(recent_ids)
            ).count()
            health_recientes_antes = session.query(HealthCheckResult).filter(
                HealthCheckResult.snapshot_id.in_(recent_ids)
            ).count()
            containers_recientes_antes = session.query(ContainerMetric).filter(
                ContainerMetric.snapshot_id.in_(recent_ids)
            ).count()

            # Ejecutar cleanup
            collector = SystemStatusCollector()
            collector.cleanup_old_snapshots(session)

            # Verificar que los registros de snapshots recientes no fueron afectados
            metrics_recientes_despues = session.query(MetricRecord).filter(
                MetricRecord.snapshot_id.in_(recent_ids)
            ).count()
            health_recientes_despues = session.query(HealthCheckResult).filter(
                HealthCheckResult.snapshot_id.in_(recent_ids)
            ).count()
            containers_recientes_despues = session.query(ContainerMetric).filter(
                ContainerMetric.snapshot_id.in_(recent_ids)
            ).count()

            assert metrics_recientes_despues == metrics_recientes_antes, (
                f"MetricRecords de snapshots recientes fueron afectados: "
                f"antes={metrics_recientes_antes}, después={metrics_recientes_despues}"
            )
            assert health_recientes_despues == health_recientes_antes, (
                f"HealthCheckResults de snapshots recientes fueron afectados: "
                f"antes={health_recientes_antes}, después={health_recientes_despues}"
            )
            assert containers_recientes_despues == containers_recientes_antes, (
                f"ContainerMetrics de snapshots recientes fueron afectados: "
                f"antes={containers_recientes_antes}, después={containers_recientes_despues}"
            )

            # Verificar que los snapshots antiguos sí fueron eliminados
            assert session.query(StatusSnapshot).filter(
                StatusSnapshot.id.notin_(recent_ids)
            ).count() == 0, (
                "Los snapshots antiguos deberían haber sido eliminados"
            )
