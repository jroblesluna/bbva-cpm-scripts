"""
Property tests para la resiliencia ante fallos parciales del collector.

Verifica que el SystemStatusCollector es resiliente ante fallos parciales:
- Si un subconjunto de funciones de psutil falla, las demás siguen funcionando
- Las métricas fallidas se reportan con valores por defecto (0.0 o 0)
- El método collect_os_metrics() NUNCA lanza una excepción
- Siempre retorna un OsMetricsResponse válido

**Validates: Requirements 1.8, 1.9**

Feature: system-status-monitoring, Property 3: Partial failure resilience
"""

from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.system_status import SystemStatusCollector, BYTES_TO_MB
from app.schemas.system_status import OsMetricsResponse


# === ESTRATEGIAS DE GENERACIÓN ===

# Funciones de psutil que pueden fallar individualmente
PSUTIL_FUNCTIONS = [
    "virtual_memory",
    "disk_usage",
    "cpu_percent",
    "swap_memory",
    "boot_time",
]

# Estrategia para generar subconjuntos aleatorios de funciones que fallarán
_failing_functions = st.lists(
    st.sampled_from(PSUTIL_FUNCTIONS),
    min_size=0,
    max_size=len(PSUTIL_FUNCTIONS),
    unique=True,
)

# Valores de bytes realistas para memoria/disco/swap (1 MB a 1 TB)
_bytes_value = st.integers(min_value=1048576, max_value=1099511627776)

# Porcentaje reportado por psutil (0.0 a 100.0)
_percent_value = st.floats(
    min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False
)

# Tiempo de boot (timestamp Unix razonable: año 2000 a 2030)
_boot_time = st.floats(
    min_value=946684800.0, max_value=1893456000.0, allow_nan=False, allow_infinity=False
)

# Porcentaje de CPU (0.0 a 100.0)
_cpu_percent = st.floats(
    min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False
)


@st.composite
def valid_psutil_values(draw):
    """
    Genera un conjunto completo de valores válidos para todas las funciones de psutil.

    Retorna un diccionario con los mocks preparados para cada función.
    """
    # Valores de memoria
    mem_total = draw(_bytes_value)
    mem_used = draw(st.integers(min_value=0, max_value=mem_total))
    mem_available = draw(st.integers(min_value=0, max_value=mem_total))
    mem_percent = draw(_percent_value)

    # Valores de disco
    disk_total = draw(_bytes_value)
    disk_used = draw(st.integers(min_value=0, max_value=disk_total))
    disk_free = draw(st.integers(min_value=0, max_value=disk_total))
    disk_percent = draw(_percent_value)

    # Valores de swap
    swap_total = draw(_bytes_value)
    swap_used = draw(st.integers(min_value=0, max_value=swap_total))
    swap_free = draw(st.integers(min_value=0, max_value=swap_total))

    # CPU y boot time
    cpu = draw(_cpu_percent)
    boot = draw(_boot_time)

    return {
        "memory": {
            "total": mem_total,
            "used": mem_used,
            "available": mem_available,
            "percent": mem_percent,
        },
        "disk": {
            "total": disk_total,
            "used": disk_used,
            "free": disk_free,
            "percent": disk_percent,
        },
        "swap": {
            "total": swap_total,
            "used": swap_used,
            "free": swap_free,
        },
        "cpu": cpu,
        "boot_time": boot,
    }


