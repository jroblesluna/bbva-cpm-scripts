"""
Gestor de conexiones WebSocket.

Este módulo implementa el ConnectionManager que gestiona:
- Conexiones persistentes con Tray Clients (workstations)
- Conexiones de operadores (frontend)
- Envío/recepción de mensajes
- Ping/pong para detección de conexiones muertas
- Encolado de mensajes para workstations offline
- Espera de respuestas de comandos (request-response sobre WebSocket)
"""

import asyncio
import json
from typing import Any, Dict, List, Optional, Set, Tuple
from datetime import datetime, timezone
from fastapi import WebSocket
from sqlalchemy.orm import Session

from app.services.workstation import WorkstationService
from app.services.message import MessageService
from app.services.config import ConfigService


class ConnectionManager:
    """
    Gestor centralizado de conexiones WebSocket.
    
    Mantiene registro de:
    - Conexiones de workstations (Tray Clients)
    - Conexiones de operadores (Frontend)
    - Mensajes pendientes para workstations offline
    """
    
    def __init__(self):
        # Conexiones de Tray Clients: {workstation_id: WebSocket}
        self.workstation_connections: Dict[str, WebSocket] = {}
        
        # Conexiones de Operadores: {user_id: Set[WebSocket]}
        # Un operador puede tener múltiples pestañas abiertas
        self.operator_connections: Dict[str, Set[WebSocket]] = {}
        
        # Timestamps de último pong: {workstation_id: datetime}
        self.last_pong: Dict[str, datetime] = {}
        
        # Lock para operaciones thread-safe
        self._lock = asyncio.Lock()
        
        # Flag para detener el ping loop
        self._ping_loop_running = False

        # Cola de desconexiones pendientes de persistir en BD (batch)
        self._disconnect_queue: List[str] = []
        self._disconnect_flush_task: Optional[asyncio.Task] = None
        self._db_session_factory = None
        
        # Respuestas pendientes de comandos: {command_id: (asyncio.Event, dict|None)}
        # Permite esperar la respuesta de un comando específico
        self._pending_command_responses: Dict[str, Tuple[asyncio.Event, List[Optional[dict]]]] = {}
    
    async def connect_workstation(
        self, 
        workstation_id: str, 
        websocket: WebSocket,
        db: Session
    ):
        """
        Registra conexión de un Tray Client.
        
        Args:
            workstation_id: UUID de la workstation
            websocket: Conexión WebSocket (ya aceptada por el endpoint)
            db: Sesión de base de datos
        """
        async with self._lock:
            self.workstation_connections[workstation_id] = websocket
            self.last_pong[workstation_id] = datetime.now(timezone.utc).replace(tzinfo=None)
        
        # Actualizar estado en base de datos
        workstation_service = WorkstationService()
        workstation_service.update_workstation_status(
            db=db,
            workstation_id=workstation_id,
            is_online=True
        )
    
    async def disconnect_workstation(
        self, 
        workstation_id: str,
        db: Session,
        websocket: WebSocket = None
    ):
        """
        Desconecta un Tray Client y encola el mark-offline para batch update.
        
        Solo marca offline si el WebSocket que se desconecta es el mismo que está
        actualmente registrado. Si ya fue reemplazado por una nueva conexión
        (reconexión rápida tras StopTray/StartTray), no se marca offline.
        
        El UPDATE a BD se encola y se ejecuta en batch cada 3 segundos para
        evitar saturar el pool en desconexiones masivas.
        
        Args:
            workstation_id: UUID de la workstation
            db: Sesión de base de datos (conservada por compatibilidad, no se usa directamente)
            websocket: WebSocket que se está desconectando (para comparar con el activo)
        """
        should_mark_offline = False
        
        async with self._lock:
            if workstation_id in self.workstation_connections:
                current_ws = self.workstation_connections[workstation_id]
                # Solo desconectar si es el mismo WebSocket (o si no se proporcionó)
                if websocket is None or current_ws is websocket:
                    del self.workstation_connections[workstation_id]
                    should_mark_offline = True
                # Si el WebSocket activo es diferente, ya se reconectó — no marcar offline
            
            if should_mark_offline and workstation_id in self.last_pong:
                del self.last_pong[workstation_id]
        
        # Encolar para batch update en vez de query individual
        if should_mark_offline:
            self._disconnect_queue.append(workstation_id)
            # Iniciar flush task si no existe
            if self._disconnect_flush_task is None or self._disconnect_flush_task.done():
                self._disconnect_flush_task = asyncio.create_task(
                    self._flush_disconnect_queue()
                )

    async def _flush_disconnect_queue(self):
        """
        Espera 3 segundos y luego hace batch UPDATE de todas las ws encoladas.
        Esto agrupa desconexiones masivas (ej: 500 ws desconectándose a la vez)
        en una sola query a la BD.
        """
        await asyncio.sleep(3)
        
        # Tomar todos los IDs pendientes
        ids_to_flush = self._disconnect_queue.copy()
        self._disconnect_queue.clear()
        
        if not ids_to_flush and self._db_session_factory is None:
            return
        
        if not ids_to_flush:
            return
        
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            db = self._db_session_factory()
            try:
                from app.models.workstation import Workstation
                updated = db.query(Workstation).filter(
                    Workstation.id.in_(ids_to_flush)
                ).update(
                    {Workstation.is_online: False},
                    synchronize_session=False
                )
                db.commit()
                logger.info(
                    f"Batch disconnect: {updated} workstations marcadas offline "
                    f"(de {len(ids_to_flush)} encoladas)"
                )
            except Exception as e:
                db.rollback()
                logger.error(f"Error en batch disconnect: {e}")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error creando sesión para batch disconnect: {e}")
    
    async def connect_operator(
        self, 
        user_id: str, 
        websocket: WebSocket
    ):
        """
        Registra conexión de un operador (Frontend).
        
        Args:
            user_id: UUID del usuario
            websocket: Conexión WebSocket
        """
        await websocket.accept()
        
        async with self._lock:
            if user_id not in self.operator_connections:
                self.operator_connections[user_id] = set()
            self.operator_connections[user_id].add(websocket)
    
    async def disconnect_operator(
        self, 
        user_id: str, 
        websocket: WebSocket
    ):
        """
        Desconecta un operador.
        
        Args:
            user_id: UUID del usuario
            websocket: Conexión WebSocket
        """
        async with self._lock:
            if user_id in self.operator_connections:
                self.operator_connections[user_id].discard(websocket)
                
                # Si no quedan conexiones, eliminar entrada
                if not self.operator_connections[user_id]:
                    del self.operator_connections[user_id]
    
    async def send_to_workstation(
        self, 
        workstation_id: str, 
        message: dict
    ) -> bool:
        """
        Envía mensaje a una workstation.
        
        Si la workstation está offline, descarta el mensaje (no encola).
        Los mensajes de tipo "message" se gestionan por BD (deliveries),
        no necesitan cola in-memory.
        
        Args:
            workstation_id: UUID de la workstation
            message: Mensaje a enviar (dict que se serializa a JSON)
            
        Returns:
            True si se envió, False si no se pudo enviar
        """
        async with self._lock:
            if workstation_id in self.workstation_connections:
                ws = self.workstation_connections[workstation_id]
                try:
                    await ws.send_json(message)
                    return True
                except Exception as e:
                    # Conexión muerta, eliminar
                    del self.workstation_connections[workstation_id]
                    if workstation_id in self.last_pong:
                        del self.last_pong[workstation_id]
            
            return False
    
    async def send_direct_to_workstation(
        self,
        workstation_id: str,
        message: dict
    ) -> bool:
        """
        Envía mensaje directamente a una workstation sin encolar.
        
        Diseñado para mensajes gestionados por BD (deliveries) donde el estado
        se trackea en la tabla message_deliveries. No usa cola in-memory.
        
        Args:
            workstation_id: UUID de la workstation
            message: Mensaje a enviar (dict que se serializa a JSON)
            
        Returns:
            True si se envió exitosamente, False si falló
        """
        async with self._lock:
            if workstation_id in self.workstation_connections:
                ws = self.workstation_connections[workstation_id]
                try:
                    await ws.send_json(message)
                    return True
                except Exception as e:
                    # Conexión muerta, eliminar
                    del self.workstation_connections[workstation_id]
                    if workstation_id in self.last_pong:
                        del self.last_pong[workstation_id]
            return False
    
    async def send_to_operator(
        self, 
        user_id: str, 
        message: dict
    ):
        """
        Envía mensaje a un operador (todas sus conexiones).
        
        Args:
            user_id: UUID del usuario
            message: Mensaje a enviar
        """
        async with self._lock:
            if user_id not in self.operator_connections:
                return
            
            # Enviar a todas las conexiones del operador
            dead_connections = []
            for ws in self.operator_connections[user_id]:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead_connections.append(ws)
            
            # Limpiar conexiones muertas
            for ws in dead_connections:
                self.operator_connections[user_id].discard(ws)
            
            if not self.operator_connections[user_id]:
                del self.operator_connections[user_id]
    
    async def broadcast_to_organization(
        self, 
        organization_id: str, 
        message: dict,
        db: Session
    ):
        """
        Envía mensaje a todos los operadores de una organización.
        
        Args:
            organization_id: UUID de la organización
            message: Mensaje a enviar
            db: Sesión de base de datos
        """
        # Obtener todos los usuarios de la organización
        from app.models.user import User
        users = db.query(User).filter_by(organization_id=organization_id).all()
        
        # Enviar a cada usuario
        for user in users:
            await self.send_to_operator(str(user.id), message)
    
    async def broadcast_to_all_operators(self, message: dict):
        """
        Envía mensaje a todos los operadores conectados.
        
        Args:
            message: Mensaje a enviar
        """
        async with self._lock:
            user_ids = list(self.operator_connections.keys())
        
        for user_id in user_ids:
            await self.send_to_operator(user_id, message)
    
    async def handle_pong(self, workstation_id: str):
        """
        Registra recepción de pong de una workstation.
        
        Args:
            workstation_id: UUID de la workstation
        """
        async with self._lock:
            self.last_pong[workstation_id] = datetime.now(timezone.utc).replace(tzinfo=None)
    
    async def start_ping_loop(self, db_session_factory):
        """
        Inicia loop de ping/pong para detectar conexiones muertas.
        
        Envía ping cada WS_PING_INTERVAL segundos y verifica pong.
        Si no hay pong en WS_PING_TIMEOUT segundos, cierra la conexión.
        Usa batch update para marcar offline múltiples ws en una sola query.
        
        Args:
            db_session_factory: Factory para crear sesiones de BD
        """
        from app.core.config import settings
        
        ping_interval = int(getattr(settings, 'WS_PING_INTERVAL', 60))
        ping_timeout = int(getattr(settings, 'WS_PING_TIMEOUT', 120))
        
        self._ping_loop_running = True
        self._db_session_factory = db_session_factory
        
        while self._ping_loop_running:
            await asyncio.sleep(ping_interval)
            
            current_time = datetime.now(timezone.utc).replace(tzinfo=None)
            dead_workstations = []
            
            async with self._lock:
                workstation_ids = list(self.workstation_connections.keys())
            
            # Enviar ping a todas las workstations
            for ws_id in workstation_ids:
                try:
                    # Verificar si hay pong reciente
                    last_pong_time = self.last_pong.get(ws_id)
                    if last_pong_time:
                        seconds_since_pong = (current_time - last_pong_time).total_seconds()
                        if seconds_since_pong > ping_timeout:
                            # Sin pong en el timeout configurado, marcar como muerta
                            dead_workstations.append(ws_id)
                            continue
                    
                    # Enviar ping
                    await self.send_to_workstation(ws_id, {"type": "ping"})
                    
                except Exception:
                    dead_workstations.append(ws_id)
            
            # Desconectar workstations muertas con batch update
            if dead_workstations:
                # Remover del dict de conexiones en batch
                async with self._lock:
                    for ws_id in dead_workstations:
                        self.workstation_connections.pop(ws_id, None)
                        self.last_pong.pop(ws_id, None)
                
                # Batch update en BD: una sola query para todas las desconectadas
                db = db_session_factory()
                try:
                    from app.models.workstation import Workstation
                    db.query(Workstation).filter(
                        Workstation.id.in_(dead_workstations)
                    ).update(
                        {Workstation.is_online: False},
                        synchronize_session=False
                    )
                    db.commit()
                except Exception as e:
                    db.rollback()
                    import logging
                    logging.getLogger(__name__).error(
                        f"Error en batch disconnect de {len(dead_workstations)} ws: {e}"
                    )
                finally:
                    db.close()
    
    def stop_ping_loop(self):
        """Detiene el loop de ping/pong."""
        self._ping_loop_running = False
    
    def get_online_workstations(self) -> List[str]:
        """
        Obtiene lista de workstations online.
        
        Returns:
            Lista de workstation_ids
        """
        return list(self.workstation_connections.keys())
    
    def get_online_operators(self) -> List[str]:
        """
        Obtiene lista de operadores online.
        
        Returns:
            Lista de user_ids
        """
        return list(self.operator_connections.keys())
    
    def is_workstation_online(self, workstation_id: str) -> bool:
        """
        Verifica si una workstation está online.
        
        Args:
            workstation_id: UUID de la workstation
            
        Returns:
            True si está online, False si no
        """
        return workstation_id in self.workstation_connections
    
    def get_connection_count(self) -> dict:
        """
        Obtiene conteo de conexiones.
        
        Returns:
            Dict con conteos: {
                "workstations": int,
                "operators": int
            }
        """
        return {
            "workstations": len(self.workstation_connections),
            "operators": len(self.operator_connections)
        }

    def register_command_waiter(self, command_id: str) -> asyncio.Event:
        """
        Registra un waiter para esperar la respuesta de un comando específico.
        
        Args:
            command_id: ID del comando cuya respuesta se espera
            
        Returns:
            asyncio.Event que se señalará cuando llegue la respuesta
        """
        event = asyncio.Event()
        # Usamos una lista de un elemento para poder mutar el contenido
        self._pending_command_responses[command_id] = (event, [None])
        return event

    def resolve_command_response(self, command_id: str, response: dict) -> bool:
        """
        Resuelve la espera de un comando con la respuesta recibida.
        
        Args:
            command_id: ID del comando
            response: Respuesta completa del comando
            
        Returns:
            True si había un waiter esperando, False si no
        """
        if command_id in self._pending_command_responses:
            event, container = self._pending_command_responses[command_id]
            container[0] = response
            event.set()
            return True
        return False

    async def wait_for_command_response(
        self, command_id: str, timeout: float = 30.0
    ) -> Optional[dict]:
        """
        Espera la respuesta de un comando con timeout.
        
        Args:
            command_id: ID del comando
            timeout: Tiempo máximo de espera en segundos
            
        Returns:
            Respuesta del comando o None si timeout
        """
        if command_id not in self._pending_command_responses:
            return None
        
        event, container = self._pending_command_responses[command_id]
        
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return container[0]
        except asyncio.TimeoutError:
            return None
        finally:
            # Limpiar el waiter
            self._pending_command_responses.pop(command_id, None)

    async def graceful_shutdown_workstations(self, reason: str = "Servidor reiniciando"):
        """
        Cierra todas las conexiones WebSocket de workstations de forma limpia
        antes de un shutdown del servidor.
        
        Envía un close frame con código 1001 (Going Away) y la razón explícita.
        Esto permite al cliente distinguir un reciclaje/deploy del servidor
        de un corte inesperado de red/proxy.
        
        Args:
            reason: Razón del cierre (se envía en el close frame, máx 123 bytes)
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Truncar razón a 123 bytes (límite del protocolo WebSocket para control frames)
        truncated_reason = reason[:123]
        
        async with self._lock:
            workstation_ids = list(self.workstation_connections.keys())
        
        if not workstation_ids:
            logger.info("[SHUTDOWN] No hay workstations conectadas. Nada que cerrar.")
            return
        
        logger.info(
            f"[SHUTDOWN] Cerrando {len(workstation_ids)} conexiones WebSocket de workstations. "
            f"Razón: '{truncated_reason}'"
        )
        
        closed_count = 0
        error_count = 0
        
        for ws_id in workstation_ids:
            try:
                async with self._lock:
                    ws = self.workstation_connections.get(ws_id)
                
                if ws:
                    # Enviar close frame con código 1001 (Going Away) y razón descriptiva
                    await ws.close(code=1001, reason=truncated_reason)
                    closed_count += 1
            except Exception as e:
                error_count += 1
                logger.warning(
                    f"[SHUTDOWN] Error cerrando WebSocket de workstation {ws_id}: "
                    f"{type(e).__name__}: {e}"
                )
        
        logger.info(
            f"[SHUTDOWN] Graceful shutdown completado. "
            f"Cerradas: {closed_count}, Errores: {error_count}, Total: {len(workstation_ids)}"
        )


# Instancia global del ConnectionManager
connection_manager = ConnectionManager()

