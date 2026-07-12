"""
Endpoints de gestión de workstations.

Este módulo define los endpoints para:
- Registro inicial de workstations (sin autenticación)
- Listado de workstations con filtros
- Actualización de workstations
- Gestión de configuración específica
- Estadísticas
- Envío de comandos remotos a workstations
"""

import asyncio
import logging
import uuid
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.utils import get_client_ip, get_workstation_local_ip
from app.models.user import User, UserRole
from app.models.workstation import Workstation
from app.schemas import (
    WorkstationResponse,
    WorkstationDetailResponse,
    WorkstationUpdate,
    WorkstationStatusUpdate,
    WorkstationListResponse,
    WorkstationStatsResponse,
    WorkstationConfigUpdate,
    WorkstationConfigResponse,
    WorkstationRegisterRequest,
    WorkstationRegisterResponse,
    WorkstationRegisterPendingResponse,
)
from app.services.workstation import WorkstationService
from app.services.config import ConfigService
from app.services.audit import AuditService
from app.services.websocket_manager import connection_manager

router = APIRouter()
logger = logging.getLogger(__name__)


# === SCHEMAS PARA COMANDOS REMOTOS ===

class CommandRequest(BaseModel):
    """Schema de solicitud de comando remoto a una workstation."""
    command_type: str = Field(
        ...,
        description="Tipo de comando: restart_service, restart_tray, check_update"
    )
    params: dict = Field(
        default_factory=dict,
        description="Parámetros opcionales del comando"
    )


class CommandResponse(BaseModel):
    """Schema de respuesta al enviar un comando remoto."""
    command_id: str = Field(..., description="ID único del comando enviado")
    status: str = Field(..., description="Estado del envío: sent")


class OnDemandActionInfo(BaseModel):
    """Schema de información de una acción OnDemand disponible."""
    label: str = Field(..., description="Etiqueta de la acción (se usa como identificador)")
    description: str = Field("", description="Descripción de lo que hace la acción")


# === ENDPOINT DE ACCIONES ONDEMAND ===

@router.get("/{workstation_id}/ondemand-actions", response_model=list[OnDemandActionInfo])
def get_ondemand_actions(
    workstation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener las acciones OnDemand disponibles para una workstation.
    
    Resuelve la configuración efectiva (con herencia) y extrae triggers OnDemand.
    
    - Admin: puede ver acciones de cualquier workstation
    - Operador: solo puede ver acciones de workstations de su organización
    
    Args:
        workstation_id: ID de la workstation
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        Lista de OnDemandActionInfo con label y description de cada acción
    """
    import json

    # Verificar que la workstation existe
    workstation = db.query(Workstation).filter(Workstation.id == workstation_id).first()
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workstation no encontrada"
        )

    # Tenant isolation: operadores solo su org, admins todo
    if current_user.role != UserRole.ADMIN:
        if current_user.organization_id != workstation.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Sin permiso para ver esta workstation"
            )

    # Resolver config efectivo
    from app.services.action_config import ActionConfigService
    config = ActionConfigService.resolve_effective_config(db, workstation.id)

    if not config:
        return []

    # Parsear config_json y extraer triggers OnDemand
    try:
        config_data = json.loads(config.config_json)
    except json.JSONDecodeError:
        return []

    actions: list[OnDemandActionInfo] = []
    triggers = config_data.get("triggers", [])
    for trigger in triggers:
        if trigger.get("event") == "OnDemand":
            label = trigger.get("label", "")
            description = trigger.get("description", "")
            if label:
                actions.append(OnDemandActionInfo(label=label, description=description))

    return actions


# === ENDPOINT DE COMANDOS OS (remote_commands + downloadable_files) ===

@router.get("/{workstation_id}/os-commands")
def get_os_commands(
    workstation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener comandos remotos y archivos descargables definidos en el config efectivo.

    Extrae los campos `remote_commands` y `downloadable_files` del alwaysconfig
    de la workstation (con herencia organizacional).

    Returns:
        Dict con commands: [{label, command, description}] y files: [{label, path, description}]
    """
    import json

    # Verificar que la workstation existe
    workstation = db.query(Workstation).filter(Workstation.id == workstation_id).first()
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workstation no encontrada"
        )

    # Tenant isolation
    if current_user.role != UserRole.ADMIN:
        if current_user.organization_id != workstation.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Sin permiso para ver esta workstation"
            )

    # Resolver config efectivo
    from app.services.action_config import ActionConfigService
    config = ActionConfigService.resolve_effective_config(db, workstation.id)

    if not config:
        return {"commands": [], "files": []}

    # Parsear config_json
    try:
        config_data = json.loads(config.config_json)
    except json.JSONDecodeError:
        return {"commands": [], "files": []}

    # Extraer remote_commands y downloadable_files
    commands = []
    for cmd in config_data.get("remote_commands", []):
        commands.append({
            "label": cmd.get("label", ""),
            "command": cmd.get("command", ""),
            "description": cmd.get("description", ""),
        })

    files = []
    for f in config_data.get("downloadable_files", []):
        files.append({
            "label": f.get("label", ""),
            "path": f.get("path", ""),
            "description": f.get("description", ""),
        })

    return {"commands": commands, "files": files}


# === ENDPOINT DE COMANDOS REMOTOS ===

@router.post("/{workstation_id}/command",
             response_model=CommandResponse,
             status_code=status.HTTP_200_OK,
             responses={
                 200: {"description": "Comando enviado exitosamente"},
                 404: {"description": "Workstation no encontrada"},
                 409: {"description": "Workstation offline, no se puede enviar comando"},
             })
