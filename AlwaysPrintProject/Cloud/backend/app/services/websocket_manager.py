"""
Gestor de conexiones WebSocket.

Este módulo implementa el ConnectionManager que gestiona:
- Conexiones persistentes con Tray Clients (workstations)
- Conexiones de operadores (frontend)
- Envío/recepción de mensajes
- Ping/pong para detección de conexiones muertas
- Encolado de mensajes para workstations offline
"""

import asyncio
import json
from typing import Dict, List, Optional, Set
from datetime import datetime
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
        
        # Cola de mensajes pendientes: {workstation_id: List[dict]}
        self.pending_messages: Dict[str, List[dict]] = {}
        
        # Timestamps de último pong: {workstation_id: datetime}
        self.last_pong: Dict[str, datetime] = {}
        
        # Lock para operaciones thread-safe
        self._lock = asyncio.Lock()
        
        # Flag para detener el ping loop
        self._ping_loop_running = False
    
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
            self.last_pong[workstation_id] = datetime.utcnow()
        
        # Actualizar estado en base de datos
        workstation_service = WorkstationService()
        workstation_service.update_workstation_status(
            db=db,
            workstation_id=workstation_id,
            is_online=True
        )
        
        # Enviar mensajes pendientes
        await self._send_pending_messages(workstation_id)
    
    async def disconnect_workstation(
        self, 
        workstation_id: str,
        db: Session
    ):
        """
        Desconecta un Tray Client y marca como offline.
        
        Args:
            workstation_id: UUID de la workstation
            db: Sesión de base de datos
        """
        async with self._lock:
            if workstation_id in self.workstation_connections:
                del self.workstation_connections[workstation_id]
            
            if workstation_id in self.last_pong:
                del self.last_pong[workstation_id]
        
        # Actualizar estado en base de datos
        workstation_service = WorkstationService()
        workstation_service.update_workstation_status(
            db=db,
            workstation_id=workstation_id,
            is_online=False
        )
    
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
        
        Si la workstation está offline, encola el mensaje.
        
        Args:
            workstation_id: UUID de la workstation
            message: Mensaje a enviar (dict que se serializa a JSON)
            
        Returns:
            True si se envió, False si se encoló
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
            
            # Workstation offline o error: encolar mensaje
            if workstation_id not in self.pending_messages:
                self.pending_messages[workstation_id] = []
            self.pending_messages[workstation_id].append(message)
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
    
    async def broadcast_to_account(
        self, 
        account_id: str, 
        message: dict,
        db: Session
    ):
        """
        Envía mensaje a todos los operadores de una cuenta.
        
        Args:
            account_id: UUID de la cuenta
            message: Mensaje a enviar
            db: Sesión de base de datos
        """
        # Obtener todos los usuarios de la cuenta
        from app.models.user import User
        users = db.query(User).filter_by(organization_id=account_id).all()
        
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
    
    async def _send_pending_messages(self, workstation_id: str):
        """
        Envía mensajes pendientes a una workstation recién conectada.
        
        Args:
            workstation_id: UUID de la workstation
        """
        async with self._lock:
            if workstation_id not in self.pending_messages:
                return
            
            messages = self.pending_messages[workstation_id]
            del self.pending_messages[workstation_id]
        
        # Enviar cada mensaje
        for message in messages:
            await self.send_to_workstation(workstation_id, message)
    
    async def handle_pong(self, workstation_id: str):
        """
        Registra recepción de pong de una workstation.
        
        Args:
            workstation_id: UUID de la workstation
        """
        async with self._lock:
            self.last_pong[workstation_id] = datetime.utcnow()
    
    async def start_ping_loop(self, db_session_factory):
        """
        Inicia loop de ping/pong para detectar conexiones muertas.
        
        Envía ping cada 30 segundos y verifica pong.
        Si no hay pong en 60 segundos, cierra la conexión.
        
        Args:
            db_session_factory: Factory para crear sesiones de BD
        """
        self._ping_loop_running = True
        
        while self._ping_loop_running:
            await asyncio.sleep(30)  # Ping cada 30 segundos
            
            current_time = datetime.utcnow()
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
                        if seconds_since_pong > 60:
                            # Sin pong en 60 segundos, marcar como muerta
                            dead_workstations.append(ws_id)
                            continue
                    
                    # Enviar ping
                    await self.send_to_workstation(ws_id, {"type": "ping"})
                    
                except Exception:
                    dead_workstations.append(ws_id)
            
            # Desconectar workstations muertas
            if dead_workstations:
                db = db_session_factory()
                try:
                    for ws_id in dead_workstations:
                        await self.disconnect_workstation(ws_id, db)
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
                "operators": int,
                "pending_messages": int
            }
        """
        return {
            "workstations": len(self.workstation_connections),
            "operators": len(self.operator_connections),
            "pending_messages": sum(len(msgs) for msgs in self.pending_messages.values())
        }


# Instancia global del ConnectionManager
connection_manager = ConnectionManager()

