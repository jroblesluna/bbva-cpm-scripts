"""
Property tests para la corrección del cálculo de métricas del sistema.

Verifica que el SystemStatusCollector produce métricas correctas:
- Conversión de bytes a MB (bytes / 1048576)
- Porcentajes redondeados a 1 decimal (passthrough de psutil)
- Valores no negativos

**Validates: Requirements 1.1, 1.2, 1.3, 1.4**

Feature: system-status-monitoring, Property 1: Metric calculation correctness
"""

from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.system_status import SystemStatusCollector, BYTES_TO_MB


# === ESTRATEGIAS DE GENERACIÓN ===

# Valores de bytes realistas para memoria/disco/swap (1 MB a 1 TB)
_bytes_value = st.integers(min_value=1048576, max_value=1099511627776)

# Porcentaje reportado por psutil (0.0 a 100.0, con 1 decimal)
_percent_value = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)

# Tiempo de boot (timestamp Unix razonable: año 2000 a 2030)
_boot_time = st.floats(min_value=946684800.0, max_value=1893456000.0, allow_nan=False, allow_infinity=False)

# Porcentaje de CPU (0.0 a 100.0)
_cpu_percent = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)


@st.composite
def memory_values_strategy(draw):
    """
    Genera valores de memoria RAM coherentes en bytes.

    Garantiza que total >= used y total >= available.
    """
    total = draw(_bytes_value)
    used = draw(st.integers(min_value=0, max_value=total))
    available = draw(st.integers(min_value=0, max_value=total))
    percent = draw(_percent_value)
    return {
        "total": total,
        "used": used,
        "available": available,
        "percent": percent,
    }


@st.composite
def disk_values_strategy(draw):
    """
    Genera valores de disco coherentes en bytes.

    Garantiza que total >= used y total >= free.
    """
    total = draw(_bytes_value)
    used = draw(st.integers(min_value=0, max_value=total))
    free = draw(st.integers(min_value=0, max_value=total))
    percent = draw(_percent_value)
    return {
        "total": total,
        "used": used,
        "free": free,
        "percent": percent,
    }


@st.composite
def swap_values_strategy(draw):
    """
    Genera valores de swap coherentes en bytes.

    Garantiza que total >= used y total >= free.
    """
    total = draw(_bytes_value)
    used = draw(st.integers(min_value=0, max_value=total))
    free = draw(st.integers(min_value=0, max_value=total))
    return {
        "total": total,
        "used": used,
        "free": free,
    }


# === PROPERTY 1: METRIC CALCULATION CORRECTNESS ===


