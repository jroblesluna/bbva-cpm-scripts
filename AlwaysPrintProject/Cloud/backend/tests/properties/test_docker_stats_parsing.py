"""
Property tests para la corrección del parsing de estadísticas Docker.

Verifica que el SystemStatusCollector produce ContainerMetrics correctos:
- Memoria convertida a MB (bytes / 1048576)
- Network I/O preservado en bytes
- Estado normalizado (exited → stopped)
- CPU% calculado correctamente con la fórmula de Docker
- Todos los valores son no negativos

**Validates: Requirements 1.5, 1.7**

Feature: system-status-monitoring, Property 2: Docker stats parsing correctness
"""

from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.system_status import SystemStatusCollector, BYTES_TO_MB


# === ESTRATEGIAS DE GENERACIÓN ===

# Nombres de contenedores Docker válidos (alfanuméricos con guiones/underscores)
_container_names = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789-_"),
    min_size=1,
    max_size=50,
)

# Estados posibles de contenedores Docker
_container_states = st.sampled_from(["running", "exited", "restarting"])

# Valores de bytes para memoria (0 a 16 GB)
_memory_bytes = st.integers(min_value=0, max_value=17179869184)

# Valores de bytes para network I/O (0 a 100 GB)
_network_bytes = st.integers(min_value=0, max_value=107374182400)

# Valores de CPU usage (nanosegundos, valores realistas)
_cpu_usage = st.integers(min_value=0, max_value=10**15)

# Número de CPUs disponibles (1 a 128)
_num_cpus = st.integers(min_value=1, max_value=128)


@st.composite
def docker_stats_strategy(draw):
    """
    Genera un JSON de Docker stats con estructura válida.

    Incluye cpu_stats, precpu_stats, memory_stats y networks
    con valores aleatorios pero coherentes.
    """
    # Generar valores de CPU
    precpu_total = draw(_cpu_usage)
    # cpu_total debe ser >= precpu_total para un delta positivo
    cpu_delta = draw(st.integers(min_value=0, max_value=10**12))
    cpu_total = precpu_total + cpu_delta

    presystem_usage = draw(_cpu_usage)
    # system_delta debe ser > 0 para evitar división por cero
    system_delta = draw(st.integers(min_value=1, max_value=10**12))
    system_usage = presystem_usage + system_delta

    num_cpus = draw(_num_cpus)

    # Generar valores de memoria
    memory_usage = draw(_memory_bytes)
    memory_limit = draw(st.integers(min_value=memory_usage, max_value=17179869184))

    # Generar valores de red (múltiples interfaces posibles)
    num_interfaces = draw(st.integers(min_value=1, max_value=3))
    networks = {}
    total_rx = 0
    total_tx = 0
    for i in range(num_interfaces):
        iface_name = f"eth{i}"
        rx = draw(_network_bytes)
        tx = draw(_network_bytes)
        networks[iface_name] = {"rx_bytes": rx, "tx_bytes": tx}
        total_rx += rx
        total_tx += tx

    # Construir estructura de percpu_usage
    percpu_usage = [draw(st.integers(min_value=0, max_value=10**12)) for _ in range(num_cpus)]

    stats = {
        "cpu_stats": {
            "cpu_usage": {
                "total_usage": cpu_total,
                "percpu_usage": percpu_usage,
            },
            "system_cpu_usage": system_usage,
            "online_cpus": num_cpus,
        },
        "precpu_stats": {
            "cpu_usage": {
                "total_usage": precpu_total,
            },
            "system_cpu_usage": presystem_usage,
        },
        "memory_stats": {
            "usage": memory_usage,
            "limit": memory_limit,
        },
        "networks": networks,
    }

    return {
        "stats": stats,
        "memory_usage": memory_usage,
        "memory_limit": memory_limit,
        "total_rx": total_rx,
        "total_tx": total_tx,
        "cpu_delta": cpu_delta,
        "system_delta": system_delta,
        "num_cpus": num_cpus,
    }


@st.composite
def container_with_stats_strategy(draw):
    """
    Genera un contenedor Docker mock con nombre, estado y stats.

    Combina nombre, estado y estadísticas generadas aleatoriamente.
    """
    name = draw(_container_names)
    state = draw(_container_states)
    stats_data = draw(docker_stats_strategy())

    return {
        "name": name,
        "state": state,
        "stats_data": stats_data,
    }


# === PROPERTY 2: DOCKER STATS PARSING CORRECTNESS ===