def _setup_mocks(mock_psutil, mock_time, values: dict, failing: list):
    """
    Configura los mocks de psutil según las funciones que deben fallar.

    Las funciones en `failing` lanzarán una excepción OSError.
    Las funciones no incluidas retornarán valores válidos.

    Args:
        mock_psutil: Mock del módulo psutil
        mock_time: Mock del módulo time
        values: Diccionario con valores válidos para cada función
        failing: Lista de nombres de funciones que deben fallar
    """
    # Configurar virtual_memory
    if "virtual_memory" in failing:
        mock_psutil.virtual_memory.side_effect = OSError("Error simulado en virtual_memory")
    else:
        mock_mem = MagicMock()
        mock_mem.total = values["memory"]["total"]
        mock_mem.used = values["memory"]["used"]
        mock_mem.available = values["memory"]["available"]
        mock_mem.percent = values["memory"]["percent"]
        mock_psutil.virtual_memory.return_value = mock_mem

    # Configurar disk_usage
    if "disk_usage" in failing:
        mock_psutil.disk_usage.side_effect = OSError("Error simulado en disk_usage")
    else:
        mock_disk = MagicMock()
        mock_disk.total = values["disk"]["total"]
        mock_disk.used = values["disk"]["used"]
        mock_disk.free = values["disk"]["free"]
        mock_disk.percent = values["disk"]["percent"]
        mock_psutil.disk_usage.return_value = mock_disk

    # Configurar cpu_percent
    if "cpu_percent" in failing:
        mock_psutil.cpu_percent.side_effect = OSError("Error simulado en cpu_percent")
    else:
        mock_psutil.cpu_percent.return_value = values["cpu"]

    # Configurar swap_memory
    if "swap_memory" in failing:
        mock_psutil.swap_memory.side_effect = OSError("Error simulado en swap_memory")
    else:
        mock_swap = MagicMock()
        mock_swap.total = values["swap"]["total"]
        mock_swap.used = values["swap"]["used"]
        mock_swap.free = values["swap"]["free"]
        mock_psutil.swap_memory.return_value = mock_swap

    # Configurar boot_time
    if "boot_time" in failing:
        mock_psutil.boot_time.side_effect = OSError("Error simulado en boot_time")
    else:
        mock_psutil.boot_time.return_value = values["boot_time"]

    # Configurar time.time() para cálculo de uptime (1 hora después del boot)
    mock_time.time.return_value = values["boot_time"] + 3600


# === PROPERTY 3: PARTIAL FAILURE RESILIENCE ===


