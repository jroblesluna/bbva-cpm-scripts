"""
Endpoints de suscripción anual (task 19) — solo superadministrador.

Expone la creación de suscripciones anuales y la liquidación informativa del módulo Usage and
Billing:
- POST /billing/organizations/{org_id}/annual-subscription → crea la suscripción anual.
- GET  /billing/organizations/{org_id}/annual-settlement → liquidación informativa (no persiste).
- POST /billing/organizations/{org_id}/annual-settlement/confirm → aplica la liquidación
  (status='settled') manualmente (Req 9.5).

Permisos (Req 11.1): el endpoint exige rol de superadministrador. En este sistema el rol de
mayor privilegio es `UserRole.ADMIN` (acceso global, `organization_id = None`); se reutiliza
la dependencia `require_admin` para enforcar el 403 (mismo criterio que `billing_rates.py`).

Aislamiento (tenant isolation): la suscripción se crea filtrando/escribiendo por
`organization_id`; el servicio verifica que la organización exista y tenga un primer registro
antes de calcular las fechas de vigencia.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_admin
from app.core.utils import get_client_ip
from app.models.audit import ActionType
from app.models.organization import Organization
from app.models.user import User
from app.models.billing import BillingAnnualSubscription
from app.services.audit import AuditService
from app.schemas.billing_annual import (
    AnnualSettlementResponse,
    AnnualSubscriptionCreate,
    AnnualSubscriptionResponse,
)
from app.services.billing_annual_service import (
    BillingNoFirstRegistrationError,
    BillingSubscriptionAlreadySettledError,
    BillingSubscriptionOverlapError,
    billing_annual_service,
)

# Estado de una suscripción vigente: solo una activa por organización (tenant scope).
_STATUS_ACTIVE = "active"

logger = logging.getLogger(__name__)

router = APIRouter()


def _audit_safe(db: Session, **kwargs) -> None:
    """
    Registra una acción de auditoría de liquidación anual sin romper la operación principal.

    La operación (crear suscripción / confirmar liquidación) ya está commiteada por el servicio
    antes de llamar a este helper. Si la escritura del log falla, se hace `rollback` para dejar
    la sesión utilizable (una IntegrityError en el INSERT del log envenena la transacción y
    rompería la serialización de la respuesta) y se registra el error (fail-safe). Como la
    operación principal YA fue commiteada, el rollback solo descarta el intento fallido de log.
    """
    try:
        AuditService().log_action(db=db, **kwargs)
    except Exception as exc:  # noqa: BLE001 — la auditoría no debe tumbar la acción principal
        db.rollback()
        logger.error("No se pudo registrar la auditoría de liquidación anual: %s", exc)


@router.post(
    "/organizations/{org_id}/annual-subscription",
    response_model=AnnualSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una suscripción anual (superadmin)",
)
def create_annual_subscription(
    org_id: UUID,
    payload: AnnualSubscriptionCreate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Crea una suscripción anual para la organización (Req 9.1, 9.2, 8.6, 11.1).

    Deriva `start_date` del `created_at` del primer registro de la organización y
    `end_date` como el aniversario − 1 día; congela `tier_rate`/`tier_from`/`tier_to`/
    `tier_cap` y registra el `declared_volume`. Al crearla, la organización queda en
    modalidad anual, por lo que el invoice mensual se genera en US$ 0.00 durante la vigencia
    (Req 9.2, enforzado por el motor de cierre).

    Errores:
        404: la organización no existe.
        409: la organización no tiene un primer registro (no hay fecha de inicio) o ya tiene
             una suscripción anual activa.
    """
    # Tenant scope explícito: la organización debe existir.
    organization = db.query(Organization).filter(Organization.id == org_id).first()
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organización con ID {org_id} no encontrada",
        )

    try:
        subscription = billing_annual_service.create_subscription(
            db=db,
            org=organization,
            declared_volume=payload.declared_volume,
            tier_from=payload.tier_from,
            tier_rate=payload.tier_rate,
            tier_to=payload.tier_to,
            tier_cap=payload.tier_cap,
            actor_id=current_user.id,
        )
    except BillingNoFirstRegistrationError as exc:
        # Sin primer registro no hay inicio posible (fail-closed).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except BillingSubscriptionOverlapError as exc:
        # Ya existe una suscripción activa: se rechaza el solape.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except ValueError as exc:
        # Datos de tramo/volumen inválidos que no cubrió el schema.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    logger.info(
        "Suscripción anual creada: id=%s, org=%s, por user=%s",
        subscription.id,
        org_id,
        current_user.id,
    )

    # Auditoría de la creación de la suscripción anual (Req 11.4). Tenant isolation por org_id.
    _audit_safe(
        db=db,
        action_type=ActionType.ANNUAL_SETTLEMENT,
        entity_type="BillingAnnualSubscription",
        entity_id=str(subscription.id),
        user_id=str(current_user.id),
        organization_id=str(org_id),
        new_values={
            "operation": "create_subscription",
            "start_date": subscription.start_date,
            "end_date": subscription.end_date,
            "declared_volume": subscription.declared_volume,
            "tier_from": subscription.tier_from,
            "tier_to": subscription.tier_to,
            "tier_rate": str(subscription.tier_rate),
            "tier_cap": subscription.tier_cap,
            "status": subscription.status,
        },
        ip_address=get_client_ip(request),
    )
    return subscription


