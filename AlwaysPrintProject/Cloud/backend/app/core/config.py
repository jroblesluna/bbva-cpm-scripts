"""
Configuración de la aplicación usando Pydantic Settings.

Este módulo define todas las variables de entorno y configuraciones
necesarias para el sistema AlwaysPrint Cloud Management.
"""

from typing import Optional, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    DB_POOL_RECYCLE: int = 3600  # 1 hora
    
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
    FRONTEND_URL: str = "http://localhost:3000"

    # === CONFIGURACIÓN DE REDIS (CACHÉ) ===
    REDIS_URL: Optional[str] = None  # Ejemplo: redis://localhost:6379/0
    CACHE_TTL_SECONDS: int = 300  # 5 minutos
    
    # === CONFIGURACIÓN DE LOGGING ===
    LOG_LEVEL: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    LOG_FILE: str = "logs/alwaysprint.log"
    LOG_ROTATION: str = "1 day"
    LOG_RETENTION: str = "30 days"
    
    # === CONFIGURACIÓN DE WEBSOCKET ===
    WS_PING_INTERVAL: int = 30  # segundos
    WS_PING_TIMEOUT: int = 60  # segundos
    WS_MAX_CONNECTIONS: int = 5000
    
    # === CONFIGURACIÓN DE RATE LIMITING ===
    RATE_LIMIT_LOGIN: int = 5  # intentos por minuto
    RATE_LIMIT_API: int = 100  # peticiones por minuto
    
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


# Instancia global de configuración
settings = Settings()
