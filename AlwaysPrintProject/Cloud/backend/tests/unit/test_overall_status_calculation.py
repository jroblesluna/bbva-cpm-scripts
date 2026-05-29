"""
Tests unitarios para el cálculo de estado general y generación de alertas.

Verifica que calculate_overall_status() genera alertas correctas según
los umbrales definidos y determina el estado general del sistema.

**Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7**
"""

import pytest

from app.schemas.system_status import (
    AlertResponse,
    ContainerMetricsResponse,
    HealthCheckResponse,
    OsMetricsResponse,
)
from app.services.system_status import SystemStatusCollector


def _make_os_metrics(
    memory_percent: float = 50.0,
    disk_percent: float = 50.0,
    cpu_percent: float = 50.0,
) -> OsMetricsResponse:
    """Crea un OsMetricsResponse con valores por defecto saludables."""
    return OsMetricsResponse(
        memory_total_mb=16000.0,
        memory_used_mb=8000.0,
        memory_available_mb=8000.0,
        memory_percent=memory_percent,
        disk_total_mb=100000.0,
        disk_used_mb=50000.0,
        disk_available_mb=50000.0,
        disk_percent=disk_percent,
        cpu_percent=cpu_percent,
        swap_total_mb=4000.0,
        swap_used_mb=1000.0,
        swap_available_mb=3000.0,
        uptime_seconds=86400,
    )


def _make_health_checks(
    ssl_days_remaining: int = 30,
    ssl_classification: str = "valid",
) -> list:
    """Crea una lista de health checks con SSL configurable."""
    return [
        HealthCheckResponse(
            service_name="backend",
            is_available=True,
            latency_ms=50.0,
        ),
        HealthCheckResponse(
            service_name="ssl",
            is_available=True,
            latency_ms=100.0,
            details={
                "days_remaining": ssl_days_remaining,
                "classification": ssl_classification,
            },
        ),
    ]


def _make_docker_metrics(containers: list = None) -> list:
    """Crea una lista de métricas Docker con contenedores configurables."""
    if containers is None:
        return [
            ContainerMetricsResponse(
                name="backend",
                status="running",
                cpu_percent=5.0,
                memory_used_mb=256.0,
                memory_limit_mb=1024.0,
                network_rx_bytes=1000,
                network_tx_bytes=2000,
                uptime_seconds=3600,
            ),
        ]
    return containers