def _get_active_subscription(db: Session, org_id: UUID) -> BillingAnnualSubscription:
    """
    Obtiene la suscripción anual activa de la organización o lanza 404.

    Tenant isolation: filtra por `organization_id`. Solo hay una suscripción 'active' por
    organización (guard de solape en la creación).
    """
    subscription = (
        db.query(BillingAnnualSubscription)
        .filter(
            BillingAnnualSubscription.organization_id == org_id,
            BillingAnnualSubscription.status == _STATUS_ACTIVE,
        )
        .first()
    )
    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"La organización {org_id} no tiene una suscripción anual activa",
        )
    return subscription


@router.get(
    "/organizations/{org_id}/annual-settlement",
    response_model=AnnualSettlementResponse,
    summary="Liquidación anual informativa (superadmin)",
)
def get_annual_settlement(
    org_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Devuelve la liquidación anual de forma INFORMATIVA (Req 9.3-9.6, 11.1).

    Calcula la liquidación en vivo sobre la suscripción anual activa de la organización sin
    persistir nada: base = IPs 'billable', `real = min(billable, tier_cap)`, diferencia contra
    el volumen declarado y crédito/cargo sugerido. Incluye el indicador informativo de
    crecimiento libre. La aplicación es manual (ver el endpoint /confirm).

    Errores:
        404: la organización no tiene una suscripción anual activa.
    """
    subscription = _get_active_subscription(db, org_id)
    return billing_annual_service.compute_settlement(db, subscription)


@router.post(
    "/organizations/{org_id}/annual-settlement/confirm",
    response_model=AnnualSubscriptionResponse,
    summary="Confirmar (aplicar) la liquidación anual (superadmin)",
)
def confirm_annual_settlement(
    org_id: UUID,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Aplica manualmente la liquidación anual (Req 9.5, 11.1).

    Recalcula la liquidación, la guarda en `settlement` y pasa la suscripción a 'settled'.
    Requiere confirmación explícita del superadministrador (no es automática).

    Errores:
        404: la organización no tiene una suscripción anual activa.
        409: la suscripción ya fue liquidada (status='settled').
    """
    subscription = _get_active_subscription(db, org_id)
    try:
        updated = billing_annual_service.confirm_settlement(
            db=db,
            subscription=subscription,
            actor_id=current_user.id,
        )
    except BillingSubscriptionAlreadySettledError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    logger.info(
        "Liquidación anual confirmada: id=%s, org=%s, por user=%s",
        updated.id,
        org_id,
        current_user.id,
    )

    # Auditoría de la confirmación de la liquidación anual (Req 11.4). Se registra el resumen
    # de la liquidación aplicada (crédito/cargo/estado). Tenant isolation por org_id.
    _audit_safe(
        db=db,
        action_type=ActionType.ANNUAL_SETTLEMENT,
        entity_type="BillingAnnualSubscription",
        entity_id=str(updated.id),
        user_id=str(current_user.id),
        organization_id=str(org_id),
        new_values={
            "operation": "confirm_settlement",
            "status": updated.status,
            "settlement": updated.settlement,
        },
        ip_address=get_client_ip(request),
    )
    return updated
