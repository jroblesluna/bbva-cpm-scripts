"""
Endpoints de actividad de usuario (timeline).

Este módulo define los endpoints para:
- Consulta paginada de la línea de tiempo de actividad de un usuario
- Exportación CSV de la actividad de un usuario
"""

from typing import Optional
from uuid import UUID
from datetime import datetime
import base64
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from starlette.responses import StreamingResponse

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User, UserRole
from app.models.audit import AuditLog
from app.schemas import AuditLogListResponse
from app.api.v1.endpoints.audit import _resolve_entity_names
from app.services.export_csv import CSVExportService

router = APIRouter()


def _validate_user_access(
    db: Session,
    current_user: User,
    target_user_id: UUID
) -> User:
    """
    Valida que el usuario actual tiene permiso para ver la actividad del usuario objetivo.

    - Admin: acceso sin restricciones a cualquier usuario.
    - Operator: solo puede ver usuarios de su misma organización.

    Retorna el usuario objetivo si la validación es exitosa.
    Lanza HTTPException 404 si el usuario no existe, 403 si no tiene permisos.
    """
    # Buscar el usuario objetivo en la BD
    target_user = db.query(User).filter(User.id == target_user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )

    # Admin tiene acceso sin restricciones
    if current_user.role == UserRole.ADMIN:
        return target_user

    # Operator: verificar que pertenece a la misma organización
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario sin organización asignada"
        )

    if target_user.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sin permisos para ver la actividad de este usuario"
        )

    return target_user


@router.get("/", response_model=AuditLogListResponse)
def get_user_activity(
    user_id: UUID,
    start_date: Optional[datetime] = Query(None, description="Fecha inicio (created_at >= start_date)"),
    end_date: Optional[datetime] = Query(None, description="Fecha fin (created_at <= end_date)"),
    cursor: Optional[str] = Query(None, description="Cursor para paginación (formato: timestamp|uuid)"),
    limit: int = Query(15, ge=1, le=100, description="Elementos por página"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtener la línea de tiempo de actividad de un usuario específico.

    Retorna una lista paginada (cursor-based) de logs de auditoría
    filtrados por el user_id indicado, ordenados por created_at DESC.

    - Admin: acceso sin restricciones a cualquier usuario.
    - Operator: solo usuarios de su misma organización.
    """
    # Validar acceso al usuario objetivo
    _validate_user_access(db, current_user, user_id)

    # Construir query base filtrada por user_id
    query = db.query(AuditLog).filter(AuditLog.user_id == str(user_id))

    # Aplicar filtros de rango de fechas
    if start_date:
        query = query.filter(AuditLog.created_at >= start_date)
    if end_date:
        query = query.filter(AuditLog.created_at <= end_date)

    # Contar total de registros que coinciden
    total = query.count()

    # Aplicar cursor si se proporcionó
    if cursor:
        try:
            decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
            cursor_ts_str, cursor_id = decoded.rsplit("|", 1)
            cursor_ts = datetime.fromisoformat(cursor_ts_str)
            # Filtrar registros anteriores al cursor (orden descendente)
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

    # Ordenar y limitar (pedimos limit+1 para detectar has_more)
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

    # Resolver nombres de entidades
    resolved_logs = _resolve_entity_names(db, logs)

    return AuditLogListResponse(
        total=total,
        page=1,
        page_size=limit,
        logs=resolved_logs,
        next_cursor=next_cursor,
        has_more=has_more
    )


@router.get("/export")
def export_user_activity(
    user_id: UUID,
    start_date: Optional[datetime] = Query(None, description="Fecha inicio (created_at >= start_date)"),
    end_date: Optional[datetime] = Query(None, description="Fecha fin (created_at <= end_date)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Exportar la actividad de un usuario como CSV con BOM UTF-8.

    Genera un archivo CSV con TODAS las entradas de auditoría del usuario
    (sin paginación), aplicando los filtros de fecha si se proporcionan.

    - Admin: acceso sin restricciones a cualquier usuario.
    - Operator: solo usuarios de su misma organización.
    """
    # Validar acceso al usuario objetivo
    target_user = _validate_user_access(db, current_user, user_id)

    # Construir query sin paginación
    query = db.query(AuditLog).filter(AuditLog.user_id == str(user_id))

    if start_date:
        query = query.filter(AuditLog.created_at >= start_date)
    if end_date:
        query = query.filter(AuditLog.created_at <= end_date)

    # Obtener todos los registros ordenados
    logs = query.order_by(AuditLog.created_at.desc()).all()

    # Resolver nombres de entidades para el CSV
    resolved_logs = _resolve_entity_names(db, logs)
    entity_names = {
        str(log_dict.get("entity_id", "")): log_dict.get("entity_name", "")
        for log_dict in resolved_logs
        if log_dict.get("entity_name")
    }

    # Construir nombre de archivo
    user_email = target_user.email.replace("@", "_at_").replace(".", "_")
    start_str = start_date.strftime("%Y-%m-%d") if start_date else "all"
    end_str = end_date.strftime("%Y-%m-%d") if end_date else "all"
    filename = f"activity_{user_email}_{start_str}_{end_str}.csv"

    # Generar CSV con streaming
    def generate():
        # Emitir BOM UTF-8 primero
        yield CSVExportService.utf8_bom().decode("utf-8")
        # Generar filas CSV
        for row in CSVExportService.generate_activity_csv(logs, entity_names):
            yield row

    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        }
    )
