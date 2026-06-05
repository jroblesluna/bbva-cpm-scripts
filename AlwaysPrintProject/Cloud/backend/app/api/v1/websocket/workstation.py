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
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.workstation import Workstation
from app.models.organization import Organization, PublicIP
from app.schemas.websocket import RegisterMessage, TelemetryMessage, ConnectivityResultMessage
from app.schemas.telemetry import TelemetryMessagePayload, ConnectivityResultPayload
from app.services.websocket_manager import connection_manager
from app.services.workstation import WorkstationService
from app.services.config import ConfigService
from app.services.message import MessageService
from app.services.audit import AuditService
from app.services.telemetry import TelemetryService


async def _safe_close(websocket: WebSocket, code: int, reason: str) -> None:
    """
    Cierra un WebSocket de forma segura:
    - Trunca el reason a 123 bytes (límite del protocolo WebSocket para control frames)
    - Captura errores si el socket ya se cerró
    """
    # El protocolo WebSocket limita control frames (close/ping/pong) a 125 bytes de payload.
    # 2 bytes son para el código de cierre, quedan 123 para el reason.
    truncated_reason = reason[:123]
    try:
        await websocket.close(code=code, reason=truncated_reason)
    except RuntimeError:
        # "Cannot call send once a close message has been sent"
        pass
    except Exception:
        pass
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
    - {"type": "register", "ip_private": "...", "hostname": "...", "os_serial": "...", "current_user": "...", "cidr": "192.168.1.0/24", "tray_version": "2.1.0"}
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
            await _safe_close(websocket, 1008, "First message must be register")
            return
        
        # Validar mensaje de registro con schema Pydantic (incluye validación CIDR)
        try:
            register_msg = RegisterMessage(**data)
        except ValidationError as e:
            # Extraer mensaje de error legible
            error_detail = str(e.errors()[0].get("msg", "Datos de registro inválidos"))
            await _safe_close(websocket, 1008, f"Registro inválido: {error_detail}")
            return
        
        # Extraer datos validados del mensaje de registro
        ip_private = register_msg.ip_private
        hostname = register_msg.hostname
        os_serial = register_msg.os_serial
        current_user = register_msg.current_user
        cidr = register_msg.cidr
        tray_version = register_msg.tray_version
        
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
            f"cidr={cidr}, "
            f"tray_version={tray_version}, "
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
                current_user=current_user,
                cidr=cidr,
                tray_version=tray_version
            )
            
            if status == "pending":
                # IP pública no autorizada
                await _safe_close(websocket, 1008, f"IP {client_host} no autorizada")
                return
            
            elif status == "inactive_organization":
                # Organización desactivada
                await _safe_close(websocket, 1008, "Organizacion desactivada")
                return
            
            elif status != "authorized" or not workstation:
                # Error inesperado
                await _safe_close(websocket, 1011, "Error al registrar")
                return
            
            workstation_id = str(workstation.id)
            print(f"[WS] Registro exitoso: id={workstation_id}, status={status}", flush=True)
            
        except Exception as e:
            # Error en registro
            print(f"[WS] ERROR en registro: {type(e).__name__}: {e}", flush=True)
            logger.error(f"Error registrando workstation ip={ip_private}: {e}")
            await _safe_close(websocket, 1011, f"Error: {str(e)}")
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
        
        # Enviar confirmación de registro con workstation_id
        await websocket.send_json({
            "type": "registered",
            "workstation_id": workstation_id
        })
        print(f"[WS] Mensaje registered enviado: {workstation_id}", flush=True)
        
        await websocket.send_json({
            "type": "config_update",
            "config": config
        })
        print(f"[WS] Config enviada", flush=True)
        
        # Sincronizar estado de contingencia forzada (por si se activó mientras estaba offline)
        # Prioridad: organización > VLAN > workstation individual
        forced_contingency_enabled = False
        forced_source = None
        forced_source_name = None

        org = db.query(Organization).filter(Organization.id == workstation.organization_id).first()
        if org and org.forced_contingency:
            forced_contingency_enabled = True
            forced_source = "organization"
            forced_source_name = org.name

        if not forced_contingency_enabled and workstation.vlan_id:
            from app.models.vlan import VLAN as VLANModel
            ws_vlan = db.query(VLANModel).filter(VLANModel.id == workstation.vlan_id).first()
            if ws_vlan and ws_vlan.forced_contingency:
                forced_contingency_enabled = True
                forced_source = "vlan"
                forced_source_name = ws_vlan.name

        if not forced_contingency_enabled and workstation.forced_contingency:
            forced_contingency_enabled = True
            forced_source = "workstation"
            forced_source_name = workstation.hostname or str(workstation.ip_private)

        if forced_contingency_enabled:
            # Resolver printer_ip
            from app.models.device import Device
            printer_ip = None
            if workstation.default_printer_id:
                printer = db.query(Device).filter(Device.id == workstation.default_printer_id).first()
                if printer:
                    printer_ip = printer.ip_address
            if not printer_ip and workstation.vlan_id:
                from app.models.vlan import VLAN as VLANModel2
                ws_vlan2 = db.query(VLANModel2).filter(VLANModel2.id == workstation.vlan_id).first()
                if ws_vlan2 and ws_vlan2.default_device_id:
                    default_dev = db.query(Device).filter(Device.id == ws_vlan2.default_device_id).first()
                    if default_dev:
                        printer_ip = default_dev.ip_address
                if not printer_ip:
                    first_device = db.query(Device).filter(
                        Device.vlan_id == workstation.vlan_id,
                        Device.organization_id == workstation.organization_id,
                        Device.is_active == True
                    ).order_by(Device.ip_address).first()
                    if first_device:
                        printer_ip = first_device.ip_address

            await websocket.send_json({
                "type": "forced_contingency",
                "enabled": True,
                "source": forced_source,
                "source_name": forced_source_name,
                "printer_ip": printer_ip,
            })
            print(f"[WS] Contingencia forzada sincronizada: source={forced_source}, printer_ip={printer_ip}", flush=True)

        else:
            # No hay contingencia forzada activa. Enviar estado explícito para que
            # el cliente sincronice su semáforo local (ContingencyEnabled=0).
            # Cubre el caso donde la Cloud desactivó contingencia mientras la workstation
            # estaba offline y el semáforo local quedó en 1.
            await websocket.send_json({
                "type": "forced_contingency",
                "enabled": False,
                "source": "sync",
                "source_name": "normal",
                "printer_ip": None,
            })

        print(f"[WS] Entrando al loop", flush=True)
        
        # Enviar mensajes pendientes (nuevo sistema de deliveries)
        pending_deliveries = message_service.get_pending_deliveries_for_workstation(
            db=db,
            workstation_id=workstation_id
        )
        
        for delivery in pending_deliveries:
            msg = delivery.message
            await websocket.send_json({
                "type": "message",
                "message_id": str(msg.id),
                "content": msg.content,
                "sent_at": msg.sent_at.isoformat()
            })
            
            # Marcar delivery individual como enviado
            message_service.mark_delivery_as_sent(db, str(msg.id), workstation_id)
        
        # Loop de recepción de mensajes
        while True:
            data = await websocket.receive_json()
            message_type = data.get("type")
            
            if message_type == "pong":
                # Registrar pong
                await connection_manager.handle_pong(workstation_id)
            
            elif message_type == "status_update":
                # Verificar que la workstation aún existe en BD antes de actualizar
                ws_exists = db.query(Workstation).filter(
                    Workstation.id == workstation_id
                ).first()
                
                if not ws_exists:
                    # Workstation eliminada: verificar si la organización permite re-registro
                    org = db.query(Organization).filter(
                        Organization.id == workstation.organization_id
                    ).first()
                    
                    if org and org.auto_reregister_enabled:
                        logger.info(
                            "[WS] status_update para workstation %s eliminada. "
                            "auto_reregister_enabled=True para org %s. Solicitando re-registro.",
                            workstation_id, org.name
                        )
                        await websocket.send_json({
                            "type": "request_reregister",
                            "reason": "workstation_not_found"
                        })
                        await _safe_close(websocket, 1000, "Re-registro requerido")
                        return
                    else:
                        logger.warning(
                            "[WS] status_update para workstation %s eliminada. "
                            "auto_reregister_enabled=False. Descartando.",
                            workstation_id
                        )
                        continue
                
                # Actualizar estado de contingencia
                contingency_active = data.get("contingency_active")
                contingency_printer_ip = data.get("contingency_printer_ip")
                current_user = data.get("current_user")
                
                if contingency_active is not None:
                    workstation_service.update_contingency_status(
                        db=db,
                        workstation_id=workstation_id,
                        contingency_active=contingency_active,
                        contingency_ip=contingency_printer_ip
                    )
                    
                    # Registrar en auditoría
                    audit_service.log_contingency_toggle(
                        db=db,
                        workstation_id=workstation_id,
                        organization_id=str(workstation.organization_id),
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
                await connection_manager.broadcast_to_organization(
                    organization_id=str(workstation.organization_id),
                    message={
                        "type": "workstation_status_change",
                        "workstation_id": workstation_id,
                        "contingency_active": contingency_active,
                        "contingency_printer_ip": contingency_printer_ip,
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
                    organization_id=str(workstation.organization_id),
                    old_values={field: old_value},
                    new_values={field: new_value},
                    ip_address=client_host
                )
            
            elif message_type == "command_result":
                # Resultado de ejecución de comando
                command_id = data.get("command_id")
                success = data.get("success")
                output = data.get("output")
                
                # Resolver waiter si hay alguno esperando esta respuesta
                connection_manager.resolve_command_response(command_id, {
                    "command_id": command_id,
                    "success": success,
                    "output": output
                })
                
                # Notificar a operadores
                await connection_manager.broadcast_to_organization(
                    organization_id=str(workstation.organization_id),
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
                result = await _handle_telemetry(
                    data=data,
                    workstation_id=workstation_id,
                    organization_id=str(workstation.organization_id),
                    db=db
                )
                
                # Si la workstation fue eliminada de la BD, verificar flag de re-registro
                if result == "request_reregister":
                    org = db.query(Organization).filter(
                        Organization.id == workstation.organization_id
                    ).first()
                    
                    if org and org.auto_reregister_enabled:
                        logger.info(
                            "[WS] Telemetría para workstation %s eliminada. "
                            "auto_reregister_enabled=True para org %s. Solicitando re-registro.",
                            workstation_id, org.name
                        )
                        await websocket.send_json({
                            "type": "request_reregister",
                            "reason": "workstation_not_found"
                        })
                        await _safe_close(websocket, 1000, "Re-registro requerido")
                        return
                    else:
                        logger.warning(
                            "[WS] Telemetría para workstation %s eliminada. "
                            "auto_reregister_enabled=False. Descartando sin re-registro.",
                            workstation_id
                        )
            
            elif message_type == "connectivity_result":
                # Procesar resultado de chequeo de conectividad
                await _handle_connectivity_result(
                    data=data,
                    workstation_id=workstation_id,
                    organization_id=str(workstation.organization_id),
                    db=db
                )
            
            else:
                # Tipo de mensaje desconocido
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {message_type}"
                })
            
            # Liberar objetos cacheados de la sesión de BD después de cada mensaje.
            # Conexiones WebSocket son de larga duración (horas/días) y sin esto,
            # la identity map de SQLAlchemy acumula objetos indefinidamente.
            db.expire_all()
    
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
                db=db,
                websocket=websocket
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
            organization_id=organization_id,
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
        # workstation_id no existe para esta cuenta: solicitar re-registro
        # Esto ocurre cuando la workstation fue eliminada de la BD pero el cliente
        # sigue conectado con su workstation_id antiguo
        logger.warning(
            "Telemetría descartada - workstation_id=%s no encontrada para organization_id=%s. "
            "Solicitando re-registro al cliente.",
            workstation_id,
            organization_id
        )
        return "request_reregister"

    # Telemetría recibida exitosamente: asegurar que is_online=True
    # Esto cubre el caso donde el WebSocket se reconectó pero is_online quedó en False
    from app.models.workstation import Workstation as WS
    from datetime import datetime, timezone
    ws = db.query(WS).filter(WS.id == workstation_id).first()
    if ws and not ws.is_online:
        ws.is_online = True
        ws.last_connection = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        logger.info("Telemetría restauró is_online=True para workstation_id=%s", workstation_id)

    # Persistencia exitosa: broadcast 'telemetry_received' a operadores de la organización
    await connection_manager.broadcast_to_organization(
        organization_id=organization_id,
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
            datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            workstation_id,
            str(e)
        )
        return

    try:
        # Persistir resultado usando ConnectivityService (verifica tenant isolation internamente)
        result = connectivity_service.persist_connectivity_result(
            db=db,
            workstation_id=workstation_id,
            organization_id=organization_id,
            payload=payload
        )

        if result is None:
            # Workstation no encontrada para la cuenta: ya logueado por el servicio como WARNING
            logger.warning(
                "[%s] Resultado de conectividad descartado - workstation_id=%s "
                "no encontrada para organization_id=%s",
                datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
                workstation_id,
                organization_id
            )
            return

        # Persistencia exitosa: broadcast a operadores de la misma organización
        await connection_manager.broadcast_to_organization(
            organization_id=organization_id,
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
            datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
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
            datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
            workstation_id,
            data.get("check_id", "desconocido"),
            str(e)
        )

