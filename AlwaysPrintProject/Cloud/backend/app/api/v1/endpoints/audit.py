"""
Endpoints de auditoría.

Este módulo define los endpoints para:
- Búsqueda de logs de auditoría
- Estadísticas de auditoría
- Actividad reciente
"""

from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone
import base64
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, and_, cast, false, String

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
    AuditLogGlobalStatsResponse,
)
from app.services.audit import AuditService

router = APIRouter()


def _get_scoped_organization_id(current_user: User) -> Optional[UUID]:
    """
    Devuelve la organización a la que debe quedar acotado el usuario.

    - Admin: sin scope (None)
    - No admin: obligatorio scope a su organización
    """
    if current_user.role == UserRole.ADMIN:
        return None

    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario sin organización asignada"
        )

    return current_user.organization_id


def _resolve_entity_names(db: Session, logs: list) -> list[dict]:
    """
    Resuelve el nombre legible de cada entidad según su tipo.
    Agrupa las consultas por tipo para minimizar queries a la BD.
    """
    from app.models.user import User as UserModel
    from app.models.organization import Organization
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

    # Soportar tanto "organization" (nuevo) como "account" (legacy en BD)
    org_ids = ids_by_type.get("organization", set()) | ids_by_type.get("account", set())
    if org_ids:
        orgs = db.query(Organization).filter(Organization.id.in_(org_ids)).all()
        for o in orgs:
            names[str(o.id)] = o.name

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
        entity_name = names.get(str(log.entity_id))

        # Fallback: extraer nombre de old_values o new_values si la entidad ya no existe
        if entity_name is None:
            for values in (log.old_values, log.new_values):
                if isinstance(values, dict):
                    candidate = (
                        values.get("name")
                        or values.get("hostname")
                        or values.get("full_name")
                        or values.get("email")
                        or (values.get("content", "")[:40] if "content" in values else None)
                    )
                    if candidate:
                        entity_name = candidate
                        break

        log_dict = {
            "id": log.id,
            "user_id": log.user_id,
            "workstation_id": log.workstation_id,
            "organization_id": log.organization_id,
            "action_type": log.action_type,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "entity_name": entity_name,
            "old_values": log.old_values,
            "new_values": log.new_values,
            "ip_address": log.ip_address,
            "created_at": log.created_at,
        }
        result.append(log_dict)

    return result


def _get_entity_ids_matching_name(db: Session, name: str) -> set[str]:
    """
    Busca IDs de entidades cuyo nombre legible coincide con `name` (ILIKE),
    cruzando con las tablas relacionadas. Es la operación inversa de
    _resolve_entity_names (de nombre a ID en vez de ID a nombre), necesaria
    porque entity_name no es una columna real de audit_logs.
    """
    from app.models.user import User as UserModel
    from app.models.organization import Organization
    from app.models.workstation import Workstation
    from app.models.vlan import VLAN
    from app.models.message import Message

    term = f"%{name}%"
    ids: set[str] = set()

    users = db.query(UserModel.id).filter(
        or_(UserModel.full_name.ilike(term), UserModel.email.ilike(term))
    ).all()
    ids.update(str(row[0]) for row in users)

    orgs = db.query(Organization.id).filter(Organization.name.ilike(term)).all()
    ids.update(str(row[0]) for row in orgs)

    workstations = db.query(Workstation.id).filter(
        or_(Workstation.hostname.ilike(term), Workstation.ip_private.ilike(term))
    ).all()
    ids.update(str(row[0]) for row in workstations)

    vlans = db.query(VLAN.id).filter(VLAN.name.ilike(term)).all()
    ids.update(str(row[0]) for row in vlans)

    messages = db.query(Message.id).filter(Message.content.ilike(term)).all()
    ids.update(str(row[0]) for row in messages)

    return ids


