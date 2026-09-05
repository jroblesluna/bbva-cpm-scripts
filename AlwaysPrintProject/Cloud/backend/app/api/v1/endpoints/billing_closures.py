"""
Endpoints de cierres mensuales (task 27) del módulo Usage and Billing.

Expone:
- GET  /billing/organizations/{org_id}/closures            → lista de cierres (cabecera).
- GET  /billing/closures/{closure_id}/items                → detalle por IP (paginado).
- POST /billing/organizations/{org_id}/closures/retroactive → cierra el mes pendiente más antiguo.

Permisos y aislamiento:
- Los dos GET son de rol `admin` en el diseño: se permiten a operadores y superadministradores
  (`require_operator_or_admin`), pero un operador solo puede consultar los cierres de SU propia
  organización (tenant isolation, Req 11.3). El superadministrador (`UserRole.ADMIN`, acceso
  global con `organization_id = None`) puede consultar cualquiera.
- El POST retroactivo es exclusivo de superadministrador (`require_admin`, Req 11.2), mismo
  criterio que `billing_rates.py`/`billing_annual.py`.

El cierre retroactivo reutiliza `BillingCloseService`:
1. `next_pending_period` determina el mes pendiente MÁS ANTIGUO (Req 7.2, 7.3). Si no hay
   meses pendientes se responde 200 con `closed = False` (idempotente, no error).
2. `close_month(..., is_retroactive=True)` ejecuta el cierre respetando secuencialidad
   (Req 7.4) e idempotencia (Req 7.6); el capping de `last_seen` en el snapshot lo aplica el
   propio motor (Req 7.5, vía `min(last_seen, cutoff)` en cada ítem). Aunque partimos del mes
   más antiguo pendiente (que no debería violar secuencialidad/idempotencia), se capturan las
   excepciones del servicio y se traducen a 409 (fail-closed, guardas defensivas).
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_admin, require_operator_or_admin
from app.models.billing import BillingClosure, BillingClosureItem
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.schemas.billing_closures import (
    ClosureHeaderResponse,
    ClosureItemResponse,
    ClosureItemsPage,
    RetroactiveCloseResponse,
)
from app.services.billing_close_service import (
    BillingAlreadyClosedError,
    BillingSequenceError,
    billing_close_service,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_org_or_404(db: Session, org_id: UUID) -> Organization:
    """Obtiene la organización o lanza 404 (tenant scope explícito)."""
    organization = db.query(Organization).filter(Organization.id == org_id).first()
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organización con ID {org_id} no encontrada",
        )
    return organization


def _assert_org_scope(current_user: User, org_id: UUID) -> None:
    """
    Aísla por organización: un operador solo puede consultar su propia org (Req 11.3).

    El superadministrador (`UserRole.ADMIN`, acceso global) puede consultar cualquiera.
    """
    if (
        current_user.role == UserRole.OPERATOR
        and current_user.organization_id != org_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sin permisos para consultar los cierres de esta organización",
        )


# ── Lectura de cierres (admin/operador de su org) ────────────────────────────


@router.get(
    "/organizations/{org_id}/closures",
    response_model=list[ClosureHeaderResponse],
    summary="Listar cierres mensuales de una organización (admin)",
)
def list_closures(
    org_id: UUID,
    current_user: User = Depends(require_operator_or_admin),
    db: Session = Depends(get_db),
):
    """
    Lista las cabeceras de cierre de una organización (Req 10.3, 11.3).

    Ordenadas del más reciente al más antiguo (`(period_year, period_month)` desc). Tenant
    isolation: un operador solo ve los cierres de su organización; el superadministrador ve
    los de cualquiera.

    Errores:
        403: operador consultando una organización distinta a la suya.
        404: la organización no existe.
    """
    _get_org_or_404(db, org_id)
    _assert_org_scope(current_user, org_id)

    closures = (
        db.query(BillingClosure)
        .filter(BillingClosure.organization_id == org_id)
        .order_by(
            BillingClosure.period_year.desc(),
            BillingClosure.period_month.desc(),
        )
        .all()
    )
    return closures


@router.get(
    "/closures/{closure_id}/items",
    response_model=ClosureItemsPage,
    summary="Detalle por IP de un cierre, paginado (admin)",
)
def list_closure_items(
    closure_id: UUID,
    page: int = Query(1, ge=1, description="Número de página (1-based)"),
    page_size: int = Query(50, ge=1, le=500, description="Ítems por página"),
    current_user: User = Depends(require_operator_or_admin),
    db: Session = Depends(get_db),
):
    """
    Devuelve el detalle por IP de un cierre, paginado (Req 10.3, 11.3).

    Tenant isolation: el cierre se resuelve primero para conocer su `organization_id` y
    validar que el operador solo consulte los de su organización. Los ítems se ordenan por
    `ip_private` para una visualización estable.

    Errores:
        403: operador consultando un cierre de otra organización.
        404: el cierre no existe.
    """
    closure = (
        db.query(BillingClosure)
        .filter(BillingClosure.id == closure_id)
        .first()
    )
    if closure is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cierre con ID {closure_id} no encontrado",
        )
    _assert_org_scope(current_user, closure.organization_id)

    base_query = db.query(BillingClosureItem).filter(
        BillingClosureItem.closure_id == closure_id
    )
    total = base_query.count()
    items = (
        base_query.order_by(BillingClosureItem.ip_private.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ClosureItemsPage(
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )


# ── Cierre retroactivo (solo superadmin) ─────────────────────────────────────


@router.post(
    "/organizations/{org_id}/closures/retroactive",
    response_model=RetroactiveCloseResponse,
    summary="Cerrar el mes pendiente más antiguo, uno por uno (superadmin)",
)
def close_retroactive(
    org_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Genera el cierre retroactivo del mes pendiente MÁS ANTIGUO de la organización, uno por
    llamada (Req 7.2, 7.3, 7.4, 7.5, 11.2).

    Flujo:
    1. Determina el mes pendiente más antiguo con `next_pending_period` (primer mes finalizado
       sin cierre, desde el `created_at` más antiguo de una IP). Si no hay ninguno (todos los
       meses finalizados ya cerraron, o la org no tiene IPs), responde 200 con `closed = False`
       (respuesta idempotente, no error).
    2. Ejecuta `close_month(..., is_retroactive=True)`. El motor aplica el capping de
       `last_seen` en el snapshot (Req 7.5) y valida secuencialidad (Req 7.4) e idempotencia
       (Req 7.6). Como partimos del mes más antiguo pendiente, esas validaciones no deberían
       fallar; aun así se capturan y se traducen a 409 (fail-closed, guarda defensiva ante
       carreras).

    Errores:
        404: la organización no existe.
        409: colisión de idempotencia/secuencialidad (carrera con otro cierre).
    """
    organization = _get_org_or_404(db, org_id)

    pending = billing_close_service.next_pending_period(db, organization)
    if pending is None:
        # No hay meses finalizados pendientes por cerrar (o la org no tiene IPs).
        logger.info(
            "Cierre retroactivo sin meses pendientes: org=%s, por user=%s",
            org_id,
            current_user.id,
        )
        return RetroactiveCloseResponse(
            closed=False,
            detail=(
                "No hay meses pendientes por cerrar para esta organización "
                "(todos los meses finalizados ya tienen cierre o la organización no "
                "tiene workstations registradas)."
            ),
            closure=None,
        )

    year, month = pending
    try:
        closure = billing_close_service.close_month(
            db=db,
            org=organization,
            year=year,
            month=month,
            actor_id=current_user.id,
            is_retroactive=True,
        )
    except (BillingAlreadyClosedError, BillingSequenceError) as exc:
        # No debería ocurrir porque elegimos el mes más antiguo pendiente; guarda defensiva
        # ante una carrera con el scheduler u otro cierre concurrente (fail-closed).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    logger.info(
        "Cierre retroactivo generado: org=%s, periodo=%d-%02d, por user=%s",
        org_id,
        year,
        month,
        current_user.id,
    )
    return RetroactiveCloseResponse(
        closed=True,
        detail=f"Cierre retroactivo generado para {year}-{month:02d}.",
        closure=closure,
    )
