"""
Endpoint WebSocket para operadores (Frontend).

Este módulo maneja la comunicación con el frontend:
- Notificaciones en tiempo real
- Cambios de estado de workstations
- Resultados de comandos
- Alertas del sistema
"""

from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.websocket_manager import connection_manager
from app.core.security import decode_access_token


router = APIRouter()


@router.websocket("/ws/operator")
async def operator_websocket(
    websocket: WebSocket,
    token: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Endpoint WebSocket para operadores (Frontend).
    
    Requiere autenticación mediante token JWT en query parameter.
    
    Protocolo de mensajes:
    
    Servidor → Cliente:
    - {"type": "workstation_online", "workstation_id": "...", "ip_private": "..."}
    - {"type": "workstation_offline", "workstation_id": "...", "ip_private": "..."}
    - {"type": "workstation_status_change", "workstation_id": "...", "contingency_active": bool}
    - {"type": "command_result", "workstation_id": "...", "command_id": "...", "success": bool}
    - {"type": "message_delivered", "message_id": "..."}
    - {"type": "alert", "level": "info|warning|error", "message": "..."}
    
    Cliente → Servidor:
    - {"type": "ping"}
    - {"type": "subscribe", "events": ["workstation_status", "commands", "messages"]}
    """
    
    user_id: Optional[str] = None
    
    try:
        # Validar token JWT
        if not token:
            await websocket.close(code=1008, reason="Authentication required")
            return
        
        try:
            payload = decode_access_token(token)
            user_id = payload.get("sub")
            
            if not user_id:
                await websocket.close(code=1008, reason="Invalid token")
                return
        
        except Exception:
            await websocket.close(code=1008, reason="Invalid token")
            return
        
        # Conectar WebSocket
        await connection_manager.connect_operator(
            user_id=user_id,
            websocket=websocket
        )
        
        # Enviar confirmación de conexión
        await websocket.send_json({
            "type": "connected",
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        })
        
        # Enviar estado inicial de workstations online
        online_workstations = connection_manager.get_online_workstations()
        await websocket.send_json({
            "type": "initial_state",
            "online_workstations": online_workstations,
            "connection_count": connection_manager.get_connection_count()
        })
        
        # Loop de recepción de mensajes
        while True:
            data = await websocket.receive_json()
            message_type = data.get("type")
            
            if message_type == "ping":
                # Responder con pong
                await websocket.send_json({"type": "pong"})
            
            elif message_type == "subscribe":
                # Cliente solicita suscribirse a eventos específicos
                # (Por ahora todos los eventos se envían automáticamente)
                events = data.get("events", [])
                await websocket.send_json({
                    "type": "subscribed",
                    "events": events
                })
            
            # === Remote View: relay de mensajes del operador a la workstation ===
            elif message_type in (
                "remote_view_config",
                "remote_view_pause",
                "remote_view_resume",
                "remote_view_stop",
                "rv_request_frame",
                "rv_input",
                "rv_clipboard",
            ):
                from app.services.remote_view_relay import remote_view_relay
                session_id = data.get("session_id")
                if session_id:
                    # Lazy register: si la sesión no está en el relay local
                    # (cross-worker issue), cargarla de BD y registrarla.
                    if not remote_view_relay.get_session(session_id):
                        _lazy_register_rv_session(session_id)
                    # Si es cambio de modo, registrar en audit trail (Req 11.4)
                    if message_type == "remote_view_config" and "mode" in data:
                        await _handle_mode_change_audit(
                            db, session_id, data["mode"], user_id
                        )
                    # Relay del mensaje a la workstation
                    await remote_view_relay.relay_to_workstation(session_id, data)
            
            else:
                # Tipo de mensaje desconocido
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {message_type}"
                })
    
    except WebSocketDisconnect:
        # Cliente desconectado
        pass
    
    except Exception as e:
        # Error inesperado
        print(f"Operator WebSocket error: {e}")
    
    finally:
        # Limpiar conexión
        if user_id:
            await connection_manager.disconnect_operator(
                user_id=user_id,
                websocket=websocket
            )

            # Invalidar sesiones de Remote View activas del usuario (Req 7.5, 12.3)
            # Cubre: cierre de pestaña, navegación, logout explícito, JWT expirado
            try:
                from app.services.remote_view_relay import remote_view_relay
                await remote_view_relay.handle_operator_disconnect(user_id)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(
                    "[WS_OPERATOR] Error al invalidar sesiones RV en desconexión: "
                    "user_id=%s, error=%s",
                    user_id, e,
                )


from datetime import datetime, timezone


async def _handle_mode_change_audit(
    db: Session,
    session_id: str,
    new_mode: str,
    user_id: str,
) -> None:
    """
    Actualiza el modo de la sesión en BD y registra REMOTE_VIEW_MODE_CHANGE en audit trail.
    Requirements: 11.4, 9.9
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        from app.services.remote_view_session import session_manager
        updated = session_manager.update_mode(db, session_id, new_mode)
        if updated:
            old_mode = getattr(updated, "_old_mode", None)
            # Registrar en audit trail
            from app.services.audit import audit_service
            audit_service.log_action(
                db=db,
                action_type="REMOTE_VIEW_MODE_CHANGE",
                entity_type="RemoteViewSession",
                entity_id=session_id,
                user_id=user_id,
                workstation_id=str(updated.workstation_id),
                organization_id=str(updated.organization_id),
                new_values={
                    "session_id": session_id,
                    "old_mode": old_mode,
                    "new_mode": new_mode,
                },
            )
            logger.info(
                "[WS_OPERATOR] Modo cambiado: session_id=%s, %s → %s",
                session_id, old_mode, new_mode,
            )
    except Exception as e:
        logger.error(
            "[WS_OPERATOR] Error registrando cambio de modo: session_id=%s, error=%s",
            session_id, e,
        )


def _lazy_register_rv_session(session_id: str) -> None:
    """
    Registra una sesión RV en el relay local si existe en BD (cross-worker lazy load).

    Con 2 workers, la sesión se registra en el relay del worker que maneja POST /start,
    pero el WS del operador puede estar en otro worker. Este lazy load resuelve esa
    discrepancia consultando BD una sola vez; mensajes posteriores usan el mapping en memoria.
    """
    import logging
    _logger = logging.getLogger(__name__)
    try:
        from app.models.remote_view import RemoteViewSession
        from app.services.remote_view_relay import remote_view_relay
        from app.core.database import SessionLocal

        rv_db = SessionLocal()
        try:
            db_session = rv_db.query(RemoteViewSession).filter(
                RemoteViewSession.id == session_id,
                RemoteViewSession.status.in_(("pending_consent", "active")),
            ).first()
            if db_session:
                remote_view_relay.register_session(
                    session_id=str(db_session.id),
                    workstation_id=str(db_session.workstation_id),
                    user_id=str(db_session.user_id),
                )
                _logger.info(
                    "[RV] Lazy register exitoso (operator): session_id=%s, ws=%s",
                    session_id, db_session.workstation_id,
                )
            else:
                _logger.warning(
                    "[RV] Lazy register: sesión %s no encontrada en BD (inactiva o inexistente)",
                    session_id,
                )
        finally:
            rv_db.close()
    except Exception as e:
        _logger.warning(
            "[RV] Error en lazy register de sesión %s: %s", session_id, e
        )