async def send_command(
    workstation_id: UUID,
    command_data: CommandRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Enviar un comando remoto a una workstation conectada vía WebSocket.
    
    Comandos soportados:
    - restart_service: Reinicia el servicio AlwaysPrintService en la workstation
    - restart_tray: Reinicia la aplicación Tray (el Service la relanza automáticamente)
    - check_update: Fuerza verificación de actualización disponible
    
    Requiere autenticación de administrador u operador.
    Si la workstation está offline, retorna 409 Conflict.
    
    Args:
        workstation_id: ID de la workstation destino
        command_data: Tipo de comando y parámetros opcionales
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        CommandResponse con el command_id generado y estado "sent"
    
    Raises:
        HTTPException 404: Workstation no encontrada
        HTTPException 409: Workstation offline
    """
    # Verificar que la workstation existe
    workstation = db.query(Workstation).filter(Workstation.id == workstation_id).first()
    
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )
    
    # Verificar permisos: operadores solo pueden enviar comandos a workstations de su cuenta
    if current_user.role == UserRole.OPERATOR:
        if workstation.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para enviar comandos a esta workstation"
            )
    
    # Verificar que la workstation está online
    workstation_id_str = str(workstation_id)
    if not connection_manager.is_workstation_online(workstation_id_str):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La workstation está offline. No se puede enviar el comando."
        )
    
    # Validar tipo de comando
    valid_commands = ["restart_service", "restart_tray", "check_update", "execute_on_demand"]
    if command_data.command_type not in valid_commands:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Tipo de comando inválido: {command_data.command_type}. "
                   f"Comandos válidos: {', '.join(valid_commands)}"
        )
    
    # Validación específica para execute_on_demand: verificar que el label existe en config efectivo
    if command_data.command_type == "execute_on_demand":
        import json
        label = command_data.params.get("label")
        if not label:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="El parámetro 'label' es requerido para execute_on_demand"
            )
        
        from app.services.action_config import ActionConfigService
        config = ActionConfigService.resolve_effective_config(db, workstation.id)
        
        if not config:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"La workstation no tiene configuración de acciones activa"
            )
        
        # Verificar que el label existe entre los triggers OnDemand
        try:
            config_data = json.loads(config.config_json)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="La configuración de acciones tiene un formato JSON inválido"
            )
        
        triggers = config_data.get("triggers", [])
        valid_labels = [
            t.get("label") for t in triggers
            if t.get("event") == "OnDemand" and t.get("label")
        ]
        
        if label not in valid_labels:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"La acción OnDemand '{label}' no existe en la configuración efectiva de esta workstation"
            )
    
    # Generar ID único para el comando
    command_id = str(uuid.uuid4())
    
    # Enviar comando vía WebSocket
    message = {
        "type": "command",
        "command_id": command_id,
        "command_type": command_data.command_type,
        "params": command_data.params
    }
    
    # Para execute_on_demand: registrar waiter antes de enviar para esperar respuesta
    if command_data.command_type == "execute_on_demand":
        connection_manager.register_command_waiter(command_id)
    
    sent = await connection_manager.send_to_workstation(workstation_id_str, message)
    
    if not sent:
        # La workstation se desconectó entre la verificación y el envío
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La workstation se desconectó antes de recibir el comando."
        )
    
    logger.info(
        f"[COMANDO] Comando enviado: command_id={command_id}, "
        f"command_type={command_data.command_type}, "
        f"workstation_id={workstation_id}, "
        f"enviado_por={current_user.email}"
    )
    
    # Para execute_on_demand: esperar respuesta con timeout de 120s y registrar auditoría
    if command_data.command_type == "execute_on_demand":
        response_data = await connection_manager.wait_for_command_response(
            command_id, timeout=120.0
        )
        
        # Registrar AuditLog con resultado (éxito o timeout)
        from app.models.audit import ActionType
        audit_service = AuditService()
        
        success = response_data.get("success", False) if response_data else False
        duration_ms = response_data.get("duration_ms") if response_data else None
        result_message = response_data.get("message", "") if response_data else "Timeout"
        
        audit_service.log_action(
            db=db,
            action_type=ActionType.ONDEMAND_EXECUTED,
            entity_type="workstation",
            entity_id=str(workstation_id),
            user_id=str(current_user.id),
            organization_id=str(workstation.organization_id),
            new_values={
                "label": command_data.params.get("label"),
                "command_id": command_id,
                "success": success,
                "duration_ms": duration_ms,
                "message": result_message,
            }
        )
        
        if response_data is None:
            raise HTTPException(
                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                detail="Timeout esperando respuesta de la workstation (120s). La acción puede seguir ejecutándose."
            )
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"La acción OnDemand falló: {result_message}"
            )
        
        return CommandResponse(command_id=command_id, status="completed")
    
    return CommandResponse(command_id=command_id, status="sent")


# === ENDPOINT DE DESCARGA DE LOGS ===

@router.get("/{workstation_id}/logs/download",
            status_code=status.HTTP_200_OK,
            responses={
                200: {"description": "Contenido del último archivo de log"},
                404: {"description": "Workstation no encontrada"},
                408: {"description": "Timeout esperando respuesta de la workstation"},
                409: {"description": "Workstation offline"},
                422: {"description": "Versión del Tray incompatible"},
                500: {"description": "Error al obtener el log"},
            })
async def download_latest_log(
    workstation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Solicita y descarga el último archivo de log de una workstation online.
    
    Envía un comando 'get_latest_log' a la workstation vía WebSocket,
    espera la respuesta con el contenido del archivo y lo retorna como descarga.
    
    La workstation lee el último archivo de C:\\ProgramData\\AlwaysPrint\\logs
    y envía su contenido codificado en base64.
    
    Args:
        workstation_id: ID de la workstation
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        Response con el contenido del archivo de log como descarga
    
    Raises:
        HTTPException 404: Workstation no encontrada
        HTTPException 408: Timeout esperando respuesta
        HTTPException 409: Workstation offline
        HTTPException 500: Error al obtener el log
    """
    import base64
    from fastapi.responses import Response
    
    # Verificar que la workstation existe
    workstation = db.query(Workstation).filter(Workstation.id == workstation_id).first()
    
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )
    
    # Verificar permisos
    if current_user.role == UserRole.OPERATOR:
        if workstation.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para acceder a los logs de esta workstation"
            )
    
    # Verificar compatibilidad de versión del Tray
    # El comando get_latest_log requiere Tray >= 1.26.519.550
    MIN_LOG_DOWNLOAD_VERSION = "1.26.519.550"
    if workstation.tray_version:
        try:
            # Comparar versiones (formato: "X.Y.Z.W")
            ws_parts = [int(p) for p in workstation.tray_version.split(".")]
            min_parts = [int(p) for p in MIN_LOG_DOWNLOAD_VERSION.split(".")]
            # Rellenar con ceros si tienen diferente longitud
            max_len = max(len(ws_parts), len(min_parts))
            ws_parts.extend([0] * (max_len - len(ws_parts)))
            min_parts.extend([0] * (max_len - len(min_parts)))
            if ws_parts < min_parts:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"La workstation tiene Tray v{workstation.tray_version} "
                        f"pero se requiere v{MIN_LOG_DOWNLOAD_VERSION} o superior "
                        f"para descargar logs remotamente. "
                        f"Actualice el Tray de esta workstation para habilitar esta función."
                    )
                )
        except (ValueError, AttributeError):
            # Si no se puede parsear la versión, continuar (no bloquear)
            logger.warning(
                f"[LOGS] No se pudo parsear tray_version='{workstation.tray_version}' "
                f"de workstation_id={workstation_id}"
            )

    # Verificar que la workstation está online
    workstation_id_str = str(workstation_id)
    if not connection_manager.is_workstation_online(workstation_id_str):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La workstation está offline. No se puede obtener el log."
        )
    
    # Generar ID único para el comando
    command_id = str(uuid.uuid4())
    
    # Registrar waiter ANTES de enviar el comando
    connection_manager.register_command_waiter(command_id)
    
    # Enviar comando vía WebSocket
    message = {
        "type": "command",
        "command_id": command_id,
        "command_type": "get_latest_log",
        "params": {}
    }
    
    logger.info(
        f"[LOGS] Enviando get_latest_log: workstation_id={workstation_id}, command_id={command_id}"
    )
    
    sent = await connection_manager.send_to_workstation(workstation_id_str, message)
    
    if not sent:
        # Retry una vez: el primer fallo puede ser por registro stale en WorkerRegistry
        # que ya fue invalidado por send_to_workstation. El segundo intento resuelve
        # el worker correcto.
        logger.info(
            f"[LOGS] Primer intento falló (registro stale probable), reintentando: "
            f"workstation_id={workstation_id}, command_id={command_id}"
        )
        # Limpiar waiter del primer intento
        connection_manager._pending_command_responses.pop(command_id, None)
        
        # Pequeña espera para que la invalidación del registry se propague
        await asyncio.sleep(0.1)
        
        # Generar nuevo command_id para el retry
        command_id = str(uuid.uuid4())
        connection_manager.register_command_waiter(command_id)
        message["command_id"] = command_id
        
        sent = await connection_manager.send_to_workstation(workstation_id_str, message)
        if not sent:
            logger.warning(
                f"[LOGS] Segundo intento también falló: workstation_id={workstation_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La workstation se desconectó antes de recibir el comando."
            )
    
    logger.info(
        f"[LOGS] Comando enviado (sent=True), esperando respuesta: command_id={command_id}"
    )
    
    # Esperar respuesta con timeout de 30 segundos
    response_data = await connection_manager.wait_for_command_response(
        command_id, timeout=30.0
    )
    
    if response_data is None:
        logger.warning(
            f"[LOGS] TIMEOUT esperando respuesta: workstation_id={workstation_id}, command_id={command_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail="Timeout esperando respuesta de la workstation. Intente nuevamente."
        )
    
    if not response_data.get("success"):
        # Si es error de workstation no alcanzable (routing stale), dar mensaje claro
        error_type = response_data.get("error", "")
        if error_type == "workstation_not_reachable":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La workstation no está accesible en este momento. Intente nuevamente."
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en la workstation: {response_data.get('output', response_data.get('message', 'Error desconocido'))}"
        )
    
    # Decodificar contenido base64
    output = response_data.get("output", "")
    filename = response_data.get("filename", "alwaysprint.log")
    
    # El output puede ser el contenido en base64 o un JSON con filename y content
    try:
        # Intentar parsear como JSON (formato: {"filename": "...", "content": "base64..."})
        import json as json_module
        output_data = json_module.loads(output)
        if isinstance(output_data, dict):
            filename = output_data.get("filename", filename)
            content_b64 = output_data.get("content", "")
            file_content = base64.b64decode(content_b64)
        else:
            file_content = base64.b64decode(output)
    except (json_module.JSONDecodeError, ValueError):
        # Si no es JSON, asumir que es base64 directo
        try:
            file_content = base64.b64decode(output)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error decodificando el contenido del log recibido."
            )
    
    logger.info(
        f"[LOGS] Log descargado: workstation_id={workstation_id}, "
        f"filename={filename}, size={len(file_content)} bytes, "
        f"solicitado_por={current_user.email}"
    )
    
    # Retornar como descarga de archivo
    return Response(
        content=file_content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(file_content))
        }
    )


