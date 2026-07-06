"""
Gestor de conexiones WebSocket.

Este módulo implementa el ConnectionManager que gestiona:
- Conexiones persistentes con Tray Clients (workstations)
- Conexiones de operadores (frontend)
- Envío/recepción de mensajes
- Death Ping selectivo para detección de conexiones muertas por inactividad
- Encolado de mensajes para workstations offline
- Espera de respuestas de comandos (request-response sobre WebSocket)
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from datetime import datetime, timedelta, timezone
from fastapi import WebSocket
from sqlalchemy.orm import Session

from app.services.workstation import WorkstationService
from app.services.message import MessageService
from app.services.config import ConfigService


logger = logging.getLogger(__name__)


# Segundos de espera máxima para pong tras Death Ping
PONG_TIMEOUT_SECONDS: int = 30


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
        
        # Última actividad por workstation: {workstation_id: datetime (UTC naive)}
        self.last_activity: Dict[str, datetime] = {}
        
        # Organización de cada workstation conectada: {workstation_id: str(org_id)}
        self.org_ids: Dict[str, str] = {}
        
        # Death pings pendientes de respuesta: {workstation_id: datetime_enviado}
        self._pending_pongs: Dict[str, datetime] = {}
        
        # Respuestas pendientes de comandos: {command_id: (asyncio.Event, dict|None)}
        # Permite esperar la respuesta de un comando específico
        self._pending_command_responses: Dict[str, Tuple[asyncio.Event, List[Optional[dict]]]] = {}
    
    async def connect_workstation(
        self, 
        workstation_id: str, 
        websocket: WebSocket,
        db: Session,
        organization_id: str,
        vlan_id: str = None
    ):
        """
        Registra conexión de un Tray Client.
        Inicializa last_activity y almacena org_id para Death Ping selectivo.
        
        Args:
            workstation_id: UUID de la workstation
            websocket: Conexión WebSocket (ya aceptada por el endpoint)
            db: Sesión de base de datos
            organization_id: UUID de la organización a la que pertenece la workstation
            vlan_id: ID de la VLAN (opcional, ignorado en modo single-worker)
        """
        async with self._lock:
            self.workstation_connections[workstation_id] = websocket
            self.last_pong[workstation_id] = datetime.now(timezone.utc).replace(tzinfo=None)
            # Inicializar actividad y org para Death Ping selectivo
            self.last_activity[workstation_id] = datetime.now(timezone.utc).replace(tzinfo=None)
            self.org_ids[workstation_id] = organization_id
        
        # Actualizar estado en base de datos
        workstation_service = WorkstationService()
        workstation_service.update_workstation_status(
            db=db,
            workstation_id=workstation_id,
            is_online=True
        )
    
    async def update_last_activity(self, workstation_id: str):
        """
        Actualiza el timestamp de última actividad de una workstation.
        Se invoca al recibir cualquier mensaje válido (register, telemetry, pong, status_update, connectivity_result).
        """
        async with self._lock:
            if workstation_id in self.workstation_connections:
                self.last_activity[workstation_id] = datetime.now(timezone.utc).replace(tzinfo=None)

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
            
            # Limpiar registros de actividad, organización y pongs pendientes
            if should_mark_offline:
                self.last_activity.pop(workstation_id, None)
                self.org_ids.pop(workstation_id, None)
                self._pending_pongs.pop(workstation_id, None)
        
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
        Repite mientras sigan llegando desconexiones a la cola.
        Esto agrupa desconexiones masivas (ej: 500 ws desconectándose a la vez)
        en queries batch a la BD.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        while True:
            await asyncio.sleep(3)
            
            # Tomar todos los IDs pendientes
            ids_to_flush = self._disconnect_queue.copy()
            self._disconnect_queue.clear()
            
            if not ids_to_flush:
                # Cola vacía — terminar el loop
                return
            
            if self._db_session_factory is None:
                logger.warning(
                    f"_flush_disconnect_queue: {len(ids_to_flush)} ws pendientes "
                    f"pero _db_session_factory es None. Descartando."
                )
                return
            
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
                logger.error(f"Error creando sesión para flush disconnect: {e}")
    
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
        db: Session = None
    ):
        """
        Envía mensaje a todos los operadores conectados.
        
        Nota: Envía a TODOS los operadores conectados (no filtra por org).
        En producción hay muy pocos operadores simultáneos (1-3 admins).
        El frontend filtra los mensajes por organization_id.
        
        Args:
            organization_id: UUID de la organización (incluido en el mensaje para filtrado frontend)
            message: Mensaje a enviar
            db: Sesión de base de datos (no utilizada, mantenida por compatibilidad de interfaz)
        """
        # Enviar a todos los operadores conectados — el frontend filtra por org_id
        async with self._lock:
            user_ids = list(self.operator_connections.keys())
        
        for user_id in user_ids:
            await self.send_to_operator(user_id, message)
    
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
        Remueve de pending_pongs para confirmar que está viva y evitar
        que sea marcada como muerta en el siguiente ciclo del Death Ping.
        
        Args:
            workstation_id: UUID de la workstation
        """
        async with self._lock:
            self.last_pong[workstation_id] = datetime.now(timezone.utc).replace(tzinfo=None)
            # Confirmar que respondió al Death Ping — no marcar como muerta
            self._pending_pongs.pop(workstation_id, None)
    
    async def start_ping_loop(self, db_session_factory):
        """
        Loop de verificación de inactividad selectivo (Death Ping).
        
        Cada CHECK_INTERVAL (60s):
        1. Verificar pending_pongs del ciclo anterior (timeout 30s → dead)
        2. Consultar offline_timeout_minutes de cada org con ws conectadas
        3. Identificar ws inactivas (last_activity > timeout de su org)
        4. Enviar Death Ping solo a inactivas
        5. Batch disconnect de las muertas (remover de dicts + UPDATE en BD)
        
        Args:
            db_session_factory: Factory para crear sesiones de BD
        """
        from app.core.config import settings
        from app.models.organization import Organization
        from app.models.workstation import Workstation
        
        ping_interval = int(getattr(settings, 'WS_PING_INTERVAL', 60))
        
        self._ping_loop_running = True
        self._db_session_factory = db_session_factory
        
        # === LIMPIEZA INICIAL: marcar offline workstations fantasma ===
        # Al reiniciar el backend, la BD puede tener ws con is_online=True
        # que ya no tienen conexión WebSocket activa (ej: crash, deploy, test previo)
        try:
            db = db_session_factory()
            try:
                async with self._lock:
                    connected_ids = list(self.workstation_connections.keys())
                
                if connected_ids:
                    # Marcar offline las que están en BD como online pero NO conectadas
                    cleaned = db.query(Workstation).filter(
                        Workstation.is_online == True,
                        ~Workstation.id.in_(connected_ids)
                    ).update(
                        {Workstation.is_online: False},
                        synchronize_session=False
                    )
                else:
                    # No hay nadie conectado — marcar TODAS como offline
                    cleaned = db.query(Workstation).filter(
                        Workstation.is_online == True
                    ).update(
                        {Workstation.is_online: False},
                        synchronize_session=False
                    )
                
                db.commit()
                if cleaned > 0:
                    logger.info(
                        f"Limpieza inicial: {cleaned} workstations fantasma marcadas offline "
                        f"({len(connected_ids)} realmente conectadas)"
                    )
            except Exception as e:
                db.rollback()
                logger.error(f"Error en limpieza inicial de workstations: {e}")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error creando sesión para limpieza inicial: {e}")
        
        while self._ping_loop_running:
            await asyncio.sleep(ping_interval)
            
            current_time = datetime.now(timezone.utc).replace(tzinfo=None)
            dead_workstations: List[str] = []
            
            # === FASE 1: Verificar pending_pongs del ciclo anterior ===
            async with self._lock:
                for ws_id, ping_sent_at in list(self._pending_pongs.items()):
                    if (current_time - ping_sent_at).total_seconds() > PONG_TIMEOUT_SECONDS:
                        dead_workstations.append(ws_id)
                
                # Limpiar pending_pongs de las muertas
                for ws_id in dead_workstations:
                    self._pending_pongs.pop(ws_id, None)
            
            if dead_workstations:
                logger.info(
                    f"Fase 1: {len(dead_workstations)} workstations sin respuesta de pong "
                    f"(>{PONG_TIMEOUT_SECONDS}s) → marcadas como muertas"
                )
            
            # === FASE 2: Consultar timeouts por organización ===
            org_timeouts: Dict[str, int] = {}
            async with self._lock:
                org_ids_unicos = set(self.org_ids.values())
            
            if org_ids_unicos:
                try:
                    db = db_session_factory()
                    try:
                        results = db.query(
                            Organization.id, Organization.offline_timeout_minutes
                        ).filter(
                            Organization.id.in_(list(org_ids_unicos))
                        ).all()
                        
                        for org_id, timeout_min in results:
                            org_timeouts[str(org_id)] = timeout_min
                    finally:
                        db.close()
                except Exception as e:
                    logger.warning(
                        f"Error consultando timeouts de organizaciones: {e}. "
                        f"Usando default de 10 minutos para todas."
                    )
                    # Si falla la consulta, usar default 10 para todas
                    org_timeouts = {}
            
            # === FASE 3: Identificar inactivas y enviar Death Ping ===
            async with self._lock:
                workstation_ids = list(self.workstation_connections.keys())
            
            pings_enviados = 0
            for ws_id in workstation_ids:
                async with self._lock:
                    # Si ya tiene ping pendiente, no enviar otro
                    if ws_id in self._pending_pongs:
                        continue
                    
                    # Obtener org_id y last_activity de esta ws
                    org_id = self.org_ids.get(ws_id)
                    ws_last_activity = self.last_activity.get(ws_id)
                
                if org_id is None or ws_last_activity is None:
                    continue
                
                # Determinar timeout: usar el de la org o default 10
                timeout_minutes = org_timeouts.get(org_id, 10)
                threshold = current_time - timedelta(minutes=timeout_minutes)
                
                if ws_last_activity < threshold:
                    # Workstation inactiva → enviar Death Ping
                    try:
                        sent = await self.send_to_workstation(ws_id, {"type": "ping"})
                        if sent:
                            async with self._lock:
                                self._pending_pongs[ws_id] = current_time
                            pings_enviados += 1
                        else:
                            # No se pudo enviar (ws ya no existe en conexiones)
                            dead_workstations.append(ws_id)
                    except Exception as e:
                        logger.warning(
                            f"Excepción enviando Death Ping a {ws_id}: {e}. "
                            f"Marcada como muerta."
                        )
                        dead_workstations.append(ws_id)
            
            if pings_enviados > 0:
                logger.info(
                    f"Fase 3: {pings_enviados} Death Pings enviados a workstations inactivas "
                    f"(de {len(workstation_ids)} conectadas)"
                )
            
            # === FASE 4: Batch disconnect de muertas ===
            if dead_workstations:
                # Eliminar duplicados
                dead_workstations = list(set(dead_workstations))
                
                # Remover de dicts en memoria
                async with self._lock:
                    for ws_id in dead_workstations:
                        self.workstation_connections.pop(ws_id, None)
                        self.last_activity.pop(ws_id, None)
                        self.last_pong.pop(ws_id, None)
                        self.org_ids.pop(ws_id, None)
                        self._pending_pongs.pop(ws_id, None)
                
                # Batch UPDATE en BD
                try:
                    db = db_session_factory()
                    try:
                        updated = db.query(Workstation).filter(
                            Workstation.id.in_(dead_workstations)
                        ).update(
                            {Workstation.is_online: False},
                            synchronize_session=False
                        )
                        db.commit()
                        logger.info(
                            f"Fase 4: Batch disconnect completado — "
                            f"{updated} workstations marcadas offline "
                            f"(de {len(dead_workstations)} muertas detectadas)"
                        )
                    except Exception as e:
                        db.rollback()
                        logger.error(
                            f"Error en batch disconnect de {len(dead_workstations)} ws: {e}. "
                            f"Se hizo rollback."
                        )
                    finally:
                        db.close()
                except Exception as e:
                    logger.error(
                        f"Error creando sesión para batch disconnect: {e}"
                    )
    
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

    def get_global_online_snapshot(self) -> set:
        """
        Retorna set de workstation_ids online (single-worker, solo local).
        Interfaz compatible con RedisConnectionManager.
        """
        return set(self.workstation_connections.keys())

    async def get_global_online_snapshot_async(self) -> set:
        """
        Versión async (single-worker retorna lo mismo que sync).
        Interfaz compatible con RedisConnectionManager.
        """
        return set(self.workstation_connections.keys())
    
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

    async def get_global_connection_count(self) -> dict:
        """
        Versión async del conteo global (single-worker, solo local).
        Interfaz compatible con RedisConnectionManager.
        """
        return {
            "workstations": len(self.workstation_connections),
            "operators": len(self.operator_connections),
            "workers": 1,
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


# === FACTORY CONDICIONAL ===
# Selecciona el manager según la configuración de Redis.
# Si REDIS_URL está configurado, usa RedisConnectionManager para coordinación
# inter-worker via pub/sub. Si no, usa ConnectionManager (modo single-worker).
from app.core.config import settings

if settings.REDIS_URL:
    from app.services.redis_connection_manager import RedisConnectionManager
    connection_manager = RedisConnectionManager(redis_url=settings.REDIS_URL)
else:
    connection_manager = ConnectionManager()

