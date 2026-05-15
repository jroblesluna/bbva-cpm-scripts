"""
Endpoints de gestión de workstations.

Este módulo define los endpoints para:
- Registro inicial de workstations (sin autenticación)
- Listado de workstations con filtros
- Actualización de workstations
- Gestión de configuración específica
- Estadísticas
"""

import logging
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
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

router = APIRouter()
logger = logging.getLogger(__name__)


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
        f"workstation_local_ip={workstation_local_ip}"
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
            current_user=data.current_user
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
        
        elif reg_status == "inactive_account":
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
                f"account_id={workstation.account_id}, "
                f"is_new={is_new}"
            )
            
            # Obtener información de la cuenta
            from app.models.account import Account
            account = db.query(Account).filter(Account.id == workstation.account_id).first()
            
            if not account:
                logger.error(
                    f"[REGISTRO HTTP] Cuenta no encontrada: {workstation.account_id}"
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Error interno: cuenta no encontrada"
                )
            
            # Construir URL del servidor cloud
            # Usar el host del request para construir la URL
            cloud_api_url = f"{request.url.scheme}://{request.url.netloc}"
            
            logger.info(
                f"[REGISTRO HTTP] Devolviendo credenciales: "
                f"workstation_id={workstation.id}, "
                f"account_id={account.id}, "
                f"account_name={account.name}, "
                f"cloud_api_url={cloud_api_url}"
            )
            
            return WorkstationRegisterResponse(
                workstation_id=workstation.id,
                account_id=account.id,
                account_name=account.name,
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
    account_id: Optional[UUID] = Query(None, description="Filtrar por cuenta"),
    is_online: Optional[bool] = Query(None, description="Filtrar por estado online"),
    contingency_active: Optional[bool] = Query(None, description="Filtrar por contingencia activa"),
    search: Optional[str] = Query(None, description="Buscar por IP o hostname"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Listar workstations con filtros.
    
    - Admin: puede ver workstations de todas las cuentas
    - Operador: solo puede ver workstations de su cuenta
    
    Args:
        page: Número de página
        page_size: Tamaño de página (1-100)
        vlan_id: Filtrar por VLAN opcional
        account_id: Filtrar por cuenta opcional
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
        if not current_user.account_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operador sin cuenta asignada"
            )
        base_query = base_query.filter(Workstation.account_id == current_user.account_id)
    
    # Filtrar por cuenta si se proporciona (solo Admin)
    if account_id:
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo Admin puede filtrar por cuenta"
            )
        base_query = base_query.filter(Workstation.account_id == account_id)
    
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
        .options(joinedload(Workstation.account))
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
        
        # Determinar account_id según rol
        account_id = None
        if current_user.role in (UserRole.OPERATOR, UserRole.READONLY):
            if not current_user.account_id:
                # Devolver estadísticas vacías si no tiene cuenta asignada
                return WorkstationStatsResponse(
                    total=0,
                    online=0,
                    offline=0,
                    contingency_active=0
                )
            account_id = str(current_user.account_id) if current_user.account_id else None
        
        # Obtener estadísticas generales
        total = workstation_service.get_total_count(db, account_id)
        online = workstation_service.get_online_count(db, account_id)
        contingency = workstation_service.get_contingency_count(db, account_id)
        
        # Contar VLANs totales de la organización
        from app.models.vlan import VLAN
        if account_id:
            total_vlans = db.query(VLAN).filter(VLAN.account_id == account_id).count()
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
            from app.models.account import Account
            import uuid
            
            # Obtener todas las cuentas
            accounts = db.query(Account).all()
            
            by_account = {}
            for account in accounts:
                try:
                    # Convertir account.id a string de manera segura
                    # El tipo GUID puede devolver UUID o str dependiendo del dialecto
                    if isinstance(account.id, uuid.UUID):
                        account_id_str = str(account.id)
                    elif isinstance(account.id, str):
                        account_id_str = account.id
                    else:
                        account_id_str = str(account.id)
                    
                    account_total = workstation_service.get_total_count(db, account_id_str)
                    account_online = workstation_service.get_online_count(db, account_id_str)
                    account_contingency = workstation_service.get_contingency_count(db, account_id_str)
                    
                    by_account[account_id_str] = {
                        "name": account.name,
                        "total": account_total,
                        "online": account_online,
                        "offline": account_total - account_online,
                        "contingency": account_contingency
                    }
                except Exception as e:
                    # Si falla para una cuenta específica, continuar con las demás
                    print(f"Error al obtener estadísticas para cuenta {account.id}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            response.by_account = by_account
        
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
    
    workstation = db.query(Workstation).options(joinedload(Workstation.account)).filter(Workstation.id == workstation_id).first()
    
    if not workstation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workstation con ID {workstation_id} no encontrada"
        )
    
    # Verificar permisos
    if current_user.role == UserRole.OPERATOR:
        if workstation.account_id != current_user.account_id:
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
        if workstation.account_id != current_user.account_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para actualizar esta workstation"
            )
    
    # Guardar valores anteriores para auditoría
    old_values = {
        "hostname": workstation.hostname,
        "os_serial": workstation.os_serial,
        "current_user": workstation.current_user,
        "account_id": str(workstation.account_id) if workstation.account_id else None
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
        account_id=str(workstation.account_id) if workstation.account_id else None,
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
        if workstation.account_id != current_user.account_id:
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
        account_id=str(workstation.account_id),
        old_config={},
        new_config=config_data.model_dump(exclude_unset=True),
        ip_address=get_client_ip(request)
    )
    
    return config


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
        if workstation.account_id != current_user.account_id:
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
        account_id=str(workstation.account_id),
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
        if workstation.account_id != current_user.account_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para eliminar esta workstation"
            )
    
    # Guardar datos para auditoría
    old_data = {
        "ip_private": workstation.ip_private,
        "hostname": workstation.hostname,
        "account_id": str(workstation.account_id) if workstation.account_id else None,
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
        account_id=old_data["account_id"],
        old_values=old_data,
        new_values={},
        ip_address=get_client_ip(request)
    )
    
    return None
