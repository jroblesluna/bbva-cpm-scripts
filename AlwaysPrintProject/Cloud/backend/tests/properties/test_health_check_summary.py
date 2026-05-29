"""
Property tests para la corrección del conteo de resumen de health checks.

Verifica que el SystemStatusCollector produce un resumen correcto donde:
- ok_count + warning_count + failed_count == total de checks
- failed_count == cantidad de resultados con is_available == False
- warning_count == cantidad de resultados con is_available == True Y details.classification == "warning"
- ok_count == cantidad de resultados con is_available == True Y NO warning

**Validates: Requirements 2.8**

Feature: system-status-monitoring, Property 7: Health check summary counts
"""

from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.system_status import SystemStatusCollector
from app.schemas.system_status import HealthCheckResponse


# === ESTRATEGIAS DE GENERACIÓN ===

# Nombres de servicios que verifica el collector
_SERVICE_NAMES = ["backend", "frontend", "nginx", "redis", "rds", "ssl"]


@st.composite
def health_check_response_strategy(draw, service_name: str):
    """
    Genera un HealthCheckResponse aleatorio para un servicio dado.

    Produce tres tipos de resultados:
    - Disponible sin warning (ok): is_available=True, sin classification "warning"
    - Disponible con warning: is_available=True, details.classification="warning"
    - No disponible (failed): is_available=False

    Args:
        service_name: Nombre del servicio para el health check
    """
    # Decidir el tipo de resultado: ok, warning, o failed
    result_type = draw(st.sampled_from(["ok", "warning", "failed"]))

    latency_ms = draw(
        st.floats(min_value=0.1, max_value=10000.0, allow_nan=False, allow_infinity=False)
    )

    if result_type == "failed":
        # Servicio no disponible
        return HealthCheckResponse(
            service_name=service_name,
            is_available=False,
            latency_ms=round(latency_ms, 1),
            error_message="Error simulado para test",
            details=None,
        )
    elif result_type == "warning":
        # Servicio disponible pero con advertencia (ej: SSL próximo a expirar)
        days_remaining = draw(st.integers(min_value=1, max_value=14))
        return HealthCheckResponse(
            service_name=service_name,
            is_available=True,
            latency_ms=round(latency_ms, 1),
            error_message=None,
            details={
                "classification": "warning",
                "days_remaining": days_remaining,
            },
        )
    else:
        # Servicio disponible y sin problemas
        # Puede tener details sin classification, o details=None, o details con otro valor
        has_details = draw(st.booleans())
        if has_details:
            details = {
                "classification": "valid",
                "days_remaining": draw(st.integers(min_value=15, max_value=365)),
            }
        else:
            details = None

        return HealthCheckResponse(
            service_name=service_name,
            is_available=True,
            latency_ms=round(latency_ms, 1),
            error_message=None,
            details=details,
        )


@st.composite
def six_health_check_responses_strategy(draw):
    """
    Genera exactamente 6 HealthCheckResponse (uno por servicio verificado).

    Cada respuesta puede ser ok, warning o failed de forma independiente.
    """
    responses = []
    for service_name in _SERVICE_NAMES:
        response = draw(health_check_response_strategy(service_name))
        responses.append(response)
    return responses


# === PROPERTY 7: HEALTH CHECK SUMMARY COUNTS ===


