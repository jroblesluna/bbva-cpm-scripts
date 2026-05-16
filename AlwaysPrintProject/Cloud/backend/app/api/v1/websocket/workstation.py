"""
Endpoint WebSocket para Tray Clients (workstations).

Este módulo maneja la comunicación bidireccional con las workstations:
- Registro inicial
- Recepción de estado y telemetría
- Envío de comandos y configuración
- Ping/pong para keep-alive
- Recepción de telemetría periódica
- Recepción de resultados de conectividad
"""

import json
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.workstation import Workstation
from app.schemas.websocket import TelemetryMessage, ConnectivityResultMessage
from app.schemas.telemetry import TelemetryMessagePayload, ConnectivityResultPayload
from app.services.websocket_manager import connection_manager
from app.services.workstation import WorkstationService
from app.services.config import ConfigService
from app.services.message import MessageService
from app.services.audit import AuditService
from app.services.telemetry import TelemetryService
from app.services.connectivity import ConnectivityService


logger = logging.getLogger(__name__)


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
        # Aceptar la conexión WebSocket antes de cualquier operación
        await websocket.accept()
        print(f"[WS] Conexión aceptada", flush=True)
        
        # Esperar mensaje de registro
        data = await websocket.receive_json()
        print(f"[WS] Mensaje recibido: type={data.get('type')}", flush=True)
        
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
        
        # Obtener IP pública del cliente desde headers de Nginx (X-Forwarded-For o X-Real-IP)
        # En WebSocket, los headers del handshake están disponibles en websocket.headers
        forwarded_for = websocket.headers.get("x-forwarded-for")
        real_ip = websocket.headers.get("x-real-ip")
        workstation_local_ip = websocket.headers.get("x-workstation-local-ip")
        
        if forwarded_for:
            client_host = forwarded_for.split(",")[0].strip()
        elif real_ip:
            client_host = real_ip.strip()
        else:
            client_host = websocket.client.host if websocket.client else None
        
        # Log detallado para debugging
        logger.info(
            f"[REGISTRO WS] Datos recibidos: "
            f"ip_private={ip_private}, "
            f"hostname={hostname}, "
            f"X-Workstation-Local-IP={workstation_local_ip}, "
            f"X-Forwarded-For={forwarded_for}, "
            f"X-Real-IP={real_ip}, "
            f"client_host={client_host}"
        )
        
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
            print(f"[WS] Registro exitoso: id={workstation_id}, status={status}", flush=True)
            
        except Exception as e:
            # Error en registro
            print(f"[WS] ERROR en registro: {type(e).__name__}: {e}", flush=True)
            logger.error(f"Error registrando workstation ip={ip_private}: {e}")
            await websocket.close(code=1011, reason=f"Error: {str(e)}")
            return
        
        # Conectar WebSocket
        await connection_manager.connect_workstation(
            workstation_id=workstation_id,
            websocket=websocket,
            db=db
        )
        print(f"[WS] Conectado al manager", flush=True)
        
        # Enviar configuración efectiva
        config = config_service.get_effective_config(db, workstation_id)
        print(f"[WS] Config obtenida, enviando...", flush=True)
        await websocket.send_json({
            "type": "config_update",
            "config": config
        })
        print(f"[WS] Config enviada, entrando al loop", flush=True)
        
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
            
            elif message_type == "telemetry":
                # Procesar mensaje de telemetría periódica
                await _handle_telemetry(
                    data=data,
                    workstation_id=workstation_id,
                    organization_id=str(workstation.account_id),
                    db=db
                )
            
            elif message_type == "connectivity_result":
                # Procesar resultado de chequeo de conectividad
                await _handle_connectivity_result(
                    data=data,
                    workstation_id=workstation_id,
                    organization_id=str(workstation.account_id),
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
        print(f"[WS] WebSocketDisconnect para {workstation_id}", flush=True)
    
    except Exception as e:
        # Error inesperado
        print(f"[WS] EXCEPCION INESPERADA: {type(e).__name__}: {e}", flush=True)
        logger.error(f"WebSocket error inesperado para workstation_id={workstation_id}: {e}", exc_info=True)
    
    finally:
        # Limpiar conexión
        if workstation_id:
            await connection_manager.disconnect_workstation(
                workstation_id=workstation_id,
                db=db
            )


async def _handle_telemetry(
    data: dict,
    workstation_id: str,
    organization_id: str,
    db: Session
) -> None:
    """
    Procesa un mensaje de telemetría recibido de una workstation.

    Flujo:
    1. Valida el payload con TelemetryMessagePayload (Pydantic)
    2. Persiste en BD usando TelemetryService (verifica tenant isolation)
    3. Si persist exitoso, broadcast 'telemetry_received' a operadores de la cuenta
    4. Si validación falla: log ERROR, descartar, NO cerrar conexión
    5. Si workstation no existe para la cuenta: log WARNING, descartar, NO cerrar conexión
    6. Si escritura BD falla: log ERROR, omitir broadcast, NO cerrar conexión

    Args:
        data: Datos crudos del mensaje WebSocket
        workstation_id: UUID de la workstation que envió el mensaje
        organization_id: UUID de la cuenta/organización (para tenant isolation)
        db: Sesión de base de datos
    """
    try:
        # Validar payload con schema Pydantic (excluir campo 'type' del mensaje WS)
        payload_data = {k: v for k, v in data.items() if k != "type"}
        payload = TelemetryMessagePayload(**payload_data)
    except ValidationError as e:
        # Payload inválido: registrar error y descartar mensaje (NO cerrar WebSocket)
        logger.error(
            "Payload de telemetría inválido - workstation_id=%s, error=%s",
            workstation_id,
            str(e)
        )
        return

    # Persistir telemetría usando TelemetryService (incluye verificación de tenant)
    telemetry_service = TelemetryService()
    try:
        telemetry_log = telemetry_service.persist_telemetry(
            db=db,
            workstation_id=workstation_id,
            account_id=organization_id,
            payload=payload
        )
    except Exception as e:
        # Fallo de escritura en BD: log ERROR, omitir broadcast, NO cerrar conexión
        logger.error(
            "Error al persistir telemetría en BD - workstation_id=%s, error=%s",
            workstation_id,
            str(e)
        )
        return

    if telemetry_log is None:
        # workstation_id no existe para esta cuenta: log WARNING, descartar
        logger.warning(
            "Telemetría descartada - workstation_id=%s no encontrada para account_id=%s",
            workstation_id,
            organization_id
        )
        return

    # Persistencia exitosa: broadcast 'telemetry_received' a operadores de la cuenta
    await connection_manager.broadcast_to_account(
        account_id=organization_id,
        message={
            "type": "telemetry_received",
            "workstation_id": workstation_id,
            "queue_status": payload.queue_status,
            "contingency_active": payload.contingency_active,
            "jobs_identified": payload.jobs_identified,
            "avg_release_time_ms": payload.avg_release_time_ms,
            "disconnection_count": len(payload.disconnection_log)
        },
        db=db
    )

    logger.info(
        "Telemetría persistida y broadcast enviado - workstation_id=%s, "
        "queue_status=%s, jobs_identified=%d, contingency_active=%s",
        workstation_id,
        payload.queue_status,
        payload.jobs_identified,
        payload.contingency_active
    )


async def _handle_connectivity_result(
    data: dict,
    workstation_id: str,
    organization_id: str,
    db: Session
) -> None:
    """
    Procesa un resultado de chequeo de conectividad recibido de una workstation.
    
    Flujo:
    1. Validar payload con ConnectivityResultPayload (Pydantic)
    2. Persistir resultado usando ConnectivityService (incluye tenant isolation)
    3. Si persist retorna None (workstation no encontrada para la cuenta), log WARNING y continuar
    4. Si persist exitoso, broadcast connectivity_result a operadores de la misma cuenta
    5. Si error de BD, log ERROR, omitir broadcast, continuar
    6. NUNCA cerrar la conexión WebSocket por errores
    
    Args:
        data: Datos crudos del mensaje WebSocket
        workstation_id: UUID de la workstation que envió el mensaje
        organization_id: UUID de la cuenta/organización (para tenant isolation)
        db: Sesión de base de datos
    """
    connectivity_service = ConnectivityService()

    try:
        # Extraer datos del payload (excluir campo 'type' del mensaje WebSocket)
        payload_data = {k: v for k, v in data.items() if k != "type"}

        # Validar payload con schema Pydantic ConnectivityResultPayload
        payload = ConnectivityResultPayload(**payload_data)

    except ValidationError as e:
        # Payload inválido: registrar error y descartar mensaje (NO cerrar WebSocket)
        logger.error(
            "[%s] Payload de connectivity_result inválido - workstation_id=%s, error=%s",
            datetime.utcnow().isoformat(),
            workstation_id,
            str(e)
        )
        return

    try:
        # Persistir resultado usando ConnectivityService (verifica tenant isolation internamente)
        result = connectivity_service.persist_connectivity_result(
            db=db,
            workstation_id=workstation_id,
            account_id=organization_id,
            payload=payload
        )

        if result is None:
            # Workstation no encontrada para la cuenta: ya logueado por el servicio como WARNING
            logger.warning(
                "[%s] Resultado de conectividad descartado - workstation_id=%s "
                "no encontrada para organization_id=%s",
                datetime.utcnow().isoformat(),
                workstation_id,
                organization_id
            )
            return

        # Persistencia exitosa: broadcast a operadores de la misma cuenta
        await connection_manager.broadcast_to_account(
            account_id=organization_id,
            message={
                "type": "connectivity_result",
                "workstation_id": str(workstation_id),
                "check_id": payload.check_id,
                "check_type": payload.check_type,
                "success": payload.success,
                "latency_ms": payload.latency_ms,
                "error": payload.error
            },
            db=db
        )

        logger.info(
            "[%s] Resultado de conectividad persistido y broadcast - workstation_id=%s, "
            "check_id=%s, check_type=%s, success=%s, latency_ms=%s",
            datetime.utcnow().isoformat(),
            workstation_id,
            payload.check_id,
            payload.check_type,
            payload.success,
            payload.latency_ms
        )

    except Exception as e:
        # Error de BD u otro error inesperado: log ERROR, omitir broadcast, NO cerrar WebSocket
        logger.error(
            "[%s] Error al persistir resultado de conectividad - workstation_id=%s, "
            "check_id=%s, error=%s",
            datetime.utcnow().isoformat(),
            workstation_id,
            data.get("check_id", "desconocido"),
            str(e)
        )