# === ENDPOINT DE REGISTRO (SIN AUTENTICACIÓN) ===

@router.post("/register", 
             response_model=WorkstationRegisterResponse,
             status_code=status.HTTP_201_CREATED,
             responses={
                 201: {"description": "Workstation registrada exitosamente"},
                 403: {"model": WorkstationRegisterPendingResponse, "description": "IP pública pendiente de autorización"},
                 500: {"description": "Error interno del servidor"}
             })
def register_workstation(
    request: Request,
    data: WorkstationRegisterRequest,
    db: Session = Depends(get_db)
):
    """
    Registrar una workstation nueva (endpoint sin autenticación).
    
    Este endpoint permite que workstations se registren automáticamente
    sin necesidad de credenciales previas.
    
    Flujo:
    1. Detecta la IP pública del cliente
    2. Verifica si la IP pública está autorizada
    3. Si NO autorizada: registra IP como pendiente y devuelve 403
    4. Si autorizada: crea workstation y devuelve credenciales
    
    Args:
        request: Request de FastAPI (para extraer IP)
        data: Datos de la workstation
        db: Sesión de base de datos
    
    Returns:
        WorkstationRegisterResponse: Credenciales si registro exitoso
        WorkstationRegisterPendingResponse: Info de espera si IP pendiente (403)
    
    Raises:
        HTTPException 403: IP pública no autorizada (pendiente)
        HTTPException 500: Error interno
    """
    # Detectar IP pública del cliente
    public_ip = get_client_ip(request)
    workstation_local_ip = get_workstation_local_ip(request)
    
    logger.info(
        f"[REGISTRO HTTP] Solicitud de registro recibida: "
        f"ip_private={data.ip_private}, "
        f"hostname={data.hostname}, "
        f"public_ip={public_ip}, "
        f"workstation_local_ip={workstation_local_ip}, "
        f"cidr={data.cidr}, "
        f"tray_version={data.tray_version}"
    )
    
    try:
        workstation_service = WorkstationService()
        
        # Intentar registrar workstation
        workstation, is_new, reg_status = workstation_service.register_workstation(
            db=db,
            ip_private=data.ip_private,
            public_ip=public_ip,
            hostname=data.hostname,
            os_serial=data.os_serial,
            current_user=data.current_user,
            cidr=data.cidr,
            tray_version=data.tray_version
        )
        
        if reg_status == "pending":
            # IP pública no autorizada
            logger.warning(
                f"[REGISTRO HTTP] IP pública no autorizada: {public_ip}. "
                f"Registro rechazado para ip_private={data.ip_private}"
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "status": "pending",
                    "public_ip": public_ip,
                    "message": (
                        f"Tu IP pública ({public_ip}) no está autorizada. "
                        "Un administrador debe autorizar esta IP antes de que puedas registrarte. "
                        "La IP ha sido registrada y está pendiente de autorización. "
                        "Por favor, reintenta en unos minutos."
                    ),
                    "retry_after_seconds": 300  # 5 minutos
                }
            )
        
        elif reg_status == "inactive_organization":
            # Cuenta desactivada
            logger.warning(
                f"[REGISTRO HTTP] Cuenta desactivada para IP pública: {public_ip}. "
                f"Registro rechazado para ip_private={data.ip_private}"
            )
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="La cuenta asociada a esta IP está desactivada."
            )
        
        elif reg_status == "authorized" and workstation:
            # Registro exitoso
            logger.info(
                f"[REGISTRO HTTP] Workstation registrada exitosamente: "
                f"id={workstation.id}, "
                f"ip_private={workstation.ip_private}, "
                f"hostname={workstation.hostname}, "
                f"organization_id={workstation.organization_id}, "
                f"is_new={is_new}"
            )
            
            # Obtener información de la organización
            from app.models.organization import Organization
            org = db.query(Organization).filter(Organization.id == workstation.organization_id).first()
            
            if not org:
                logger.error(
                    f"[REGISTRO HTTP] Organización no encontrada: {workstation.organization_id}"
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Error interno: organización no encontrada"
                )
            
            # Construir URL del servidor cloud
            # Siempre HTTPS en producción (nginx termina SSL)
            host = request.headers.get("Host", request.url.netloc)
            # Limpiar puerto si viene incluido (ej: host:8000)
            if ":" in host and not host.startswith("["):
                host = host.split(":")[0]
            cloud_api_url = f"https://{host}"
            
            logger.info(
                f"[REGISTRO HTTP] Devolviendo credenciales: "
                f"workstation_id={workstation.id}, "
                f"organization_id={org.id}, "
                f"organization_name={org.name}, "
                f"cloud_api_url={cloud_api_url}"
            )
            
            # Obtener cert_url si la org tiene certificado ECDSA (y firma no está pausada)
            cert_url = None
            cert_version = None
            from datetime import datetime, timezone
            signature_paused = (
                org.signature_paused_until is not None
                and org.signature_paused_until > datetime.now(timezone.utc).replace(tzinfo=None)
            )
            if org.ecdsa_cert_version and org.ecdsa_cert_version > 0 and org.ecdsa_cert_s3_key and not signature_paused:
                from app.services.s3_config_service import S3ConfigService
                cert_url = S3ConfigService().get_public_url(org.ecdsa_cert_s3_key)
                cert_version = org.ecdsa_cert_version
            
            return WorkstationRegisterResponse(
                workstation_id=workstation.id,
                organization_id=org.id,
                organization_name=org.name,
                message="Workstation registrada exitosamente" if is_new else "Workstation actualizada exitosamente",
                cloud_api_url=cloud_api_url,
                cert_url=cert_url,
                cert_version=cert_version
            )
        
        else:
            # Estado inesperado
            logger.error(
                f"[REGISTRO HTTP] Estado inesperado: reg_status={reg_status}, "
                f"workstation={workstation}"
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error interno al registrar workstation"
            )
    
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Log el error y devolver un error 500
        logger.error(
            f"[REGISTRO HTTP] Error inesperado al registrar workstation: {e}",
            exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al registrar workstation: {str(e)}"
        )


# === ENDPOINTS AUTENTICADOS ===