class TestDockerStatsParsingCorrectness:
    """
    Property 2: Docker stats parsing correctness.

    Para cualquier respuesta JSON válida de Docker stats/inspect que contenga
    nombre del contenedor, estado, porcentaje de CPU, uso de memoria, límite
    de memoria y network I/O, el parser SHALL producir un ContainerMetrics
    donde todos los campos se extraen correctamente, los valores de memoria
    están en MB, los valores de red están en bytes, y el estado es uno de
    (running, stopped, restarting).

    **Validates: Requirements 1.5, 1.7**
    """

    @given(data=container_with_stats_strategy())
    @settings(max_examples=200, deadline=None)
    def test_memoria_convertida_a_mb_correctamente(self, data: dict):
        """
        Los valores de memoria se convierten correctamente de bytes a MB
        (bytes / 1048576) redondeados a 1 decimal.

        **Validates: Requirements 1.5**
        """
        # Solo contenedores running tienen stats disponibles
        assume(data["state"] == "running")

        container_mock = self._create_container_mock(data)
        collector = SystemStatusCollector()

        with patch("app.services.system_status.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2025, 6, 1, tzinfo=timezone.utc)
            mock_datetime.fromisoformat = datetime.fromisoformat
            result = collector._collect_single_container_metrics(container_mock)

        assert result is not None

        # Verificar conversión de memoria usada a MB
        expected_memory_used_mb = round(
            data["stats_data"]["memory_usage"] / BYTES_TO_MB, 1
        )
        assert result.memory_used_mb == expected_memory_used_mb, (
            f"memory_used_mb incorrecto. "
            f"Esperado: {expected_memory_used_mb}, Obtenido: {result.memory_used_mb}"
        )

        # Verificar conversión de memoria límite a MB
        expected_memory_limit_mb = round(
            data["stats_data"]["memory_limit"] / BYTES_TO_MB, 1
        )
        assert result.memory_limit_mb == expected_memory_limit_mb, (
            f"memory_limit_mb incorrecto. "
            f"Esperado: {expected_memory_limit_mb}, Obtenido: {result.memory_limit_mb}"
        )

    @given(data=container_with_stats_strategy())
    @settings(max_examples=200, deadline=None)
    def test_network_io_preservado_en_bytes(self, data: dict):
        """
        Los valores de network I/O se preservan en bytes (suma de todas
        las interfaces de red del contenedor).

        **Validates: Requirements 1.5**
        """
        # Solo contenedores running tienen stats disponibles
        assume(data["state"] == "running")

        container_mock = self._create_container_mock(data)
        collector = SystemStatusCollector()

        with patch("app.services.system_status.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2025, 6, 1, tzinfo=timezone.utc)
            mock_datetime.fromisoformat = datetime.fromisoformat
            result = collector._collect_single_container_metrics(container_mock)

        assert result is not None

        # Verificar que network_rx_bytes es la suma de todas las interfaces
        expected_rx = data["stats_data"]["total_rx"]
        assert result.network_rx_bytes == expected_rx, (
            f"network_rx_bytes incorrecto. "
            f"Esperado: {expected_rx}, Obtenido: {result.network_rx_bytes}"
        )

        # Verificar que network_tx_bytes es la suma de todas las interfaces
        expected_tx = data["stats_data"]["total_tx"]
        assert result.network_tx_bytes == expected_tx, (
            f"network_tx_bytes incorrecto. "
            f"Esperado: {expected_tx}, Obtenido: {result.network_tx_bytes}"
        )

    @given(data=container_with_stats_strategy())
    @settings(max_examples=200, deadline=None)
    def test_estado_normalizado_correctamente(self, data: dict):
        """
        El estado del contenedor se normaliza: 'exited' → 'stopped',
        y el resultado es siempre uno de (running, stopped, restarting).

        **Validates: Requirements 1.7**
        """
        container_mock = self._create_container_mock(data)
        collector = SystemStatusCollector()

        with patch("app.services.system_status.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2025, 6, 1, tzinfo=timezone.utc)
            mock_datetime.fromisoformat = datetime.fromisoformat
            result = collector._collect_single_container_metrics(container_mock)

        assert result is not None

        # Verificar normalización de estado
        expected_status = data["state"]
        if expected_status == "exited":
            expected_status = "stopped"

        assert result.status == expected_status, (
            f"Estado incorrecto. Estado original: '{data['state']}', "
            f"Esperado: '{expected_status}', Obtenido: '{result.status}'"
        )

        # Verificar que el estado es uno de los valores válidos
        assert result.status in ("running", "stopped", "restarting"), (
            f"Estado no válido: '{result.status}'. "
            f"Debe ser uno de: running, stopped, restarting"
        )

    @given(data=container_with_stats_strategy())
    @settings(max_examples=200, deadline=None)
    def test_cpu_percent_calculado_con_formula_docker(self, data: dict):
        """
        El porcentaje de CPU se calcula usando la fórmula oficial de Docker:
        cpu_delta = cpu_usage - precpu_usage
        system_delta = system_cpu_usage - presystem_cpu_usage
        cpu_percent = (cpu_delta / system_delta) * num_cpus * 100

        **Validates: Requirements 1.5**
        """
        # Solo contenedores running tienen stats disponibles
        assume(data["state"] == "running")

        container_mock = self._create_container_mock(data)
        collector = SystemStatusCollector()

        with patch("app.services.system_status.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2025, 6, 1, tzinfo=timezone.utc)
            mock_datetime.fromisoformat = datetime.fromisoformat
            result = collector._collect_single_container_metrics(container_mock)

        assert result is not None

        # Calcular CPU% esperado con la fórmula de Docker
        cpu_delta = data["stats_data"]["cpu_delta"]
        system_delta = data["stats_data"]["system_delta"]
        num_cpus = data["stats_data"]["num_cpus"]

        if system_delta <= 0 or cpu_delta < 0:
            expected_cpu = 0.0
        else:
            expected_cpu = round((cpu_delta / system_delta) * num_cpus * 100.0, 1)

        assert result.cpu_percent == expected_cpu, (
            f"cpu_percent incorrecto. "
            f"Esperado: {expected_cpu}, Obtenido: {result.cpu_percent}. "
            f"cpu_delta={cpu_delta}, system_delta={system_delta}, num_cpus={num_cpus}"
        )

    @given(data=container_with_stats_strategy())
    @settings(max_examples=200, deadline=None)
    def test_todos_los_valores_no_negativos(self, data: dict):
        """
        Todos los valores numéricos producidos por el parser son no negativos,
        independientemente de los valores de entrada.

        **Validates: Requirements 1.5, 1.7**
        """
        container_mock = self._create_container_mock(data)
        collector = SystemStatusCollector()

        with patch("app.services.system_status.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2025, 6, 1, tzinfo=timezone.utc)
            mock_datetime.fromisoformat = datetime.fromisoformat
            result = collector._collect_single_container_metrics(container_mock)

        assert result is not None

        # Verificar que todos los valores numéricos son no negativos
        assert result.cpu_percent >= 0, f"cpu_percent negativo: {result.cpu_percent}"
        assert result.memory_used_mb >= 0, f"memory_used_mb negativo: {result.memory_used_mb}"
        assert result.memory_limit_mb >= 0, f"memory_limit_mb negativo: {result.memory_limit_mb}"
        assert result.network_rx_bytes >= 0, f"network_rx_bytes negativo: {result.network_rx_bytes}"
        assert result.network_tx_bytes >= 0, f"network_tx_bytes negativo: {result.network_tx_bytes}"
        assert result.uptime_seconds >= 0, f"uptime_seconds negativo: {result.uptime_seconds}"

    @given(name=_container_names)
    @settings(max_examples=200, deadline=None)
    def test_nombre_contenedor_extraido_correctamente(self, name: str):
        """
        El nombre del contenedor se extrae correctamente del objeto Docker.

        **Validates: Requirements 1.5**
        """
        container_mock = MagicMock()
        container_mock.name = name
        container_mock.status = "running"
        container_mock.attrs = {"State": {"StartedAt": "0001-01-01T00:00:00Z"}}
        container_mock.stats.return_value = {
            "cpu_stats": {
                "cpu_usage": {"total_usage": 100, "percpu_usage": [100]},
                "system_cpu_usage": 1000,
                "online_cpus": 1,
            },
            "precpu_stats": {
                "cpu_usage": {"total_usage": 50},
                "system_cpu_usage": 500,
            },
            "memory_stats": {"usage": 1048576, "limit": 2097152},
            "networks": {"eth0": {"rx_bytes": 100, "tx_bytes": 200}},
        }

        collector = SystemStatusCollector()

        with patch("app.services.system_status.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2025, 6, 1, tzinfo=timezone.utc)
            mock_datetime.fromisoformat = datetime.fromisoformat
            result = collector._collect_single_container_metrics(container_mock)

        assert result is not None
        assert result.name == name, (
            f"Nombre incorrecto. Esperado: '{name}', Obtenido: '{result.name}'"
        )

    # === MÉTODOS AUXILIARES ===

    def _create_container_mock(self, data: dict) -> MagicMock:
        """
        Crea un mock de contenedor Docker con los datos proporcionados.

        Args:
            data: Diccionario con name, state y stats_data

        Returns:
            MagicMock configurado como un contenedor Docker
        """
        container_mock = MagicMock()
        container_mock.name = data["name"]
        container_mock.status = data["state"]
        container_mock.attrs = {
            "State": {"StartedAt": "2025-01-01T00:00:00.000000000Z"}
        }

        # Configurar stats solo si el contenedor está running
        if data["state"] == "running":
            container_mock.stats.return_value = data["stats_data"]["stats"]
        else:
            # Contenedores no running no deberían llamar a stats
            container_mock.stats.side_effect = Exception(
                "No se puede obtener stats de contenedor detenido"
            )

        return container_mock
