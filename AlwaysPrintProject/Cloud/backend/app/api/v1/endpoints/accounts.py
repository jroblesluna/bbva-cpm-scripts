"""
Endpoints de gestión de cuentas (solo Admin).

Este módulo define los endpoints para:
- CRUD de cuentas
- Gestión de IPs públicas
"""

from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.models.user import User, UserRole
from app.models.account import Account, PublicIP
from app.schemas import (
    AccountCreate,
    AccountUpdate,
    AccountResponse,
    AccountDetailResponse,
    AccountListResponse,
    PublicIPCreate,
    PublicIPResponse,
    PublicIPPendingResponse,
    PublicIPAuthorizeRequest,
)
from app.services.audit import AuditService

router = APIRouter()


@router.get("/", response_model=AccountListResponse)
def list_accounts(
    page: int = Query(1, ge=1, description="Número de página"),
    page_size: int = Query(50, ge=1, le=100, description="Tamaño de página"),
    search: Optional[str] = Query(None, description="Buscar por nombre"),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Listar todas las cuentas (solo Admin).
    
    Args:
        page: Número de página
        page_size: Tamaño de página (1-100)
        search: Término de búsqueda opcional
        current_user: Usuario autenticado (debe ser Admin)
        db: Sesión de base de datos
    
    Returns:
        AccountListResponse con lista paginada de cuentas
    """
    query = db.query(Account)
    
    # Filtrar por búsqueda si se proporciona
    if search:
        query = query.filter(Account.name.ilike(f"%{search}%"))
    
    # Contar total
    total = query.count()
    
    # Paginar
    offset = (page - 1) * page_size
    accounts = query.offset(offset).limit(page_size).all()
    
    return AccountListResponse(
        items=accounts,
        total=total,
        skip=offset,
        limit=page_size
    )


@router.post("/", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
def create_account(
    account_data: AccountCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Crear una nueva cuenta (solo Admin).
    
    Args:
        account_data: Datos de la cuenta a crear
        current_user: Usuario autenticado (debe ser Admin)
        db: Sesión de base de datos
    
    Returns:
        AccountResponse con la cuenta creada
    
    Raises:
        HTTPException 409: Cuenta con ese nombre ya existe
    """
    # Verificar que no exista una cuenta con el mismo nombre
    existing = db.query(Account).filter(Account.name == account_data.name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe una cuenta con el nombre '{account_data.name}'"
        )
    
    # Crear cuenta
    account = Account(
        name=account_data.name,
        description=account_data.description,
        timezone=account_data.timezone,
        language=account_data.language if account_data.language in ('en', 'es') else 'en',
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_create(
        db=db,
        entity_type="account",
        entity_id=str(account.id),
        user_id=str(current_user.id),
        account_id=str(account.id),
        entity_data={
            "name": account.name,
            "description": account.description,
            "timezone": account.timezone
        }
    )
    
    return account


@router.get("/{account_id}", response_model=AccountDetailResponse)
def get_account(
    account_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Obtener detalles de una cuenta (solo Admin).
    
    Args:
        account_id: ID de la cuenta
        current_user: Usuario autenticado (debe ser Admin)
        db: Sesión de base de datos
    
    Returns:
        AccountDetailResponse con detalles completos de la cuenta
    
    Raises:
        HTTPException 404: Cuenta no encontrada
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cuenta con ID {account_id} no encontrada"
        )
    
    # Contar usuarios y workstations
    user_count = len(account.users)
    workstation_count = len(account.workstations)
    
    # Crear respuesta detallada
    response = AccountDetailResponse(
        **account.__dict__,
        public_ips=[PublicIPResponse(**ip.__dict__) for ip in account.public_ips],
        user_count=user_count,
        workstation_count=workstation_count
    )
    
    return response


@router.put("/{account_id}", response_model=AccountResponse)
def update_account(
    account_id: UUID,
    account_data: AccountUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Actualizar una cuenta (solo Admin).
    
    Args:
        account_id: ID de la cuenta
        account_data: Datos a actualizar
        current_user: Usuario autenticado (debe ser Admin)
        db: Sesión de base de datos
    
    Returns:
        AccountResponse con la cuenta actualizada
    
    Raises:
        HTTPException 404: Cuenta no encontrada
        HTTPException 409: Nombre ya existe
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cuenta con ID {account_id} no encontrada"
        )
    
    # Guardar valores anteriores para auditoría
    old_values = {
        "name": account.name,
        "description": account.description,
        "timezone": account.timezone
    }
    
    # Actualizar campos
    update_data = account_data.model_dump(exclude_unset=True)
    
    # Verificar nombre único si se está actualizando
    if "name" in update_data and update_data["name"] != account.name:
        existing = db.query(Account).filter(Account.name == update_data["name"]).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe una cuenta con el nombre '{update_data['name']}'"
            )
    
    for field, value in update_data.items():
        setattr(account, field, value)
    
    db.commit()
    db.refresh(account)
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_update(
        db=db,
        entity_type="account",
        entity_id=str(account.id),
        user_id=str(current_user.id),
        account_id=str(account.id),
        old_data=old_values,
        new_data=update_data
    )
    
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    account_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Eliminar una cuenta (solo Admin).
    
    ADVERTENCIA: Esto eliminará en cascada todos los usuarios, workstations,
    VLANs y configuraciones asociadas a la cuenta.
    
    Args:
        account_id: ID de la cuenta
        current_user: Usuario autenticado (debe ser Admin)
        db: Sesión de base de datos
    
    Raises:
        HTTPException 404: Cuenta no encontrada
    """
    account = db.query(Account).filter(Account.id == account_id).first()
    
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cuenta con ID {account_id} no encontrada"
        )
    
    # Guardar valores para auditoría
    old_values = {
        "name": account.name,
        "description": account.description,
        "timezone": account.timezone
    }
    
    # Eliminar cuenta (cascada automática)
    db.delete(account)
    db.commit()
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_delete(
        db=db,
        entity_type="account",
        entity_id=str(account_id),
        user_id=str(current_user.id),
        account_id=str(account_id),
        entity_data=old_values
    )
    
    return None


# === ENDPOINTS DE IPS PÚBLICAS ===

@router.post("/{account_id}/public-ips", response_model=PublicIPResponse, status_code=status.HTTP_201_CREATED)
def add_public_ip(
    account_id: UUID,
    ip_data: PublicIPCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Agregar una IP pública a una cuenta (solo Admin).
    
    Args:
        account_id: ID de la cuenta
        ip_data: Datos de la IP pública
        current_user: Usuario autenticado (debe ser Admin)
        db: Sesión de base de datos
    
    Returns:
        PublicIPResponse con la IP creada
    
    Raises:
        HTTPException 404: Cuenta no encontrada
        HTTPException 409: IP ya existe
    """
    # Verificar que la cuenta existe
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cuenta con ID {account_id} no encontrada"
        )
    
    # Verificar que la IP no existe
    existing = db.query(PublicIP).filter(PublicIP.ip_address == ip_data.ip_address).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La IP {ip_data.ip_address} ya está registrada"
        )
    
    # Crear IP pública
    public_ip = PublicIP(
        account_id=account_id,
        ip_address=ip_data.ip_address,
        description=ip_data.description
    )
    db.add(public_ip)
    db.commit()
    db.refresh(public_ip)
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_create(
        db=db,
        entity_type="public_ip",
        entity_id=str(public_ip.id),
        user_id=str(current_user.id),
        account_id=str(account_id),
        entity_data={
            "ip_address": public_ip.ip_address,
            "description": public_ip.description
        }
    )
    
    return public_ip


