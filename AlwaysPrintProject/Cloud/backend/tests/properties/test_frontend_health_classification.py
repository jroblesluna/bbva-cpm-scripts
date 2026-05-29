"""
Property tests para la clasificación del health check del frontend por status code.

Verifica que el SystemStatusCollector clasifica correctamente la disponibilidad
del frontend basándose en el código de respuesta HTTP:
- Disponible (is_available=True): solo para status codes 200, 302, 307
- No disponible (is_available=False): para cualquier otro código HTTP

**Validates: Requirements 2.2**

Feature: system-status-monitoring, Property 5: Frontend health check classification by status code
"""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.system_status import SystemStatusCollector


# === ESTRATEGIAS DE GENERACIÓN ===

# Códigos HTTP válidos en el rango 100-599
_http_status_code = st.integers(min_value=100, max_value=599)

# Códigos que indican disponibilidad del frontend
AVAILABLE_CODES = {200, 302, 307}


# === PROPERTY 5: FRONTEND HEALTH CHECK CLASSIFICATION BY STATUS CODE ===


class TestFrontendHealthClassification:
    """
    Property 5: Frontend health check classification by status code.

    Para cualquier código de estado HTTP en el rango 100-599, el health check
    del frontend SHALL clasificar el servicio como disponible si y solo si
    el código es 200, 302 o 307, y como no disponible para cualquier otro código.

    **Validates: Requirements 2.2**
    """

    @given(status_code=_http_status_code)
    @settings(max_examples=200, deadline=None)
    def test_clasificacion_disponible_solo_para_200_302_307(
        self, status_code: int
    ):
        """
        El frontend se clasifica como disponible si y solo si el status code
        es 200, 302 o 307. Para cualquier otro código, se clasifica como
        no disponible.

        **Validates: Requirements 2.2**
        """
        # Crear mock de la respuesta HTTP con el status code generado
        mock_response = MagicMock()
        mock_response.status_code = status_code

        # Mockear httpx.AsyncClient para retornar la respuesta simulada
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.system_status.httpx.AsyncClient", return_value=mock_client_instance):
            collector = SystemStatusCollector()
            result = asyncio.run(collector._check_frontend())

        # Verificar clasificación: disponible solo para 200, 302, 307
        expected_available = status_code in AVAILABLE_CODES

        assert result.is_available == expected_available, (
            f"Clasificación incorrecta para status code {status_code}. "
            f"Esperado is_available={expected_available}, "
            f"Obtenido is_available={result.is_available}"
        )

    @given(status_code=_http_status_code)
    @settings(max_examples=200, deadline=None)
    def test_clasificacion_es_exhaustiva_y_determinista(
        self, status_code: int
    ):
        """
        La clasificación es exhaustiva (todo código produce un resultado booleano)
        y determinista (el mismo código siempre produce el mismo resultado).

        **Validates: Requirements 2.2**
        """
        # Crear mock de la respuesta HTTP
        mock_response = MagicMock()
        mock_response.status_code = status_code

        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.system_status.httpx.AsyncClient", return_value=mock_client_instance):
            collector = SystemStatusCollector()
            # Ejecutar dos veces para verificar determinismo
            result1 = asyncio.run(collector._check_frontend())

        # Recrear mocks para segunda ejecución
        mock_client_instance2 = AsyncMock()
        mock_client_instance2.get = AsyncMock(return_value=mock_response)
        mock_client_instance2.__aenter__ = AsyncMock(return_value=mock_client_instance2)
        mock_client_instance2.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.system_status.httpx.AsyncClient", return_value=mock_client_instance2):
            collector2 = SystemStatusCollector()
            result2 = asyncio.run(collector2._check_frontend())

        # Verificar exhaustividad: el resultado siempre es un booleano
        assert isinstance(result1.is_available, bool), (
            f"is_available no es booleano para status code {status_code}: "
            f"{type(result1.is_available)}"
        )

        # Verificar determinismo: misma entrada produce misma salida
        assert result1.is_available == result2.is_available, (
            f"Clasificación no determinista para status code {status_code}. "
            f"Primera ejecución: {result1.is_available}, "
            f"Segunda ejecución: {result2.is_available}"
        )

    @given(status_code=st.sampled_from([200, 302, 307]))
    @settings(max_examples=50, deadline=None)
    def test_codigos_disponibles_siempre_retornan_true(
        self, status_code: int
    ):
        """
        Los códigos 200, 302 y 307 siempre clasifican el servicio como disponible.

        **Validates: Requirements 2.2**
        """
        # Crear mock de la respuesta HTTP
        mock_response = MagicMock()
        mock_response.status_code = status_code

        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.system_status.httpx.AsyncClient", return_value=mock_client_instance):
            collector = SystemStatusCollector()
            result = asyncio.run(collector._check_frontend())

        assert result.is_available is True, (
            f"Status code {status_code} debería ser disponible, "
            f"pero is_available={result.is_available}"
        )
        # Sin error_message cuando está disponible
        assert result.error_message is None, (
            f"No debería haber error_message para status code disponible {status_code}, "
            f"pero se obtuvo: {result.error_message}"
        )

    @given(
        status_code=_http_status_code.filter(lambda x: x not in {200, 302, 307})
    )
    @settings(max_examples=200, deadline=None)
    def test_codigos_no_disponibles_siempre_retornan_false(
        self, status_code: int
    ):
        """
        Cualquier código HTTP distinto de 200, 302 y 307 clasifica el servicio
        como no disponible.

        **Validates: Requirements 2.2**
        """
        # Crear mock de la respuesta HTTP
        mock_response = MagicMock()
        mock_response.status_code = status_code

        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.system_status.httpx.AsyncClient", return_value=mock_client_instance):
            collector = SystemStatusCollector()
            result = asyncio.run(collector._check_frontend())

        assert result.is_available is False, (
            f"Status code {status_code} NO debería ser disponible, "
            f"pero is_available={result.is_available}"
        )
        # Debe incluir error_message cuando no está disponible
        assert result.error_message is not None, (
            f"Debería haber error_message para status code no disponible {status_code}"
        )

    @given(status_code=_http_status_code)
    @settings(max_examples=200, deadline=None)
    def test_service_name_siempre_es_frontend(
        self, status_code: int
    ):
        """
        El nombre del servicio en el resultado siempre es "frontend",
        independientemente del status code recibido.

        **Validates: Requirements 2.2**
        """
        # Crear mock de la respuesta HTTP
        mock_response = MagicMock()
        mock_response.status_code = status_code

        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)

        with patch("app.services.system_status.httpx.AsyncClient", return_value=mock_client_instance):
            collector = SystemStatusCollector()
            result = asyncio.run(collector._check_frontend())

        assert result.service_name == "frontend", (
            f"service_name debería ser 'frontend', "
            f"pero se obtuvo: '{result.service_name}'"
        )
