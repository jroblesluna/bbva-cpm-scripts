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
)
from app.services.audit import AuditService

router = APIRouter()


@router.get("/", response_model=AccountListResponse)
async def list_accounts(
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
        total=total,
        page=page,
        page_size=page_size,
        accounts=accounts
    )


@router.post("/", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
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
        description=account_data.description
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    
    # Registrar en auditoría
    audit_service = AuditService()
    await audit_service.log_create(
        db=db,
        user_id=current_user.id,
        entity_type="account",
        entity_id=account.id,
        new_values={"name": account.name, "description": account.description}
    )
    
    return account


@router.get("/{account_id}", response_model=AccountDetailResponse)
async def get_account(
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
async def update_account(
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
    old_values = {"name": account.name, "description": account.description}
    
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
    await audit_service.log_update(
        db=db,
        user_id=current_user.id,
        entity_type="account",
        entity_id=account.id,
        old_values=old_values,
        new_values=update_data
    )
    
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
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
    old_values = {"name": account.name, "description": account.description}
    
    # Eliminar cuenta (cascada automática)
    db.delete(account)
    db.commit()
    
    # Registrar en auditoría
    audit_service = AuditService()
    await audit_service.log_delete(
        db=db,
        user_id=current_user.id,
        entity_type="account",
        entity_id=account_id,
        old_values=old_values
    )
    
    return None


# === ENDPOINTS DE IPS PÚBLICAS ===

@router.post("/{account_id}/public-ips", response_model=PublicIPResponse, status_code=status.HTTP_201_CREATED)
async def add_public_ip(
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
    await audit_service.log_create(
        db=db,
        user_id=current_user.id,
        account_id=account_id,
        entity_type="public_ip",
        entity_id=public_ip.id,
        new_values={"ip_address": public_ip.ip_address, "description": public_ip.description}
    )
    
    return public_ip


@router.delete("/{account_id}/public-ips/{ip_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_public_ip(
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
    old_values = {"ip_address": public_ip.ip_address, "description": public_ip.description}
    
    # Eliminar IP
    db.delete(public_ip)
    db.commit()
    
    # Registrar en auditoría
    audit_service = AuditService()
    await audit_service.log_delete(
        db=db,
        user_id=current_user.id,
        account_id=account_id,
        entity_type="public_ip",
        entity_id=ip_id,
        old_values=old_values
    )
    
    return None
