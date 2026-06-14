"""
Property tests para la persistencia round-trip de snapshots.

Verifica que para cualquier StatusSnapshot válido con MetricRecords,
HealthCheckResults y ContainerMetrics asociados, persistir en la base
de datos y leer de vuelta produce datos equivalentes al original
(todos los campos coinciden dentro de tolerancia de punto flotante
para campos numéricos).

**Validates: Requirements 4.1, 4.2, 4.5**

Feature: system-status-monitoring, Property 9: Snapshot persistence round-trip
"""

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
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


# === TOLERANCIA PARA COMPARACIÓN DE PUNTO FLOTANTE ===

FLOAT_TOLERANCE = 1e-5


# === HELPER: SESIÓN DE BASE DE DATOS EN MEMORIA ===

@contextmanager
def create_test_session():
    """
    Crea una sesión de base de datos SQLite en memoria aislada.

    Cada invocación crea un engine nuevo con todas las tablas,
    garantizando aislamiento total entre iteraciones de Hypothesis.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# === ESTRATEGIAS DE GENERACIÓN ===

# Porcentajes válidos (0.0 a 100.0, 1 decimal)
_percent = st.floats(
    min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False
).map(lambda x: round(x, 1))

# Valores en MB (0.0 a 1_000_000.0, 1 decimal)
_mb_value = st.floats(
    min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False
).map(lambda x: round(x, 1))

# Uptime en segundos (0 a 10 años)
_uptime = st.integers(min_value=0, max_value=315_360_000)

# Bytes de red (0 a 10 TB)
_network_bytes = st.integers(min_value=0, max_value=10_000_000_000_000)

# Estado del contenedor
_container_status = st.sampled_from(["running", "stopped", "restarting"])

# Estado general del sistema
_overall_status = st.sampled_from(["healthy", "degraded", "critical"])

# Nombres de servicio para health checks
_service_name = st.sampled_from(["backend", "frontend", "nginx", "redis", "rds", "ssl"])

# Nombres de contenedor (alfanuméricos con guiones y guiones bajos)
_container_name = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-_"),
    min_size=1,
    max_size=50,
)

# Latencia en milisegundos (nullable)
_latency_ms = st.one_of(
    st.none(),
    st.floats(min_value=0.1, max_value=30000.0, allow_nan=False, allow_infinity=False).map(
        lambda x: round(x, 1)
    ),
)

# Mensaje de error (nullable, sin caracteres nulos para SQLite)
_error_message = st.one_of(
    st.none(),
    st.text(
        alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"),
        min_size=1,
        max_size=200,
    ),
)


# Estrategia para generar OsMetricsResponse válido
@st.composite
def os_metrics_strategy(draw):
    """Genera un OsMetricsResponse con valores aleatorios válidos."""
    memory_total = draw(st.floats(
        min_value=1.0, max_value=1_000_000.0,
        allow_nan=False, allow_infinity=False
    ).map(lambda x: round(x, 1)))
    memory_used = draw(st.floats(
        min_value=0.0, max_value=float(memory_total),
        allow_nan=False, allow_infinity=False
    ).map(lambda x: round(x, 1)))
    memory_available = round(memory_total - memory_used, 1)

    disk_total = draw(st.floats(
        min_value=1.0, max_value=1_000_000.0,
        allow_nan=False, allow_infinity=False
    ).map(lambda x: round(x, 1)))
    disk_used = draw(st.floats(
        min_value=0.0, max_value=float(disk_total),
        allow_nan=False, allow_infinity=False
    ).map(lambda x: round(x, 1)))
    disk_available = round(disk_total - disk_used, 1)

    swap_total = draw(st.floats(
        min_value=0.0, max_value=1_000_000.0,
        allow_nan=False, allow_infinity=False
    ).map(lambda x: round(x, 1)))
    swap_used = draw(st.floats(
        min_value=0.0, max_value=max(float(swap_total), 0.1),
        allow_nan=False, allow_infinity=False
    ).map(lambda x: round(x, 1)))
    swap_available = round(max(swap_total - swap_used, 0.0), 1)

    return OsMetricsResponse(
        memory_total_mb=memory_total,
        memory_used_mb=memory_used,
        memory_available_mb=memory_available,
        memory_percent=draw(_percent),
        disk_total_mb=disk_total,
        disk_used_mb=disk_used,
        disk_available_mb=disk_available,
        disk_percent=draw(_percent),
        cpu_percent=draw(_percent),
        swap_total_mb=swap_total,
        swap_used_mb=swap_used,
        swap_available_mb=swap_available,
        uptime_seconds=draw(_uptime),
    )


# Estrategia para generar HealthCheckResponse válido
@st.composite
def health_check_strategy(draw):
    """Genera un HealthCheckResponse con valores aleatorios válidos."""
    is_available = draw(st.booleans())
    service_name = draw(_service_name)

    # Generar detalles opcionales (solo para SSL)
    details = None
    if service_name == "ssl" and draw(st.booleans()):
        days_remaining = draw(st.integers(min_value=-30, max_value=365))
        if days_remaining > 14:
            classification = "valid"
        elif days_remaining >= 1:
            classification = "warning"
        else:
            classification = "expired"
        details = {"days_remaining": days_remaining, "classification": classification}

    return HealthCheckResponse(
        service_name=service_name,
        is_available=is_available,
        latency_ms=draw(_latency_ms),
        error_message=draw(_error_message) if not is_available else None,
        details=details,
    )


# Estrategia para generar ContainerMetricsResponse válido
@st.composite
def container_metrics_strategy(draw):
    """Genera un ContainerMetricsResponse con valores aleatorios válidos."""
    return ContainerMetricsResponse(
        name=draw(_container_name),
        status=draw(_container_status),
        cpu_percent=draw(_percent),
        memory_used_mb=draw(_mb_value),
        memory_limit_mb=draw(_mb_value),
        network_rx_bytes=draw(_network_bytes),
        network_tx_bytes=draw(_network_bytes),
        uptime_seconds=draw(_uptime),
    )


# === PROPERTY 9: SNAPSHOT PERSISTENCE ROUND-TRIP ===


class TestSnapshotPersistenceRoundTrip:
    """
    Property 9: Snapshot persistence round-trip.

    Para cualquier StatusSnapshot válido con MetricRecords, HealthCheckResults
    y ContainerMetrics asociados, persistir en la base de datos y leer de vuelta
    SHALL producir datos equivalentes al original (todos los campos coinciden
    dentro de tolerancia de punto flotante para campos numéricos).

    **Validates: Requirements 4.1, 4.2, 4.5**
    """

    @given(
        os_metrics=os_metrics_strategy(),
        overall_status=_overall_status,
        docker_available=st.booleans(),
        health_checks=st.lists(health_check_strategy(), min_size=1, max_size=6),
        docker_metrics=st.lists(container_metrics_strategy(), min_size=0, max_size=5),
    )
    @settings(max_examples=100, deadline=None)
    def test_snapshot_round_trip_campos_principales(
        self,
        os_metrics: OsMetricsResponse,
        overall_status: str,
        docker_available: bool,
        health_checks: list,
        docker_metrics: list,
    ):
        """
        Los campos principales del snapshot se preservan tras persistir y leer.

        Verifica que timestamp, overall_status, y todas las métricas del OS
        se mantienen intactas después del round-trip a la base de datos.

        **Validates: Requirements 4.1**
        """
        with create_test_session() as db_session:
            collector = SystemStatusCollector()
            timestamp = datetime.now(timezone.utc)

            # Persistir el snapshot
            snapshot = collector.save_snapshot(
                db=db_session,
                os_metrics=os_metrics,
                docker_available=docker_available,
                docker_metrics=docker_metrics,
                health_checks=health_checks,
                overall_status=overall_status,
                alerts=[],
                timestamp=timestamp,
            )

            assert snapshot is not None, "save_snapshot retornó None (falló la persistencia)"

            # Leer de vuelta desde la base de datos
            loaded = db_session.query(StatusSnapshot).filter(
                StatusSnapshot.id == snapshot.id
            ).first()

            assert loaded is not None, "No se encontró el snapshot en la base de datos"

            # Verificar campos principales del snapshot
            assert loaded.overall_status.value == overall_status
            assert loaded.docker_available == docker_available
            assert loaded.uptime_seconds == os_metrics.uptime_seconds

            # Verificar métricas de memoria (tolerancia de punto flotante)
            assert abs(loaded.memory_percent - os_metrics.memory_percent) < FLOAT_TOLERANCE
            assert abs(loaded.memory_total_mb - os_metrics.memory_total_mb) < FLOAT_TOLERANCE
            assert abs(loaded.memory_used_mb - os_metrics.memory_used_mb) < FLOAT_TOLERANCE
            assert abs(loaded.memory_available_mb - os_metrics.memory_available_mb) < FLOAT_TOLERANCE

            # Verificar métricas de disco
            assert abs(loaded.disk_percent - os_metrics.disk_percent) < FLOAT_TOLERANCE
            assert abs(loaded.disk_total_mb - os_metrics.disk_total_mb) < FLOAT_TOLERANCE
            assert abs(loaded.disk_used_mb - os_metrics.disk_used_mb) < FLOAT_TOLERANCE
            assert abs(loaded.disk_available_mb - os_metrics.disk_available_mb) < FLOAT_TOLERANCE

            # Verificar métricas de CPU
            assert abs(loaded.cpu_percent - os_metrics.cpu_percent) < FLOAT_TOLERANCE

            # Verificar métricas de swap
            assert abs(loaded.swap_total_mb - os_metrics.swap_total_mb) < FLOAT_TOLERANCE
            assert abs(loaded.swap_used_mb - os_metrics.swap_used_mb) < FLOAT_TOLERANCE
            assert abs(loaded.swap_available_mb - os_metrics.swap_available_mb) < FLOAT_TOLERANCE

    @given(
        os_metrics=os_metrics_strategy(),
        overall_status=_overall_status,
        health_checks=st.lists(health_check_strategy(), min_size=1, max_size=6),
    )
    @settings(max_examples=100, deadline=None)
    def test_metric_records_round_trip(
        self,
        os_metrics: OsMetricsResponse,
        overall_status: str,
        health_checks: list,
    ):
        """
        Los MetricRecords se persisten correctamente con nombre, valor y unidad.

        Verifica que cada métrica del OS se almacena como un MetricRecord
        individual y que los valores coinciden con los originales.

        **Validates: Requirements 4.2**
        """
        with create_test_session() as db_session:
            collector = SystemStatusCollector()
            timestamp = datetime.now(timezone.utc)

            # Persistir el snapshot
            snapshot = collector.save_snapshot(
                db=db_session,
                os_metrics=os_metrics,
                docker_available=True,
                docker_metrics=[],
                health_checks=health_checks,
                overall_status=overall_status,
                alerts=[],
                timestamp=timestamp,
            )

            assert snapshot is not None, "save_snapshot retornó None"

            # Leer MetricRecords desde la base de datos
            records = db_session.query(MetricRecord).filter(
                MetricRecord.snapshot_id == snapshot.id
            ).all()

            # Debe haber 14 métricas del OS (definidas en _persist_snapshot_transaction)
            assert len(records) == 14, (
                f"Se esperaban 14 MetricRecords, se encontraron {len(records)}"
            )

            # Construir diccionario de métricas para verificación
            records_dict = {r.metric_name: r for r in records}

            # Verificar cada métrica individualmente
            expected_metrics = {
                "memory_percent": (os_metrics.memory_percent, "percent"),
                "memory_total_mb": (os_metrics.memory_total_mb, "mb"),
                "memory_used_mb": (os_metrics.memory_used_mb, "mb"),
                "memory_available_mb": (os_metrics.memory_available_mb, "mb"),
                "disk_percent": (os_metrics.disk_percent, "percent"),
                "disk_total_mb": (os_metrics.disk_total_mb, "mb"),
                "disk_used_mb": (os_metrics.disk_used_mb, "mb"),
                "disk_available_mb": (os_metrics.disk_available_mb, "mb"),
                "cpu_percent": (os_metrics.cpu_percent, "percent"),
                "swap_total_mb": (os_metrics.swap_total_mb, "mb"),
                "swap_used_mb": (os_metrics.swap_used_mb, "mb"),
                "swap_available_mb": (os_metrics.swap_available_mb, "mb"),
                "uptime_seconds": (float(os_metrics.uptime_seconds), "seconds"),
            }

            for metric_name, (expected_value, expected_unit) in expected_metrics.items():
                assert metric_name in records_dict, (
                    f"MetricRecord '{metric_name}' no encontrado en la base de datos"
                )
                record = records_dict[metric_name]
                assert abs(record.value - expected_value) < FLOAT_TOLERANCE, (
                    f"Valor de '{metric_name}': esperado {expected_value}, "
                    f"obtenido {record.value}"
                )
                assert record.unit == expected_unit, (
                    f"Unidad de '{metric_name}': esperada '{expected_unit}', "
                    f"obtenida '{record.unit}'"
                )

    @given(
        os_metrics=os_metrics_strategy(),
        overall_status=_overall_status,
        health_checks=st.lists(health_check_strategy(), min_size=1, max_size=6),
    )
    @settings(max_examples=100, deadline=None)
    def test_health_check_results_round_trip(
        self,
        os_metrics: OsMetricsResponse,
        overall_status: str,
        health_checks: list,
    ):
        """
        Los HealthCheckResults se persisten correctamente con todos sus campos.

        Verifica que service_name, is_available, latency_ms, error_message
        y details_json se preservan tras el round-trip.

        **Validates: Requirements 4.5**
        """
        with create_test_session() as db_session:
            collector = SystemStatusCollector()
            timestamp = datetime.now(timezone.utc)

            # Persistir el snapshot
            snapshot = collector.save_snapshot(
                db=db_session,
                os_metrics=os_metrics,
                docker_available=True,
                docker_metrics=[],
                health_checks=health_checks,
                overall_status=overall_status,
                alerts=[],
                timestamp=timestamp,
            )

            assert snapshot is not None, "save_snapshot retornó None"

            # Leer HealthCheckResults desde la base de datos
            results = db_session.query(HealthCheckResult).filter(
                HealthCheckResult.snapshot_id == snapshot.id
            ).all()

            # Debe haber el mismo número de health checks
            assert len(results) == len(health_checks), (
                f"Se esperaban {len(health_checks)} HealthCheckResults, "
                f"se encontraron {len(results)}"
            )

            # Ordenar ambas listas por service_name para comparación consistente
            # (puede haber duplicados de service_name, así que comparamos en orden de inserción)
            # Los resultados de la BD mantienen el orden de inserción en SQLite
            for i, original in enumerate(health_checks):
                # Buscar resultado correspondiente por posición
                result = results[i]

                # Verificar campos
                assert result.service_name == original.service_name, (
                    f"service_name[{i}]: esperado '{original.service_name}', "
                    f"obtenido '{result.service_name}'"
                )
                assert result.is_available == original.is_available, (
                    f"is_available[{i}]: esperado {original.is_available}, "
                    f"obtenido {result.is_available}"
                )

                # Latencia (nullable, tolerancia de punto flotante)
                if original.latency_ms is None:
                    assert result.latency_ms is None
                else:
                    assert result.latency_ms is not None
                    assert abs(result.latency_ms - original.latency_ms) < FLOAT_TOLERANCE

                # Mensaje de error (nullable)
                assert result.error_message == original.error_message

                # Detalles JSON (nullable)
                if original.details is None:
                    assert result.details_json is None
                else:
                    loaded_details = json.loads(result.details_json)
                    assert loaded_details == original.details, (
                        f"Detalles JSON no coinciden para '{original.service_name}': "
                        f"esperado {original.details}, obtenido {loaded_details}"
                    )

    @given(
        os_metrics=os_metrics_strategy(),
        overall_status=_overall_status,
        docker_metrics=st.lists(container_metrics_strategy(), min_size=1, max_size=5),
    )
    @settings(max_examples=100, deadline=None)
    def test_container_metrics_round_trip(
        self,
        os_metrics: OsMetricsResponse,
        overall_status: str,
        docker_metrics: list,
    ):
        """
        Los ContainerMetrics se persisten correctamente con todos sus campos.

        Verifica que container_name, status, cpu_percent, memory_used_mb,
        memory_limit_mb, network_rx_bytes, network_tx_bytes y uptime_seconds
        se preservan tras el round-trip.

        **Validates: Requirements 4.1, 4.5**
        """
        with create_test_session() as db_session:
            collector = SystemStatusCollector()
            timestamp = datetime.now(timezone.utc)

            # Health check mínimo para cumplir requisitos
            health_checks = [
                HealthCheckResponse(
                    service_name="backend",
                    is_available=True,
                    latency_ms=50.0,
                    error_message=None,
                    details=None,
                )
            ]

            # Persistir el snapshot
            snapshot = collector.save_snapshot(
                db=db_session,
                os_metrics=os_metrics,
                docker_available=True,
                docker_metrics=docker_metrics,
                health_checks=health_checks,
                overall_status=overall_status,
                alerts=[],
                timestamp=timestamp,
            )

            assert snapshot is not None, "save_snapshot retornó None"

            # Leer ContainerMetrics desde la base de datos
            results = db_session.query(ContainerMetric).filter(
                ContainerMetric.snapshot_id == snapshot.id
            ).all()

            # Debe haber el mismo número de container metrics
            assert len(results) == len(docker_metrics), (
                f"Se esperaban {len(docker_metrics)} ContainerMetrics, "
                f"se encontraron {len(results)}"
            )

            # Comparar en orden de inserción (SQLite mantiene orden)
            for i, (result, original) in enumerate(zip(results, docker_metrics)):
                # Verificar campos de texto
                assert result.container_name == original.name, (
                    f"container_name[{i}]: esperado '{original.name}', "
                    f"obtenido '{result.container_name}'"
                )
                assert result.status == original.status, (
                    f"status[{i}]: esperado '{original.status}', "
                    f"obtenido '{result.status}'"
                )

                # Verificar campos numéricos con tolerancia de punto flotante
                assert abs(result.cpu_percent - original.cpu_percent) < FLOAT_TOLERANCE, (
                    f"cpu_percent[{i}]: esperado {original.cpu_percent}, "
                    f"obtenido {result.cpu_percent}"
                )
                assert abs(result.memory_used_mb - original.memory_used_mb) < FLOAT_TOLERANCE, (
                    f"memory_used_mb[{i}]: esperado {original.memory_used_mb}, "
                    f"obtenido {result.memory_used_mb}"
                )
                assert abs(result.memory_limit_mb - original.memory_limit_mb) < FLOAT_TOLERANCE, (
                    f"memory_limit_mb[{i}]: esperado {original.memory_limit_mb}, "
                    f"obtenido {result.memory_limit_mb}"
                )

                # Verificar campos enteros (exactos)
                assert result.network_rx_bytes == original.network_rx_bytes, (
                    f"network_rx_bytes[{i}]: esperado {original.network_rx_bytes}, "
                    f"obtenido {result.network_rx_bytes}"
                )
                assert result.network_tx_bytes == original.network_tx_bytes, (
                    f"network_tx_bytes[{i}]: esperado {original.network_tx_bytes}, "
                    f"obtenido {result.network_tx_bytes}"
                )
                assert result.uptime_seconds == original.uptime_seconds, (
                    f"uptime_seconds[{i}]: esperado {original.uptime_seconds}, "
                    f"obtenido {result.uptime_seconds}"
                )

    @given(
        os_metrics=os_metrics_strategy(),
        overall_status=_overall_status,
        docker_available=st.booleans(),
        health_checks=st.lists(health_check_strategy(), min_size=1, max_size=6),
        docker_metrics=st.lists(container_metrics_strategy(), min_size=0, max_size=5),
    )
    @settings(max_examples=100, deadline=None)
    def test_snapshot_completo_round_trip(
        self,
        os_metrics: OsMetricsResponse,
        overall_status: str,
        docker_available: bool,
        health_checks: list,
        docker_metrics: list,
    ):
        """
        Un snapshot completo con todos sus hijos se preserva íntegramente.

        Verifica que la cantidad de registros hijos (MetricRecords,
        HealthCheckResults, ContainerMetrics) coincide con los datos
        originales después del round-trip.

        **Validates: Requirements 4.1, 4.2, 4.5**
        """
        with create_test_session() as db_session:
            collector = SystemStatusCollector()
            timestamp = datetime.now(timezone.utc)

            # Persistir el snapshot completo
            snapshot = collector.save_snapshot(
                db=db_session,
                os_metrics=os_metrics,
                docker_available=docker_available,
                docker_metrics=docker_metrics,
                health_checks=health_checks,
                overall_status=overall_status,
                alerts=[],
                timestamp=timestamp,
            )

            assert snapshot is not None, "save_snapshot retornó None"

            # Verificar conteo de registros hijos
            metric_count = db_session.query(MetricRecord).filter(
                MetricRecord.snapshot_id == snapshot.id
            ).count()
            health_count = db_session.query(HealthCheckResult).filter(
                HealthCheckResult.snapshot_id == snapshot.id
            ).count()
            container_count = db_session.query(ContainerMetric).filter(
                ContainerMetric.snapshot_id == snapshot.id
            ).count()

            # 14 métricas del OS siempre (incluyendo swap_percent)
            assert metric_count == 14, (
                f"MetricRecords: esperados 14, encontrados {metric_count}"
            )
            assert health_count == len(health_checks), (
                f"HealthCheckResults: esperados {len(health_checks)}, "
                f"encontrados {health_count}"
            )
            assert container_count == len(docker_metrics), (
                f"ContainerMetrics: esperados {len(docker_metrics)}, "
                f"encontrados {container_count}"
            )

            # Verificar que el snapshot tiene un ID válido (UUID)
            assert snapshot.id is not None
            assert isinstance(snapshot.id, uuid.UUID)