@router.get("/", response_model=WorkstationListResponse)
async def list_workstations(
    page: int = Query(1, ge=1, description="Número de página"),
    page_size: int = Query(50, ge=1, le=1000, description="Tamaño de página"),
    vlan_id: Optional[str] = Query(None, description="Filtrar por VLAN (UUID o 'none' para sin VLAN)"),
    organization_id: Optional[UUID] = Query(None, description="Filtrar por organización"),
    is_online: Optional[bool] = Query(None, description="Filtrar por estado online"),
    contingency_active: Optional[bool] = Query(None, description="Filtrar por contingencia activa"),
    search: Optional[str] = Query(None, description="Buscar por IP o hostname"),
    version_filter: Optional[str] = Query(None, description="Filtrar por versión: 'current' (última) o 'outdated' (anteriores)"),
    has_specific_config: Optional[bool] = Query(None, description="Filtrar workstations con action config propia (scope=workstation)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Listar workstations con filtros.
    
    - Admin: puede ver workstations de todas las organizaciones
    - Operador: solo puede ver workstations de su organización
    
    Args:
        page: Número de página
        page_size: Tamaño de página (1-100)
        vlan_id: Filtrar por VLAN opcional
        organization_id: Filtrar por organización opcional
        is_online: Filtrar por estado online opcional
        contingency_active: Filtrar por contingencia activa opcional
        search: Buscar por IP o hostname opcional
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        WorkstationListResponse con lista paginada de workstations
    """
    from sqlalchemy.orm import joinedload
    
    # Forzar que la sesión vea los datos más recientes (importante con SQLite y WebSockets concurrentes)
    db.expire_all()
    
    # Construir query base de filtros (sin joinedload para evitar problemas con count)
    base_query = db.query(Workstation)
    
    # Operadores solo pueden ver workstations de su cuenta
    if current_user.role == UserRole.OPERATOR:
        if not current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operador sin cuenta asignada"
            )
        base_query = base_query.filter(Workstation.organization_id == current_user.organization_id)
    
    # Filtrar por organización si se proporciona (solo Admin)
    if organization_id:
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo Admin puede filtrar por organización"
            )
        base_query = base_query.filter(Workstation.organization_id == organization_id)
    
    # Filtrar por VLAN si se proporciona
    if vlan_id:
        if vlan_id.lower() == 'none':
            # Filtrar workstations que NO tienen VLAN asignada
            base_query = base_query.filter(Workstation.vlan_id.is_(None))
        else:
            # Filtrar por VLAN específica (UUID)
            try:
                from uuid import UUID as PyUUID_vlan
                vlan_uuid = PyUUID_vlan(vlan_id)
                base_query = base_query.filter(Workstation.vlan_id == vlan_uuid)
            except (ValueError, AttributeError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"vlan_id inválido: '{vlan_id}'. Debe ser un UUID válido o 'none'."
                )
    
    # Obtener snapshot global de WS online (lectura fresca de Redis, cross-worker).
    from app.services.websocket_manager import connection_manager
    global_online = await connection_manager.get_global_online_snapshot_async()

    # Filtrar por estado online usando snapshot Redis (no BD stale).
    # Se aplica en SQL con IN/NOT IN para mantener paginación eficiente.
    if is_online is not None and global_online:
        # Convertir strings a UUIDs para match correcto con columna UUID de PostgreSQL
        from uuid import UUID as PyUUID
        online_uuids = set()
        for ws_id in global_online:
            try:
                online_uuids.add(PyUUID(ws_id) if not isinstance(ws_id, PyUUID) else ws_id)
            except (ValueError, AttributeError):
                pass
        if is_online:
            base_query = base_query.filter(Workstation.id.in_(online_uuids))
        else:
            base_query = base_query.filter(~Workstation.id.in_(online_uuids))
    elif is_online is not None and not global_online:
        # Snapshot vacío (Redis no disponible): fallback a BD
        base_query = base_query.filter(Workstation.is_online.is_(is_online))
    
    # Filtrar por contingencia activa si se proporciona
    if contingency_active is not None:
        base_query = base_query.filter(Workstation.contingency_active.is_(contingency_active))
    
    # Buscar por IP o hostname si se proporciona
    if search:
        base_query = base_query.filter(
            (Workstation.ip_private.ilike(f"%{search}%")) |
            (Workstation.hostname.ilike(f"%{search}%"))
        )
    
    # Filtrar por config específica (scope=workstation)
    if has_specific_config is not None:
        from app.models.action_config import ActionConfig, ActionConfigScope
        if has_specific_config:
            # Workstations que TIENEN action config propia activa
            ws_ids_with_config = (
                db.query(ActionConfig.workstation_id)
                .filter(
                    ActionConfig.scope == ActionConfigScope.WORKSTATION,
                    ActionConfig.is_active == True,
                    ActionConfig.workstation_id.isnot(None),
                )
                .subquery()
            )
            base_query = base_query.filter(Workstation.id.in_(ws_ids_with_config))
        else:
            # Workstations que NO tienen action config propia activa
            ws_ids_with_config = (
                db.query(ActionConfig.workstation_id)
                .filter(
                    ActionConfig.scope == ActionConfigScope.WORKSTATION,
                    ActionConfig.is_active == True,
                    ActionConfig.workstation_id.isnot(None),
                )
                .subquery()
            )
            base_query = base_query.filter(~Workstation.id.in_(ws_ids_with_config))
    
    # Filtrar por versión (current = última, outdated = anteriores)
    if version_filter in ("current", "outdated"):
        from app.models.organization import Organization
        
        def parse_version(v: str) -> tuple:
            """Parsear versión '1.26.702.2322' como tupla numérica para comparación correcta."""
            try:
                return tuple(int(x) for x in v.lstrip("v").split("."))
            except (ValueError, AttributeError):
                return (0,)
        
        # Determinar la versión latest global (max numérica de tray_version)
        all_versions = (
            db.query(Workstation.tray_version)
            .filter(Workstation.tray_version.isnot(None), Workstation.tray_version != "")
            .distinct()
            .all()
        )
        version_strings = [row[0] for row in all_versions if row[0]]
        latest_version = max(version_strings, key=parse_version) if version_strings else None
        
        # Obtener versiones pinneadas por organización
        pinned_orgs = (
            db.query(Organization.id, Organization.target_version)
            .filter(Organization.target_version.isnot(None), Organization.target_version != "")
            .all()
        )
        pinned_map = {org_id: tv for org_id, tv in pinned_orgs}  # {org_id: target_version}
        
        if latest_version or pinned_map:
            # Construir lista de IDs de workstations "vigentes":
            # - Si su org tiene pinned → tray_version == pinned
            # - Si su org NO tiene pinned → tray_version == latest_version
            from sqlalchemy import or_, and_
            
            current_conditions = []
            
            # Workstations de orgs SIN pinned: vigente si tray_version == latest
            if latest_version:
                pinned_org_ids = list(pinned_map.keys())
                if pinned_org_ids:
                    current_conditions.append(
                        and_(
                            Workstation.organization_id.notin_(pinned_org_ids),
                            Workstation.tray_version == latest_version
                        )
                    )
                else:
                    current_conditions.append(Workstation.tray_version == latest_version)
            
            # Workstations de orgs CON pinned: vigente si tray_version == target_version
            for org_id, target_ver in pinned_map.items():
                current_conditions.append(
                    and_(
                        Workstation.organization_id == org_id,
                        Workstation.tray_version == target_ver
                    )
                )
            
            if version_filter == "current":
                base_query = base_query.filter(or_(*current_conditions))
            else:
                # Outdated = tiene versión pero NO cumple ninguna condición de "vigente"
                base_query = base_query.filter(
                    Workstation.tray_version.isnot(None),
                    ~or_(*current_conditions)
                )
    
    # Contar total (sin joinedload para query limpia)
    total = base_query.count()
    
    # Paginar y cargar relaciones
    offset = (page - 1) * page_size
    workstations = (
        base_query
        .options(joinedload(Workstation.organization))
        .options(joinedload(Workstation.vlan))
        .order_by(Workstation.ip_private.asc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    
    # Enriquecer is_online con snapshot global (para items de esta página).
    # También obtener worker_id para cada WS online.
    ws_id_strs = [str(ws.id) for ws in workstations]
    worker_map = await connection_manager.get_worker_ids_for_workstations(ws_id_strs)

    for ws in workstations:
        ws_id_str = str(ws.id)
        real_online = ws_id_str in global_online
        if real_online != ws.is_online:
            ws.is_online = real_online
        # Inyectar worker_id como atributo transitorio para el response schema
        ws.worker_id = worker_map.get(ws_id_str)

    # Stats inline: conteo exacto basado en métricas de workers (len(workstation_connections))
    # Esto es más preciso que contar IDs del SUNIONSTORE que puede tener micro-gap del batch.
    all_ws_ids = {str(row[0]) for row in db.query(Workstation.id).all()}
    total_registered = len(all_ws_ids)
    global_metrics = await connection_manager.get_global_connection_count()
    online_count = min(global_metrics.get("workstations", 0), total_registered)
    offline_count = total_registered - online_count

    return WorkstationListResponse(
        items=workstations,
        total=total,
        skip=offset,
        limit=page_size,
        online_count=online_count,
        offline_count=offline_count,
    )


@router.get("/stats", response_model=WorkstationStatsResponse)
async def get_workstation_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener estadísticas de workstations.
    
    - Admin: estadísticas de todas las cuentas + desglose por cuenta
    - Operador: estadísticas de su cuenta
    
    Args:
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        WorkstationStatsResponse con estadísticas
    """
    try:
        # Forzar que la sesión vea los datos más recientes
        db.expire_all()
        
        workstation_service = WorkstationService()
        
        # Determinar organization_id según rol
        org_id = None
        if current_user.role in (UserRole.OPERATOR, UserRole.READONLY):
            if not current_user.organization_id:
                # Devolver estadísticas vacías si no tiene cuenta asignada
                return WorkstationStatsResponse(
                    total=0,
                    online=0,
                    offline=0,
                    contingency_active=0
                )
            org_id = str(current_user.organization_id) if current_user.organization_id else None
        
        # Obtener estadísticas generales
        total = workstation_service.get_total_count(db, org_id)
        online = workstation_service.get_online_count(db, org_id)
        contingency = workstation_service.get_contingency_count(db, org_id)

        # Corregir conteo online con snapshot real de WebSocket (cross-worker).
        # get_online_count() usa BD (puede estar stale); el snapshot es en tiempo real.
        from app.services.websocket_manager import connection_manager
        if not org_id:
            # Admin sin filtro: usar suma exacta de métricas de workers
            global_metrics = await connection_manager.get_global_connection_count()
            online = min(global_metrics.get("workstations", 0), total)
        else:
            # Con filtro por org: usar SUNIONSTORE + intersección con IDs de la org
            global_online = await connection_manager.get_global_online_snapshot_async()
            if global_online:
                all_ws_ids = {str(ws.id) for ws in db.query(Workstation.id).filter(
                    Workstation.organization_id == org_id).all()}
                online = len(global_online & all_ws_ids)
            # else: mantener valor de get_online_count() (BD)
        
        # Contar VLANs totales de la organización
        from app.models.vlan import VLAN
        if org_id:
            total_vlans = db.query(VLAN).filter(VLAN.organization_id == org_id).count()
            vlans_in_contingency = db.query(VLAN).filter(
                VLAN.organization_id == org_id,
                VLAN.forced_contingency == True
            ).count()
        else:
            # Admin: contar todas las VLANs
            total_vlans = db.query(VLAN).count()
            vlans_in_contingency = db.query(VLAN).filter(VLAN.forced_contingency == True).count()

        # Calcular VLANs sin dispositivos y con config
        from app.models.device import Device
        from sqlalchemy import func

        if org_id:
            all_vlans_query = db.query(VLAN).filter(VLAN.organization_id == org_id)
        else:
            all_vlans_query = db.query(VLAN)
        
        all_vlans_for_stats = all_vlans_query.all()
        vlans_without_devices = 0
        vlans_with_config = 0
        
        # IDs de VLANs que tienen una ActionConfig con scope=vlan activa
        from app.models.action_config import ActionConfig, ActionConfigScope
        vlan_ids_with_active_config = set(
            str(ac.vlan_id) for ac in db.query(ActionConfig.vlan_id).filter(
                ActionConfig.scope == ActionConfigScope.VLAN,
                ActionConfig.is_active == True,
                ActionConfig.vlan_id.isnot(None),
            ).all()
        )
        
        for v in all_vlans_for_stats:
            device_count = db.query(Device).filter(
                Device.vlan_id == v.id,
                Device.is_active == True
            ).count()
            if device_count == 0:
                vlans_without_devices += 1
            if str(v.id) in vlan_ids_with_active_config:
                vlans_with_config += 1

        # Preparar respuesta base
        response = WorkstationStatsResponse(
            total=total,
            online=online,
            offline=total - online,
            contingency_active=contingency,
            total_vlans=total_vlans,
            vlans_in_contingency=vlans_in_contingency,
            vlans_without_devices=vlans_without_devices,
            vlans_with_config=vlans_with_config,
        )
        
        # Si es admin, agregar estadísticas por cuenta
        if current_user.role == UserRole.ADMIN:
            from app.models.organization import Organization
            
            # Obtener todas las organizaciones
            organizations = db.query(Organization).all()
            
            by_organization = {}
            for org in organizations:
                try:
                    # Convertir org.id a string de manera segura
                    # El tipo GUID puede devolver UUID o str dependiendo del dialecto
                    if isinstance(org.id, uuid.UUID):
                        org_id_str = str(org.id)
                    elif isinstance(org.id, str):
                        org_id_str = org.id
                    else:
                        org_id_str = str(org.id)
                    
                    org_total = workstation_service.get_total_count(db, org_id_str)
                    org_online = workstation_service.get_online_count(db, org_id_str)
                    org_contingency = workstation_service.get_contingency_count(db, org_id_str)
                    
                    by_organization[org_id_str] = {
                        "name": org.name,
                        "total": org_total,
                        "online": org_online,
                        "offline": org_total - org_online,
                        "contingency": org_contingency
                    }
                except Exception as e:
                    # Si falla para una organización específica, continuar con las demás
                    print(f"Error al obtener estadísticas para organización {org.id}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            response.by_organization = by_organization
        
        # Generar resumen de VLANs (para operadores y admins con org_id)
        # Muestra: VLANs sin dispositivos, VLANs con config, workstations con config por VLAN
        target_org_id = None
        if current_user.role in (UserRole.OPERATOR, UserRole.READONLY):
            target_org_id = str(current_user.organization_id) if current_user.organization_id else None
        
        if target_org_id:
            from app.models.device import Device
            from app.models.action_config import ActionConfig, ActionConfigScope
            from app.schemas.workstation import VLANSummaryItem
            
            org_vlans = db.query(VLAN).filter(VLAN.organization_id == target_org_id).all()
            vlan_summary_list = []
            
            for v in org_vlans:
                vlan_id_str = str(v.id) if isinstance(v.id, uuid.UUID) else v.id
                
                # Contar dispositivos en la VLAN
                device_count = db.query(Device).filter(
                    Device.vlan_id == v.id,
                    Device.is_active == True
                ).count()
                
                # Contar workstations en la VLAN
                ws_count = db.query(Workstation).filter(
                    Workstation.vlan_id == v.id
                ).count()
                
                # Verificar si la VLAN tiene action config activa a su nivel
                has_vlan_config = db.query(ActionConfig).filter(
                    ActionConfig.organization_id == target_org_id,
                    ActionConfig.scope == ActionConfigScope.VLAN,
                    ActionConfig.vlan_id == v.id,
                    ActionConfig.is_active == True
                ).count() > 0
                
                # Contar workstations de esta VLAN que tienen action config propia
                ws_ids_in_vlan = [
                    ws.id for ws in db.query(Workstation.id).filter(
                        Workstation.vlan_id == v.id
                    ).all()
                ]
                ws_with_config = 0
                if ws_ids_in_vlan:
                    ws_with_config = db.query(ActionConfig).filter(
                        ActionConfig.organization_id == target_org_id,
                        ActionConfig.scope == ActionConfigScope.WORKSTATION,
                        ActionConfig.workstation_id.in_(ws_ids_in_vlan),
                        ActionConfig.is_active == True
                    ).count()
                
                vlan_summary_list.append(VLANSummaryItem(
                    id=vlan_id_str,
                    name=v.name,
                    has_devices=device_count > 0,
                    device_count=device_count,
                    workstation_count=ws_count,
                    has_vlan_config=has_vlan_config,
                    workstations_with_config=ws_with_config,
                    forced_contingency=v.forced_contingency or False,
                ))
            
            response.vlan_summary = vlan_summary_list
        
        # Agregar info de la organización para operadores
        if target_org_id:
            from app.models.organization import Organization
            from app.models.action_config import ActionConfig, ActionConfigScope
            from app.schemas.workstation import OrganizationInfo, WorkstationConfigItem
            
            org = db.query(Organization).filter(Organization.id == target_org_id).first()
            if org:
                # Verificar si tiene action config activa a nivel org
                has_org_config = db.query(ActionConfig).filter(
                    ActionConfig.organization_id == target_org_id,
                    ActionConfig.scope == ActionConfigScope.ORG,
                    ActionConfig.is_active == True
                ).count() > 0
                
                response.organization_info = OrganizationInfo(
                    id=str(org.id) if isinstance(org.id, uuid.UUID) else org.id,
                    name=org.name,
                    forced_contingency=org.forced_contingency or False,
                    has_org_config=has_org_config,
                    action_config_mandatory=org.action_config_mandatory or False,
                )
            
            # Obtener workstations con action config propia
            ws_configs = db.query(ActionConfig).filter(
                ActionConfig.organization_id == target_org_id,
                ActionConfig.scope == ActionConfigScope.WORKSTATION,
                ActionConfig.is_active == True,
                ActionConfig.workstation_id.isnot(None),
            ).all()
            
            if ws_configs:
                ws_config_items = []
                for ac in ws_configs:
                    ws = db.query(Workstation).filter(Workstation.id == ac.workstation_id).first()
                    if ws:
                        # Obtener nombre de VLAN si tiene
                        vlan_name = None
                        if ws.vlan_id:
                            vlan_obj = db.query(VLAN).filter(VLAN.id == ws.vlan_id).first()
                            if vlan_obj:
                                vlan_name = vlan_obj.name
                        ws_config_items.append(WorkstationConfigItem(
                            id=str(ws.id) if isinstance(ws.id, uuid.UUID) else ws.id,
                            ip_private=ws.ip_private,
                            hostname=ws.hostname,
                            vlan_name=vlan_name,
                            config_name=ac.name,
                        ))
                response.workstations_with_config = ws_config_items
        
        return response
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Log el error y devolver un error 500 con detalles
        print(f"Error en get_workstation_stats: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al obtener estadísticas: {str(e)}"
        )


@router.get("/{workstation_id}", response_model=WorkstationDetailResponse)
def get_workstation(
    workstation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener detalles de una workstation.
    
    - Admin: puede ver cualquier workstation
    - Operador: solo puede ver workstations de su cuenta
    
    Args:
        workstation_id: ID de la workstation
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        WorkstationDetailResponse con detalles completos
    
    Raises:
        HTTPException 403: Sin permisos
        HTTPException 404: Workstation no encontrada
    """
    from sqlalchemy.orm import joinedload
    
    workstation = db.query(Workstation).options(joinedload(Workstation.organization)).options(joinedload(Workstation.vlan)).filter(Workstation.id == workstation_id).first()
    
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )
    
    # Verificar permisos
    if current_user.role == UserRole.OPERATOR:
        if workstation.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para ver esta workstation"
            )
    
    return workstation


@router.put("/{workstation_id}", response_model=WorkstationResponse)
def update_workstation(
    request: Request,
    workstation_id: UUID,
    workstation_data: WorkstationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Actualizar información de una workstation.
    
    - Admin: puede actualizar cualquier workstation
    - Operador: solo puede actualizar workstations de su cuenta
    
    Args:
        workstation_id: ID de la workstation
        workstation_data: Datos a actualizar
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        WorkstationResponse con la workstation actualizada
    
    Raises:
        HTTPException 403: Sin permisos
        HTTPException 404: Workstation no encontrada
    """
    workstation = db.query(Workstation).filter(Workstation.id == workstation_id).first()
    
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )
    
    # Verificar permisos
    if current_user.role == UserRole.OPERATOR:
        if workstation.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para actualizar esta workstation"
            )
    
    # Guardar valores anteriores para auditoría
    old_values = {
        "hostname": workstation.hostname,
        "os_serial": workstation.os_serial,
        "current_user": workstation.current_user,
        "organization_id": str(workstation.organization_id) if workstation.organization_id else None
    }
    
    # Actualizar campos
    update_data = workstation_data.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(workstation, field, value)
    
    db.commit()
    db.refresh(workstation)
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_update(
        db=db,
        entity_type="workstation",
        entity_id=str(workstation.id),
        user_id=str(current_user.id),
        organization_id=str(workstation.organization_id) if workstation.organization_id else None,
        old_data=old_values,
        new_data=update_data,
        ip_address=get_client_ip(request)
    )
    
    return workstation


# === ENDPOINTS DE CONFIGURACIÓN ===


@router.put("/{workstation_id}/config", response_model=WorkstationConfigResponse)
def update_workstation_config(
    request: Request,
    workstation_id: UUID,
    config_data: WorkstationConfigUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Actualizar configuración específica de una workstation.
    
    Crea o actualiza un override de configuración para esta workstation.
    Los campos NULL heredan de VLANConfig o GlobalConfig.
    
    Args:
        workstation_id: ID de la workstation
        config_data: Datos de configuración a actualizar
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        WorkstationConfigResponse con la configuración actualizada
    
    Raises:
        HTTPException 403: Sin permisos
        HTTPException 404: Workstation no encontrada
    """
    workstation_service = WorkstationService()
    config_service = ConfigService()
    
    workstation = workstation_service.get_workstation_by_id(db, workstation_id)
    
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )
    
    # Verificar permisos
    if current_user.role == UserRole.OPERATOR:
        if workstation.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para actualizar la configuración de esta workstation"
            )
    
    # Actualizar configuración
    config = config_service.create_or_update_workstation_config(
        db=db,
        workstation_id=workstation_id,
        **config_data.model_dump(exclude_unset=True)
    )
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_config_change(
        db=db,
        entity_type="workstation_config",
        entity_id=str(workstation_id),
        user_id=str(current_user.id),
        organization_id=str(workstation.organization_id),
        old_config={},
        new_config=config_data.model_dump(exclude_unset=True),
        ip_address=get_client_ip(request)
    )
    
    return config


@router.patch("/{workstation_id}/forced-contingency")
async def toggle_workstation_forced_contingency(
    workstation_id: UUID,
    enabled: bool = Query(..., description="Activar o desactivar contingencia forzada"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Activar o desactivar contingencia forzada para una workstation individual.
    """
    workstation = db.query(Workstation).filter(Workstation.id == workstation_id).first()

    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )

    if current_user.role == UserRole.OPERATOR:
        if workstation.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para modificar esta workstation"
            )

    # Bloquear desactivación individual si la VLAN tiene contingencia forzada activa
    if not enabled and workstation.vlan_id:
        from app.models.vlan import VLAN
        vlan = db.query(VLAN).filter(VLAN.id == workstation.vlan_id).first()
        if vlan and vlan.forced_contingency:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No se puede desactivar contingencia individual: la VLAN tiene contingencia forzada activa"
            )

    # Resolver printer_ip ANTES de modificar estado o hacer commit
    # 1. Favorita (default_printer_id) si existe
    # 2. Primer dispositivo activo en la VLAN si no hay favorita
    printer_ip = None
    from app.models.device import Device
    if workstation.default_printer_id:
        printer = db.query(Device).filter(Device.id == workstation.default_printer_id).first()
        if printer:
            printer_ip = printer.ip_address

    if not printer_ip and workstation.vlan_id:
        # Fallback: primer dispositivo activo en la VLAN
        first_device = db.query(Device).filter(
            Device.organization_id == workstation.organization_id,
            Device.vlan_id == workstation.vlan_id,
            Device.is_active == True
        ).order_by(Device.ip_address).first()
        if first_device:
            printer_ip = first_device.ip_address

    # Validación: si se activa contingencia y no hay IP resoluble, rechazar
    if enabled and printer_ip is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se puede activar contingencia: no hay dispositivo de impresión disponible"
        )

    workstation.forced_contingency = enabled
    db.commit()
    db.refresh(workstation)

    logger.info(
        "Contingencia forzada workstation actualizada: workstation_id=%s, enabled=%s, user_id=%s",
        workstation_id, enabled, current_user.id,
    )

    # Notificar a la workstation si está online
    workstation_id_str = str(workstation_id)
    if connection_manager.is_workstation_online(workstation_id_str):
        message = {
            "type": "forced_contingency",
            "enabled": enabled,
            "source": "workstation",
            "source_name": workstation.hostname or workstation.ip_private,
            "printer_ip": printer_ip,
        }
        await connection_manager.send_to_workstation(workstation_id_str, message)

    return {
        "forced_contingency": workstation.forced_contingency,
        "workstation_id": str(workstation.id),
        "updated_at": workstation.updated_at,
    }


