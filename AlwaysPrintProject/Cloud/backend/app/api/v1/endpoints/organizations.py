"""
Endpoints de gestión de organizaciones.

Este módulo define los endpoints para:
- Toggle de actualizaciones automáticas por organización (solo Admin)
"""

import logging
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_admin
from app.models.user import User
from app.models.account import Account
from app.schemas.organization import AutoUpdateToggleRequest, AutoUpdateToggleResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.patch(
    "/{org_id}/auto-update",
    response_model=AutoUpdateToggleResponse,
    summary="Activar/desactivar actualizaciones automáticas",
    description="Permite a un administrador habilitar o deshabilitar las actualizaciones automáticas para una organización."
)
def toggle_auto_update(
    org_id: UUID,
    body: AutoUpdateToggleRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Activar o desactivar actualizaciones automáticas para una organización.

    - **org_id**: ID de la organización (UUID)
    - **enabled**: true para habilitar, false para deshabilitar

    Requiere autenticación de administrador (JWT Bearer).
    Retorna 404 si la organización no existe.
    Retorna 403 si el usuario no es administrador.
    """
    # Buscar la organización por ID
    account = db.query(Account).filter(Account.id == org_id).first()

    if not account:
        logger.warning(
            "Intento de toggle auto-update en organización inexistente: org_id=%s, user_id=%s",
            org_id,
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada"
        )

    # Actualizar el flag de auto-actualización
    account.auto_update_enabled = body.enabled
    db.commit()
    db.refresh(account)

    logger.info(
        "Auto-update actualizado: org_id=%s, enabled=%s, admin_id=%s",
        org_id,
        body.enabled,
        current_user.id,
    )

    return AutoUpdateToggleResponse(
        auto_update_enabled=account.auto_update_enabled,
        organization_id=str(account.id),
        updated_at=account.updated_at,
    )
