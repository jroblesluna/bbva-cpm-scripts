"""
Property tests para la generación de alertas por umbrales excedidos.

Verifica que el SystemStatusCollector genera alertas correctamente cuando
las métricas superan los umbrales definidos:
- Memoria > 80% → alerta severity "warning"
- Disco > 85% → alerta severity "warning"
- CPU > 90% → alerta severity "critical"
- SSL < 14 días → alerta severity "warning"

Y que las alertas desaparecen cuando los valores vuelven a estar dentro
de los umbrales.

**Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.7**

Feature: system-status-monitoring, Property 12: Threshold alert generation
"""

from typing import List

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.schemas.system_status import (
    AlertResponse,
    ContainerMetricsResponse,
    HealthCheckResponse,
    OsMetricsResponse,
)
from app.services.system_status import SystemStatusCollector


# === ESTRATEGIAS DE GENERACIÓN ===

# Porcentajes de métricas del sistema (0.0 a 100.0, 1 decimal)
_memory_percent = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False).map(
    lambda x: round(x, 1)
)
_disk_percent = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False).map(
    lambda x: round(x, 1)
)
_cpu_percent = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False).map(
    lambda x: round(x, 1)
)

# Días restantes del certificado SSL (-30 a 365)
_ssl_days_remaining = st.integers(min_value=-30, max_value=365)


def _build_os_metrics(
    memory_percent: float, disk_percent: float, cpu_percent: float
) -> OsMetricsResponse:
    """
    Construye un OsMetricsResponse con los porcentajes dados.

    Los valores absolutos (MB) se generan de forma coherente pero no son
    relevantes para la lógica de umbrales.
    """
    return OsMetricsResponse(
        memory_total_mb=8192.0,
        memory_used_mb=round(8192.0 * memory_percent / 100.0, 1),
        memory_available_mb=round(8192.0 * (100.0 - memory_percent) / 100.0, 1),
        memory_percent=memory_percent,
        disk_total_mb=51200.0,
        disk_used_mb=round(51200.0 * disk_percent / 100.0, 1),
        disk_available_mb=round(51200.0 * (100.0 - disk_percent) / 100.0, 1),
        disk_percent=disk_percent,
        cpu_percent=cpu_percent,
        swap_total_mb=2048.0,
        swap_used_mb=512.0,
        swap_available_mb=1536.0,
        uptime_seconds=86400,
    )


def _build_health_checks_with_ssl(ssl_days_remaining: int) -> List[HealthCheckResponse]:
    """
    Construye una lista de health checks incluyendo SSL con los días restantes dados.

    Incluye un health check de SSL con los detalles de días restantes y clasificación.
    """
    # Clasificar según días restantes
    if ssl_days_remaining > 14:
        classification = "valid"
    elif ssl_days_remaining >= 1:
        classification = "warning"
    else:
        classification = "expired"

    is_available = classification != "expired"

    return [
        HealthCheckResponse(
            service_name="backend",
            is_available=True,
            latency_ms=50.0,
            error_message=None,
            details=None,
        ),
        HealthCheckResponse(
            service_name="ssl",
            is_available=is_available,
            latency_ms=100.0,
            error_message=None if is_available else "Certificado SSL expirado",
            details={
                "days_remaining": ssl_days_remaining,
                "classification": classification,
            },
        ),
    ]


def _build_docker_metrics_all_running() -> List[ContainerMetricsResponse]:
    """
    Construye una lista de contenedores Docker todos en estado running.

    No genera alertas de contenedores para aislar las pruebas de umbrales de métricas.
    """
    return [
        ContainerMetricsResponse(
            name="backend",
            status="running",
            cpu_percent=5.0,
            memory_used_mb=256.0,
            memory_limit_mb=512.0,
            network_rx_bytes=1000,
            network_tx_bytes=2000,
            uptime_seconds=3600,
        ),
    ]


# === PROPERTY 12: THRESHOLD ALERT GENERATION ===


