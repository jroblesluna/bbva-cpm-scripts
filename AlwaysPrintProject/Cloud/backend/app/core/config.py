"""
Configuración de la aplicación usando Pydantic Settings.

Este módulo define todas las variables de entorno y configuraciones
necesarias para el sistema AlwaysPrint Cloud Management.
"""

import logging
from typing import Optional, Union

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    Configuración de la aplicación.
    
    Las variables se cargan desde:
    1. Variables de entorno del sistema
    2. Archivo .env en el directorio raíz del backend
    """
    
    # === CONFIGURACIÓN GENERAL ===
    PROJECT_NAME: str = "AlwaysPrint Cloud Management"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    # === CONFIGURACIÓN DE BASE DE DATOS ===
    # Formato de DATABASE_URL:
    # - SQLite: sqlite:///./alwaysprint.db
    # - PostgreSQL: postgresql://user:password@localhost:5432/alwaysprint
    # - SQL Server: mssql+pyodbc://user:password@localhost/alwaysprint?driver=ODBC+Driver+17+for+SQL+Server
    DATABASE_URL: str = "sqlite:///./alwaysprint.db"
    
    # Pool de conexiones (solo para PostgreSQL/SQL Server)
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800  # 30 minutos — evita conexiones stale por timeout de RDS
    
    # === CONFIGURACIÓN DE SEGURIDAD ===
    SECRET_KEY: str = "CHANGE_THIS_IN_PRODUCTION_TO_A_SECURE_RANDOM_STRING"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 horas
    
    # === CONFIGURACIÓN DE CORS ===
    CORS_ORIGINS: Union[list[str], str] = [
        "http://localhost:3000",
        "http://localhost:8000",
    ]
    
    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        """
        Parsea CORS_ORIGINS desde string separado por comas o lista.
        
        Acepta:
        - Lista: ["http://localhost:3000", "http://localhost:8000"]
        - String: "http://localhost:3000,http://localhost:8000"
        """
        if isinstance(v, str):
            # Si es string vacío, retornar lista vacía
            if not v.strip():
                return []
            # Separar por comas y limpiar espacios
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v
    
    # === CONFIGURACIÓN SES ===
    SES_ENABLED: bool = False
    SES_FROM_EMAIL: str = "noreply@apps.iol.pe"
    AWS_REGION: str = "us-west-2"
    AWS_PROFILE: Optional[str] = None
    S3_ARTIFACTS_BUCKET: str = "alwaysprint-prod-artifacts"
    S3_DOCS_BUCKET: str = "alwaysprint-prod-docs"
    FRONTEND_URL: str = "http://localhost:3000"

    # === CONFIGURACIÓN DE REDIS (CACHÉ) ===
    REDIS_URL: Optional[str] = None  # Ejemplo: redis://localhost:6379/0
    CACHE_TTL_SECONDS: int = 300  # 5 minutos
    
    # === CONFIGURACIÓN DE LOGGING ===
    LOG_LEVEL: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    LOG_FILE: str = "logs/alwaysprint.log"
    LOG_ROTATION: str = "1 day"
    LOG_RETENTION: str = "30 days"
    
    # === CONFIGURACIÓN MULTI-WORKER ===
    UVICORN_WORKERS: int = 1
    WORKER_REGISTRY_TTL: int = 60  # segundos
    WS_REDIS_RECONNECT_MAX_INTERVAL: int = 30  # segundos (backoff cap)
    WS_DEBUG_LOGGING: bool = True  # Logging estructurado detallado (dev)

    # === CONFIGURACIÓN DE WEBSOCKET ===
    WS_PING_INTERVAL: int = 30  # segundos
    WS_PING_TIMEOUT: int = 60  # segundos
    WS_MAX_CONNECTIONS: int = 5000
    
    # === CONFIGURACIÓN DE RATE LIMITING ===
    RATE_LIMIT_LOGIN: int = 5  # intentos por minuto
    RATE_LIMIT_API: int = 100  # peticiones por minuto

    # === CONFIGURACIÓN DE BOOTSTRAP DOMAINS ===
    # Dominios de bootstrap por defecto para nuevas configuraciones globales.
    # Configurar via env var o Terraform según el entorno:
    # DEV: "dev.iol.pe" | PROD: "apps.iol.pe,sistemas.com.pe"
    DEFAULT_BOOTSTRAP_DOMAINS: str = "apps.iol.pe,sistemas.com.pe"

    # === CONFIGURACIÓN DEL LOG ANALYZER ===
    # Umbral de compresión en bytes (default 50KB). Rango válido: 1KB - 10MB.
    LOG_ANALYZER_COMPRESSION_THRESHOLD: int = 51200
    # Umbral de procesamiento estructural en bytes (default 100KB). Rango válido: 1KB - 50MB.
    LOG_ANALYZER_PROCESSING_THRESHOLD: int = 102400
    # Líneas de contexto antes/después de cada hallazgo (default 5). Rango válido: 0 - 500.
    LOG_ANALYZER_CONTEXT_WINDOW_SIZE: int = 5
    # Máximo de bloques de contexto (default 10). Rango válido: 1 - 1000.
    LOG_ANALYZER_MAX_CONTEXT_BLOCKS: int = 10
    # Top N patrones recurrentes a incluir (default 20). Rango válido: 1 - 500.
    LOG_ANALYZER_TOP_PATTERNS: int = 20
    # Máximo de tokens en la respuesta del LLM (default 4096). Rango válido: 100 - 16384.
    LOG_ANALYZER_LLM_MAX_TOKENS: int = 4096
    # Tamaño máximo de upload en bytes (default 50MB). Rango válido: 1MB - 200MB.
    LOG_ANALYZER_MAX_UPLOAD_SIZE: int = 52428800
    # Keywords adicionales separados por coma, se añaden a la lista por defecto.
    LOG_ANALYZER_EXTRA_KEYWORDS: str = ""
    # Timeout en segundos para esperar respuesta de la workstation (default 30). Rango válido: 5 - 300.
    LOG_ANALYZER_COMMAND_TIMEOUT: int = 30

    # === LLM PROVIDER ===
    # Provider de LLM a utilizar: "bedrock", "openai", "anthropic"
    LOG_ANALYZER_LLM_PROVIDER: str = "bedrock"
    # Model ID para AWS Bedrock
    LOG_ANALYZER_LLM_MODEL_ID: str = "us.anthropic.claude-sonnet-4-20250514-v1:0"
    # Región AWS para Bedrock
    LOG_ANALYZER_LLM_REGION: str = "us-west-2"
    # API Key para OpenAI (requerido si LLM_PROVIDER = "openai")
    LOG_ANALYZER_OPENAI_API_KEY: str = ""
    # Modelo de OpenAI
    LOG_ANALYZER_OPENAI_MODEL: str = "gpt-4o"
    # API Key para Anthropic (requerido si LLM_PROVIDER = "anthropic")
    LOG_ANALYZER_ANTHROPIC_API_KEY: str = ""
    # Modelo de Anthropic
    LOG_ANALYZER_ANTHROPIC_MODEL: str = "claude-3-5-sonnet-20241022"

    @model_validator(mode="after")
    def _validate_multi_worker(self) -> "Settings":
        """
        Valida que REDIS_URL esté configurado cuando se usan múltiples workers.

        Multi-worker necesita Redis para coordinación inter-worker (pub/sub,
        WorkerRegistry). Sin Redis, los workers no pueden comunicarse entre sí.
        """
        if self.UVICORN_WORKERS > 1 and not self.REDIS_URL:
            raise ValueError(
                "REDIS_URL es requerido cuando UVICORN_WORKERS > 1. "
                "Multi-worker necesita Redis para coordinación inter-worker."
            )
        return self

    @model_validator(mode="after")
    def _validate_log_analyzer_settings(self) -> "Settings":
        """
        Valida rangos de configuración del Log Analyzer al inicio.

        Si un valor está fuera de rango, emite un warning y aplica el default.
        """
        # Definición de rangos: (campo, min, max, default)
        _ranges: list[tuple[str, int, int, int]] = [
            ("LOG_ANALYZER_COMPRESSION_THRESHOLD", 1024, 10485760, 51200),
            ("LOG_ANALYZER_PROCESSING_THRESHOLD", 1024, 52428800, 102400),
            ("LOG_ANALYZER_CONTEXT_WINDOW_SIZE", 0, 500, 5),
            ("LOG_ANALYZER_MAX_CONTEXT_BLOCKS", 1, 1000, 10),
            ("LOG_ANALYZER_TOP_PATTERNS", 1, 500, 20),
            ("LOG_ANALYZER_LLM_MAX_TOKENS", 100, 16384, 4096),
            ("LOG_ANALYZER_MAX_UPLOAD_SIZE", 1048576, 209715200, 52428800),
            ("LOG_ANALYZER_COMMAND_TIMEOUT", 5, 300, 30),
        ]

        for field_name, min_val, max_val, default_val in _ranges:
            value = getattr(self, field_name)
            if value < min_val or value > max_val:
                logger.warning(
                    "[LOG_ANALYZER] %s=%d fuera de rango [%d, %d]. "
                    "Usando valor por defecto: %d",
                    field_name, value, min_val, max_val, default_val,
                )
                object.__setattr__(self, field_name, default_val)

        # Validar LLM_PROVIDER
        valid_providers = ("bedrock", "openai", "anthropic")
        if self.LOG_ANALYZER_LLM_PROVIDER not in valid_providers:
            logger.warning(
                "[LOG_ANALYZER] LOG_ANALYZER_LLM_PROVIDER='%s' no es válido. "
                "Opciones: %s. Usando valor por defecto: 'bedrock'",
                self.LOG_ANALYZER_LLM_PROVIDER, valid_providers,
            )
            object.__setattr__(self, "LOG_ANALYZER_LLM_PROVIDER", "bedrock")

        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )
    
    @property
    def is_sqlite(self) -> bool:
        """Verifica si la base de datos es SQLite."""
        return self.DATABASE_URL.startswith("sqlite")
    
    @property
    def is_postgresql(self) -> bool:
        """Verifica si la base de datos es PostgreSQL."""
        return self.DATABASE_URL.startswith("postgresql")
    
    @property
    def is_sqlserver(self) -> bool:
        """Verifica si la base de datos es SQL Server."""
        return self.DATABASE_URL.startswith("mssql")

    @property
    def log_analyzer_extra_keywords_list(self) -> list[str]:
        """Parsea LOG_ANALYZER_EXTRA_KEYWORDS en una lista de strings."""
        if not self.LOG_ANALYZER_EXTRA_KEYWORDS.strip():
            return []
        return [
            kw.strip()
            for kw in self.LOG_ANALYZER_EXTRA_KEYWORDS.split(",")
            if kw.strip()
        ]


# Instancia global de configuración
settings = Settings()
