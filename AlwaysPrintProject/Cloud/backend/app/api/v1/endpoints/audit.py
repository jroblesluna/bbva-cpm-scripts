"""
Endpoints de auditoría.

Este módulo define los endpoints para:
- Búsqueda de logs de auditoría
- Estadísticas de auditoría
- Actividad reciente
"""

from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_admin
from app.models.user import User, UserRole
from app.models.audit import AuditLog, ActionType
from app.schemas import (
    AuditLogResponse,
    AuditLogDetailResponse,
    AuditLogSearch,
    AuditLogListResponse,
    AuditLogStatsResponse,
)
from app.services.audit import AuditService

router = APIRouter()


@router.get("/", response_model=AuditLogListResponse)
async def search_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    user_id: Optional[UUID] = Query(None),
    workstation_id: Optional[UUID] = Query(None),
    account_id: Optional[UUID] = Query(None),
    action_type: Optional[ActionType] = Query(None),
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[UUID] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Buscar logs de auditoría con filtros.
    
    - Admin: puede ver todos los logs
    - Operador: solo puede ver logs de su cuenta
    """
    audit_service = AuditService()
    
    # Operadores solo pueden ver logs de su cuenta
    if current_user.role == UserRole.OPERATOR:
        if not current_user.account_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operador sin cuenta asignada")
        account_id = current_user.account_id
    
    # Crear objeto de búsqueda
    search_params = AuditLogSearch(
        user_id=user_id,
        workstation_id=workstation_id,
        account_id=account_id,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size
    )
    
    # Buscar logs
    result = await audit_service.search_audit_logs(db, search_params)
    
    return result


@router.get("/stats", response_model=AuditLogStatsResponse)
async def get_audit_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener estadísticas de auditoría.
    
    - Admin: estadísticas de todas las cuentas
    - Operador: estadísticas de su cuenta
    """
    audit_service = AuditService()
    
    # Determinar account_id según rol
    account_id = None
    if current_user.role == UserRole.OPERATOR:
        if not current_user.account_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operador sin cuenta asignada")
        account_id = current_user.account_id
    
    # Obtener estadísticas
    query = db.query(AuditLog)
    if account_id:
        query = query.filter(AuditLog.account_id == account_id)
    
    total_actions = query.count()
    
    # Acciones por tipo
    actions_by_type = await audit_service.get_action_count_by_type(db, account_id)
    
    # Usuarios más activos (top 10)
    most_active_query = db.query(
        AuditLog.user_id,
        db.func.count(AuditLog.id).label("count")
    )
    if account_id:
        most_active_query = most_active_query.filter(AuditLog.account_id == account_id)
    
    most_active = most_active_query.group_by(AuditLog.user_id).order_by(
        db.func.count(AuditLog.id).desc()
    ).limit(10).all()
    
    most_active_users = [
        {"user_id": str(user_id), "action_count": count}
        for user_id, count in most_active if user_id
    ]
    
    # Actividad reciente (últimas 24 horas)
    recent_date = datetime.utcnow() - timedelta(hours=24)
    recent_query = query.filter(AuditLog.created_at >= recent_date)
    recent_activity_count = recent_query.count()
    
    return AuditLogStatsResponse(
        total_actions=total_actions,
        actions_by_type=actions_by_type,
        most_active_users=most_active_users,
        recent_activity_count=recent_activity_count
    )


@router.get("/recent", response_model=AuditLogListResponse)
async def get_recent_activity(
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener actividad reciente.
    
    - Admin: actividad de todas las cuentas
    - Operador: actividad de su cuenta
    """
    audit_service = AuditService()
    
    # Determinar account_id según rol
    account_id = None
    if current_user.role == UserRole.OPERATOR:
        if not current_user.account_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operador sin cuenta asignada")
        account_id = current_user.account_id
    
    # Obtener actividad reciente
    logs = await audit_service.get_recent_activity(db, account_id, limit)
    
    return AuditLogListResponse(
        total=len(logs),
        page=1,
        page_size=limit,
        logs=logs
    )


@router.get("/{log_id}", response_model=AuditLogDetailResponse)
async def get_audit_log(
    log_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Obtener detalles de un log de auditoría."""
    log = db.query(AuditLog).filter(AuditLog.id == log_id).first()
    
    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log no encontrado")
    
    # Verificar permisos
    if current_user.role == UserRole.OPERATOR:
        if log.account_id != current_user.account_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin permisos")
    
    # Agregar información adicional
    user_name = log.user.full_name if log.user else None
    user_email = log.user.email if log.user else None
    workstation_ip = log.workstation.ip_private if log.workstation else None
    
    return AuditLogDetailResponse(
        **log.__dict__,
        user_name=user_name,
        user_email=user_email,
        workstation_ip=workstation_ip
    )
