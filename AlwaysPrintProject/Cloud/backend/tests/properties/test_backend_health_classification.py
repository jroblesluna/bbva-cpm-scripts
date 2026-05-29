"""
Property tests para la clasificación del health check del backend.

Verifica que el método _check_backend del SystemStatusCollector clasifica
correctamente la disponibilidad del servicio basándose en si la respuesta
HTTP contiene la subcadena "healthy".

**Validates: Requirements 2.1**

Feature: system-status-monitoring, Property 4: Backend health check classification
"""

import asyncio
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.system_status import SystemStatusCollector


# === ESTRATEGIAS DE GENERACIÓN ===

# Strings arbitrarios que NO contienen "healthy"
_text_without_healthy = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=0,
    max_size=500,
).filter(lambda s: "healthy" not in s)

# Strings que SÍ contienen "healthy" en alguna posición
_text_with_healthy = st.builds(
    lambda prefix, suffix: prefix + "healthy" + suffix,
    prefix=st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        min_size=0,
        max_size=200,
    ),
    suffix=st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        min_size=0,
        max_size=200,
    ),
)

# Cualquier string arbitrario (con o sin "healthy")
_arbitrary_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=0,
    max_size=500,
)


# === PROPERTY 4: BACKEND HEALTH CHECK CLASSIFICATION ===


class TestBackendHealthCheckClassification:
    """
    Property 4: Backend health check classification.

    Para cualquier string de respuesta HTTP, el health check del backend
    SHALL clasificar el servicio como disponible si y solo si la respuesta
    contiene la subcadena "healthy", y como no disponible en caso contrario.

    **Validates: Requirements 2.1**
    """

    @given(response_text=_text_with_healthy)
    @settings(max_examples=200, deadline=None)
    def test_disponible_cuando_respuesta_contiene_healthy(
        self, response_text: str
    ):
        """
        Si la respuesta HTTP contiene "healthy", el servicio se clasifica
        como disponible (is_available=True).

        **Validates: Requirements 2.1**
        """
        # Crear mock de la respuesta HTTP
        mock_response = MagicMock()
        mock_response.text = response_text

        # Mockear httpx.AsyncClient para retornar la respuesta simulada
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(
            return_value=mock_client_instance
        )
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.system_status.httpx.AsyncClient") as mock_client_cls, \
             patch("app.services.system_status.time") as mock_time:
            mock_client_cls.return_value = mock_client_instance
            mock_time.time.return_value = 1000.0

            collector = SystemStatusCollector()
            result = asyncio.run(collector._check_backend())

        # Verificar clasificación: disponible porque contiene "healthy"
        assert result.is_available is True, (
            f"El servicio debería estar disponible cuando la respuesta "
            f"contiene 'healthy'. Respuesta: {repr(response_text[:100])}"
        )
        assert result.service_name == "backend"
        assert result.error_message is None

    @given(response_text=_text_without_healthy)
    @settings(max_examples=200, deadline=None)
    def test_no_disponible_cuando_respuesta_no_contiene_healthy(
        self, response_text: str
    ):
        """
        Si la respuesta HTTP NO contiene "healthy", el servicio se clasifica
        como no disponible (is_available=False).

        **Validates: Requirements 2.1**
        """
        # Crear mock de la respuesta HTTP
        mock_response = MagicMock()
        mock_response.text = response_text

        # Mockear httpx.AsyncClient para retornar la respuesta simulada
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(
            return_value=mock_client_instance
        )
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.system_status.httpx.AsyncClient") as mock_client_cls, \
             patch("app.services.system_status.time") as mock_time:
            mock_client_cls.return_value = mock_client_instance
            mock_time.time.return_value = 1000.0

            collector = SystemStatusCollector()
            result = asyncio.run(collector._check_backend())

        # Verificar clasificación: no disponible porque no contiene "healthy"
        assert result.is_available is False, (
            f"El servicio NO debería estar disponible cuando la respuesta "
            f"no contiene 'healthy'. Respuesta: {repr(response_text[:100])}"
        )
        assert result.service_name == "backend"
        assert result.error_message is not None

    @given(response_text=_arbitrary_text)
    @settings(max_examples=200, deadline=None)
    def test_clasificacion_determinista_para_cualquier_entrada(
        self, response_text: str
    ):
        """
        La clasificación es determinista: para cualquier string dado,
        is_available == ("healthy" in response_text).

        Verifica la propiedad bicondicional completa: disponible si y solo si
        contiene "healthy".

        **Validates: Requirements 2.1**
        """
        # Crear mock de la respuesta HTTP
        mock_response = MagicMock()
        mock_response.text = response_text

        # Mockear httpx.AsyncClient para retornar la respuesta simulada
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(
            return_value=mock_client_instance
        )
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.system_status.httpx.AsyncClient") as mock_client_cls, \
             patch("app.services.system_status.time") as mock_time:
            mock_client_cls.return_value = mock_client_instance
            mock_time.time.return_value = 1000.0

            collector = SystemStatusCollector()
            result = asyncio.run(collector._check_backend())

        # Propiedad bicondicional: is_available ↔ "healthy" in response_text
        expected_available = "healthy" in response_text
        assert result.is_available == expected_available, (
            f"Clasificación incorrecta. "
            f"Respuesta contiene 'healthy': {expected_available}, "
            f"is_available: {result.is_available}. "
            f"Respuesta: {repr(response_text[:100])}"
        )