@router.delete("/{account_id}/public-ips/{ip_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_public_ip(
    account_id: UUID,
    ip_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Eliminar una IP pública de una cuenta (solo Admin).
    
    Args:
        account_id: ID de la cuenta
        ip_id: ID de la IP pública
        current_user: Usuario autenticado (debe ser Admin)
        db: Sesión de base de datos
    
    Raises:
        HTTPException 404: Cuenta o IP no encontrada
    """
    # Verificar que la cuenta existe
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cuenta con ID {account_id} no encontrada"
        )
    
    # Buscar IP pública
    public_ip = db.query(PublicIP).filter(
        PublicIP.id == ip_id,
        PublicIP.account_id == account_id
    ).first()
    
    if not public_ip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"IP pública con ID {ip_id} no encontrada en la cuenta"
        )
    
    # Guardar valores para auditoría
    old_values = {
        "ip_address": public_ip.ip_address,
        "description": public_ip.description
    }
    
    # Eliminar IP
    db.delete(public_ip)
    db.commit()
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_delete(
        db=db,
        entity_type="public_ip",
        entity_id=str(ip_id),
        user_id=str(current_user.id),
        account_id=str(account_id),
        entity_data=old_values
    )
    
    return None


# === ENDPOINTS DE IPS PÚBLICAS PENDIENTES ===

@router.get("/public-ips/pending", response_model=list[PublicIPPendingResponse])
def list_pending_public_ips(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Listar IPs públicas pendientes de autorización (solo Admin).
    
    Estas son IPs desde las cuales clientes intentaron conectarse
    pero aún no han sido autorizadas y asignadas a una cuenta.
    
    Args:
        current_user: Usuario autenticado (debe ser Admin)
        db: Sesión de base de datos
    
    Returns:
        Lista de IPs públicas pendientes
    """
    pending_ips = db.query(PublicIP).filter(
        PublicIP.is_authorized == False
    ).order_by(PublicIP.first_seen.desc()).all()
    
    return pending_ips


@router.post("/public-ips/{ip_id}/authorize", response_model=PublicIPResponse)
def authorize_public_ip(
    ip_id: UUID,
    authorize_data: PublicIPAuthorizeRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Autorizar una IP pública y asignarla a una cuenta (solo Admin).
    
    Args:
        ip_id: ID de la IP pública pendiente
        authorize_data: Datos de autorización (account_id, descripción)
        current_user: Usuario autenticado (debe ser Admin)
        db: Sesión de base de datos
    
    Returns:
        PublicIPResponse con la IP autorizada
    
    Raises:
        HTTPException 404: IP no encontrada
        HTTPException 400: IP ya autorizada o cuenta no existe
    """
    from datetime import datetime
    
    # Buscar IP
    public_ip = db.query(PublicIP).filter(PublicIP.id == ip_id).first()
    
    if not public_ip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"IP pública con ID {ip_id} no encontrada"
        )
    
    if public_ip.is_authorized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta IP ya está autorizada"
        )
    
    # Verificar que la cuenta existe
    account = db.query(Account).filter(Account.id == authorize_data.account_id).first()
    
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cuenta con ID {authorize_data.account_id} no encontrada"
        )
    
    # Autorizar IP
    public_ip.is_authorized = True
    public_ip.account_id = authorize_data.account_id
    public_ip.authorized_at = datetime.utcnow()
    
    if authorize_data.description:
        public_ip.description = authorize_data.description
    
    db.commit()
    db.refresh(public_ip)
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_action(
        db=db,
        action_type="update",
        entity_type="PublicIP",
        entity_id=str(public_ip.id),
        user_id=str(current_user.id),
        account_id=str(authorize_data.account_id),
        old_values={"is_authorized": False, "account_id": None},
        new_values={"is_authorized": True, "account_id": str(authorize_data.account_id)}
    )
    
    return public_ip


@router.delete("/public-ips/{ip_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
def reject_public_ip(
    ip_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Rechazar y eliminar una IP pública pendiente (solo Admin).
    
    Args:
        ip_id: ID de la IP pública pendiente
        current_user: Usuario autenticado (debe ser Admin)
        db: Sesión de base de datos
    
    Raises:
        HTTPException 404: IP no encontrada
        HTTPException 400: IP ya autorizada (no se puede rechazar)
    """
    # Buscar IP
    public_ip = db.query(PublicIP).filter(PublicIP.id == ip_id).first()
    
    if not public_ip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"IP pública con ID {ip_id} no encontrada"
        )
    
    if public_ip.is_authorized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se puede rechazar una IP ya autorizada. Usa DELETE para eliminarla."
        )
    
    # Eliminar IP
    db.delete(public_ip)
    db.commit()
    
    # Registrar en auditoría
    audit_service = AuditService()
    audit_service.log_action(
        db=db,
        action_type="delete",
        entity_type="PublicIP",
        entity_id=str(public_ip.id),
        user_id=str(current_user.id),
        account_id=None,
        old_values={"ip_address": public_ip.ip_address, "is_authorized": False},
        new_values={}
    )
    
    return None
