"""
Configuración de structlog para logging estructurado.

Este módulo configura structlog con formato key-value, niveles, timestamps,
y binding de contexto (worker_id, workstation_id). Se usa en el WebSocket handler
y componentes multi-worker para trazabilidad y debugging.

Uso:
    from app.core.logging import get_logger

    logger = get_logger()
    logger.info("ws.conexion_aceptada", worker_id=worker_id, workstation_id=ws_id)
"""

import os
import logging
import sys

import structlog
from structlog.types import Processor

from app.core.config import settings


def _get_worker_id() -> str:
    """Obtiene el identificador del worker actual basado en el PID del proceso."""
    return f"worker_{os.getpid()}"


def configure_structlog() -> None:
    """
    Configura structlog con formato key-value, timestamps, y niveles.

    Procesadores aplicados:
    1. add_log_level - Agrega nivel (info, warning, error, debug)
    2. TimeStamper - Agrega timestamp ISO 8601
    3. StackInfoRenderer - Renderiza stack traces si se solicitan
    4. format_exc_info - Formatea excepciones
    5. KeyValueRenderer - Formato final key=value para fácil parseo

    La configuración respeta LOG_LEVEL de settings para filtrar mensajes.
    """
    # Procesadores compartidos entre structlog y logging estándar
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # Configurar structlog
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configurar formatter para el logging estándar de Python
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer()
            if settings.WS_DEBUG_LOGGING
            else structlog.processors.KeyValueRenderer(
                key_order=["timestamp", "level", "event", "worker_id", "workstation_id"]
            ),
        ],
        foreign_pre_chain=shared_processors,
    )

    # Aplicar formatter al handler raíz
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Configurar logger raíz
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    # Silenciar loggers ruidosos de terceros
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Obtiene un logger structlog con el worker_id pre-bindeado.

    Args:
        name: Nombre opcional del módulo. Si no se proporciona, se usa el caller.

    Returns:
        Logger structlog con worker_id en el contexto.

    Ejemplo:
        logger = get_logger()
        logger.info("ws.registro_exitoso", workstation_id="abc123")
        # Output: timestamp=2024-... level=info event=ws.registro_exitoso worker_id=worker_1234 workstation_id=abc123
    """
    logger = structlog.get_logger(name) if name else structlog.get_logger()
    return logger.bind(worker_id=_get_worker_id())


# Configurar structlog al importar el módulo
configure_structlog()