class TestCalculateOverallStatus:
    """Tests para el método calculate_overall_status()."""

    def setup_method(self):
        """Inicializar el collector para cada test."""
        self.collector = SystemStatusCollector()

    def test_estado_healthy_sin_alertas(self):
        """Sistema saludable: todas las métricas dentro de umbrales."""
        os_metrics = _make_os_metrics(
            memory_percent=70.0, disk_percent=60.0, cpu_percent=50.0
        )
        health_checks = _make_health_checks(ssl_days_remaining=30)
        docker_metrics = _make_docker_metrics()

        status, alerts = self.collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        assert status == "healthy"
        assert len(alerts) == 0

    def test_alerta_memoria_mayor_80_porciento(self):
        """Memoria > 80% genera alerta warning."""
        os_metrics = _make_os_metrics(memory_percent=85.0)
        health_checks = _make_health_checks(ssl_days_remaining=30)
        docker_metrics = _make_docker_metrics()

        status, alerts = self.collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        assert status == "degraded"
        memory_alerts = [a for a in alerts if a.metric_name == "memory"]
        assert len(memory_alerts) == 1
        assert memory_alerts[0].severity == "warning"
        assert memory_alerts[0].threshold == 80.0
        assert memory_alerts[0].current_value == 85.0

    def test_alerta_disco_mayor_85_porciento(self):
        """Disco > 85% genera alerta warning."""
        os_metrics = _make_os_metrics(disk_percent=90.0)
        health_checks = _make_health_checks(ssl_days_remaining=30)
        docker_metrics = _make_docker_metrics()

        status, alerts = self.collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        assert status == "degraded"
        disk_alerts = [a for a in alerts if a.metric_name == "disk"]
        assert len(disk_alerts) == 1
        assert disk_alerts[0].severity == "warning"
        assert disk_alerts[0].threshold == 85.0
        assert disk_alerts[0].current_value == 90.0

    def test_alerta_cpu_mayor_90_porciento_es_critical(self):
        """CPU > 90% genera alerta critical y estado critical."""
        os_metrics = _make_os_metrics(cpu_percent=95.0)
        health_checks = _make_health_checks(ssl_days_remaining=30)
        docker_metrics = _make_docker_metrics()

        status, alerts = self.collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        assert status == "critical"
        cpu_alerts = [a for a in alerts if a.metric_name == "cpu"]
        assert len(cpu_alerts) == 1
        assert cpu_alerts[0].severity == "critical"
        assert cpu_alerts[0].threshold == 90.0
        assert cpu_alerts[0].current_value == 95.0

    def test_alerta_ssl_menor_14_dias(self):
        """SSL < 14 días genera alerta warning."""
        os_metrics = _make_os_metrics()
        health_checks = _make_health_checks(
            ssl_days_remaining=7, ssl_classification="warning"
        )
        docker_metrics = _make_docker_metrics()

        status, alerts = self.collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        assert status == "degraded"
        ssl_alerts = [a for a in alerts if a.metric_name == "ssl"]
        assert len(ssl_alerts) == 1
        assert ssl_alerts[0].severity == "warning"
        assert ssl_alerts[0].threshold == 14.0
        assert ssl_alerts[0].current_value == 7.0

    def test_alerta_contenedor_no_running(self):
        """Contenedor no running genera alerta warning."""
        os_metrics = _make_os_metrics()
        health_checks = _make_health_checks(ssl_days_remaining=30)
        docker_metrics = [
            ContainerMetricsResponse(
                name="redis",
                status="stopped",
                cpu_percent=0.0,
                memory_used_mb=0.0,
                memory_limit_mb=512.0,
                network_rx_bytes=0,
                network_tx_bytes=0,
                uptime_seconds=0,
            ),
        ]

        status, alerts = self.collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        assert status == "degraded"
        container_alerts = [
            a for a in alerts if a.metric_name == "container_redis"
        ]
        assert len(container_alerts) == 1
        assert container_alerts[0].severity == "warning"
        assert container_alerts[0].current_value == 0.0

    def test_multiples_alertas_sin_critical_es_degraded(self):
        """Múltiples alertas warning sin ninguna critical → degraded."""
        os_metrics = _make_os_metrics(memory_percent=85.0, disk_percent=90.0)
        health_checks = _make_health_checks(ssl_days_remaining=30)
        docker_metrics = _make_docker_metrics()

        status, alerts = self.collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        assert status == "degraded"
        assert len(alerts) == 2

    def test_critical_prevalece_sobre_warnings(self):
        """Si hay una alerta critical, el estado es critical aunque haya warnings."""
        os_metrics = _make_os_metrics(
            memory_percent=85.0, disk_percent=90.0, cpu_percent=95.0
        )
        health_checks = _make_health_checks(ssl_days_remaining=30)
        docker_metrics = _make_docker_metrics()

        status, alerts = self.collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        assert status == "critical"
        assert len(alerts) == 3  # memoria, disco, cpu

    def test_umbral_exacto_memoria_80_no_genera_alerta(self):
        """Memoria exactamente en 80% NO genera alerta (solo > 80%)."""
        os_metrics = _make_os_metrics(memory_percent=80.0)
        health_checks = _make_health_checks(ssl_days_remaining=30)
        docker_metrics = _make_docker_metrics()

        status, alerts = self.collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        assert status == "healthy"
        assert len(alerts) == 0

    def test_umbral_exacto_disco_85_no_genera_alerta(self):
        """Disco exactamente en 85% NO genera alerta (solo > 85%)."""
        os_metrics = _make_os_metrics(disk_percent=85.0)
        health_checks = _make_health_checks(ssl_days_remaining=30)
        docker_metrics = _make_docker_metrics()

        status, alerts = self.collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        assert status == "healthy"
        assert len(alerts) == 0

    def test_umbral_exacto_cpu_90_no_genera_alerta(self):
        """CPU exactamente en 90% NO genera alerta (solo > 90%)."""
        os_metrics = _make_os_metrics(cpu_percent=90.0)
        health_checks = _make_health_checks(ssl_days_remaining=30)
        docker_metrics = _make_docker_metrics()

        status, alerts = self.collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        assert status == "healthy"
        assert len(alerts) == 0

    def test_ssl_exactamente_14_dias_no_genera_alerta(self):
        """SSL exactamente en 14 días NO genera alerta (solo < 14)."""
        os_metrics = _make_os_metrics()
        health_checks = _make_health_checks(ssl_days_remaining=14)
        docker_metrics = _make_docker_metrics()

        status, alerts = self.collector.calculate_overall_status(
            os_metrics, health_checks, docker_metrics
        )

        assert status == "healthy"
        assert len(alerts) == 0

    def test_sin_health_checks_ni_docker(self):
        """Sin health checks ni contenedores Docker, solo métricas OS."""
        os_metrics = _make_os_metrics()

        status, alerts = self.collector.calculate_overall_status(
            os_metrics, [], []
        )

        assert status == "healthy"
        assert len(alerts) == 0
