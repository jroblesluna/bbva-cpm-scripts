"""
Tests unitarios para el servicio LLM.

Verifica:
- Retry con exponential backoff en throttling (429) para Bedrock
- Error LLMServiceError después de agotar reintentos
- Respuesta exitosa con métricas loggeadas
- Selección de provider según variable de entorno
- OpenAI provider con mock de httpx
- Anthropic provider con mock de httpx

Requirements: 10.6, 10.7, 10.8
"""

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.services.llm_service import (
    AnthropicProvider,
    BedrockProvider,
    LLMService,
    LLMServiceError,
    MAX_RETRIES,
    OpenAIProvider,
    RETRY_DELAYS,
)


# === FIXTURES ===


@pytest.fixture
def mock_settings_bedrock():
    """Settings con provider bedrock (default)."""
    with patch("app.services.llm_service.settings") as mock_s:
        mock_s.LOG_ANALYZER_LLM_PROVIDER = "bedrock"
        mock_s.LOG_ANALYZER_LLM_MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"
        mock_s.LOG_ANALYZER_LLM_REGION = "us-west-2"
        mock_s.LOG_ANALYZER_LLM_MAX_TOKENS = 4096
        mock_s.LOG_ANALYZER_OPENAI_API_KEY = "sk-test-key"
        mock_s.LOG_ANALYZER_OPENAI_MODEL = "gpt-4o"
        mock_s.LOG_ANALYZER_ANTHROPIC_API_KEY = "sk-ant-test-key"
        mock_s.LOG_ANALYZER_ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"
        yield mock_s


@pytest.fixture
def mock_settings_openai():
    """Settings con provider openai."""
    with patch("app.services.llm_service.settings") as mock_s:
        mock_s.LOG_ANALYZER_LLM_PROVIDER = "openai"
        mock_s.LOG_ANALYZER_LLM_MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"
        mock_s.LOG_ANALYZER_LLM_REGION = "us-west-2"
        mock_s.LOG_ANALYZER_LLM_MAX_TOKENS = 4096
        mock_s.LOG_ANALYZER_OPENAI_API_KEY = "sk-test-key"
        mock_s.LOG_ANALYZER_OPENAI_MODEL = "gpt-4o"
        mock_s.LOG_ANALYZER_ANTHROPIC_API_KEY = "sk-ant-test-key"
        mock_s.LOG_ANALYZER_ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"
        yield mock_s


@pytest.fixture
def mock_settings_anthropic():
    """Settings con provider anthropic."""
    with patch("app.services.llm_service.settings") as mock_s:
        mock_s.LOG_ANALYZER_LLM_PROVIDER = "anthropic"
        mock_s.LOG_ANALYZER_LLM_MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"
        mock_s.LOG_ANALYZER_LLM_REGION = "us-west-2"
        mock_s.LOG_ANALYZER_LLM_MAX_TOKENS = 4096
        mock_s.LOG_ANALYZER_OPENAI_API_KEY = "sk-test-key"
        mock_s.LOG_ANALYZER_OPENAI_MODEL = "gpt-4o"
        mock_s.LOG_ANALYZER_ANTHROPIC_API_KEY = "sk-ant-test-key"
        mock_s.LOG_ANALYZER_ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"
        yield mock_s


# === TESTS BEDROCK PROVIDER ===


