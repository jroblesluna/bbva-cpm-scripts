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


from datetime import datetime, timezone