class TestMetricCalculationCorrectness:
    """
    Property 1: Metric calculation correctness.

    Para cualquier conjunto de valores crudos del sistema (memoria total/usada/disponible,
    disco total/usado/disponible, CPU raw, swap total/usado/disponible), el collector
    SHALL producir métricas donde: los valores están expresados en MB (convertidos desde
    bytes dividiendo por 1048576), los porcentajes son el passthrough de psutil redondeados
    a 1 decimal, y todos los valores son no negativos.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
    """

    @given(
        mem=memory_values_strategy(),
        disk=disk_values_strategy(),
        swap=swap_values_strategy(),
        cpu=_cpu_percent,
        boot_time=_boot_time,
    )
    @settings(max_examples=200, deadline=None)
    def test_conversion_bytes_a_mb_correcta(
        self, mem: dict, disk: dict, swap: dict, cpu: float, boot_time: float
    ):
        """
        Los valores en bytes se convierten correctamente a MB (bytes / 1048576)
        redondeados a 1 decimal.

        **Validates: Requirements 1.1, 1.2, 1.4**
        """
        # Preparar mocks de psutil
        mock_mem = MagicMock()
        mock_mem.total = mem["total"]
        mock_mem.used = mem["used"]
        mock_mem.available = mem["available"]
        mock_mem.percent = mem["percent"]

        mock_disk = MagicMock()
        mock_disk.total = disk["total"]
        mock_disk.used = disk["used"]
        mock_disk.free = disk["free"]
        mock_disk.percent = disk["percent"]

        mock_swap = MagicMock()
        mock_swap.total = swap["total"]
        mock_swap.used = swap["used"]
        mock_swap.free = swap["free"]

        with patch("app.services.system_status.psutil") as mock_psutil, \
             patch("app.services.system_status.time") as mock_time:
            mock_psutil.virtual_memory.return_value = mock_mem
            mock_psutil.disk_usage.return_value = mock_disk
            mock_psutil.cpu_percent.return_value = cpu
            mock_psutil.swap_memory.return_value = mock_swap
            mock_psutil.boot_time.return_value = boot_time
            mock_time.time.return_value = boot_time + 3600  # 1 hora de uptime

            collector = SystemStatusCollector()
            result = collector.collect_os_metrics()

        # Verificar conversión de memoria a MB
        expected_mem_total = round(mem["total"] / BYTES_TO_MB, 1)
        expected_mem_used = round(mem["used"] / BYTES_TO_MB, 1)
        expected_mem_available = round(mem["available"] / BYTES_TO_MB, 1)

        assert result.memory_total_mb == expected_mem_total, (
            f"memory_total_mb incorrecto. "
            f"Esperado: {expected_mem_total}, Obtenido: {result.memory_total_mb}"
        )
        assert result.memory_used_mb == expected_mem_used, (
            f"memory_used_mb incorrecto. "
            f"Esperado: {expected_mem_used}, Obtenido: {result.memory_used_mb}"
        )
        assert result.memory_available_mb == expected_mem_available, (
            f"memory_available_mb incorrecto. "
            f"Esperado: {expected_mem_available}, Obtenido: {result.memory_available_mb}"
        )

        # Verificar conversión de disco a MB
        expected_disk_total = round(disk["total"] / BYTES_TO_MB, 1)
        expected_disk_used = round(disk["used"] / BYTES_TO_MB, 1)
        expected_disk_available = round(disk["free"] / BYTES_TO_MB, 1)

        assert result.disk_total_mb == expected_disk_total, (
            f"disk_total_mb incorrecto. "
            f"Esperado: {expected_disk_total}, Obtenido: {result.disk_total_mb}"
        )
        assert result.disk_used_mb == expected_disk_used, (
            f"disk_used_mb incorrecto. "
            f"Esperado: {expected_disk_used}, Obtenido: {result.disk_used_mb}"
        )
        assert result.disk_available_mb == expected_disk_available, (
            f"disk_available_mb incorrecto. "
            f"Esperado: {expected_disk_available}, Obtenido: {result.disk_available_mb}"
        )

        # Verificar conversión de swap a MB
        expected_swap_total = round(swap["total"] / BYTES_TO_MB, 1)
        expected_swap_used = round(swap["used"] / BYTES_TO_MB, 1)
        expected_swap_available = round(swap["free"] / BYTES_TO_MB, 1)

        assert result.swap_total_mb == expected_swap_total, (
            f"swap_total_mb incorrecto. "
            f"Esperado: {expected_swap_total}, Obtenido: {result.swap_total_mb}"
        )
        assert result.swap_used_mb == expected_swap_used, (
            f"swap_used_mb incorrecto. "
            f"Esperado: {expected_swap_used}, Obtenido: {result.swap_used_mb}"
        )
        assert result.swap_available_mb == expected_swap_available, (
            f"swap_available_mb incorrecto. "
            f"Esperado: {expected_swap_available}, Obtenido: {result.swap_available_mb}"
        )

    @given(
        mem=memory_values_strategy(),
        disk=disk_values_strategy(),
        swap=swap_values_strategy(),
        cpu=_cpu_percent,
        boot_time=_boot_time,
    )
    @settings(max_examples=200, deadline=None)
    def test_porcentajes_redondeados_a_un_decimal(
        self, mem: dict, disk: dict, swap: dict, cpu: float, boot_time: float
    ):
        """
        Los porcentajes de psutil se pasan correctamente redondeados a 1 decimal.

        El collector usa directamente el percent reportado por psutil (no lo recalcula),
        y lo redondea a 1 decimal.

        **Validates: Requirements 1.1, 1.2, 1.3**
        """
        # Preparar mocks de psutil
        mock_mem = MagicMock()
        mock_mem.total = mem["total"]
        mock_mem.used = mem["used"]
        mock_mem.available = mem["available"]
        mock_mem.percent = mem["percent"]

        mock_disk = MagicMock()
        mock_disk.total = disk["total"]
        mock_disk.used = disk["used"]
        mock_disk.free = disk["free"]
        mock_disk.percent = disk["percent"]

        mock_swap = MagicMock()
        mock_swap.total = swap["total"]
        mock_swap.used = swap["used"]
        mock_swap.free = swap["free"]

        with patch("app.services.system_status.psutil") as mock_psutil, \
             patch("app.services.system_status.time") as mock_time:
            mock_psutil.virtual_memory.return_value = mock_mem
            mock_psutil.disk_usage.return_value = mock_disk
            mock_psutil.cpu_percent.return_value = cpu
            mock_psutil.swap_memory.return_value = mock_swap
            mock_psutil.boot_time.return_value = boot_time
            mock_time.time.return_value = boot_time + 3600

            collector = SystemStatusCollector()
            result = collector.collect_os_metrics()

        # Verificar porcentaje de memoria (passthrough de psutil, redondeado)
        expected_mem_percent = round(mem["percent"], 1)
        assert result.memory_percent == expected_mem_percent, (
            f"memory_percent incorrecto. "
            f"Esperado: {expected_mem_percent}, Obtenido: {result.memory_percent}"
        )

        # Verificar porcentaje de disco (passthrough de psutil, redondeado)
        expected_disk_percent = round(disk["percent"], 1)
        assert result.disk_percent == expected_disk_percent, (
            f"disk_percent incorrecto. "
            f"Esperado: {expected_disk_percent}, Obtenido: {result.disk_percent}"
        )

        # Verificar porcentaje de CPU (passthrough de psutil, redondeado)
        expected_cpu_percent = round(cpu, 1)
        assert result.cpu_percent == expected_cpu_percent, (
            f"cpu_percent incorrecto. "
            f"Esperado: {expected_cpu_percent}, Obtenido: {result.cpu_percent}"
        )

    @given(
        mem=memory_values_strategy(),
        disk=disk_values_strategy(),
        swap=swap_values_strategy(),
        cpu=_cpu_percent,
        boot_time=_boot_time,
    )
    @settings(max_examples=200, deadline=None)
    def test_todos_los_valores_son_no_negativos(
        self, mem: dict, disk: dict, swap: dict, cpu: float, boot_time: float
    ):
        """
        Todas las métricas producidas por el collector son no negativas.

        Independientemente de los valores de entrada, el resultado nunca
        debe contener valores negativos.

        **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
        """
        # Preparar mocks de psutil
        mock_mem = MagicMock()
        mock_mem.total = mem["total"]
        mock_mem.used = mem["used"]
        mock_mem.available = mem["available"]
        mock_mem.percent = mem["percent"]

        mock_disk = MagicMock()
        mock_disk.total = disk["total"]
        mock_disk.used = disk["used"]
        mock_disk.free = disk["free"]
        mock_disk.percent = disk["percent"]

        mock_swap = MagicMock()
        mock_swap.total = swap["total"]
        mock_swap.used = swap["used"]
        mock_swap.free = swap["free"]

        with patch("app.services.system_status.psutil") as mock_psutil, \
             patch("app.services.system_status.time") as mock_time:
            mock_psutil.virtual_memory.return_value = mock_mem
            mock_psutil.disk_usage.return_value = mock_disk
            mock_psutil.cpu_percent.return_value = cpu
            mock_psutil.swap_memory.return_value = mock_swap
            mock_psutil.boot_time.return_value = boot_time
            mock_time.time.return_value = boot_time + 3600

            collector = SystemStatusCollector()
            result = collector.collect_os_metrics()

        # Verificar que todos los valores de MB son no negativos
        assert result.memory_total_mb >= 0, f"memory_total_mb negativo: {result.memory_total_mb}"
        assert result.memory_used_mb >= 0, f"memory_used_mb negativo: {result.memory_used_mb}"
        assert result.memory_available_mb >= 0, f"memory_available_mb negativo: {result.memory_available_mb}"
        assert result.disk_total_mb >= 0, f"disk_total_mb negativo: {result.disk_total_mb}"
        assert result.disk_used_mb >= 0, f"disk_used_mb negativo: {result.disk_used_mb}"
        assert result.disk_available_mb >= 0, f"disk_available_mb negativo: {result.disk_available_mb}"
        assert result.swap_total_mb >= 0, f"swap_total_mb negativo: {result.swap_total_mb}"
        assert result.swap_used_mb >= 0, f"swap_used_mb negativo: {result.swap_used_mb}"
        assert result.swap_available_mb >= 0, f"swap_available_mb negativo: {result.swap_available_mb}"

        # Verificar que todos los porcentajes son no negativos
        assert result.memory_percent >= 0, f"memory_percent negativo: {result.memory_percent}"
        assert result.disk_percent >= 0, f"disk_percent negativo: {result.disk_percent}"
        assert result.cpu_percent >= 0, f"cpu_percent negativo: {result.cpu_percent}"

        # Verificar que uptime es no negativo
        assert result.uptime_seconds >= 0, f"uptime_seconds negativo: {result.uptime_seconds}"

    @given(
        mem=memory_values_strategy(),
        disk=disk_values_strategy(),
        swap=swap_values_strategy(),
        cpu=_cpu_percent,
        boot_time=_boot_time,
    )
    @settings(max_examples=200, deadline=None)
    def test_uptime_calculado_correctamente(
        self, mem: dict, disk: dict, swap: dict, cpu: float, boot_time: float
    ):
        """
        El uptime se calcula como la diferencia entre el tiempo actual y boot_time,
        expresado en segundos enteros.

        **Validates: Requirements 1.1**
        """
        # Definir un tiempo actual fijo para el test
        current_time = boot_time + 7200.5  # 2 horas después del boot

        # Preparar mocks de psutil
        mock_mem = MagicMock()
        mock_mem.total = mem["total"]
        mock_mem.used = mem["used"]
        mock_mem.available = mem["available"]
        mock_mem.percent = mem["percent"]

        mock_disk = MagicMock()
        mock_disk.total = disk["total"]
        mock_disk.used = disk["used"]
        mock_disk.free = disk["free"]
        mock_disk.percent = disk["percent"]

        mock_swap = MagicMock()
        mock_swap.total = swap["total"]
        mock_swap.used = swap["used"]
        mock_swap.free = swap["free"]

        with patch("app.services.system_status.psutil") as mock_psutil, \
             patch("app.services.system_status.time") as mock_time:
            mock_psutil.virtual_memory.return_value = mock_mem
            mock_psutil.disk_usage.return_value = mock_disk
            mock_psutil.cpu_percent.return_value = cpu
            mock_psutil.swap_memory.return_value = mock_swap
            mock_psutil.boot_time.return_value = boot_time
            mock_time.time.return_value = current_time

            collector = SystemStatusCollector()
            result = collector.collect_os_metrics()

        # Verificar cálculo de uptime
        expected_uptime = int(current_time - boot_time)
        assert result.uptime_seconds == expected_uptime, (
            f"uptime_seconds incorrecto. "
            f"Esperado: {expected_uptime}, Obtenido: {result.uptime_seconds}"
        )
