"""
Servicio de integración con modelos LLM.

Soporta múltiples providers configurables via variable de entorno:
- "bedrock": AWS Bedrock Claude (default)
- "openai": OpenAI API (GPT-4o)
- "anthropic": Anthropic API directa (Claude)

Maneja invocación del modelo, reintentos con backoff exponencial,
y logging de métricas (duración, tokens).
"""

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# Delays para reintentos con exponential backoff (en segundos)
RETRY_DELAYS = [1, 2, 4]
MAX_RETRIES = 3


class LLMServiceError(Exception):
    """Error del servicio LLM después de agotar reintentos."""

    pass


class LLMProvider(ABC):
    """Interfaz abstracta para providers de LLM."""

    @abstractmethod
    async def invoke(self, payload: str, max_tokens: int, model_id: Optional[str] = None) -> str:
        """
        Invoca el modelo con el payload dado.

        Parámetros:
            payload: Texto completo a enviar al modelo
            max_tokens: Máximo de tokens en la respuesta
            model_id: Override del modelo a usar (None = usar default del provider)

        Retorna:
            Texto de respuesta del modelo.

        Raises:
            LLMServiceError: Si falla después de todos los reintentos.
        """
        ...

    @abstractmethod
    def get_provider_name(self) -> str:
        """Retorna nombre del provider para logging."""
        ...


