"""
Tests unitarios para la recolección de métricas Docker.

Verifica el comportamiento de collect_docker_metrics() y métodos auxiliares:
- Conexión exitosa al daemon Docker
- Manejo de daemon no disponible (docker_available=False)
- Cálculo de CPU% usando la fórmula oficial de Docker
- Conversión de memoria a MB
- Extracción de network I/O
- Manejo de contenedores detenidos (sin stats)
- Cálculo de uptime del contenedor
"""

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

from app.services.system_status import SystemStatusCollector, BYTES_TO_MB


class TestCollectDockerMetrics:
    """Tests para el método collect_docker_metrics()."""

    @pytest.fixture
    def collector(self):
        """Instancia del collector para tests."""
        return SystemStatusCollector()

    def test_docker_daemon_no_disponible(self, collector):
        """Si Docker daemon no está disponible, retorna docker_available=False."""
        with patch("app.services.system_status.docker") as mock_docker:
            mock_docker.from_env.side_effect = Exception("Connection refused")
            mock_docker.errors.DockerException = Exception

            result = asyncio.run(collector.collect_docker_metrics())

        docker_available, metrics = result
        assert docker_available is False
        assert metrics == []

    def test_docker_ping_falla(self, collector):
        """Si el ping al daemon falla, retorna docker_available=False."""
        with patch("app.services.system_status.docker") as mock_docker:
            mock_client = MagicMock()
            mock_client.ping.side_effect = Exception("Daemon not responding")
            mock_docker.from_env.return_value = mock_client
            mock_docker.errors.DockerException = Exception

            result = asyncio.run(collector.collect_docker_metrics())

        docker_available, metrics = result
        assert docker_available is False
        assert metrics == []

    def test_contenedor_running_con_stats(self, collector):
        """Contenedor running retorna métricas completas."""
        # Preparar mock de contenedor
        mock_container = MagicMock()
        mock_container.name = "alwaysprint-backend-1"
        mock_container.status = "running"
        mock_container.attrs = {
            "State": {
                "StartedAt": "2024-06-01T10:00:00.000000000Z"
            }
        }
        mock_container.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200000000, "percpu_usage": [100000000, 100000000]},
                "system_cpu_usage": 10000000000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100000000, "percpu_usage": [50000000, 50000000]},
                "system_cpu_usage": 9000000000,
            },
            "memory_stats": {
                "usage": 256 * BYTES_TO_MB,  # 256 MB
                "limit": 1024 * BYTES_TO_MB,  # 1024 MB
            },
            "networks": {
                "eth0": {
                    "rx_bytes": 1000000,
                    "tx_bytes": 500000,
                }
            },
        }

        with patch("app.services.system_status.docker") as mock_docker:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_client.containers.list.return_value = [mock_container]
            mock_docker.from_env.return_value = mock_client
            mock_docker.errors.DockerException = Exception

            result = asyncio.run(collector.collect_docker_metrics())

        docker_available, metrics = result
        assert docker_available is True
        assert len(metrics) == 1

        m = metrics[0]
        assert m.name == "alwaysprint-backend-1"
        assert m.status == "running"
        assert m.memory_used_mb == 256.0
        assert m.memory_limit_mb == 1024.0
        assert m.network_rx_bytes == 1000000
        assert m.network_tx_bytes == 500000
        assert m.cpu_percent >= 0.0

    def test_contenedor_stopped_sin_stats(self, collector):
        """Contenedor detenido retorna valores de 0 para CPU, memoria y red."""
        mock_container = MagicMock()
        mock_container.name = "alwaysprint-redis-1"
        mock_container.status = "exited"
        mock_container.attrs = {
            "State": {
                "StartedAt": "2024-06-01T10:00:00.000000000Z"
            }
        }

        with patch("app.services.system_status.docker") as mock_docker:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_client.containers.list.return_value = [mock_container]
            mock_docker.from_env.return_value = mock_client
            mock_docker.errors.DockerException = Exception

            result = asyncio.run(collector.collect_docker_metrics())

        docker_available, metrics = result
        assert docker_available is True
        assert len(metrics) == 1

        m = metrics[0]
        assert m.name == "alwaysprint-redis-1"
        assert m.status == "stopped"  # 'exited' se normaliza a 'stopped'
        assert m.cpu_percent == 0.0
        assert m.memory_used_mb == 0.0
        assert m.memory_limit_mb == 0.0
        assert m.network_rx_bytes == 0
        assert m.network_tx_bytes == 0

    def test_timeout_configurado_a_10_segundos(self, collector):
        """El cliente Docker se crea con timeout=10."""
        with patch("app.services.system_status.docker") as mock_docker:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_client.containers.list.return_value = []
            mock_docker.from_env.return_value = mock_client
            mock_docker.errors.DockerException = Exception

            asyncio.run(collector.collect_docker_metrics())

        mock_docker.from_env.assert_called_once_with(timeout=10)

    def test_multiples_contenedores(self, collector):
        """Se recolectan métricas de múltiples contenedores."""
        containers = []
        for name in ["backend-1", "frontend-1", "redis-1"]:
            mock_c = MagicMock()
            mock_c.name = name
            mock_c.status = "running"
            mock_c.attrs = {"State": {"StartedAt": "2024-06-01T10:00:00.000000000Z"}}
            mock_c.stats.return_value = {
                "cpu_stats": {
                    "cpu_usage": {"total_usage": 200, "percpu_usage": [100, 100]},
                    "system_cpu_usage": 10000,
                    "online_cpus": 2,
                },
                "precpu_stats": {
                    "cpu_usage": {"total_usage": 100, "percpu_usage": [50, 50]},
                    "system_cpu_usage": 9000,
                },
                "memory_stats": {"usage": 100 * BYTES_TO_MB, "limit": 512 * BYTES_TO_MB},
                "networks": {"eth0": {"rx_bytes": 100, "tx_bytes": 50}},
            }
            containers.append(mock_c)

        with patch("app.services.system_status.docker") as mock_docker:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_client.containers.list.return_value = containers
            mock_docker.from_env.return_value = mock_client
            mock_docker.errors.DockerException = Exception

            result = asyncio.run(collector.collect_docker_metrics())

        docker_available, metrics = result
        assert docker_available is True
        assert len(metrics) == 3

    def test_error_en_un_contenedor_no_interrumpe_otros(self, collector):
        """Si un contenedor falla, los demás se recolectan correctamente."""
        # Contenedor que falla
        mock_bad = MagicMock()
        mock_bad.name = "bad-container"
        mock_bad.status = "running"
        mock_bad.attrs = {"State": {"StartedAt": "2024-06-01T10:00:00.000000000Z"}}
        mock_bad.stats.side_effect = Exception("Stats error")

        # Contenedor que funciona
        mock_good = MagicMock()
        mock_good.name = "good-container"
        mock_good.status = "running"
        mock_good.attrs = {"State": {"StartedAt": "2024-06-01T10:00:00.000000000Z"}}
        mock_good.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200, "percpu_usage": [100, 100]},
                "system_cpu_usage": 10000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100, "percpu_usage": [50, 50]},
                "system_cpu_usage": 9000,
            },
            "memory_stats": {"usage": 50 * BYTES_TO_MB, "limit": 256 * BYTES_TO_MB},
            "networks": {"eth0": {"rx_bytes": 100, "tx_bytes": 50}},
        }

        with patch("app.services.system_status.docker") as mock_docker:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_client.containers.list.return_value = [mock_bad, mock_good]
            mock_docker.from_env.return_value = mock_client
            mock_docker.errors.DockerException = Exception

            result = asyncio.run(collector.collect_docker_metrics())

        docker_available, metrics = result
        assert docker_available is True
        # El contenedor con error de stats retorna métricas con valores 0
        # El contenedor bueno retorna métricas normales
        assert len(metrics) == 2


