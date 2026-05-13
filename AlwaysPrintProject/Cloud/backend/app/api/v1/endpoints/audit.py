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
from sqlalchemy import func

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


def _resolve_entity_names(db: Session, logs: list) -> list[dict]:
    """
    Resuelve el nombre legible de cada entidad según su tipo.
    Agrupa las consultas por tipo para minimizar queries a la BD.
    """
    from app.models.user import User as UserModel
    from app.models.account import Account
    from app.models.workstation import Workstation
    from app.models.vlan import VLAN
    from app.models.message import Message

    # Agrupar entity_ids por tipo
    ids_by_type: dict[str, set] = {}
    for log in logs:
        entity_type = log.entity_type.lower()
        entity_id = str(log.entity_id)
        if entity_type not in ids_by_type:
            ids_by_type[entity_type] = set()
        ids_by_type[entity_type].add(entity_id)

    # Resolver nombres por tipo
    names: dict[str, str] = {}

    if "user" in ids_by_type:
        users = db.query(UserModel).filter(UserModel.id.in_(ids_by_type["user"])).all()
        for u in users:
            names[str(u.id)] = u.full_name or u.email

    if "account" in ids_by_type:
        accounts = db.query(Account).filter(Account.id.in_(ids_by_type["account"])).all()
        for a in accounts:
            names[str(a.id)] = a.name

    if "workstation" in ids_by_type:
        workstations = db.query(Workstation).filter(Workstation.id.in_(ids_by_type["workstation"])).all()
        for w in workstations:
            names[str(w.id)] = w.hostname or w.ip_private or str(w.id)[:8]

    if "vlan" in ids_by_type:
        vlans = db.query(VLAN).filter(VLAN.id.in_(ids_by_type["vlan"])).all()
        for v in vlans:
            names[str(v.id)] = v.name

    if "message" in ids_by_type:
        messages = db.query(Message).filter(Message.id.in_(ids_by_type["message"])).all()
        for m in messages:
            names[str(m.id)] = m.content[:40] + ("..." if len(m.content) > 40 else "")

    # Construir respuesta con entity_name
    result = []
    for log in logs:
        log_dict = {
            "id": log.id,
            "user_id": log.user_id,
            "workstation_id": log.workstation_id,
            "account_id": log.account_id,
            "action_type": log.action_type,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "entity_name": names.get(str(log.entity_id)),
            "old_values": log.old_values,
            "new_values": log.new_values,
            "ip_address": log.ip_address,
            "created_at": log.created_at,
        }
        result.append(log_dict)

    return result


@router.get("/", response_model=AuditLogListResponse)
def search_audit_logs(
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
    
    # Calcular skip para paginación
    skip = (page - 1) * page_size
    
    # Buscar logs usando el servicio
    logs, total = audit_service.search_audit_logs(
        db=db,
        account_id=str(account_id) if account_id else None,
        user_id=str(user_id) if user_id else None,
        workstation_id=str(workstation_id) if workstation_id else None,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id else None,
        start_date=start_date,
        end_date=end_date,
        skip=skip,
        limit=page_size
    )
    
    return AuditLogListResponse(
        total=total,
        page=page,
        page_size=page_size,
        logs=_resolve_entity_names(db, logs)
    )


@router.get("/stats", response_model=AuditLogStatsResponse)
def get_audit_stats(
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
    
    # Acciones por tipo - solo si hay account_id
    actions_by_type = {}
    if account_id:
        actions_by_type = audit_service.get_action_count_by_type(db, str(account_id))
    else:
        # Para admin sin filtro, contar todos los tipos
        all_logs = db.query(AuditLog).all()
        for log in all_logs:
            action_type = log.action_type.value
            actions_by_type[action_type] = actions_by_type.get(action_type, 0) + 1
    
    # Usuarios más activos (top 10)
    most_active_query = db.query(
        AuditLog.user_id,
        func.count(AuditLog.id).label("count")
    )
    if account_id:
        most_active_query = most_active_query.filter(AuditLog.account_id == account_id)
    
    most_active = most_active_query.group_by(AuditLog.user_id).order_by(
        func.count(AuditLog.id).desc()
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
def get_recent_activity(
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
    if account_id:
        logs = audit_service.get_recent_activity(db, str(account_id), hours=24, limit=limit)
    else:
        # Para admin, obtener actividad reciente de todas las cuentas
        recent_date = datetime.utcnow() - timedelta(hours=24)
        logs = db.query(AuditLog).filter(
            AuditLog.created_at >= recent_date
        ).order_by(
            AuditLog.created_at.desc()
        ).limit(limit).all()
    
    return AuditLogListResponse(
        total=len(logs),
        page=1,
        page_size=limit,
        logs=_resolve_entity_names(db, logs)
    )


@router.get("/{log_id}", response_model=AuditLogDetailResponse)
def get_audit_log(
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
