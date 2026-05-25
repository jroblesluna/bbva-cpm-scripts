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
    valid_commands = ["restart_service", "restart_tray", "check_update"]
    if command_data.command_type not in valid_commands:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Tipo de comando inválido: {command_data.command_type}. "
                   f"Comandos válidos: {', '.join(valid_commands)}"
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
    
    sent = await connection_manager.send_to_workstation(workstation_id_str, message)
    
    if not sent:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La workstation se desconectó antes de recibir el comando."
        )
    
    # Esperar respuesta con timeout de 30 segundos
    response_data = await connection_manager.wait_for_command_response(
        command_id, timeout=30.0
    )
    
    if response_data is None:
        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail="Timeout esperando respuesta de la workstation. Intente nuevamente."
        )
    
    if not response_data.get("success"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en la workstation: {response_data.get('output', 'Error desconocido')}"
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
            
            return WorkstationRegisterResponse(
                workstation_id=workstation.id,
                organization_id=org.id,
                organization_name=org.name,
                message="Workstation registrada exitosamente" if is_new else "Workstation actualizada exitosamente",
                cloud_api_url=cloud_api_url
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
def list_workstations(
    page: int = Query(1, ge=1, description="Número de página"),
    page_size: int = Query(50, ge=1, le=1000, description="Tamaño de página"),
    vlan_id: Optional[UUID] = Query(None, description="Filtrar por VLAN"),
    organization_id: Optional[UUID] = Query(None, description="Filtrar por organización"),
    is_online: Optional[bool] = Query(None, description="Filtrar por estado online"),
    contingency_active: Optional[bool] = Query(None, description="Filtrar por contingencia activa"),
    search: Optional[str] = Query(None, description="Buscar por IP o hostname"),
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
        base_query = base_query.filter(Workstation.vlan_id == vlan_id)
    
    # Filtrar por estado online si se proporciona
    if is_online is not None:
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
    
    # Contar total (sin joinedload para query limpia)
    total = base_query.count()
    
    # Paginar y cargar relaciones
    offset = (page - 1) * page_size
    workstations = (
        base_query
        .options(joinedload(Workstation.organization))
        .options(joinedload(Workstation.vlan))
        .offset(offset)
        .limit(page_size)
        .all()
    )
    
    return WorkstationListResponse(
        items=workstations,
        total=total,
        skip=offset,
        limit=page_size
    )


@router.get("/stats", response_model=WorkstationStatsResponse)
def get_workstation_stats(
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
        
        # Contar VLANs totales de la organización
        from app.models.vlan import VLAN
        if org_id:
            total_vlans = db.query(VLAN).filter(VLAN.organization_id == org_id).count()
        else:
            # Admin: contar todas las VLANs
            total_vlans = db.query(VLAN).count()
        
        # Preparar respuesta base
        response = WorkstationStatsResponse(
            total=total,
            online=online,
            offline=total - online,
            contingency_active=contingency,
            total_vlans=total_vlans
        )
        
        # Si es admin, agregar estadísticas por cuenta
        if current_user.role == UserRole.ADMIN:
            from app.models.organization import Organization
            import uuid
            
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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener recursos de contingencia para una workstation.
    
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

    # Verificar permisos: operadores solo pueden ver recursos de su cuenta
    if current_user.role == UserRole.OPERATOR:
        if workstation.organization_id != current_user.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para ver los recursos de esta workstation"
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