class TestCalculateCpuPercent:
    """Tests para el cálculo de CPU% de contenedores Docker."""

    @pytest.fixture
    def collector(self):
        return SystemStatusCollector()

    def test_calculo_cpu_correcto(self, collector):
        """Verifica la fórmula oficial de Docker para CPU%."""
        stats = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200000000, "percpu_usage": [100000000, 100000000]},
                "system_cpu_usage": 10000000000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100000000, "percpu_usage": [50000000, 50000000]},
                "system_cpu_usage": 9000000000,
            },
        }

        # cpu_delta = 200000000 - 100000000 = 100000000
        # system_delta = 10000000000 - 9000000000 = 1000000000
        # num_cpus = 2
        # cpu_percent = (100000000 / 1000000000) * 2 * 100 = 20.0
        result = collector._calculate_cpu_percent(stats)
        assert result == 20.0

    def test_cpu_delta_negativo_retorna_cero(self, collector):
        """Si cpu_delta es negativo, retorna 0.0."""
        stats = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 50, "percpu_usage": [25, 25]},
                "system_cpu_usage": 10000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100, "percpu_usage": [50, 50]},
                "system_cpu_usage": 9000,
            },
        }

        result = collector._calculate_cpu_percent(stats)
        assert result == 0.0

    def test_system_delta_cero_retorna_cero(self, collector):
        """Si system_delta es 0, retorna 0.0 (evita división por cero)."""
        stats = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200, "percpu_usage": [100, 100]},
                "system_cpu_usage": 10000,
                "online_cpus": 2,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100, "percpu_usage": [50, 50]},
                "system_cpu_usage": 10000,  # Mismo valor = delta 0
            },
        }

        result = collector._calculate_cpu_percent(stats)
        assert result == 0.0

    def test_stats_vacios_retorna_cero(self, collector):
        """Stats vacíos retornan 0.0 sin errores."""
        result = collector._calculate_cpu_percent({})
        assert result == 0.0

    def test_usa_online_cpus_si_percpu_vacio(self, collector):
        """Si percpu_usage está vacío, usa online_cpus."""
        stats = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 200000000, "percpu_usage": []},
                "system_cpu_usage": 10000000000,
                "online_cpus": 4,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 100000000, "percpu_usage": []},
                "system_cpu_usage": 9000000000,
            },
        }

        # cpu_delta = 100000000, system_delta = 1000000000, num_cpus = 4
        # cpu_percent = (100000000 / 1000000000) * 4 * 100 = 40.0
        result = collector._calculate_cpu_percent(stats)
        assert result == 40.0
