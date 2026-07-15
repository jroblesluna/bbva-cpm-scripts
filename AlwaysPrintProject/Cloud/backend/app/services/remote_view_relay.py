"""
Servicio de relay para Remote View.

Gestiona el mapeo de sesiones activas (session_id → workstation_id, user_id)
y proporciona métodos para reenviar mensajes entre operadores y workstations
usando la infraestructura existente de connection_manager (que ya maneja
cross-worker relay vía Redis internamente).

El backend actúa como PURE RELAY — zero processing de video (Req 13.1).
Cross-worker relay se resuelve internamente por RedisConnectionManager (Req 13.5).
"""

import asyncio
import logging
from typing import Optional

from app.services.websocket_manager import connection_manager


logger = logging.getLogger(__name__)


class RemoteViewRelay:
    """
    Relay de frames y comandos de Remote View entre operadores y workstations.

    Mantiene un mapping in-memory de sesiones activas para resolver
    a qué workstation/operador enviar cada mensaje sin consultar BD.

    El cross-worker relay se delega a connection_manager (RedisConnectionManager)
    que ya implementa pub/sub internamente.
    """

    def __init__(self):
        # Mapping: session_id → {"workstation_id": str, "user_id": str}
        self._sessions: dict[str, dict] = {}
        # Tareas pendientes de desconexión de workstation: workstation_id → asyncio.Task
        # Si la WS reconecta dentro del grace period (30s), la tarea se cancela.
        self._pending_disconnects: dict[str, asyncio.Task] = {}
        # Tareas pendientes de desconexión de operador: user_id → asyncio.Task
        # Si el operador reconecta dentro del grace period (15s), la tarea se cancela.
        # Cubre el caso de page reload (reconexión en 1-2s).
        self._pending_operator_disconnects: dict[str, asyncio.Task] = {}

    def register_session(self, session_id: str, workstation_id: str, user_id: str) -> None:
        """
        Registra una sesión activa para routing de mensajes.

        Se invoca cuando la sesión pasa a estado 'active' (workstation acepta)
        o al iniciar una sesión que no requiere consentimiento.

        Args:
            session_id: UUID de la sesión de Remote View
            workstation_id: UUID de la workstation objetivo
            user_id: UUID del admin/operador que inició la sesión
        """
        self._sessions[session_id] = {
            "workstation_id": workstation_id,
            "user_id": user_id,
        }
        logger.info(
            "[RV_RELAY] Sesión registrada: session_id=%s, ws=%s, user=%s",
            session_id, workstation_id, user_id,
        )

    def unregister_session(self, session_id: str) -> None:
        """
        Elimina una sesión del mapping al cerrarse/expirar.

        Args:
            session_id: UUID de la sesión a eliminar
        """
        removed = self._sessions.pop(session_id, None)
        if removed:
            logger.info(
                "[RV_RELAY] Sesión eliminada: session_id=%s, ws=%s, user=%s",
                session_id, removed["workstation_id"], removed["user_id"],
            )

    def get_session(self, session_id: str) -> Optional[dict]:
        """
        Obtiene el mapping de una sesión activa.

        Returns:
            Dict con workstation_id y user_id, o None si no existe.
        """
        return self._sessions.get(session_id)

    def get_workstation_id(self, session_id: str) -> Optional[str]:
        """
        Obtiene el workstation_id de una sesión activa.

        Args:
            session_id: UUID de la sesión

        Returns:
            workstation_id o None si la sesión no está registrada.
        """
        session = self._sessions.get(session_id)
        return session["workstation_id"] if session else None

    def get_user_id(self, session_id: str) -> Optional[str]:
        """
        Obtiene el user_id (admin/operador) de una sesión activa.

        Args:
            session_id: UUID de la sesión

        Returns:
            user_id o None si la sesión no está registrada.
        """
        session = self._sessions.get(session_id)
        return session["user_id"] if session else None

    async def relay_to_workstation(self, session_id: str, message: dict) -> bool:
        """
        Envía un mensaje del admin a la workstation de la sesión.

        Usa connection_manager.send_to_workstation() que ya maneja
        cross-worker relay vía Redis pub/sub internamente.

        Args:
            session_id: UUID de la sesión
            message: Mensaje JSON a enviar

        Returns:
            True si se envió exitosamente, False si la sesión no existe
            o la workstation está offline.
        """
        session = self._sessions.get(session_id)
        if not session:
            logger.warning(
                "[RV_RELAY] relay_to_workstation: sesión no encontrada session_id=%s",
                session_id,
            )
            return False

        workstation_id = session["workstation_id"]
        sent = await connection_manager.send_to_workstation(workstation_id, message)

        if not sent:
            logger.warning(
                "[RV_RELAY] relay_to_workstation: no se pudo enviar a ws=%s (offline?)",
                workstation_id,
            )

        return sent

    async def relay_to_operator(self, session_id: str, message: dict) -> bool:
        """
        Envía un mensaje de la workstation al admin/operador de la sesión.

        Usa connection_manager.send_to_operator() que ya maneja
        cross-worker relay vía Redis pub/sub internamente.

        Args:
            session_id: UUID de la sesión
            message: Mensaje JSON a enviar

        Returns:
            True si se envió (al menos a una conexión del operador),
            False si la sesión no existe.
        """
        session = self._sessions.get(session_id)
        if not session:
            logger.warning(
                "[RV_RELAY] relay_to_operator: sesión no encontrada session_id=%s",
                session_id,
            )
            return False

        user_id = session["user_id"]
        await connection_manager.send_to_operator(user_id, message)
        return True

    @property
    def active_session_count(self) -> int:
        """Número de sesiones activas en el relay."""
        return len(self._sessions)

    def get_session_for_workstation(self, workstation_id: str) -> Optional[str]:
        """
        Obtiene el session_id de la sesión activa asociada a una workstation.

        Args:
            workstation_id: UUID de la workstation

        Returns:
            session_id si existe una sesión activa para esa WS, o None.
        """
        for session_id, info in self._sessions.items():
            if info["workstation_id"] == workstation_id:
                return session_id
        return None

    async def handle_workstation_disconnect(self, workstation_id: str) -> None:
        """
        Maneja la desconexión del WebSocket de una workstation durante sesión activa.

        Si hay una sesión de Remote View activa para esta workstation:
        1. Notifica al admin inmediatamente con mensaje "workstation_disconnected"
        2. Inicia un timer de 30s (grace period para reconexión)
        3. Si no reconecta en 30s → end_session con razón "ws_disconnected"

        Args:
            workstation_id: UUID de la workstation que se desconectó
        """
        session_id = self.get_session_for_workstation(workstation_id)
        if not session_id:
            # No hay sesión activa de Remote View para esta WS
            return

        logger.warning(
            "[RV_RELAY] Workstation desconectada durante sesión activa: "
            "ws=%s, session_id=%s. Iniciando grace period 30s.",
            workstation_id, session_id,
        )

        # Notificar al admin inmediatamente
        await self.relay_to_operator(session_id, {
            "type": "workstation_disconnected",
            "session_id": session_id,
        })

        # Cancelar tarea previa si existía (caso de disconnect rápido repetido)
        existing_task = self._pending_disconnects.pop(workstation_id, None)
        if existing_task and not existing_task.done():
            existing_task.cancel()

        # Iniciar timer de 30s para cierre definitivo
        task = asyncio.create_task(
            self._disconnect_cleanup(workstation_id, session_id)
        )
        self._pending_disconnects[workstation_id] = task

    async def handle_workstation_reconnect(self, workstation_id: str) -> None:
        """
        Maneja la reconexión de una workstation que tenía un timer de desconexión pendiente.

        Cancela el timer de 30s si la WS reconecta antes de que expire.
        Notifica al admin que la WS se reconectó.

        Args:
            workstation_id: UUID de la workstation que se reconectó
        """
        task = self._pending_disconnects.pop(workstation_id, None)
        if task and not task.done():
            task.cancel()
            logger.info(
                "[RV_RELAY] Workstation reconectada dentro del grace period: ws=%s. "
                "Timer de desconexión cancelado.",
                workstation_id,
            )

            # Notificar al admin que la WS se reconectó
            session_id = self.get_session_for_workstation(workstation_id)
            if session_id:
                await self.relay_to_operator(session_id, {
                    "type": "workstation_reconnected",
                    "session_id": session_id,
                })

    async def _disconnect_cleanup(self, workstation_id: str, session_id: str) -> None:
        """
        Tarea interna que espera 30s y, si la WS no reconectó, cierra la sesión.

        Se ejecuta como asyncio.Task y puede ser cancelada por handle_workstation_reconnect.

        Args:
            workstation_id: UUID de la workstation
            session_id: UUID de la sesión a cerrar
        """
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            # La WS reconectó y se canceló este timer
            return

        # Grace period expirado — cerrar sesión
        logger.warning(
            "[RV_RELAY] Grace period expirado (30s). Cerrando sesión por desconexión: "
            "ws=%s, session_id=%s",
            workstation_id, session_id,
        )

        # Limpiar referencia de la tarea
        self._pending_disconnects.pop(workstation_id, None)

        # Cerrar sesión en BD
        from app.core.database import SessionLocal
        from app.services.remote_view_session import SessionManager

        session_manager = SessionManager()
        db = SessionLocal()
        try:
            ended = session_manager.end_session(db, session_id, "ws_disconnected")
            if ended:
                logger.info(
                    "[RV_RELAY] Sesión cerrada por ws_disconnected: session_id=%s",
                    session_id,
                )
        except Exception as e:
            logger.error(
                "[RV_RELAY] Error al cerrar sesión por desconexión: "
                "session_id=%s, error=%s",
                session_id, e,
            )
        finally:
            db.close()

        # Notificar al admin que la sesión terminó
        await self.relay_to_operator(session_id, {
            "type": "remote_view_session_ended",
            "session_id": session_id,
            "reason": "ws_disconnected",
        })

        # Eliminar sesión del mapping de relay
        self.unregister_session(session_id)


    async def handle_operator_disconnect(self, user_id: str) -> None:
        """
        Maneja la desconexión del operador con grace period de 15s.

        Si el operador reconecta dentro de 15s (page reload), no se cierran las sesiones.
        Esto evita que un simple F5 mate sesiones activas de Remote View.

        Si el grace period expira sin reconexión (cierre real de pestaña, logout, etc.),
        se cierran todas las sesiones con razón "admin_logout".

        Args:
            user_id: UUID del admin/operador que se desconectó
        """
        # Buscar sesiones activas de este usuario en el mapping del relay
        user_sessions = [
            sid for sid, info in self._sessions.items()
            if info["user_id"] == user_id
        ]

        if not user_sessions:
            return

        logger.info(
            "[RV_RELAY] Operador desconectado con %d sesiones activas. "
            "Iniciando grace period 15s. user_id=%s",
            len(user_sessions), user_id,
        )

        # Cancelar tarea previa si existía (disconnect rápido repetido)
        existing_task = self._pending_operator_disconnects.pop(user_id, None)
        if existing_task and not existing_task.done():
            existing_task.cancel()

        # Iniciar timer de 15s para cierre definitivo
        task = asyncio.create_task(
            self._operator_disconnect_cleanup(user_id, user_sessions)
        )
        self._pending_operator_disconnects[user_id] = task

    async def handle_operator_reconnect(self, user_id: str) -> None:
        """
        Cancela el timer de desconexión si el operador reconectó (page reload).

        Se invoca al conectar un operador WS. Si hay un timer pendiente de 15s,
        se cancela y las sesiones RV siguen activas sin interrupción.

        Args:
            user_id: UUID del admin/operador que se reconectó
        """
        task = self._pending_operator_disconnects.pop(user_id, None)
        if task and not task.done():
            task.cancel()
            logger.info(
                "[RV_RELAY] Operador reconectado dentro del grace period. "
                "Timer cancelado. user_id=%s",
                user_id,
            )

    async def _operator_disconnect_cleanup(self, user_id: str, session_ids: list[str]) -> None:
        """
        Espera 15s y cierra sesiones si el operador no reconectó.

        Se ejecuta como asyncio.Task y puede ser cancelada por handle_operator_reconnect.

        Args:
            user_id: UUID del admin/operador
            session_ids: Lista de session_ids que estaban activos al desconectarse
        """
        try:
            await asyncio.sleep(15)
        except asyncio.CancelledError:
            # El operador reconectó y se canceló este timer
            return

        # Grace period expirado — cerrar sesiones
        logger.warning(
            "[RV_RELAY] Grace period de operador expirado (15s). "
            "Cerrando %d sesiones. user_id=%s",
            len(session_ids), user_id,
        )

        # Limpiar referencia de la tarea
        self._pending_operator_disconnects.pop(user_id, None)

        from app.core.database import SessionLocal
        from app.services.remote_view_session import SessionManager

        session_manager = SessionManager()
        db = SessionLocal()
        try:
            for session_id in session_ids:
                try:
                    # Cerrar sesión en BD
                    ended = session_manager.end_session(db, session_id, "admin_logout")
                    if ended:
                        logger.info(
                            "[RV_RELAY] Sesión cerrada por admin_logout: "
                            "session_id=%s",
                            session_id,
                        )

                    # Notificar a la workstation que la sesión terminó
                    ws_id = self.get_workstation_id(session_id)
                    if ws_id:
                        await connection_manager.send_to_workstation(ws_id, {
                            "type": "remote_view_stop",
                            "session_id": session_id,
                            "reason": "admin_logout",
                        })

                    # Eliminar sesión del mapping de relay
                    self.unregister_session(session_id)

                except Exception as e:
                    logger.error(
                        "[RV_RELAY] Error cerrando sesión %s por operator disconnect: %s",
                        session_id, e,
                    )
        finally:
            db.close()


# Singleton — instanciar a nivel de módulo (mismo patrón que connection_manager)
remote_view_relay = RemoteViewRelay()
