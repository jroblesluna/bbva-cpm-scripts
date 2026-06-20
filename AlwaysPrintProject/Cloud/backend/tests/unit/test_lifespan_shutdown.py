"""
Tests que verifican que el shutdown graceful en lifespan invoca:
1. graceful_shutdown_workstations (cierra WS con código 1001)
2. cleanup_on_shutdown del WorkerRegistry (limpia keys Redis)
3. stop_ping_loop y cancelación de ping_task

Validates: Requirements 8.1, 8.2
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_lifespan_calls_graceful_shutdown():
    """
    Verifica que la función lifespan invoca graceful_shutdown_workstations
    durante el shutdown (después del yield).
    Requirement 8.1: enviar close frame a todas las workstations locales.
    """
    from app.main import lifespan

    mock_app = MagicMock()

    with patch("app.main.connection_manager") as mock_cm, \
         patch("app.main.status_scheduler") as mock_scheduler, \
         patch("app.main.scalability_collector") as mock_collector:

        # Configurar mocks
        mock_cm.start_ping_loop = AsyncMock()
        mock_cm.graceful_shutdown_workstations = AsyncMock()
        mock_cm.stop_ping_loop = MagicMock()

        # Simular que no tiene 'initialize' (modo in-memory)
        if hasattr(mock_cm, 'initialize'):
            del mock_cm.initialize

        mock_scheduler.start = MagicMock()
        mock_scheduler.stop = MagicMock()
        mock_collector.capture_baseline = MagicMock()

        async with lifespan(mock_app):
            pass  # Simular que la app estuvo corriendo

        # Verificar que se llamó graceful_shutdown_workstations
        mock_cm.graceful_shutdown_workstations.assert_called_once_with(
            reason="Servidor reiniciando (deploy/reciclaje)"
        )


@pytest.mark.asyncio
async def test_lifespan_calls_stop_ping_loop():
    """
    Verifica que la función lifespan detiene el ping loop y cancela la task.
    """
    from app.main import lifespan

    mock_app = MagicMock()

    with patch("app.main.connection_manager") as mock_cm, \
         patch("app.main.status_scheduler") as mock_scheduler, \
         patch("app.main.scalability_collector") as mock_collector:

        mock_cm.start_ping_loop = AsyncMock()
        mock_cm.graceful_shutdown_workstations = AsyncMock()
        mock_cm.stop_ping_loop = MagicMock()

        if hasattr(mock_cm, 'initialize'):
            del mock_cm.initialize

        mock_scheduler.start = MagicMock()
        mock_scheduler.stop = MagicMock()
        mock_collector.capture_baseline = MagicMock()

        async with lifespan(mock_app):
            pass

        # Verificar que stop_ping_loop se llamó
        mock_cm.stop_ping_loop.assert_called_once()


@pytest.mark.asyncio
async def test_lifespan_initializes_redis_manager():
    """
    Verifica que si connection_manager tiene 'initialize', se invoca en startup.
    Requirement 8.4 (1.3): Inicializar Redis si el manager lo requiere.
    """
    from app.main import lifespan

    mock_app = MagicMock()

    with patch("app.main.connection_manager") as mock_cm, \
         patch("app.main.status_scheduler") as mock_scheduler, \
         patch("app.main.scalability_collector") as mock_collector, \
         patch("app.main.settings") as mock_settings:

        mock_cm.initialize = AsyncMock()
        mock_cm.start_ping_loop = AsyncMock()
        mock_cm.graceful_shutdown_workstations = AsyncMock()
        mock_cm.stop_ping_loop = MagicMock()

        mock_settings.is_sqlite = False

        mock_scheduler.start = MagicMock()
        mock_scheduler.stop = MagicMock()
        mock_collector.capture_baseline = MagicMock()

        async with lifespan(mock_app):
            pass

        # Verificar que initialize() se llamó (Redis manager)
        mock_cm.initialize.assert_called_once()


@pytest.mark.asyncio
async def test_redis_connection_manager_shutdown_calls_cleanup():
    """
    Verifica que RedisConnectionManager.graceful_shutdown_workstations
    invoca cleanup_on_shutdown del WorkerRegistry.
    Requirement 8.2: WorkerRegistry ejecuta cleanup_on_shutdown()
    eliminando SET y heartbeat key de Redis.
    """
    from app.services.redis_connection_manager import RedisConnectionManager

    manager = RedisConnectionManager(redis_url=None)

    # Simular un WorkerRegistry con cleanup_on_shutdown
    mock_registry = AsyncMock()
    mock_registry.cleanup_on_shutdown = AsyncMock()
    manager._worker_registry = mock_registry

    # Ejecutar shutdown (sin workstations conectadas)
    await manager.graceful_shutdown_workstations(reason="Test shutdown")

    # Verificar que cleanup_on_shutdown se invocó
    mock_registry.cleanup_on_shutdown.assert_called_once()


@pytest.mark.asyncio
async def test_redis_connection_manager_shutdown_closes_workstations():
    """
    Verifica que graceful_shutdown_workstations envía close frame (1001)
    a todas las workstations conectadas.
    Requirement 8.1: close frame con código 1001 a todas las workstations locales.
    """
    from app.services.redis_connection_manager import RedisConnectionManager

    manager = RedisConnectionManager(redis_url=None)

    # Simular workstations conectadas
    mock_ws1 = AsyncMock()
    mock_ws2 = AsyncMock()
    manager.workstation_connections = {
        "ws-001": mock_ws1,
        "ws-002": mock_ws2,
    }

    # Sin registry para simplificar
    manager._worker_registry = None

    await manager.graceful_shutdown_workstations(reason="Deploy")

    # Verificar close frame con código 1001
    mock_ws1.close.assert_called_once_with(code=1001, reason="Deploy")
    mock_ws2.close.assert_called_once_with(code=1001, reason="Deploy")


@pytest.mark.asyncio
async def test_redis_connection_manager_shutdown_cancels_tasks():
    """
    Verifica que graceful_shutdown_workstations cancela listener y heartbeat tasks.
    """
    from app.services.redis_connection_manager import RedisConnectionManager

    manager = RedisConnectionManager(redis_url=None)
    manager._worker_registry = None

    # Simular tasks activas
    mock_listener = MagicMock()
    mock_listener.done.return_value = False
    mock_listener.cancel = MagicMock()

    mock_heartbeat = MagicMock()
    mock_heartbeat.done.return_value = False
    mock_heartbeat.cancel = MagicMock()

    manager._listener_task = mock_listener
    manager._heartbeat_task = mock_heartbeat

    await manager.graceful_shutdown_workstations(reason="Test")

    # Verificar que se cancelaron ambas tasks
    mock_listener.cancel.assert_called_once()
    mock_heartbeat.cancel.assert_called_once()