@router.delete("/{workstation_id}/config", status_code=status.HTTP_204_NO_CONTENT)
def delete_workstation_config(
    request: Request,
    workstation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Eliminar override de configuración de una workstation.
    
    Después de eliminar, la workstation heredará configuración de VLAN o Global.
    
    Args:
        workstation_id: ID de la workstation
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Raises:
        HTTPException 403: Sin permisos
        HTTPException 404: Workstation no encontrada
    """
    workstation_service = WorkstationService()
    config_service = ConfigService()
    
    workstation = workstation_service.get_workstation_by_id(db, workstation_id)
    
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )
    
    # Verificar permisos
    if current_user.role == UserRole.OPERATOR:
        if workstation.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para eliminar la configuración de esta workstation"
            )
    
    # Eliminar configuración
    config_service.delete_workstation_config(db, workstation_id)
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_config_change(
        db=db,
        entity_type="workstation_config",
        entity_id=str(workstation_id),
        user_id=str(current_user.id),
        organization_id=str(workstation.organization_id),
        old_config={"action": "config_deleted"},
        new_config={},
        ip_address=get_client_ip(request)
    )
    
    return None


@router.delete("/{workstation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workstation(
    request: Request,
    workstation_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Eliminar una workstation del sistema.
    
    - Admin: puede eliminar cualquier workstation
    - Operador: solo puede eliminar workstations de su cuenta
    
    Elimina la workstation y todos sus datos asociados (telemetría, conectividad, licencias).
    
    Args:
        workstation_id: ID de la workstation a eliminar
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Raises:
        HTTPException 403: Sin permisos
        HTTPException 404: Workstation no encontrada
    """
    workstation = db.query(Workstation).filter(Workstation.id == workstation_id).first()
    
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )
    
    # Verificar permisos
    if current_user.role == UserRole.OPERATOR:
        if workstation.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para eliminar esta workstation"
            )
    
    # Guardar datos para auditoría
    old_data = {
        "ip_private": workstation.ip_private,
        "hostname": workstation.hostname,
        "organization_id": str(workstation.organization_id) if workstation.organization_id else None,
    }
    
    # Eliminar workstation (cascade elimina relaciones)
    db.delete(workstation)
    db.commit()
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_action(
        db=db,
        action_type="delete",
        entity_type="Workstation",
        entity_id=str(workstation_id),
        user_id=str(current_user.id),
        organization_id=old_data["organization_id"],
        old_values=old_data,
        new_values={},
        ip_address=get_client_ip(request)
    )
    
    return None