class TestHealthCheckSummaryCounts:
    """
    Property 7: Health check summary counts.

    Para cualquier lista de resultados de health checks con estados
    (available, warning, unavailable), el resumen SHALL reportar conteos
    donde ok_count + warning_count + failed_count es igual al número total
    de checks, y cada conteo coincide con la cantidad real de resultados
    con ese estado.

    **Validates: Requirements 2.8**
    """

    @given(responses=six_health_check_responses_strategy())
    @settings(max_examples=200, deadline=None)
    @pytest.mark.asyncio
    async def test_suma_de_conteos_igual_al_total(
        self, responses: list,
    ):
        """
        La suma ok_count + warning_count + failed_count siempre es igual
        al número total de health checks realizados (6 servicios).

        **Validates: Requirements 2.8**
        """
        collector = SystemStatusCollector()

        # Mock de la sesión de DB (necesaria para _check_rds)
        mock_db = MagicMock()

        # Mockear los 6 métodos de verificación para retornar las respuestas generadas
        with patch.object(collector, "_check_backend", new_callable=AsyncMock, return_value=responses[0]), \
             patch.object(collector, "_check_frontend", new_callable=AsyncMock, return_value=responses[1]), \
             patch.object(collector, "_check_nginx", return_value=responses[2]), \
             patch.object(collector, "_check_redis", return_value=responses[3]), \
             patch.object(collector, "_check_rds", return_value=responses[4]), \
             patch.object(collector, "_check_ssl", return_value=responses[5]):

            results, summary = await collector.collect_health_checks(db=mock_db)

        # Verificar que la suma de conteos es igual al total de checks
        total = summary["ok_count"] + summary["warning_count"] + summary["failed_count"]
        assert total == len(results), (
            f"La suma de conteos ({total}) no coincide con el total de checks ({len(results)}). "
            f"Resumen: {summary}"
        )

    @given(responses=six_health_check_responses_strategy())
    @settings(max_examples=200, deadline=None)
    @pytest.mark.asyncio
    async def test_failed_count_coincide_con_no_disponibles(
        self, responses: list,
    ):
        """
        El failed_count coincide exactamente con la cantidad de resultados
        donde is_available == False.

        **Validates: Requirements 2.8**
        """
        collector = SystemStatusCollector()
        mock_db = MagicMock()

        with patch.object(collector, "_check_backend", new_callable=AsyncMock, return_value=responses[0]), \
             patch.object(collector, "_check_frontend", new_callable=AsyncMock, return_value=responses[1]), \
             patch.object(collector, "_check_nginx", return_value=responses[2]), \
             patch.object(collector, "_check_redis", return_value=responses[3]), \
             patch.object(collector, "_check_rds", return_value=responses[4]), \
             patch.object(collector, "_check_ssl", return_value=responses[5]):

            results, summary = await collector.collect_health_checks(db=mock_db)

        # Contar manualmente los servicios no disponibles
        expected_failed = sum(1 for r in results if not r.is_available)

        assert summary["failed_count"] == expected_failed, (
            f"failed_count ({summary['failed_count']}) no coincide con "
            f"la cantidad real de servicios no disponibles ({expected_failed}). "
            f"Resultados: {[(r.service_name, r.is_available) for r in results]}"
        )

    @given(responses=six_health_check_responses_strategy())
    @settings(max_examples=200, deadline=None)
    @pytest.mark.asyncio
    async def test_warning_count_coincide_con_disponibles_con_warning(
        self, responses: list,
    ):
        """
        El warning_count coincide exactamente con la cantidad de resultados
        donde is_available == True Y details.classification == "warning".

        **Validates: Requirements 2.8**
        """
        collector = SystemStatusCollector()
        mock_db = MagicMock()

        with patch.object(collector, "_check_backend", new_callable=AsyncMock, return_value=responses[0]), \
             patch.object(collector, "_check_frontend", new_callable=AsyncMock, return_value=responses[1]), \
             patch.object(collector, "_check_nginx", return_value=responses[2]), \
             patch.object(collector, "_check_redis", return_value=responses[3]), \
             patch.object(collector, "_check_rds", return_value=responses[4]), \
             patch.object(collector, "_check_ssl", return_value=responses[5]):

            results, summary = await collector.collect_health_checks(db=mock_db)

        # Contar manualmente los servicios con warning
        expected_warning = sum(
            1 for r in results
            if r.is_available and r.details and r.details.get("classification") == "warning"
        )

        assert summary["warning_count"] == expected_warning, (
            f"warning_count ({summary['warning_count']}) no coincide con "
            f"la cantidad real de servicios con warning ({expected_warning}). "
            f"Resultados: {[(r.service_name, r.is_available, r.details) for r in results]}"
        )

    @given(responses=six_health_check_responses_strategy())
    @settings(max_examples=200, deadline=None)
    @pytest.mark.asyncio
    async def test_ok_count_coincide_con_disponibles_sin_warning(
        self, responses: list,
    ):
        """
        El ok_count coincide exactamente con la cantidad de resultados
        donde is_available == True Y NO tiene classification "warning".

        **Validates: Requirements 2.8**
        """
        collector = SystemStatusCollector()
        mock_db = MagicMock()

        with patch.object(collector, "_check_backend", new_callable=AsyncMock, return_value=responses[0]), \
             patch.object(collector, "_check_frontend", new_callable=AsyncMock, return_value=responses[1]), \
             patch.object(collector, "_check_nginx", return_value=responses[2]), \
             patch.object(collector, "_check_redis", return_value=responses[3]), \
             patch.object(collector, "_check_rds", return_value=responses[4]), \
             patch.object(collector, "_check_ssl", return_value=responses[5]):

            results, summary = await collector.collect_health_checks(db=mock_db)

        # Contar manualmente los servicios ok (disponibles sin warning)
        expected_ok = sum(
            1 for r in results
            if r.is_available and not (r.details and r.details.get("classification") == "warning")
        )

        assert summary["ok_count"] == expected_ok, (
            f"ok_count ({summary['ok_count']}) no coincide con "
            f"la cantidad real de servicios ok ({expected_ok}). "
            f"Resultados: {[(r.service_name, r.is_available, r.details) for r in results]}"
        )
