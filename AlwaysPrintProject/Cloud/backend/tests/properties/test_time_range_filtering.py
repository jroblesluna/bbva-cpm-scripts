"""
Property tests para el filtrado por rango temporal de métricas históricas.

Verifica que para cualquier conjunto de MetricRecords y un rango temporal
seleccionado (7, 14 o 30 días), la consulta de historial retorna SOLO
los data points cuyo timestamp cae dentro del rango (now - days, now],
y excluye todos los data points fuera de ese rango.

**Validates: Requirements 7.1, 7.2**

Feature: system-status-monitoring, Property 13: Time range filtering
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base

# Importar todos los modelos para que Base.metadata conozca todas las tablas
import app.models  # noqa: F401

from app.models.system_status import (
    MetricRecord,
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

# Rangos temporales válidos según el diseño (7, 14 o 30 días)
_time_ranges = st.sampled_from([7, 14, 30])

# Días de antigüedad de un data point (0 a 60 días atrás)
_days_ago = st.floats(min_value=0.01, max_value=60.0, allow_nan=False, allow_infinity=False)

# Lista de data points con timestamps variados (entre 2 y 20 registros)
_data_points_days = st.lists(
    _days_ago,
    min_size=2,
    max_size=20,
)

# Nombres de métricas válidos para generar variedad
_metric_names = st.sampled_from([
    "cpu_percent", "memory_percent", "disk_percent", "swap_used_mb"
])

# Valores de métrica (0 a 100 para porcentajes, hasta 32768 para MB)
_metric_values = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)


def _crear_snapshot_con_metricas(
    session: Session,
    metric_name: str,
    data_points_days_ago: list,
) -> tuple:
    """
    Crea un StatusSnapshot padre y MetricRecords con timestamps variados.

    Cada data point se crea con un timestamp calculado como (now - days_ago).
    Retorna la lista de timestamps creados para verificación posterior.

    Parámetros:
        session: Sesión SQLAlchemy
        metric_name: Nombre de la métrica para los registros
        data_points_days_ago: Lista de días de antigüedad para cada data point

    Retorna:
        Tupla (snapshot_id, lista de timestamps creados)
    """
    now = datetime.now(timezone.utc)

    # Crear snapshot padre (necesario por la FK)
    snapshot = StatusSnapshot(
        id=uuid.uuid4(),
        timestamp=now,
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

    # Crear MetricRecords con timestamps variados
    timestamps_creados = []
    for days in data_points_days_ago:
        ts = now - timedelta(days=days)
        metric = MetricRecord(
            id=uuid.uuid4(),
            snapshot_id=snapshot.id,
            metric_name=metric_name,
            value=round(days * 2.5, 1),  # Valor arbitrario basado en días
            unit="percent" if metric_name.endswith("_percent") else "mb",
            timestamp=ts,
        )
        session.add(metric)
        timestamps_creados.append(ts)

    session.flush()
    return snapshot.id, timestamps_creados


def _query_metric_history(session: Session, metric_name: str, days: int):
    """
    Replica la lógica de filtrado del endpoint get_metric_history.

    Aplica el mismo filtro que usa el endpoint: MetricRecords donde
    metric_name coincide y timestamp está en el rango (now - days, now].

    Parámetros:
        session: Sesión SQLAlchemy
        metric_name: Nombre de la métrica a filtrar
        days: Número de días del rango temporal

    Retorna:
        Lista de MetricRecords que pasan el filtro
    """
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days)

    # Misma lógica que el endpoint get_metric_history
    records = (
        session.query(MetricRecord)
        .filter(
            MetricRecord.metric_name == metric_name,
            MetricRecord.timestamp >= start_date,
            MetricRecord.timestamp <= now,
        )
        .order_by(MetricRecord.timestamp)
        .all()
    )

    return records


# === PROPERTY 13: TIME RANGE FILTERING ===


class TestTimeRangeFiltering:
    """
    Property 13: Time range filtering.

    Para cualquier conjunto de data points de métricas y un rango temporal
    seleccionado (7, 14 o 30 días), la consulta de historial SHALL retornar
    solo los data points cuyo timestamp cae dentro del rango seleccionado
    (now - days, now], y SHALL excluir todos los data points fuera de ese rango.

    **Validates: Requirements 7.1, 7.2**
    """

    @given(
        data_points_days=_data_points_days,
        time_range=_time_ranges,
        metric_name=_metric_names,
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_solo_retorna_data_points_dentro_del_rango(
        self,
        data_points_days: list,
        time_range: int,
        metric_name: str,
    ):
        """
        Todos los data points retornados tienen timestamp dentro del rango.

        Verifica que cada registro retornado por la consulta tiene un
        timestamp >= (now - days) y <= now.

        **Validates: Requirements 7.1, 7.2**
        """
        with create_test_session() as session:
            # Crear data points con timestamps variados
            _crear_snapshot_con_metricas(session, metric_name, data_points_days)
            session.commit()

            # Ejecutar consulta con el rango temporal
            now = datetime.now(timezone.utc)
            start_date = now - timedelta(days=time_range)
            results = _query_metric_history(session, metric_name, time_range)

            # Verificar que todos los resultados están dentro del rango
            for record in results:
                # SQLite puede devolver timestamps naive, normalizar
                record_ts = record.timestamp
                if record_ts.tzinfo is None:
                    record_ts = record_ts.replace(tzinfo=timezone.utc)

                assert record_ts >= start_date, (
                    f"Data point con timestamp {record_ts} está ANTES del "
                    f"inicio del rango {start_date} (rango: {time_range} días)"
                )
                assert record_ts <= now, (
                    f"Data point con timestamp {record_ts} está DESPUÉS de "
                    f"now {now} (rango: {time_range} días)"
                )

    @given(
        data_points_days=_data_points_days,
        time_range=_time_ranges,
        metric_name=_metric_names,
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_excluye_data_points_fuera_del_rango(
        self,
        data_points_days: list,
        time_range: int,
        metric_name: str,
    ):
        """
        Ningún data point fuera del rango temporal es incluido en los resultados.

        Verifica que los data points con timestamp < (now - days) NO aparecen
        en los resultados de la consulta.

        **Validates: Requirements 7.1, 7.2**
        """
        with create_test_session() as session:
            # Crear data points con timestamps variados
            _, timestamps = _crear_snapshot_con_metricas(
                session, metric_name, data_points_days
            )
            session.commit()

            # Ejecutar consulta con el rango temporal
            now = datetime.now(timezone.utc)
            start_date = now - timedelta(days=time_range)
            results = _query_metric_history(session, metric_name, time_range)

            # Obtener timestamps de los resultados (normalizar a naive para comparar)
            result_timestamps = set()
            for r in results:
                ts = r.timestamp
                if ts.tzinfo is not None:
                    ts = ts.replace(tzinfo=None)
                result_timestamps.add(ts)

            # Verificar que ningún data point fuera del rango fue incluido
            for i, days in enumerate(data_points_days):
                ts = timestamps[i]
                if ts.tzinfo is not None:
                    ts_naive = ts.replace(tzinfo=None)
                else:
                    ts_naive = ts

                start_naive = start_date.replace(tzinfo=None)
                now_naive = now.replace(tzinfo=None)

                # Si el timestamp está fuera del rango, no debe estar en resultados
                if ts_naive < start_naive or ts_naive > now_naive:
                    assert ts_naive not in result_timestamps, (
                        f"Data point con timestamp {ts} (días atrás: {days}) "
                        f"está FUERA del rango [{start_date}, {now}] pero fue "
                        f"incluido en los resultados (rango: {time_range} días)"
                    )

    @given(
        data_points_days=_data_points_days,
        time_range=_time_ranges,
        metric_name=_metric_names,
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_incluye_todos_los_data_points_dentro_del_rango(
        self,
        data_points_days: list,
        time_range: int,
        metric_name: str,
    ):
        """
        Todos los data points dentro del rango temporal son incluidos.

        Verifica completitud: si un data point tiene timestamp dentro de
        (now - days, now], DEBE aparecer en los resultados.

        **Validates: Requirements 7.1, 7.2**
        """
        with create_test_session() as session:
            # Crear data points con timestamps variados
            _, timestamps = _crear_snapshot_con_metricas(
                session, metric_name, data_points_days
            )
            session.commit()

            # Ejecutar consulta con el rango temporal
            now = datetime.now(timezone.utc)
            start_date = now - timedelta(days=time_range)
            results = _query_metric_history(session, metric_name, time_range)

            # Contar cuántos data points deberían estar dentro del rango
            esperados_dentro = 0
            for ts in timestamps:
                ts_compare = ts
                if ts_compare.tzinfo is None:
                    ts_compare = ts_compare.replace(tzinfo=timezone.utc)
                start_compare = start_date
                now_compare = now
                if ts_compare >= start_compare and ts_compare <= now_compare:
                    esperados_dentro += 1

            assert len(results) == esperados_dentro, (
                f"Se esperaban {esperados_dentro} data points dentro del rango "
                f"de {time_range} días, pero se obtuvieron {len(results)}. "
                f"Días generados: {data_points_days}"
            )

    @given(
        time_range=_time_ranges,
        metric_name=_metric_names,
    )
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_rango_vacio_retorna_cero_resultados(
        self,
        time_range: int,
        metric_name: str,
    ):
        """
        Si no hay data points en el rango, la consulta retorna lista vacía.

        Crea data points SOLO fuera del rango y verifica que no se retorna nada.

        **Validates: Requirements 7.1, 7.2**
        """
        with create_test_session() as session:
            # Crear data points SOLO fuera del rango (más antiguos que el rango)
            days_fuera = [time_range + 5.0, time_range + 10.0, time_range + 20.0]
            _crear_snapshot_con_metricas(session, metric_name, days_fuera)
            session.commit()

            # Ejecutar consulta
            results = _query_metric_history(session, metric_name, time_range)

            assert len(results) == 0, (
                f"Se esperaban 0 resultados para data points fuera del rango "
                f"de {time_range} días, pero se obtuvieron {len(results)}"
            )

    @given(
        metric_name=_metric_names,
    )
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_filtrado_no_mezcla_metricas_diferentes(
        self,
        metric_name: str,
    ):
        """
        El filtrado por rango temporal solo retorna la métrica solicitada.

        Crea data points de múltiples métricas dentro del rango y verifica
        que solo se retornan los de la métrica consultada.

        **Validates: Requirements 7.1, 7.2**
        """
        with create_test_session() as session:
            now = datetime.now(timezone.utc)

            # Crear snapshot padre
            snapshot = StatusSnapshot(
                id=uuid.uuid4(),
                timestamp=now,
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

            # Crear data points de la métrica objetivo (dentro del rango)
            todas_metricas = [
                "cpu_percent", "memory_percent", "disk_percent", "swap_used_mb"
            ]
            for m in todas_metricas:
                for i in range(3):
                    ts = now - timedelta(days=i + 1)
                    record = MetricRecord(
                        id=uuid.uuid4(),
                        snapshot_id=snapshot.id,
                        metric_name=m,
                        value=float(i * 10 + 20),
                        unit="percent" if m.endswith("_percent") else "mb",
                        timestamp=ts,
                    )
                    session.add(record)

            session.flush()
            session.commit()

            # Consultar solo la métrica objetivo con rango de 7 días
            results = _query_metric_history(session, metric_name, 7)

            # Verificar que todos los resultados son de la métrica correcta
            for record in results:
                assert record.metric_name == metric_name, (
                    f"Se retornó un data point de métrica '{record.metric_name}' "
                    f"cuando se consultó '{metric_name}'"
                )

            # Verificar que se retornaron exactamente 3 (los que creamos para esa métrica)
            assert len(results) == 3, (
                f"Se esperaban 3 data points de '{metric_name}', "
                f"pero se obtuvieron {len(results)}"
            )