class TestPartialFailureResilience:
    """
    Property 3: Partial failure resilience.

    Para cualquier subconjunto de recolectores de métricas que lancen excepciones
    durante un ciclo de recolección, los recolectores restantes SHALL seguir
    produciendo sus métricas exitosamente, y las métricas fallidas SHALL reportarse
    como no disponibles (valores por defecto) sin interrumpir la recolección general.

    **Validates: Requirements 1.8, 1.9**
    """

    @given(
        failing=_failing_functions,
        values=valid_psutil_values(),
    )
    @settings(max_examples=200, deadline=None)
    def test_nunca_lanza_excepcion_independientemente_de_fallos(
        self, failing: list, values: dict
    ):
        """
        El método collect_os_metrics() NUNCA lanza una excepción,
        sin importar qué combinación de funciones de psutil falle.

        Siempre retorna un OsMetricsResponse válido.

        **Validates: Requirements 1.8, 1.9**
        """
        with patch("app.services.system_status.psutil") as mock_psutil, \
             patch("app.services.system_status.time") as mock_time:
            _setup_mocks(mock_psutil, mock_time, values, failing)

            collector = SystemStatusCollector()
            # No debe lanzar excepción bajo ninguna circunstancia
            result = collector.collect_os_metrics()

        # Siempre retorna un OsMetricsResponse válido
        assert isinstance(result, OsMetricsResponse), (
            f"Se esperaba OsMetricsResponse, se obtuvo {type(result).__name__}"
        )

    @given(
        failing=_failing_functions,
        values=valid_psutil_values(),
    )
    @settings(max_examples=200, deadline=None)
    def test_metricas_fallidas_tienen_valores_por_defecto(
        self, failing: list, values: dict
    ):
        """
        Las métricas cuyas funciones de psutil fallan se reportan con
        valores por defecto (0.0 para floats, 0 para enteros).

        **Validates: Requirements 1.9**
        """
        with patch("app.services.system_status.psutil") as mock_psutil, \
             patch("app.services.system_status.time") as mock_time:
            _setup_mocks(mock_psutil, mock_time, values, failing)

            collector = SystemStatusCollector()
            result = collector.collect_os_metrics()

        # Verificar que las métricas fallidas tienen valores por defecto
        if "virtual_memory" in failing:
            assert result.memory_total_mb == 0.0, (
                f"memory_total_mb debería ser 0.0 cuando virtual_memory falla, "
                f"obtenido: {result.memory_total_mb}"
            )
            assert result.memory_used_mb == 0.0, (
                f"memory_used_mb debería ser 0.0 cuando virtual_memory falla, "
                f"obtenido: {result.memory_used_mb}"
            )
            assert result.memory_available_mb == 0.0, (
                f"memory_available_mb debería ser 0.0 cuando virtual_memory falla, "
                f"obtenido: {result.memory_available_mb}"
            )
            assert result.memory_percent == 0.0, (
                f"memory_percent debería ser 0.0 cuando virtual_memory falla, "
                f"obtenido: {result.memory_percent}"
            )

        if "disk_usage" in failing:
            assert result.disk_total_mb == 0.0, (
                f"disk_total_mb debería ser 0.0 cuando disk_usage falla, "
                f"obtenido: {result.disk_total_mb}"
            )
            assert result.disk_used_mb == 0.0, (
                f"disk_used_mb debería ser 0.0 cuando disk_usage falla, "
                f"obtenido: {result.disk_used_mb}"
            )
            assert result.disk_available_mb == 0.0, (
                f"disk_available_mb debería ser 0.0 cuando disk_usage falla, "
                f"obtenido: {result.disk_available_mb}"
            )
            assert result.disk_percent == 0.0, (
                f"disk_percent debería ser 0.0 cuando disk_usage falla, "
                f"obtenido: {result.disk_percent}"
            )

        if "cpu_percent" in failing:
            assert result.cpu_percent == 0.0, (
                f"cpu_percent debería ser 0.0 cuando cpu_percent falla, "
                f"obtenido: {result.cpu_percent}"
            )

        if "swap_memory" in failing:
            assert result.swap_total_mb == 0.0, (
                f"swap_total_mb debería ser 0.0 cuando swap_memory falla, "
                f"obtenido: {result.swap_total_mb}"
            )
            assert result.swap_used_mb == 0.0, (
                f"swap_used_mb debería ser 0.0 cuando swap_memory falla, "
                f"obtenido: {result.swap_used_mb}"
            )
            assert result.swap_available_mb == 0.0, (
                f"swap_available_mb debería ser 0.0 cuando swap_memory falla, "
                f"obtenido: {result.swap_available_mb}"
            )

        if "boot_time" in failing:
            assert result.uptime_seconds == 0, (
                f"uptime_seconds debería ser 0 cuando boot_time falla, "
                f"obtenido: {result.uptime_seconds}"
            )

    @given(
        failing=_failing_functions,
        values=valid_psutil_values(),
    )
    @settings(max_examples=200, deadline=None)
    def test_metricas_exitosas_tienen_valores_correctos(
        self, failing: list, values: dict
    ):
        """
        Las métricas cuyas funciones de psutil NO fallan se calculan
        correctamente (conversión a MB y redondeo a 1 decimal).

        **Validates: Requirements 1.8, 1.9**
        """
        # Solo probar cuando al menos una función NO falla
        assume(len(failing) < len(PSUTIL_FUNCTIONS))

        with patch("app.services.system_status.psutil") as mock_psutil, \
             patch("app.services.system_status.time") as mock_time:
            _setup_mocks(mock_psutil, mock_time, values, failing)

            collector = SystemStatusCollector()
            result = collector.collect_os_metrics()

        # Verificar que las métricas exitosas tienen valores correctos
        if "virtual_memory" not in failing:
            expected_total = round(values["memory"]["total"] / BYTES_TO_MB, 1)
            expected_used = round(values["memory"]["used"] / BYTES_TO_MB, 1)
            expected_available = round(values["memory"]["available"] / BYTES_TO_MB, 1)
            expected_percent = round(values["memory"]["percent"], 1)

            assert result.memory_total_mb == expected_total, (
                f"memory_total_mb incorrecto. "
                f"Esperado: {expected_total}, Obtenido: {result.memory_total_mb}"
            )
            assert result.memory_used_mb == expected_used, (
                f"memory_used_mb incorrecto. "
                f"Esperado: {expected_used}, Obtenido: {result.memory_used_mb}"
            )
            assert result.memory_available_mb == expected_available, (
                f"memory_available_mb incorrecto. "
                f"Esperado: {expected_available}, Obtenido: {result.memory_available_mb}"
            )
            assert result.memory_percent == expected_percent, (
                f"memory_percent incorrecto. "
                f"Esperado: {expected_percent}, Obtenido: {result.memory_percent}"
            )

        if "disk_usage" not in failing:
            expected_total = round(values["disk"]["total"] / BYTES_TO_MB, 1)
            expected_used = round(values["disk"]["used"] / BYTES_TO_MB, 1)
            expected_available = round(values["disk"]["free"] / BYTES_TO_MB, 1)
            expected_percent = round(values["disk"]["percent"], 1)

            assert result.disk_total_mb == expected_total, (
                f"disk_total_mb incorrecto. "
                f"Esperado: {expected_total}, Obtenido: {result.disk_total_mb}"
            )
            assert result.disk_used_mb == expected_used, (
                f"disk_used_mb incorrecto. "
                f"Esperado: {expected_used}, Obtenido: {result.disk_used_mb}"
            )
            assert result.disk_available_mb == expected_available, (
                f"disk_available_mb incorrecto. "
                f"Esperado: {expected_available}, Obtenido: {result.disk_available_mb}"
            )
            assert result.disk_percent == expected_percent, (
                f"disk_percent incorrecto. "
                f"Esperado: {expected_percent}, Obtenido: {result.disk_percent}"
            )

        if "cpu_percent" not in failing:
            expected_cpu = round(values["cpu"], 1)
            assert result.cpu_percent == expected_cpu, (
                f"cpu_percent incorrecto. "
                f"Esperado: {expected_cpu}, Obtenido: {result.cpu_percent}"
            )

        if "swap_memory" not in failing:
            expected_total = round(values["swap"]["total"] / BYTES_TO_MB, 1)
            expected_used = round(values["swap"]["used"] / BYTES_TO_MB, 1)
            expected_available = round(values["swap"]["free"] / BYTES_TO_MB, 1)

            assert result.swap_total_mb == expected_total, (
                f"swap_total_mb incorrecto. "
                f"Esperado: {expected_total}, Obtenido: {result.swap_total_mb}"
            )
            assert result.swap_used_mb == expected_used, (
                f"swap_used_mb incorrecto. "
                f"Esperado: {expected_used}, Obtenido: {result.swap_used_mb}"
            )
            assert result.swap_available_mb == expected_available, (
                f"swap_available_mb incorrecto. "
                f"Esperado: {expected_available}, Obtenido: {result.swap_available_mb}"
            )

        if "boot_time" not in failing:
            expected_uptime = int(values["boot_time"] + 3600 - values["boot_time"])
            assert result.uptime_seconds == expected_uptime, (
                f"uptime_seconds incorrecto. "
                f"Esperado: {expected_uptime}, Obtenido: {result.uptime_seconds}"
            )

    @given(
        failing=st.lists(
            st.sampled_from(PSUTIL_FUNCTIONS),
            min_size=1,
            max_size=len(PSUTIL_FUNCTIONS),
            unique=True,
        ),
        values=valid_psutil_values(),
    )
    @settings(max_examples=200, deadline=None)
    def test_resiliente_a_cualquier_combinacion_de_fallos(
        self, failing: list, values: dict
    ):
        """
        El collector es resiliente a CUALQUIER combinación de fallos,
        incluyendo el caso donde TODAS las funciones fallan simultáneamente.

        En todos los casos retorna un OsMetricsResponse válido con valores
        por defecto para las métricas fallidas y valores correctos para las exitosas.

        **Validates: Requirements 1.8, 1.9**
        """
        with patch("app.services.system_status.psutil") as mock_psutil, \
             patch("app.services.system_status.time") as mock_time:
            _setup_mocks(mock_psutil, mock_time, values, failing)

            collector = SystemStatusCollector()
            result = collector.collect_os_metrics()

        # Siempre retorna un OsMetricsResponse válido
        assert isinstance(result, OsMetricsResponse)

        # Todos los valores numéricos son no negativos
        assert result.memory_total_mb >= 0.0
        assert result.memory_used_mb >= 0.0
        assert result.memory_available_mb >= 0.0
        assert result.memory_percent >= 0.0
        assert result.disk_total_mb >= 0.0
        assert result.disk_used_mb >= 0.0
        assert result.disk_available_mb >= 0.0
        assert result.disk_percent >= 0.0
        assert result.cpu_percent >= 0.0
        assert result.swap_total_mb >= 0.0
        assert result.swap_used_mb >= 0.0
        assert result.swap_available_mb >= 0.0
        assert result.uptime_seconds >= 0

        # Contar métricas que deberían tener valores por defecto
        funciones_exitosas = [f for f in PSUTIL_FUNCTIONS if f not in failing]

        # Si todas fallan, todo debe ser 0
        if len(funciones_exitosas) == 0:
            assert result.memory_total_mb == 0.0
            assert result.memory_used_mb == 0.0
            assert result.memory_available_mb == 0.0
            assert result.memory_percent == 0.0
            assert result.disk_total_mb == 0.0
            assert result.disk_used_mb == 0.0
            assert result.disk_available_mb == 0.0
            assert result.disk_percent == 0.0
            assert result.cpu_percent == 0.0
            assert result.swap_total_mb == 0.0
            assert result.swap_used_mb == 0.0
            assert result.swap_available_mb == 0.0
            assert result.uptime_seconds == 0
