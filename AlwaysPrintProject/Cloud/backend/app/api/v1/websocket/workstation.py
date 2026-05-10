"""
Endpoint WebSocket para Tray Clients (workstations).

Este módulo maneja la comunicación bidireccional con las workstations:
- Registro inicial
- Recepción de estado y telemetría
- Envío de comandos y configuración
- Ping/pong para keep-alive
"""

import json
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.websocket_manager import connection_manager
from app.services.workstation import WorkstationService
from app.services.config import ConfigService
from app.services.message import MessageService
from app.services.audit import AuditService


router = APIRouter()


@router.websocket("/ws/workstation")
async def workstation_websocket(
    websocket: WebSocket,
    db: Session = Depends(get_db)
):
    """
    Endpoint WebSocket para Tray Clients.
    
    Protocolo de mensajes:
    
    Cliente → Servidor:
    - {"type": "register", "ip_private": "...", "hostname": "...", "os_serial": "...", "current_user": "..."}
    - {"type": "pong"}
    - {"type": "status_update", "contingency_active": bool, "current_user": "..."}
    - {"type": "config_change_report", "field": "...", "old_value": "...", "new_value": "..."}
    - {"type": "command_result", "command_id": "...", "success": bool, "output": "..."}
    
    Servidor → Cliente:
    - {"type": "ping"}
    - {"type": "config_update", "config": {...}}
    - {"type": "command", "command_id": "...", "command_type": "...", "params": {...}}
    - {"type": "message", "message_id": "...", "content": "..."}
    """
    
    workstation_id: Optional[str] = None
    workstation_service = WorkstationService()
    config_service = ConfigService()
    message_service = MessageService()
    audit_service = AuditService()
    
    try:
        # Esperar mensaje de registro
        data = await websocket.receive_json()
        
        if data.get("type") != "register":
            await websocket.close(code=1008, reason="First message must be 'register'")
            return
        
        # Extraer datos de registro
        ip_private = data.get("ip_private")
        hostname = data.get("hostname")
        os_serial = data.get("os_serial")
        current_user = data.get("current_user")
        
        if not ip_private:
            await websocket.close(code=1008, reason="ip_private is required")
            return
        
        # Obtener IP pública del cliente
        client_host = websocket.client.host if websocket.client else None
        
        # Registrar workstation
        try:
            workstation, is_new, status = workstation_service.register_workstation(
                db=db,
                ip_private=ip_private,
                public_ip=client_host or "unknown",
                hostname=hostname,
                os_serial=os_serial,
                current_user=current_user
            )
            
            if status == "pending":
                # IP pública no autorizada
                await websocket.close(
                    code=1008, 
                    reason=f"IP pública {client_host} no está autorizada. "
                           "Un administrador debe autorizar esta IP antes de que puedas conectarte. "
                           "La IP ha sido registrada y está pendiente de autorización."
                )
                return
            
            elif status == "inactive_account":
                # Cuenta desactivada
                await websocket.close(
                    code=1008,
                    reason="La cuenta asociada a esta IP está desactivada."
                )
                return
            
            elif status != "authorized" or not workstation:
                # Error inesperado
                await websocket.close(
                    code=1011,
                    reason="Error al registrar workstation."
                )
                return
            
            workstation_id = str(workstation.id)
            
        except Exception as e:
            # Error en registro
            await websocket.close(code=1011, reason=f"Error: {str(e)}")
            return
        
        # Conectar WebSocket
        await connection_manager.connect_workstation(
            workstation_id=workstation_id,
            websocket=websocket,
            db=db
        )
        
        # Enviar configuración efectiva
        config = config_service.get_effective_config(db, workstation_id)
        await websocket.send_json({
            "type": "config_update",
            "config": config
        })
        
        # Enviar mensajes pendientes
        pending_messages = message_service.get_pending_messages_for_workstation(
            db=db,
            workstation_id=workstation_id
        )
        
        for msg in pending_messages:
            await websocket.send_json({
                "type": "message",
                "message_id": str(msg.id),
                "content": msg.content,
                "sent_at": msg.sent_at.isoformat()
            })
            
            # Marcar como entregado
            message_service.mark_message_as_delivered(db, str(msg.id))
        
        # Loop de recepción de mensajes
        while True:
            data = await websocket.receive_json()
            message_type = data.get("type")
            
            if message_type == "pong":
                # Registrar pong
                await connection_manager.handle_pong(workstation_id)
            
            elif message_type == "status_update":
                # Actualizar estado de contingencia
                contingency_active = data.get("contingency_active")
                current_user = data.get("current_user")
                
                if contingency_active is not None:
                    workstation_service.update_contingency_status(
                        db=db,
                        workstation_id=workstation_id,
                        contingency_active=contingency_active
                    )
                    
                    # Registrar en auditoría
                    audit_service.log_contingency_toggle(
                        db=db,
                        workstation_id=workstation_id,
                        account_id=str(workstation.account_id),
                        user_id=None,  # Cambio automático
                        activated=contingency_active,
                        ip_address=client_host
                    )
                
                if current_user is not None:
                    workstation_service.update_workstation_status(
                        db=db,
                        workstation_id=workstation_id,
                        is_online=True,
                        current_user=current_user
                    )
                
                # Notificar a operadores
                await connection_manager.broadcast_to_account(
                    account_id=str(workstation.account_id),
                    message={
                        "type": "workstation_status_change",
                        "workstation_id": workstation_id,
                        "contingency_active": contingency_active,
                        "current_user": current_user
                    },
                    db=db
                )
            
            elif message_type == "config_change_report":
                # Workstation reporta cambio de configuración local
                field = data.get("field")
                old_value = data.get("old_value")
                new_value = data.get("new_value")
                
                # Registrar en auditoría
                audit_service.log_action(
                    db=db,
                    action_type="config_change",
                    entity_type="WorkstationConfig",
                    entity_id=workstation_id,
                    workstation_id=workstation_id,
                    account_id=str(workstation.account_id),
                    old_values={field: old_value},
                    new_values={field: new_value},
                    ip_address=client_host
                )
            
            elif message_type == "command_result":
                # Resultado de ejecución de comando
                command_id = data.get("command_id")
                success = data.get("success")
                output = data.get("output")
                
                # Notificar a operadores
                await connection_manager.broadcast_to_account(
                    account_id=str(workstation.account_id),
                    message={
                        "type": "command_result",
                        "workstation_id": workstation_id,
                        "command_id": command_id,
                        "success": success,
                        "output": output
                    },
                    db=db
                )
            
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
        print(f"WebSocket error: {e}")
    
    finally:
        # Limpiar conexión
        if workstation_id:
            await connection_manager.disconnect_workstation(
                workstation_id=workstation_id,
                db=db
            )