# === ENDPOINT DE RECURSOS (CONTINGENCIA) ===

class ContingencyPrinterResource(BaseModel):
    """Schema de impresora de contingencia para el recurso."""
    id: UUID
    name: str
    ip_address: str
    port: int = 9100
    is_default: bool = False


class WorkstationResourcesResponse(BaseModel):
    """
    Schema de respuesta para recursos de una workstation.
    
    Contiene la información necesaria para que el cliente opere
    en modo contingencia y en modo normal (LPM).
    """
    remote_queue_path: Optional[str] = Field(
        None, description="Ruta UNC de la cola remota del print server (de VLAN metadata)"
    )
    vlan_metadata: Optional[dict] = Field(
        None, description="Metadatos completos de la VLAN"
    )
    contingency_printers: list[ContingencyPrinterResource] = Field(
        default_factory=list, description="Impresoras de contingencia disponibles en la VLAN"
    )


@router.get("/{workstation_id}/resources",
            response_model=WorkstationResourcesResponse,
            status_code=status.HTTP_200_OK,
            responses={
                200: {"description": "Recursos de la workstation obtenidos exitosamente"},
                404: {"description": "Workstation no encontrada"},
            })
def get_workstation_resources(
    workstation_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Obtener recursos de contingencia para una workstation.
    
    Este endpoint NO requiere autenticación Bearer (usa workstation_id como identificación,
    similar al endpoint de action config). Permite que el Tray descargue recursos
    usando solo su workstation_id como X-API-Key.
    
    Retorna la información necesaria para que el cliente descargue
    y almacene en resources.json:
    - remote_queue_path: ruta UNC de la cola del print server (desde VLAN metadata)
    - vlan_metadata: todos los metadatos de la VLAN
    - contingency_printers: dispositivos activos en la VLAN de la workstation
    
    La workstation descarga este recurso periódicamente y lo almacena
    en C:\\ProgramData\\AlwaysPrint\\config\\resources.json para uso offline.
    
    Args:
        workstation_id: ID de la workstation
        current_user: Usuario autenticado
        db: Sesión de base de datos
    
    Returns:
        WorkstationResourcesResponse con recursos de contingencia
    
    Raises:
        HTTPException 404: Workstation no encontrada
    """
    from app.models.vlan import VLAN
    from app.models.device import Device

    # Verificar que la workstation existe
    workstation = db.query(Workstation).filter(Workstation.id == workstation_id).first()

    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )

    # Obtener VLAN de la workstation
    vlan_metadata = None
    remote_queue_path = None
    contingency_printers = []

    if workstation.vlan_id:
        vlan = db.query(VLAN).filter(VLAN.id == workstation.vlan_id).first()

        if vlan:
            # Extraer metadata de la VLAN
            vlan_metadata = vlan.vlan_metadata
            if vlan_metadata and isinstance(vlan_metadata, dict):
                remote_queue_path = vlan_metadata.get("remote_queue_path")

            # Obtener dispositivos activos de la VLAN (impresoras de contingencia)
            devices = (
                db.query(Device)
                .filter(
                    Device.vlan_id == vlan.id,
                    Device.is_active.is_(True)
                )
                .all()
            )

            for device in devices:
                # Marcar como default si coincide con el default_printer_id de la workstation
                is_default = (
                    workstation.default_printer_id is not None
                    and str(device.id) == str(workstation.default_printer_id)
                )
                contingency_printers.append(
                    ContingencyPrinterResource(
                        id=device.id,
                        name=device.name,
                        ip_address=device.ip_address,
                        port=device.port,
                        is_default=is_default
                    )
                )

    logger.info(
        f"[RECURSOS] Recursos obtenidos: workstation_id={workstation_id}, "
        f"vlan_id={workstation.vlan_id}, "
        f"remote_queue_path={remote_queue_path}, "
        f"contingency_printers={len(contingency_printers)}"
    )

    return WorkstationResourcesResponse(
        remote_queue_path=remote_queue_path,
        vlan_metadata=vlan_metadata,
        contingency_printers=contingency_printers
    )


# === ENDPOINT DE ESTADO DE DISTRIBUCIÓN (PUSH-BASED) ===


class DistributionStateResponse(BaseModel):
    """
    Estado de distribución completo para una workstation.
    Usado como fallback HTTP cuando la workstation no tiene estado cacheado
    (primer inicio o reconexión pendiente).
    """
    config_hash: Optional[str] = Field(None, description="Hash SHA256 corto (8 chars) de la config activa")
    config_s3_url: Optional[str] = Field(None, description="URL pública S3 del archivo .signed")
    cert_version: int = Field(0, description="Versión del certificado ECDSA (0 = sin cert)")
    cert_url: Optional[str] = Field(None, description="URL pública S3 del certificado .cer")
    msi_version: Optional[str] = Field(None, description="Versión target del MSI")
    msi_url: Optional[str] = Field(None, description="Presigned URL S3 del MSI")


@router.get(
    "/{workstation_id}/distribution-state",
    response_model=DistributionStateResponse,
    summary="Estado de distribución para verificación manual",
    description=(
        "Retorna el estado de distribución (config, cert, MSI) para una workstation. "
        "Usado como fallback HTTP cuando el cliente no tiene estado cacheado del WebSocket."
    ),
    responses={
        200: {"description": "Estado de distribución obtenido exitosamente"},
        404: {"description": "Workstation no encontrada"},
    }
)
async def get_distribution_state(
    workstation_id: str,
    db: Session = Depends(get_db)
):
    """
    Obtiene el estado de distribución completo para una workstation.

    Flujo:
    1. Consulta el StateMapService (zero queries a BD si ya está cargado).
    2. Si el state map no tiene datos de la org, carga desde BD una sola vez.
    3. Resuelve por scope (org > vlan > workstation) y retorna.

    Este endpoint NO requiere autenticación (usa workstation_id como identificación).
    Se usa como un solo request HTTP de fallback cuando la workstation no tiene
    estado cacheado del registro enriquecido (primer inicio, reconexión pendiente).
    """
    # Buscar workstation en BD para obtener org_id y vlan_id
    workstation = db.query(Workstation).filter(
        Workstation.id == workstation_id
    ).first()

    if not workstation:
        logger.warning(
            f"[DISTRIBUTION_STATE] Workstation no encontrada: id={workstation_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workstation no encontrada"
        )

    org_id_str = str(workstation.organization_id)
    vlan_id_str = str(workstation.vlan_id) if workstation.vlan_id else None

    # Intentar resolver desde StateMapService (zero queries adicionales si ya cargado)
    try:
        from app.services.push_services import get_state_map_service
        state_map = get_state_map_service()

        if state_map is not None:
            ws_state = await state_map.resolve_workstation_state(
                org_id=org_id_str,
                vlan_id=vlan_id_str,
                ws_id=workstation_id
            )

            # Si no hay datos en el state map, cargar desde BD
            if ws_state is None or not any([
                ws_state.get("config_hash"),
                ws_state.get("cert_version"),
                ws_state.get("msi_version"),
            ]):
                await state_map._load_org_state(org_id=org_id_str)
                ws_state = await state_map.resolve_workstation_state(
                    org_id=org_id_str,
                    vlan_id=vlan_id_str,
                    ws_id=workstation_id
                )

            if ws_state is not None:
                logger.info(
                    f"[DISTRIBUTION_STATE] Estado resuelto desde StateMapService para ws={workstation_id}"
                )
                return DistributionStateResponse(
                    config_hash=ws_state.get("config_hash"),
                    config_s3_url=ws_state.get("config_s3_url"),
                    cert_version=ws_state.get("cert_version", 0),
                    cert_url=ws_state.get("cert_url"),
                    msi_version=ws_state.get("msi_version"),
                    msi_url=ws_state.get("msi_url"),
                )
    except Exception as e:
        logger.warning(
            f"[DISTRIBUTION_STATE] Error consultando StateMapService para ws={workstation_id}: {e}. "
            "Fallback a consulta directa de BD."
        )

    # Fallback: consultar BD directamente si StateMapService no está disponible
    from app.models.organization import Organization
    from app.models.action_config import ActionConfig
    from app.services.action_config import ActionConfigService

    org = db.query(Organization).filter(
        Organization.id == workstation.organization_id
    ).first()

    if not org:
        logger.warning(
            f"[DISTRIBUTION_STATE] Organización no encontrada para ws={workstation_id}"
        )
        return DistributionStateResponse()

    # Resolver configuración efectiva (con herencia de scope)
    config = ActionConfigService.resolve_effective_config(db, workstation.id)

    config_hash = None
    config_s3_url = None
    if config and config.config_hash and config.storage_path:
        config_hash = config.config_hash
        from app.services.s3_config_service import S3ConfigService
        config_s3_url = S3ConfigService().get_public_url(config.storage_path)

    # Certificado (respetar pausa temporal de firma)
    from datetime import datetime, timezone as _tz
    _sig_paused = (
        org.signature_paused_until is not None
        and org.signature_paused_until > datetime.now(_tz.utc).replace(tzinfo=None)
    )
    cert_version = 0 if _sig_paused else (org.ecdsa_cert_version or 0)
    cert_url = None
    if cert_version > 0 and org.ecdsa_cert_s3_key:
        from app.services.s3_config_service import S3ConfigService
        cert_url = S3ConfigService().get_public_url(org.ecdsa_cert_s3_key)

    # MSI
    msi_version = org.target_version if hasattr(org, 'target_version') else None
    msi_url = None

    # Si auto_update está habilitado, resolver versión target (explícita o latest de S3)
    if hasattr(org, 'auto_update_enabled') and org.auto_update_enabled:
        try:
            from app.services.s3_update_service import S3UpdateService
            s3_service = S3UpdateService()

            if msi_version:
                # Versión explícita: generar URL para esa versión
                s3_key = f"versions/{msi_version}/AlwaysPrint.msi"
                msi_url = s3_service.generate_download_url(key=s3_key, expires_in=3600)
            else:
                # Sin target_version: usar latest de S3
                metadata = s3_service.get_msi_metadata()
                if metadata and metadata.get("version"):
                    msi_version = metadata["version"]
                    msi_url = s3_service.generate_download_url(expires_in=3600)
        except Exception as e:
            logger.warning(
                f"[DISTRIBUTION_STATE] Error resolviendo MSI: {e}"
            )

    logger.info(
        f"[DISTRIBUTION_STATE] Estado resuelto desde BD para ws={workstation_id}. "
        f"config_hash={config_hash}, cert_version={cert_version}, msi_version={msi_version}"
    )

    return DistributionStateResponse(
        config_hash=config_hash,
        config_s3_url=config_s3_url,
        cert_version=cert_version,
        cert_url=cert_url,
        msi_version=msi_version,
        msi_url=msi_url,
    )