class TestBedrockProviderRetry:
    """Tests de retry con exponential backoff para BedrockProvider."""

    @pytest.mark.asyncio
    async def test_retry_en_throttling_429_con_exito_final(self, mock_settings_bedrock):
        """
        WHEN Bedrock retorna ThrottlingException en los primeros intentos,
        THEN reintenta con backoff exponencial y retorna respuesta exitosa.
        Validates: Requirement 10.6
        """
        import botocore.exceptions

        provider = BedrockProvider()

        # Simular 2 throttling seguidos de éxito
        throttle_error = botocore.exceptions.ClientError(
            {"Error": {"Code": "ThrottlingException"}, "ResponseMetadata": {"HTTPStatusCode": 429}},
            "Converse",
        )
        success_response = {
            "output": {
                "message": {
                    "content": [{"text": "Análisis completado exitosamente."}]
                }
            },
            "usage": {"inputTokens": 100, "outputTokens": 50},
        }

        mock_client = MagicMock()
        mock_client.converse = MagicMock(
            side_effect=[throttle_error, throttle_error, success_response]
        )
        provider._client = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await provider.invoke("test payload", 4096)

        assert result == "Análisis completado exitosamente."
        # Verificar que se esperó con backoff exponencial (1s, 2s)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1)
        mock_sleep.assert_any_call(2)

    @pytest.mark.asyncio
    async def test_error_despues_de_reintentos_agotados(self, mock_settings_bedrock):
        """
        WHEN Bedrock retorna ThrottlingException en todos los intentos,
        THEN lanza LLMServiceError después de agotar reintentos.
        Validates: Requirement 10.7
        """
        import botocore.exceptions

        provider = BedrockProvider()

        throttle_error = botocore.exceptions.ClientError(
            {"Error": {"Code": "ThrottlingException"}, "ResponseMetadata": {"HTTPStatusCode": 429}},
            "Converse",
        )

        mock_client = MagicMock()
        mock_client.converse = MagicMock(side_effect=throttle_error)
        provider._client = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(LLMServiceError) as exc_info:
                await provider.invoke("test payload", 4096)

        assert "reintentos agotados" in str(exc_info.value)
        assert str(MAX_RETRIES) in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_error_no_reintentable_lanza_inmediatamente(self, mock_settings_bedrock):
        """
        WHEN Bedrock retorna un error no reintentable (ej: AccessDeniedException),
        THEN lanza LLMServiceError inmediatamente sin reintentar.
        """
        import botocore.exceptions

        provider = BedrockProvider()

        access_denied = botocore.exceptions.ClientError(
            {"Error": {"Code": "AccessDeniedException"}, "ResponseMetadata": {"HTTPStatusCode": 403}},
            "Converse",
        )

        mock_client = MagicMock()
        mock_client.converse = MagicMock(side_effect=access_denied)
        provider._client = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(LLMServiceError) as exc_info:
                await provider.invoke("test payload", 4096)

        # No debe reintentar en errores no reintentables
        mock_sleep.assert_not_called()
        assert "AccessDeniedException" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_respuesta_exitosa_con_metricas(self, mock_settings_bedrock, caplog):
        """
        WHEN Bedrock retorna respuesta exitosa,
        THEN loguea input_tokens y output_tokens.
        Validates: Requirement 10.8
        """
        provider = BedrockProvider()

        success_response = {
            "output": {
                "message": {
                    "content": [{"text": "Resultado del análisis."}]
                }
            },
            "usage": {"inputTokens": 250, "outputTokens": 120},
        }

        mock_client = MagicMock()
        mock_client.converse = MagicMock(return_value=success_response)
        provider._client = mock_client

        with caplog.at_level(logging.INFO, logger="app.services.llm_service"):
            result = await provider.invoke("test payload", 4096)

        assert result == "Resultado del análisis."
        # Verificar que se loggearon las métricas
        assert any("input_tokens: 250" in record.message for record in caplog.records)
        assert any("output_tokens: 120" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_retry_en_error_servidor_5xx(self, mock_settings_bedrock):
        """
        WHEN Bedrock retorna error de servidor (500),
        THEN reintenta con backoff exponencial.
        Validates: Requirement 10.6
        """
        import botocore.exceptions

        provider = BedrockProvider()

        server_error = botocore.exceptions.ClientError(
            {"Error": {"Code": "InternalServerError"}, "ResponseMetadata": {"HTTPStatusCode": 500}},
            "Converse",
        )
        success_response = {
            "output": {
                "message": {
                    "content": [{"text": "OK"}]
                }
            },
            "usage": {"inputTokens": 10, "outputTokens": 5},
        }

        mock_client = MagicMock()
        mock_client.converse = MagicMock(side_effect=[server_error, success_response])
        provider._client = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await provider.invoke("test", 4096)

        assert result == "OK"
        mock_sleep.assert_called_once_with(1)


# === TESTS SELECCIÓN DE PROVIDER ===


class TestLLMServiceProviderSelection:
    """Tests de selección de provider según variable de entorno."""

    def test_selecciona_bedrock_por_defecto(self, mock_settings_bedrock):
        """
        WHEN LOG_ANALYZER_LLM_PROVIDER es 'bedrock',
        THEN LLMService usa BedrockProvider.
        """
        service = LLMService()
        provider = service.provider

        assert isinstance(provider, BedrockProvider)

    def test_selecciona_openai_segun_env(self, mock_settings_openai):
        """
        WHEN LOG_ANALYZER_LLM_PROVIDER es 'openai',
        THEN LLMService usa OpenAIProvider.
        """
        service = LLMService()
        provider = service.provider

        assert isinstance(provider, OpenAIProvider)

    def test_selecciona_anthropic_segun_env(self, mock_settings_anthropic):
        """
        WHEN LOG_ANALYZER_LLM_PROVIDER es 'anthropic',
        THEN LLMService usa AnthropicProvider.
        """
        service = LLMService()
        provider = service.provider

        assert isinstance(provider, AnthropicProvider)

    def test_valor_desconocido_usa_bedrock(self, mock_settings_bedrock):
        """
        WHEN LOG_ANALYZER_LLM_PROVIDER tiene un valor no reconocido,
        THEN LLMService usa BedrockProvider como fallback.
        """
        mock_settings_bedrock.LOG_ANALYZER_LLM_PROVIDER = "unknown_provider"
        service = LLMService()
        provider = service.provider

        assert isinstance(provider, BedrockProvider)


# === TESTS LLMSERVICE INVOKE ===


class TestLLMServiceInvoke:
    """Tests del método invoke de LLMService."""

    @pytest.mark.asyncio
    async def test_invoke_exitoso_loguea_duracion(self, mock_settings_bedrock, caplog):
        """
        WHEN LLMService.invoke se ejecuta exitosamente,
        THEN loguea la duración de la invocación.
        Validates: Requirement 10.8
        """
        service = LLMService()
        mock_provider = AsyncMock()
        mock_provider.invoke = AsyncMock(return_value="Respuesta del LLM")
        mock_provider.get_provider_name = MagicMock(return_value="bedrock:test-model")
        service._provider = mock_provider

        with caplog.at_level(logging.INFO, logger="app.services.llm_service"):
            result = await service.invoke("payload de prueba")

        assert result == "Respuesta del LLM"
        # Verificar que se loggeó la duración
        assert any("duración" in record.message for record in caplog.records)
        assert any("invocación completada" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_invoke_error_propaga_llm_service_error(self, mock_settings_bedrock, caplog):
        """
        WHEN el provider lanza LLMServiceError,
        THEN LLMService.invoke propaga el error y loguea la falla.
        Validates: Requirement 10.7
        """
        service = LLMService()
        mock_provider = AsyncMock()
        mock_provider.invoke = AsyncMock(
            side_effect=LLMServiceError("reintentos agotados")
        )
        mock_provider.get_provider_name = MagicMock(return_value="bedrock:test-model")
        service._provider = mock_provider

        with caplog.at_level(logging.ERROR, logger="app.services.llm_service"):
            with pytest.raises(LLMServiceError):
                await service.invoke("payload de prueba")

        assert any("invocación fallida" in record.message for record in caplog.records)


# === TESTS OPENAI PROVIDER ===


class TestOpenAIProvider:
    """Tests para OpenAIProvider con mock de httpx."""

    @pytest.mark.asyncio
    async def test_respuesta_exitosa(self, mock_settings_openai):
        """
        WHEN OpenAI retorna 200 con respuesta válida,
        THEN extrae el texto y loguea métricas.
        Validates: Requirement 10.8
        """
        provider = OpenAIProvider()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Análisis OpenAI completado."}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 80},
        }

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            result = await provider.invoke("test payload", 4096)

        assert result == "Análisis OpenAI completado."
        # Verificar que se llamó con los headers correctos
        mock_client_instance.post.assert_called_once()
        call_kwargs = mock_client_instance.post.call_args
        assert "Bearer sk-test-key" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_retry_en_throttling_429(self, mock_settings_openai):
        """
        WHEN OpenAI retorna 429 (rate limit),
        THEN reintenta con backoff exponencial.
        Validates: Requirement 10.6
        """
        provider = OpenAIProvider()

        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.text = "Rate limit exceeded"

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {
            "choices": [{"message": {"content": "OK"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(
            side_effect=[mock_response_429, mock_response_200]
        )
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await provider.invoke("test", 4096)

        assert result == "OK"
        mock_sleep.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_error_despues_de_reintentos_agotados(self, mock_settings_openai):
        """
        WHEN OpenAI retorna 429 en todos los intentos,
        THEN lanza LLMServiceError.
        Validates: Requirement 10.7
        """
        provider = OpenAIProvider()

        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.text = "Rate limit exceeded"

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_response_429)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(LLMServiceError) as exc_info:
                    await provider.invoke("test", 4096)

        assert "reintentos agotados" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_error_no_reintentable_4xx(self, mock_settings_openai):
        """
        WHEN OpenAI retorna error 4xx (no 429),
        THEN lanza LLMServiceError inmediatamente sin reintentar.
        """
        provider = OpenAIProvider()

        mock_response_401 = MagicMock()
        mock_response_401.status_code = 401
        mock_response_401.text = "Invalid API key"

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_response_401)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                with pytest.raises(LLMServiceError) as exc_info:
                    await provider.invoke("test", 4096)

        mock_sleep.assert_not_called()
        assert "401" in str(exc_info.value)


# === TESTS ANTHROPIC PROVIDER ===


class TestAnthropicProvider:
    """Tests para AnthropicProvider con mock de httpx."""

    @pytest.mark.asyncio
    async def test_respuesta_exitosa(self, mock_settings_anthropic):
        """
        WHEN Anthropic retorna 200 con respuesta válida,
        THEN extrae el texto de los content blocks y loguea métricas.
        Validates: Requirement 10.8
        """
        provider = AnthropicProvider()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Análisis Anthropic completado."}],
            "usage": {"input_tokens": 300, "output_tokens": 150},
        }

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            result = await provider.invoke("test payload", 4096)

        assert result == "Análisis Anthropic completado."
        # Verificar headers de Anthropic
        call_kwargs = mock_client_instance.post.call_args
        assert "x-api-key" in str(call_kwargs) or "sk-ant-test-key" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_retry_en_throttling_429(self, mock_settings_anthropic):
        """
        WHEN Anthropic retorna 429 (rate limit),
        THEN reintenta con backoff exponencial.
        Validates: Requirement 10.6
        """
        provider = AnthropicProvider()

        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.text = "Rate limit exceeded"

        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {
            "content": [{"type": "text", "text": "OK"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(
            side_effect=[mock_response_429, mock_response_200]
        )
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await provider.invoke("test", 4096)

        assert result == "OK"
        mock_sleep.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_error_despues_de_reintentos_agotados(self, mock_settings_anthropic):
        """
        WHEN Anthropic retorna 429 en todos los intentos,
        THEN lanza LLMServiceError.
        Validates: Requirement 10.7
        """
        provider = AnthropicProvider()

        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.text = "Rate limit exceeded"

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_response_429)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(LLMServiceError) as exc_info:
                    await provider.invoke("test", 4096)

        assert "reintentos agotados" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_error_no_reintentable_4xx(self, mock_settings_anthropic):
        """
        WHEN Anthropic retorna error 4xx (no 429),
        THEN lanza LLMServiceError inmediatamente sin reintentar.
        """
        provider = AnthropicProvider()

        mock_response_400 = MagicMock()
        mock_response_400.status_code = 400
        mock_response_400.text = "Invalid request"

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_response_400)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                with pytest.raises(LLMServiceError) as exc_info:
                    await provider.invoke("test", 4096)

        mock_sleep.assert_not_called()
        assert "400" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_multiples_content_blocks(self, mock_settings_anthropic):
        """
        WHEN Anthropic retorna múltiples content blocks de tipo text,
        THEN concatena todos los textos.
        """
        provider = AnthropicProvider()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [
                {"type": "text", "text": "Primera parte. "},
                {"type": "text", "text": "Segunda parte."},
            ],
            "usage": {"input_tokens": 50, "output_tokens": 30},
        }

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            result = await provider.invoke("test", 4096)

        assert result == "Primera parte. Segunda parte."