class BedrockProvider(LLMProvider):
    """
    Provider para AWS Bedrock Claude.

    Usa la Converse API del cliente bedrock-runtime.
    Inicialización lazy del cliente boto3.
    """

    def __init__(self):
        self.model_id: str = settings.LOG_ANALYZER_LLM_MODEL_ID
        self.region: str = settings.LOG_ANALYZER_LLM_REGION
        self._client = None

    @property
    def client(self):
        """Inicialización lazy del cliente Bedrock."""
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
            )
            logger.info(
                "[LOG_ANALYZER] Cliente Bedrock inicializado - región: %s, modelo: %s",
                self.region,
                self.model_id,
            )
        return self._client

    async def invoke(self, payload: str, max_tokens: int, model_id: Optional[str] = None) -> str:
        """
        Invoca Claude via Bedrock Converse API.

        Parámetros:
            payload: Texto completo a enviar al modelo
            max_tokens: Máximo de tokens en la respuesta
            model_id: Override del modelo (None = usar self.model_id)

        Retorna:
            Texto de respuesta del modelo.

        Raises:
            LLMServiceError: Si falla después de todos los reintentos.
        """
        import botocore.exceptions

        effective_model = model_id or self.model_id
        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            try:
                # Ejecutar llamada síncrona de boto3 en un thread para no bloquear el event loop
                response = await asyncio.to_thread(
                    self.client.converse,
                    modelId=effective_model,
                    messages=[
                        {
                            "role": "user",
                            "content": [{"text": payload}],
                        }
                    ],
                    inferenceConfig={"maxTokens": max_tokens},
                )

                # Extraer texto de respuesta
                output_message = response.get("output", {}).get("message", {})
                content_blocks = output_message.get("content", [])
                response_text = ""
                for block in content_blocks:
                    if "text" in block:
                        response_text += block["text"]

                # Extraer métricas de tokens
                usage = response.get("usage", {})
                input_tokens = usage.get("inputTokens", 0)
                output_tokens = usage.get("outputTokens", 0)

                logger.info(
                    "[LOG_ANALYZER] Bedrock respuesta exitosa - "
                    "input_tokens: %d, output_tokens: %d",
                    input_tokens,
                    output_tokens,
                )

                return response_text

            except botocore.exceptions.ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                status_code = e.response.get("ResponseMetadata", {}).get(
                    "HTTPStatusCode", 0
                )

                # Reintentar en throttling (429) o errores de servidor (5xx)
                if error_code == "ThrottlingException" or status_code == 429 or status_code >= 500:
                    last_error = e
                    if attempt < MAX_RETRIES - 1:
                        delay = RETRY_DELAYS[attempt]
                        logger.warning(
                            "[LOG_ANALYZER] Bedrock error reintentable (intento %d/%d, "
                            "código: %s, status: %d). Reintentando en %ds...",
                            attempt + 1,
                            MAX_RETRIES,
                            error_code,
                            status_code,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                else:
                    # Error no reintentable
                    raise LLMServiceError(
                        f"Error de Bedrock no reintentable: {error_code} - {e}"
                    ) from e

            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    logger.warning(
                        "[LOG_ANALYZER] Bedrock error inesperado (intento %d/%d): %s. "
                        "Reintentando en %ds...",
                        attempt + 1,
                        MAX_RETRIES,
                        str(e),
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

        raise LLMServiceError(
            f"Bedrock: reintentos agotados después de {MAX_RETRIES} intentos. "
            f"Último error: {last_error}"
        ) from last_error

    def get_provider_name(self) -> str:
        """Retorna nombre del provider para logging."""
        return f"bedrock:{self.model_id}"


class OpenAIProvider(LLMProvider):
    """
    Provider para OpenAI API (GPT-4o).

    Usa httpx para invocación HTTP directa a la API de OpenAI.
    """

    def __init__(self):
        self.api_key: str = settings.LOG_ANALYZER_OPENAI_API_KEY
        self.model: str = settings.LOG_ANALYZER_OPENAI_MODEL
        self.base_url: str = "https://api.openai.com/v1"

    async def invoke(self, payload: str, max_tokens: int, model_id: Optional[str] = None) -> str:
        """
        Invoca GPT-4o via OpenAI Chat Completions API.

        Parámetros:
            payload: Texto completo a enviar al modelo
            max_tokens: Máximo de tokens en la respuesta
            model_id: Override del modelo (no usado en OpenAI, usa self.model)

        Retorna:
            Texto de respuesta del modelo.

        Raises:
            LLMServiceError: Si falla después de todos los reintentos.
        """
        import httpx

        last_error: Optional[Exception] = None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        request_body = {
            "model": self.model,
            "messages": [{"role": "user", "content": payload}],
            "max_tokens": max_tokens,
        }

        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=headers,
                        json=request_body,
                    )

                    if response.status_code == 200:
                        data = response.json()
                        response_text = (
                            data.get("choices", [{}])[0]
                            .get("message", {})
                            .get("content", "")
                        )

                        # Extraer métricas de tokens
                        usage = data.get("usage", {})
                        input_tokens = usage.get("prompt_tokens", 0)
                        output_tokens = usage.get("completion_tokens", 0)

                        logger.info(
                            "[LOG_ANALYZER] OpenAI respuesta exitosa - "
                            "input_tokens: %d, output_tokens: %d",
                            input_tokens,
                            output_tokens,
                        )

                        return response_text

                    # Reintentar en throttling (429) o errores de servidor (5xx)
                    if response.status_code == 429 or response.status_code >= 500:
                        last_error = LLMServiceError(
                            f"OpenAI HTTP {response.status_code}: {response.text}"
                        )
                        if attempt < MAX_RETRIES - 1:
                            delay = RETRY_DELAYS[attempt]
                            logger.warning(
                                "[LOG_ANALYZER] OpenAI error reintentable "
                                "(intento %d/%d, status: %d). Reintentando en %ds...",
                                attempt + 1,
                                MAX_RETRIES,
                                response.status_code,
                                delay,
                            )
                            await asyncio.sleep(delay)
                            continue
                    else:
                        # Error no reintentable (4xx excepto 429)
                        raise LLMServiceError(
                            f"OpenAI error no reintentable HTTP {response.status_code}: "
                            f"{response.text}"
                        )

            except httpx.HTTPError as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    logger.warning(
                        "[LOG_ANALYZER] OpenAI error de conexión (intento %d/%d): %s. "
                        "Reintentando en %ds...",
                        attempt + 1,
                        MAX_RETRIES,
                        str(e),
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

            except LLMServiceError:
                raise

            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    logger.warning(
                        "[LOG_ANALYZER] OpenAI error inesperado (intento %d/%d): %s. "
                        "Reintentando en %ds...",
                        attempt + 1,
                        MAX_RETRIES,
                        str(e),
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

        raise LLMServiceError(
            f"OpenAI: reintentos agotados después de {MAX_RETRIES} intentos. "
            f"Último error: {last_error}"
        ) from last_error

    def get_provider_name(self) -> str:
        """Retorna nombre del provider para logging."""
        return f"openai:{self.model}"


class AnthropicProvider(LLMProvider):
    """
    Provider para Anthropic Messages API directa.

    Usa httpx para invocación HTTP directa a la API de Anthropic.
    """

    def __init__(self):
        self.api_key: str = settings.LOG_ANALYZER_ANTHROPIC_API_KEY
        self.model: str = settings.LOG_ANALYZER_ANTHROPIC_MODEL
        self.base_url: str = "https://api.anthropic.com/v1"

    async def invoke(self, payload: str, max_tokens: int, model_id: Optional[str] = None) -> str:
        """
        Invoca Claude via Anthropic Messages API.

        Parámetros:
            payload: Texto completo a enviar al modelo
            max_tokens: Máximo de tokens en la respuesta
            model_id: Override del modelo (no usado en Anthropic, usa self.model)

        Retorna:
            Texto de respuesta del modelo.

        Raises:
            LLMServiceError: Si falla después de todos los reintentos.
        """
        import httpx

        last_error: Optional[Exception] = None
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        request_body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": payload}],
        }

        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(
                        f"{self.base_url}/messages",
                        headers=headers,
                        json=request_body,
                    )

                    if response.status_code == 200:
                        data = response.json()

                        # Extraer texto de los content blocks
                        content_blocks = data.get("content", [])
                        response_text = ""
                        for block in content_blocks:
                            if block.get("type") == "text":
                                response_text += block.get("text", "")

                        # Extraer métricas de tokens
                        usage = data.get("usage", {})
                        input_tokens = usage.get("input_tokens", 0)
                        output_tokens = usage.get("output_tokens", 0)

                        logger.info(
                            "[LOG_ANALYZER] Anthropic respuesta exitosa - "
                            "input_tokens: %d, output_tokens: %d",
                            input_tokens,
                            output_tokens,
                        )

                        return response_text

                    # Reintentar en throttling (429) o errores de servidor (5xx)
                    if response.status_code == 429 or response.status_code >= 500:
                        last_error = LLMServiceError(
                            f"Anthropic HTTP {response.status_code}: {response.text}"
                        )
                        if attempt < MAX_RETRIES - 1:
                            delay = RETRY_DELAYS[attempt]
                            logger.warning(
                                "[LOG_ANALYZER] Anthropic error reintentable "
                                "(intento %d/%d, status: %d). Reintentando en %ds...",
                                attempt + 1,
                                MAX_RETRIES,
                                response.status_code,
                                delay,
                            )
                            await asyncio.sleep(delay)
                            continue
                    else:
                        # Error no reintentable (4xx excepto 429)
                        raise LLMServiceError(
                            f"Anthropic error no reintentable HTTP {response.status_code}: "
                            f"{response.text}"
                        )

            except httpx.HTTPError as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    logger.warning(
                        "[LOG_ANALYZER] Anthropic error de conexión (intento %d/%d): %s. "
                        "Reintentando en %ds...",
                        attempt + 1,
                        MAX_RETRIES,
                        str(e),
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

            except LLMServiceError:
                raise

            except Exception as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    logger.warning(
                        "[LOG_ANALYZER] Anthropic error inesperado (intento %d/%d): %s. "
                        "Reintentando en %ds...",
                        attempt + 1,
                        MAX_RETRIES,
                        str(e),
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

        raise LLMServiceError(
            f"Anthropic: reintentos agotados después de {MAX_RETRIES} intentos. "
            f"Último error: {last_error}"
        ) from last_error

    def get_provider_name(self) -> str:
        """Retorna nombre del provider para logging."""
        return f"anthropic:{self.model}"


class LLMService:
    """
    Servicio LLM parametrizable.

    Selecciona el provider según la variable de entorno LOG_ANALYZER_LLM_PROVIDER.
    Implementa logging de duración y métricas para todos los providers.
    El retry con exponential backoff se maneja dentro de cada provider.
    """

    def __init__(self):
        self.max_tokens: int = settings.LOG_ANALYZER_LLM_MAX_TOKENS
        self._provider: Optional[LLMProvider] = None

    @property
    def provider(self) -> LLMProvider:
        """Inicialización lazy del provider según configuración."""
        if self._provider is None:
            provider_name = settings.LOG_ANALYZER_LLM_PROVIDER
            if provider_name == "openai":
                self._provider = OpenAIProvider()
            elif provider_name == "anthropic":
                self._provider = AnthropicProvider()
            else:  # default: "bedrock"
                self._provider = BedrockProvider()
            logger.info(
                "[LOG_ANALYZER] LLM provider inicializado: %s",
                self._provider.get_provider_name(),
            )
        return self._provider

    async def invoke(self, payload: str, model_id: Optional[str] = None) -> str:
        """
        Invoca el LLM configurado.

        Mide duración total de la invocación y loguea métricas.
        El retry con exponential backoff se maneja dentro de cada provider.

        Parámetros:
            payload: Texto completo a enviar al modelo (prompt + datos)
            model_id: Override del modelo a usar (None = usar default del provider)

        Retorna:
            Texto de respuesta del modelo.

        Raises:
            LLMServiceError: Si falla después de todos los reintentos.
        """
        start_time = time.time()
        provider = self.provider

        logger.info(
            "[LOG_ANALYZER] Invocando LLM provider=%s, model_override=%s, max_tokens=%d, "
            "payload_length=%d chars",
            provider.get_provider_name(),
            model_id or "(default)",
            self.max_tokens,
            len(payload),
        )

        try:
            response = await provider.invoke(payload, self.max_tokens, model_id=model_id)
            duration_ms = int((time.time() - start_time) * 1000)

            logger.info(
                "[LOG_ANALYZER] LLM invocación completada - provider: %s, "
                "duración: %dms, respuesta_length: %d chars",
                provider.get_provider_name(),
                duration_ms,
                len(response),
            )

            return response

        except LLMServiceError:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "[LOG_ANALYZER] LLM invocación fallida - provider: %s, "
                "duración: %dms",
                provider.get_provider_name(),
                duration_ms,
            )
            raise

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(
                "[LOG_ANALYZER] LLM error inesperado - provider: %s, "
                "duración: %dms, error: %s",
                provider.get_provider_name(),
                duration_ms,
                str(e),
            )
            raise LLMServiceError(
                f"Error inesperado del servicio LLM: {e}"
            ) from e


    @staticmethod
    async def list_available_models() -> list[dict]:
        """
        Lista los modelos de texto disponibles en AWS Bedrock, agrupados por provider.

        Intenta llamar a ListFoundationModels de Bedrock sin filtro de provider.
        Si falla, retorna una lista de modelos conocidos como fallback.

        Retorna:
            Lista de dicts con: model_id, model_name, provider
        """
        import boto3

        # Modelos conocidos como fallback
        KNOWN_MODELS = [
            {"model_id": "us.anthropic.claude-sonnet-4-20250514-v1:0", "model_name": "Claude Sonnet 4", "provider": "Anthropic"},
            {"model_id": "us.anthropic.claude-sonnet-4-5-20250929-v1:0", "model_name": "Claude Sonnet 4.5", "provider": "Anthropic"},
            {"model_id": "us.anthropic.claude-sonnet-4-6-20251218-v1:0", "model_name": "Claude Sonnet 4.6", "provider": "Anthropic"},
            {"model_id": "us.anthropic.claude-opus-4-6-20250501-v1:0", "model_name": "Claude Opus 4.6", "provider": "Anthropic"},
            {"model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0", "model_name": "Claude Haiku 4.5", "provider": "Anthropic"},
            {"model_id": "anthropic.claude-3-5-haiku-20241022-v1:0", "model_name": "Claude 3.5 Haiku", "provider": "Anthropic"},
            {"model_id": "us.amazon.nova-pro-v1:0", "model_name": "Nova Pro", "provider": "Amazon"},
            {"model_id": "us.amazon.nova-lite-v1:0", "model_name": "Nova Lite", "provider": "Amazon"},
            {"model_id": "us.meta.llama3-3-70b-instruct-v1:0", "model_name": "Llama 3.3 70B", "provider": "Meta"},
        ]

        try:
            client = boto3.client("bedrock", region_name=settings.LOG_ANALYZER_LLM_REGION)

            # Listar todos los modelos de texto (sin filtro de provider)
            response = await asyncio.to_thread(
                client.list_foundation_models,
                byOutputModality="TEXT",
            )

            models = []
            for model in response.get("modelSummaries", []):
                model_id = model.get("modelId", "")
                if model.get("modelLifecycle", {}).get("status") != "ACTIVE":
                    continue
                # Filtrar solo providers relevantes para análisis de texto
                provider = model.get("providerName", "")
                if provider not in ("Anthropic", "Amazon", "Meta", "Mistral AI", "Cohere"):
                    continue
                models.append({
                    "model_id": model_id,
                    "model_name": model.get("modelName", model_id),
                    "provider": provider,
                })

            # Combinar con inference profiles conocidos
            if models:
                existing_ids = {m["model_id"] for m in models}
                for known in KNOWN_MODELS:
                    if known["model_id"] not in existing_ids:
                        models.append(known)

            models.sort(key=lambda m: (m["provider"], m["model_name"]))
            return models if models else KNOWN_MODELS

        except Exception as e:
            logger.warning("[LOG_ANALYZER] Error listando modelos Bedrock: %s. Usando fallback.", e)
            return KNOWN_MODELS