class TestThresholdAlertGeneration:
    """
    Property 12: Threshold alert generation.

    Para cualquier valor de métrica y su umbral definido (memoria > 80%,
    disco > 85%, CPU > 90%, SSL < 14 días), una Threshold_Alert SHALL
    ser generada si y solo si el valor excede el umbral. Cuando el valor
    vuelve dentro del umbral, la alerta SHALL no estar presente.

    **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.7**
    """

    @given(memory_percent=_memory_percent)
    @settings(max_examples=200, deadline=None)
    def test_alerta_memoria_generada_iff_supera_80_porciento(
        self, memory_percent: float
    ):
        """
        Se genera alerta de memoria si y solo si memory_percent > 80%.

        **Validates: Requirements 8.1**
        """
        # Construir métricas con el porcentaje de memoria dado
        os_metrics = _build_os_metrics(
            memory_percent=memory_percent, disk_percent=50.0, cpu_percent=50.0
        )
        health_checks = _build_health_checks_with_ssl(ssl_days_remaining=30)
        docker_metrics = _build_docker_metrics_all_running()

        collector = SystemStatusCollector()
        overall_status, alerts = collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        # Buscar alerta de memoria en la lista de alertas
        memory_alerts = [a for a in alerts if a.metric_name == "memory"]

        if memory_percent > 80.0:
            # Debe existir exactamente una alerta de memoria
            assert len(memory_alerts) == 1, (
                f"Se esperaba 1 alerta de memoria para {memory_percent}% > 80%, "
                f"pero se encontraron {len(memory_alerts)}"
            )
            assert memory_alerts[0].current_value == memory_percent
            assert memory_alerts[0].threshold == 80.0
            assert memory_alerts[0].severity == "warning"
        else:
            # No debe existir alerta de memoria
            assert len(memory_alerts) == 0, (
                f"No se esperaba alerta de memoria para {memory_percent}% <= 80%, "
                f"pero se encontraron {len(memory_alerts)}"
            )

    @given(disk_percent=_disk_percent)
    @settings(max_examples=200, deadline=None)
    def test_alerta_disco_generada_iff_supera_85_porciento(
        self, disk_percent: float
    ):
        """
        Se genera alerta de disco si y solo si disk_percent > 85%.

        **Validates: Requirements 8.2**
        """
        # Construir métricas con el porcentaje de disco dado
        os_metrics = _build_os_metrics(
            memory_percent=50.0, disk_percent=disk_percent, cpu_percent=50.0
        )
        health_checks = _build_health_checks_with_ssl(ssl_days_remaining=30)
        docker_metrics = _build_docker_metrics_all_running()

        collector = SystemStatusCollector()
        overall_status, alerts = collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        # Buscar alerta de disco en la lista de alertas
        disk_alerts = [a for a in alerts if a.metric_name == "disk"]

        if disk_percent > 85.0:
            # Debe existir exactamente una alerta de disco
            assert len(disk_alerts) == 1, (
                f"Se esperaba 1 alerta de disco para {disk_percent}% > 85%, "
                f"pero se encontraron {len(disk_alerts)}"
            )
            assert disk_alerts[0].current_value == disk_percent
            assert disk_alerts[0].threshold == 85.0
            assert disk_alerts[0].severity == "warning"
        else:
            # No debe existir alerta de disco
            assert len(disk_alerts) == 0, (
                f"No se esperaba alerta de disco para {disk_percent}% <= 85%, "
                f"pero se encontraron {len(disk_alerts)}"
            )

    @given(cpu_percent=_cpu_percent)
    @settings(max_examples=200, deadline=None)
    def test_alerta_cpu_generada_iff_supera_90_porciento(
        self, cpu_percent: float
    ):
        """
        Se genera alerta de CPU si y solo si cpu_percent > 90%.

        **Validates: Requirements 8.3**
        """
        # Construir métricas con el porcentaje de CPU dado
        os_metrics = _build_os_metrics(
            memory_percent=50.0, disk_percent=50.0, cpu_percent=cpu_percent
        )
        health_checks = _build_health_checks_with_ssl(ssl_days_remaining=30)
        docker_metrics = _build_docker_metrics_all_running()

        collector = SystemStatusCollector()
        overall_status, alerts = collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        # Buscar alerta de CPU en la lista de alertas
        cpu_alerts = [a for a in alerts if a.metric_name == "cpu"]

        if cpu_percent > 90.0:
            # Debe existir exactamente una alerta de CPU con severity critical
            assert len(cpu_alerts) == 1, (
                f"Se esperaba 1 alerta de CPU para {cpu_percent}% > 90%, "
                f"pero se encontraron {len(cpu_alerts)}"
            )
            assert cpu_alerts[0].current_value == cpu_percent
            assert cpu_alerts[0].threshold == 90.0
            assert cpu_alerts[0].severity == "critical"
        else:
            # No debe existir alerta de CPU
            assert len(cpu_alerts) == 0, (
                f"No se esperaba alerta de CPU para {cpu_percent}% <= 90%, "
                f"pero se encontraron {len(cpu_alerts)}"
            )

    @given(ssl_days=_ssl_days_remaining)
    @settings(max_examples=200, deadline=None)
    def test_alerta_ssl_generada_iff_dias_menor_a_14(self, ssl_days: int):
        """
        Se genera alerta de SSL si y solo si ssl_days_remaining < 14.

        **Validates: Requirements 8.4**
        """
        # Construir métricas con valores dentro de umbrales normales
        os_metrics = _build_os_metrics(
            memory_percent=50.0, disk_percent=50.0, cpu_percent=50.0
        )
        health_checks = _build_health_checks_with_ssl(ssl_days_remaining=ssl_days)
        docker_metrics = _build_docker_metrics_all_running()

        collector = SystemStatusCollector()
        overall_status, alerts = collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        # Buscar alerta de SSL en la lista de alertas
        ssl_alerts = [a for a in alerts if a.metric_name == "ssl"]

        if ssl_days < 14:
            # Debe existir exactamente una alerta de SSL
            assert len(ssl_alerts) == 1, (
                f"Se esperaba 1 alerta de SSL para {ssl_days} días < 14, "
                f"pero se encontraron {len(ssl_alerts)}"
            )
            assert ssl_alerts[0].current_value == float(ssl_days)
            assert ssl_alerts[0].threshold == 14.0
            assert ssl_alerts[0].severity == "warning"
        else:
            # No debe existir alerta de SSL
            assert len(ssl_alerts) == 0, (
                f"No se esperaba alerta de SSL para {ssl_days} días >= 14, "
                f"pero se encontraron {len(ssl_alerts)}"
            )

    @given(
        memory_percent=_memory_percent,
        disk_percent=_disk_percent,
        cpu_percent=_cpu_percent,
        ssl_days=_ssl_days_remaining,
    )
    @settings(max_examples=200, deadline=None)
    def test_sin_alertas_cuando_valores_dentro_de_umbrales(
        self,
        memory_percent: float,
        disk_percent: float,
        cpu_percent: float,
        ssl_days: int,
    ):
        """
        Cuando todos los valores están dentro de los umbrales, no se generan alertas
        de métricas (memoria, disco, CPU, SSL).

        **Validates: Requirements 8.7**
        """
        # Filtrar solo valores dentro de umbrales
        from hypothesis import assume

        assume(memory_percent <= 80.0)
        assume(disk_percent <= 85.0)
        assume(cpu_percent <= 90.0)
        assume(ssl_days >= 14)

        os_metrics = _build_os_metrics(
            memory_percent=memory_percent,
            disk_percent=disk_percent,
            cpu_percent=cpu_percent,
        )
        health_checks = _build_health_checks_with_ssl(ssl_days_remaining=ssl_days)
        docker_metrics = _build_docker_metrics_all_running()

        collector = SystemStatusCollector()
        overall_status, alerts = collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        # No debe haber alertas de métricas
        metric_alerts = [
            a for a in alerts
            if a.metric_name in ("memory", "disk", "cpu", "ssl")
        ]
        assert len(metric_alerts) == 0, (
            f"No se esperaban alertas con valores dentro de umbrales "
            f"(mem={memory_percent}%, disk={disk_percent}%, cpu={cpu_percent}%, "
            f"ssl={ssl_days} días), pero se encontraron: "
            f"{[a.metric_name for a in metric_alerts]}"
        )
        # Estado debe ser healthy (sin alertas de contenedores tampoco)
        assert overall_status == "healthy", (
            f"Estado esperado 'healthy' sin alertas, pero se obtuvo '{overall_status}'"
        )

    @given(
        memory_percent=_memory_percent,
        disk_percent=_disk_percent,
        cpu_percent=_cpu_percent,
        ssl_days=_ssl_days_remaining,
    )
    @settings(max_examples=200, deadline=None)
    def test_estado_critical_iff_cpu_supera_90(
        self,
        memory_percent: float,
        disk_percent: float,
        cpu_percent: float,
        ssl_days: int,
    ):
        """
        El estado general es "critical" si y solo si CPU > 90%.

        **Validates: Requirements 8.3**
        """
        os_metrics = _build_os_metrics(
            memory_percent=memory_percent,
            disk_percent=disk_percent,
            cpu_percent=cpu_percent,
        )
        health_checks = _build_health_checks_with_ssl(ssl_days_remaining=ssl_days)
        docker_metrics = _build_docker_metrics_all_running()

        collector = SystemStatusCollector()
        overall_status, alerts = collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        if cpu_percent > 90.0:
            assert overall_status == "critical", (
                f"Estado esperado 'critical' para CPU {cpu_percent}% > 90%, "
                f"pero se obtuvo '{overall_status}'"
            )
        else:
            assert overall_status != "critical", (
                f"Estado no debe ser 'critical' para CPU {cpu_percent}% <= 90%, "
                f"pero se obtuvo '{overall_status}'"
            )

    @given(
        memory_percent=_memory_percent,
        disk_percent=_disk_percent,
        cpu_percent=_cpu_percent,
        ssl_days=_ssl_days_remaining,
    )
    @settings(max_examples=200, deadline=None)
    def test_estado_degraded_iff_alertas_sin_critical(
        self,
        memory_percent: float,
        disk_percent: float,
        cpu_percent: float,
        ssl_days: int,
    ):
        """
        El estado general es "degraded" si hay alertas pero ninguna es critical.
        Es decir: hay alertas warning (memoria > 80%, disco > 85%, SSL < 14 días)
        pero CPU <= 90%.

        **Validates: Requirements 8.1, 8.2, 8.4**
        """
        from hypothesis import assume

        # Asegurar que CPU no supera 90% (no critical)
        assume(cpu_percent <= 90.0)

        os_metrics = _build_os_metrics(
            memory_percent=memory_percent,
            disk_percent=disk_percent,
            cpu_percent=cpu_percent,
        )
        health_checks = _build_health_checks_with_ssl(ssl_days_remaining=ssl_days)
        docker_metrics = _build_docker_metrics_all_running()

        collector = SystemStatusCollector()
        overall_status, alerts = collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        # Determinar si hay alguna alerta (sin contar contenedores)
        has_any_alert = (
            memory_percent > 80.0
            or disk_percent > 85.0
            or ssl_days < 14
        )

        if has_any_alert:
            assert overall_status == "degraded", (
                f"Estado esperado 'degraded' con alertas warning "
                f"(mem={memory_percent}%, disk={disk_percent}%, ssl={ssl_days} días), "
                f"pero se obtuvo '{overall_status}'"
            )
        else:
            assert overall_status == "healthy", (
                f"Estado esperado 'healthy' sin alertas "
                f"(mem={memory_percent}%, disk={disk_percent}%, ssl={ssl_days} días), "
                f"pero se obtuvo '{overall_status}'"
            )

    @given(
        cpu_percent=st.floats(
            min_value=90.1, max_value=100.0, allow_nan=False, allow_infinity=False
        ).map(lambda x: round(x, 1))
    )
    @settings(max_examples=200, deadline=None)
    def test_severidad_cpu_es_critical(self, cpu_percent: float):
        """
        La severidad de la alerta de CPU es siempre "critical" cuando se genera.

        **Validates: Requirements 8.3**
        """

        os_metrics = _build_os_metrics(
            memory_percent=50.0, disk_percent=50.0, cpu_percent=cpu_percent
        )
        health_checks = _build_health_checks_with_ssl(ssl_days_remaining=30)
        docker_metrics = _build_docker_metrics_all_running()

        collector = SystemStatusCollector()
        _, alerts = collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        cpu_alerts = [a for a in alerts if a.metric_name == "cpu"]
        assert len(cpu_alerts) == 1
        assert cpu_alerts[0].severity == "critical", (
            f"Severidad de alerta CPU debe ser 'critical', "
            f"pero se obtuvo '{cpu_alerts[0].severity}'"
        )

    @given(
        memory_percent=st.floats(min_value=80.1, max_value=100.0, allow_nan=False, allow_infinity=False).map(
            lambda x: round(x, 1)
        ),
        disk_percent=st.floats(min_value=85.1, max_value=100.0, allow_nan=False, allow_infinity=False).map(
            lambda x: round(x, 1)
        ),
        ssl_days=st.integers(min_value=-30, max_value=13),
    )
    @settings(max_examples=200, deadline=None)
    def test_severidad_warning_para_memoria_disco_ssl(
        self, memory_percent: float, disk_percent: float, ssl_days: int
    ):
        """
        La severidad de alertas de memoria, disco y SSL es siempre "warning".

        **Validates: Requirements 8.1, 8.2, 8.4**
        """
        os_metrics = _build_os_metrics(
            memory_percent=memory_percent,
            disk_percent=disk_percent,
            cpu_percent=50.0,
        )
        health_checks = _build_health_checks_with_ssl(ssl_days_remaining=ssl_days)
        docker_metrics = _build_docker_metrics_all_running()

        collector = SystemStatusCollector()
        _, alerts = collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        # Verificar severidad de cada tipo de alerta
        memory_alerts = [a for a in alerts if a.metric_name == "memory"]
        disk_alerts = [a for a in alerts if a.metric_name == "disk"]
        ssl_alerts = [a for a in alerts if a.metric_name == "ssl"]

        assert len(memory_alerts) == 1 and memory_alerts[0].severity == "warning", (
            f"Alerta de memoria debe tener severity 'warning'"
        )
        assert len(disk_alerts) == 1 and disk_alerts[0].severity == "warning", (
            f"Alerta de disco debe tener severity 'warning'"
        )
        assert len(ssl_alerts) == 1 and ssl_alerts[0].severity == "warning", (
            f"Alerta de SSL debe tener severity 'warning'"
        )