@router.get("/", response_model=AuditLogListResponse)
def search_audit_logs(
    cursor: Optional[str] = Query(None, description="Cursor para paginación (formato: timestamp|uuid)"),
    limit: int = Query(15, ge=1, le=100, description="Elementos por página"),
    page: int = Query(1, ge=1, description="Página (legacy, ignorado si se usa cursor)"),
    page_size: int = Query(50, ge=1, le=100, description="Tamaño de página (legacy, ignorado si se usa cursor)"),
    user_id: Optional[UUID] = Query(None),
    workstation_id: Optional[UUID] = Query(None),
    organization_id: Optional[UUID] = Query(None),
    action_type: Optional[ActionType] = Query(None),
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[UUID] = Query(None),
    entity_name: Optional[str] = Query(None, description="Filtrar por nombre legible de la entidad"),
    search: Optional[str] = Query(None, description="Búsqueda general (tipo, acción, ID, IP o nombre de entidad)"),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Buscar logs de auditoría con filtros y paginación por cursor.

    La paginación por cursor usa el parámetro `cursor` (formato: ISO_timestamp|uuid).
    Si no se envía cursor, devuelve la primera página.
    El campo `next_cursor` en la respuesta indica el cursor para la siguiente página.
    El campo `has_more` indica si hay más resultados.

    `entity_name` y `search` resuelven el nombre legible de la entidad
    (usuario, organización, workstation, VLAN, mensaje) cruzando con sus
    tablas relacionadas, ya que no es una columna de `audit_logs`.

    - Admin: puede ver todos los logs
    - Operador: solo puede ver logs de su cuenta
    """
    audit_service = AuditService()

    # No-admin: siempre restringido a su organización (ignora organization_id enviado por cliente)
    scoped_org_id = _get_scoped_organization_id(current_user)
    if scoped_org_id is not None:
        organization_id = scoped_org_id
    
    # Construir query base con filtros
    query = db.query(AuditLog)
    
    if organization_id:
        query = query.filter(AuditLog.organization_id == str(organization_id))
    if user_id:
        query = query.filter(AuditLog.user_id == str(user_id))
    if workstation_id:
        query = query.filter(AuditLog.workstation_id == str(workstation_id))
    if action_type:
        query = query.filter(AuditLog.action_type == action_type)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.filter(AuditLog.entity_id == str(entity_id))
    if entity_name:
        name_ids = _get_entity_ids_matching_name(db, entity_name)
        query = query.filter(AuditLog.entity_id.in_(name_ids) if name_ids else false())
    if search:
        search_term = f"%{search}%"
        name_ids = _get_entity_ids_matching_name(db, search)
        conditions = [
            AuditLog.entity_type.ilike(search_term),
            AuditLog.ip_address.ilike(search_term),
            cast(AuditLog.entity_id, String).ilike(search_term),
            cast(AuditLog.action_type, String).ilike(search_term),
        ]
        if name_ids:
            conditions.append(AuditLog.entity_id.in_(name_ids))
        query = query.filter(or_(*conditions))
    if start_date:
        query = query.filter(AuditLog.created_at >= start_date)
    if end_date:
        query = query.filter(AuditLog.created_at <= end_date)

    # Contar total
    total = query.count()
    
    # Aplicar cursor si se proporcionó
    if cursor:
        try:
            decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
            cursor_ts_str, cursor_id = decoded.rsplit("|", 1)
            cursor_ts = datetime.fromisoformat(cursor_ts_str)
            # Filtrar registros anteriores al cursor (orden descendente por created_at)
            query = query.filter(
                or_(
                    AuditLog.created_at < cursor_ts,
                    and_(
                        AuditLog.created_at == cursor_ts,
                        AuditLog.id < cursor_id
                    )
                )
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cursor inválido"
            )
    
    # Ordenar y limitar (pedimos limit+1 para saber si hay más)
    logs = query.order_by(
        AuditLog.created_at.desc(),
        AuditLog.id.desc()
    ).limit(limit + 1).all()
    
    # Determinar si hay más resultados
    has_more = len(logs) > limit
    if has_more:
        logs = logs[:limit]
    
    # Generar next_cursor a partir del último elemento
    next_cursor = None
    if has_more and logs:
        last_log = logs[-1]
        cursor_value = f"{last_log.created_at.isoformat()}|{str(last_log.id)}"
        next_cursor = base64.urlsafe_b64encode(cursor_value.encode()).decode()
    
    # Calcular página actual (para compatibilidad)
    current_page = 1 if not cursor else page
    
    return AuditLogListResponse(
        total=total,
        page=current_page,
        page_size=limit,
        logs=_resolve_entity_names(db, logs),
        next_cursor=next_cursor,
        has_more=has_more
    )


@router.get("/stats", response_model=AuditLogStatsResponse)
def get_audit_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener estadísticas de auditoría.
    
    - Admin: estadísticas de todas las organizaciones
    - Operador: estadísticas de su organización
    """
    audit_service = AuditService()
    
    # No-admin: estadísticas restringidas a su organización
    org_id = _get_scoped_organization_id(current_user)
    
    # Obtener estadísticas
    query = db.query(AuditLog)
    if org_id:
        query = query.filter(AuditLog.organization_id == org_id)
    
    total_actions = query.count()
    
    # Acciones por tipo - solo si hay org_id
    actions_by_type = {}
    if org_id:
        actions_by_type = audit_service.get_action_count_by_type(db, str(org_id))
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
    if org_id:
        most_active_query = most_active_query.filter(AuditLog.organization_id == org_id)
    
    most_active = most_active_query.group_by(AuditLog.user_id).order_by(
        func.count(AuditLog.id).desc()
    ).limit(10).all()
    
    most_active_users = [
        {"user_id": str(user_id), "action_count": count}
        for user_id, count in most_active if user_id
    ]
    
    # Actividad reciente (últimas 24 horas)
    recent_date = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    recent_query = query.filter(AuditLog.created_at >= recent_date)
    recent_activity_count = recent_query.count()

    # Desglose de acciones y entidades en las últimas 24 horas.
    # Se recorren los logs en Python (en vez de agregar en SQL) porque el
    # logout se guarda como action_type=DELETE + entity_type=session y debe
    # contarse aparte, igual que lo distingue el frontend (ver isLogoutEvent).
    recent_logs = recent_query.all()
    actions_by_type_24h: dict[str, int] = {}
    entities_by_type_24h: dict[str, int] = {}
    for log in recent_logs:
        action_key = log.action_type.value
        is_logout = (
            log.action_type == ActionType.DELETE
            and log.entity_type.lower() == "session"
            and isinstance(log.old_values, dict)
            and log.old_values.get("action") == "logout"
        )
        if is_logout:
            action_key = "logout"
        actions_by_type_24h[action_key] = actions_by_type_24h.get(action_key, 0) + 1
        entities_by_type_24h[log.entity_type] = entities_by_type_24h.get(log.entity_type, 0) + 1

    return AuditLogStatsResponse(
        total_actions=total_actions,
        actions_by_type=actions_by_type,
        most_active_users=most_active_users,
        recent_activity_count=recent_activity_count,
        actions_by_type_24h=actions_by_type_24h,
        entities_by_type_24h=entities_by_type_24h
    )


@router.get("/stats/global", response_model=AuditLogGlobalStatsResponse)
def get_audit_global_stats(
    period: str = Query(
        "24h",
        pattern="^(24h|week)$",
        description="'24h' = últimas 24 horas (rolling), 'week' = semana calendario actual (lunes 00:00 hasta ahora)"
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener estadísticas globales de auditoría, agrupadas por tipo de entidad.

    No aplica ningún otro filtro (tipo de acción, entidad puntual, etc.): siempre
    muestra todas las acciones registradas dentro del período.

    - Admin: todas las organizaciones
    - Operador: solo su organización
    """
    org_id = _get_scoped_organization_id(current_user)

    query = db.query(AuditLog)
    if org_id:
        query = query.filter(AuditLog.organization_id == org_id)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if period == "week":
        # Lunes 00:00 de la semana calendario actual (weekday(): lunes=0 ... domingo=6)
        since_date = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        since_date = now - timedelta(hours=24)

    logs = query.filter(AuditLog.created_at >= since_date).all()

    actions_by_type: dict[str, int] = {}
    entities_by_type: dict[str, int] = {}
    actions_by_entity_and_type: dict[str, dict[str, int]] = {}

    for log in logs:
        action_key = log.action_type.value
        is_logout = (
            log.action_type == ActionType.DELETE
            and log.entity_type.lower() == "session"
            and isinstance(log.old_values, dict)
            and log.old_values.get("action") == "logout"
        )
        if is_logout:
            action_key = "logout"

        actions_by_type[action_key] = actions_by_type.get(action_key, 0) + 1
        entities_by_type[log.entity_type] = entities_by_type.get(log.entity_type, 0) + 1

        entity_bucket = actions_by_entity_and_type.setdefault(log.entity_type, {})
        entity_bucket[action_key] = entity_bucket.get(action_key, 0) + 1

    # Incluir todos los tipos de entidad que existen en el historial (no solo
    # los que tuvieron actividad en la ventana de tiempo consultada), para que
    # el desglose muestre siempre el panorama completo.
    all_entity_types_query = db.query(AuditLog.entity_type).distinct()
    if org_id:
        all_entity_types_query = all_entity_types_query.filter(AuditLog.organization_id == org_id)
    all_entity_types = {row[0] for row in all_entity_types_query.all()}

    for entity_type in all_entity_types:
        actions_by_entity_and_type.setdefault(entity_type, {})
        entities_by_type.setdefault(entity_type, 0)

    return AuditLogGlobalStatsResponse(
        period=period,
        total_actions=len(logs),
        actions_by_type=actions_by_type,
        entities_by_type=entities_by_type,
        actions_by_entity_and_type=actions_by_entity_and_type
    )


@router.get("/recent", response_model=AuditLogListResponse)
def get_recent_activity(
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener actividad reciente.
    
    - Admin: actividad de todas las organizaciones
    - Operador: actividad de su organización
    """
    audit_service = AuditService()
    
    # No-admin: actividad reciente restringida a su organización
    org_id = _get_scoped_organization_id(current_user)
    
    # Obtener actividad reciente
    if org_id:
        logs = audit_service.get_recent_activity(db, str(org_id), hours=24, limit=limit)
    else:
        # Para admin, obtener actividad reciente de todas las organizaciones
        recent_date = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
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
    
    # Verificar permisos (no-admin solo puede ver logs de su organización)
    scoped_org_id = _get_scoped_organization_id(current_user)
    if scoped_org_id is not None and log.organization_id != scoped_org_id:
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
