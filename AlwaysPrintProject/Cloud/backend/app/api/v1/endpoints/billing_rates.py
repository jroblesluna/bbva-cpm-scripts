"""
Endpoints de tarifas y planes de facturación (task 17) — solo superadministrador.

Expone la gestión de modelos tarifarios del módulo Usage and Billing:
- GET  /billing/rate-plans            → lista los planes por defecto del sistema (ambas modalidades).
- PUT  /billing/rate-plans/{id}       → edita/programa un plan por defecto (tramos, vigencia, etc.).
- PUT  /billing/organizations/{id}/plan → crea/actualiza el plan individual de una organización.

Permisos (Req 11.1): los tres endpoints exigen rol de superadministrador. En este sistema el
rol de mayor privilegio es `UserRole.ADMIN` (acceso global, `organization_id = None`); se
reutiliza la dependencia `require_admin` para enforcar el 403.

Aislamiento (tenant isolation): el plan individual de organización siempre se lee/escribe
filtrando por `organization_id`. Editar los planes por defecto NUNCA toca `billing_org_plans`
y viceversa: son filas separadas, por lo que un cambio de defaults no sobrescribe los planes de
organización (Req 8.8).

Notas de modalidad:
- Las tarifas de la modalidad Mensual son editables y aplican a cierres futuros (Req 8.5).
- La tarifa Anual puede editarse aquí, pero por diseño solo debe aplicarse antes de una
  renovación (Req 8.6). La congelación durante una suscripción anual vigente se enforcea en el
  motor de suscripción/liquidación (tasks 19-21), no en este endpoint.
"""

import logging
from datetime import datetime
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_admin
from app.core.utils import get_client_ip
from app.models.audit import ActionType
from app.models.billing import BillingOrgPlan, BillingRatePlan
from app.models.organization import Organization
from app.models.user import User
from app.services.audit import AuditService
from app.schemas.billing_rates import (
    OrgModeResponse,
    OrgModeUpdate,
    OrgPlanResponse,
    OrgPlanUpsert,
    RatePlanResponse,
    RatePlanUpdate,
)
logger = logging.getLogger(__name__)

router = APIRouter()


def _audit_safe(db: Session, **kwargs) -> None:
    """
    Registra una acción de auditoría sin romper la operación principal (fail-safe).

    La acción de negocio (cambio de modalidad, edición de tarifas) ya está commiteada antes de
    llamar a este helper; la auditoría es un registro adicional. Si la escritura del log falla,
    se hace `rollback` para dejar la sesión utilizable (una IntegrityError en el INSERT del log
    deja la transacción envenenada y rompería la serialización de la respuesta), se registra el
    error y se continúa (no se propaga). Como la acción principal YA fue commiteada, el rollback
    solo descarta el intento fallido de auditoría, no la acción de negocio. Sigue la convención
    del resto de endpoints auditados del proyecto. Los parámetros se pasan a `log_action`.
    """
    try:
        AuditService().log_action(db=db, **kwargs)
    except Exception as exc:  # noqa: BLE001 — la auditoría no debe tumbar la acción principal
        db.rollback()
        logger.error("No se pudo registrar la auditoría de facturación: %s", exc)


# ── Planes por defecto del sistema (superadmin) ──────────────────────────────


@router.get(
    "/rate-plans",
    response_model=List[RatePlanResponse],
    summary="Listar planes tarifarios por defecto (superadmin)",
)
def list_rate_plans(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Lista todos los planes por defecto del sistema (`is_default = True`), de ambas modalidades.

    Solo accesible para superadministradores (Req 8.1, 11.1). Se ordena por modalidad y por
    `effective_from` para facilitar la visualización de cambios programados en la UI.
    """
    plans = (
        db.query(BillingRatePlan)
        .filter(BillingRatePlan.is_default.is_(True))
        .order_by(
            BillingRatePlan.mode.asc(),
            BillingRatePlan.effective_from.asc().nullsfirst(),
            BillingRatePlan.created_at.asc(),
        )
        .all()
    )
    return plans


@router.put(
    "/rate-plans/{plan_id}",
    response_model=RatePlanResponse,
    summary="Editar/programar un plan tarifario por defecto (superadmin)",
)
def update_rate_plan(
    plan_id: UUID,
    payload: RatePlanUpdate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Edita o programa un plan por defecto del sistema (Req 8.1, 8.5, 11.1).

    Actualiza solo los campos enviados (`name`, `tiers`, `currency`, `effective_from`). Un
    `effective_from` en el futuro programa el cambio (el plan vigente sigue siendo el de mayor
    `effective_from` <= ahora, resuelto por `BillingService`). Editar un plan por defecto NO
    modifica ningún `billing_org_plans` (Req 8.8).

    La modalidad (`mode`) del plan por defecto NO se cambia aquí: un plan es mensual o anual de
    forma fija; editar tramos de otra modalidad se hace sobre el plan correspondiente.
    """
    plan = (
        db.query(BillingRatePlan)
        .filter(
            BillingRatePlan.id == plan_id,
            BillingRatePlan.is_default.is_(True),
        )
        .first()
    )
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan tarifario por defecto con ID {plan_id} no encontrado",
        )

    # Captura de valores anteriores para la auditoría (antes de mutar, Req 11.4).
    old_values = {
        "name": plan.name,
        "tiers": plan.tiers,
        "currency": plan.currency,
        "effective_from": plan.effective_from,
        "mode": plan.mode,
    }

    # Solo se aplican los campos explícitamente enviados (exclude_unset).
    update_data = payload.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] is not None:
        plan.name = update_data["name"]
    if "tiers" in update_data and update_data["tiers"] is not None:
        plan.tiers = update_data["tiers"]
    if "currency" in update_data and update_data["currency"] is not None:
        plan.currency = update_data["currency"].upper()
    if "effective_from" in update_data:
        # Puede ser None (vigente de inmediato) o un datetime programado.
        plan.effective_from = update_data["effective_from"]

    plan.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(plan)

    logger.info(
        "Plan tarifario por defecto actualizado: id=%s, mode=%s, por user=%s",
        plan.id,
        plan.mode,
        current_user.id,
    )

    # Auditoría de edición de tarifas por defecto (Req 11.4). El plan por defecto es global
    # (no pertenece a una organización): organization_id = None.
    _audit_safe(
        db=db,
        action_type=ActionType.RATE_PLAN_EDIT,
        entity_type="BillingRatePlan",
        entity_id=str(plan.id),
        user_id=str(current_user.id),
        organization_id=None,
        old_values=old_values,
        new_values={
            "name": plan.name,
            "tiers": plan.tiers,
            "currency": plan.currency,
            "effective_from": plan.effective_from,
            "mode": plan.mode,
            "scope": "default",
        },
        ip_address=get_client_ip(request),
    )
    return plan


# ── Plan individual por organización (superadmin) ────────────────────────────


@router.put(
    "/organizations/{org_id}/plan",
    response_model=OrgPlanResponse,
    summary="Crear/actualizar el plan individual de una organización (superadmin)",
)
def upsert_org_plan(
    org_id: UUID,
    payload: OrgPlanUpsert,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Crea o actualiza el plan tarifario individual de una organización para una modalidad
    (Req 8.2, 8.8, 11.1).

    Hay a lo sumo una fila por `(organization_id, mode)`: si ya existe, se actualiza; si no, se
    crea. Este plan tiene prioridad sobre el plan por defecto en la resolución de tarifas
    (`BillingService.resolve_plan`), y como es una fila separada, los cambios de defaults nunca
    lo sobrescriben (Req 8.8). Tenant isolation: se filtra/escribe por `organization_id`.
    """
    # Verificar que la organización existe (tenant scope explícito).
    organization = db.query(Organization).filter(Organization.id == org_id).first()
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organización con ID {org_id} no encontrada",
        )

    # Buscar plan existente de la org para esa modalidad (a lo sumo uno por modalidad).
    org_plan = (
        db.query(BillingOrgPlan)
        .filter(
            BillingOrgPlan.organization_id == org_id,
            BillingOrgPlan.mode == payload.mode,
        )
        .order_by(BillingOrgPlan.created_at.desc())
        .first()
    )

    if org_plan is None:
        # Crear nuevo plan individual para la organización.
        was_created = True
        old_values = None
        org_plan = BillingOrgPlan(
            organization_id=org_id,
            mode=payload.mode,
            tiers=payload.tiers,
            currency=payload.currency.upper(),
            effective_from=payload.effective_from,
        )
        db.add(org_plan)
        logger.info(
            "Plan de organización creado: org=%s, mode=%s, por user=%s",
            org_id,
            payload.mode,
            current_user.id,
        )
    else:
        # Actualizar el plan existente de esa modalidad. Capturamos el estado previo para
        # la auditoría antes de mutar (Req 11.4).
        was_created = False
        old_values = {
            "tiers": org_plan.tiers,
            "currency": org_plan.currency,
            "effective_from": org_plan.effective_from,
            "mode": org_plan.mode,
        }
        org_plan.tiers = payload.tiers
        org_plan.currency = payload.currency.upper()
        org_plan.effective_from = payload.effective_from
        org_plan.updated_at = datetime.utcnow()
        logger.info(
            "Plan de organización actualizado: id=%s, org=%s, mode=%s, por user=%s",
            org_plan.id,
            org_id,
            payload.mode,
            current_user.id,
        )

    db.commit()
    db.refresh(org_plan)

    # Auditoría de edición de tarifas de organización (Req 11.4). Tenant isolation:
    # organization_id = org_id. Se distingue creación de actualización en new_values.
    _audit_safe(
        db=db,
        action_type=ActionType.RATE_PLAN_EDIT,
        entity_type="BillingOrgPlan",
        entity_id=str(org_plan.id),
        user_id=str(current_user.id),
        organization_id=str(org_id),
        old_values=old_values,
        new_values={
            "tiers": org_plan.tiers,
            "currency": org_plan.currency,
            "effective_from": org_plan.effective_from,
            "mode": org_plan.mode,
            "scope": "organization",
            "operation": "create" if was_created else "update",
        },
        ip_address=get_client_ip(request),
    )
    return org_plan


# ── Modalidad de facturación de la organización (superadmin) ─────────────────


@router.put(
    "/organizations/{org_id}/mode",
    response_model=OrgModeResponse,
    summary="Fijar la modalidad de facturación de una organización (superadmin)",
)
def set_org_mode(
    org_id: UUID,
    payload: OrgModeUpdate,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Fija la modalidad de facturación de una organización a 'monthly' o 'annual' (Req 4.1).

    Solo accesible para superadministradores (Req 11.1). El enum de la modalidad se valida en
    el schema (`OrgModeUpdate`), por lo que un valor fuera de ('monthly', 'annual') se rechaza
    con 422 antes de llegar aquí. Tenant isolation: la organización se lee/escribe por su id.

    Notas de diseño (Req 4.6): `billing_mode` tiene `server_default = 'monthly'`, de modo que
    una organización recién creada ya nace con una modalidad segura por defecto; este endpoint
    permite al superadministrador cambiarla explícitamente. Se permite alternar monthly↔annual
    sin más restricciones: en modalidad anual los invoices mensuales se emiten en 0.00 y la
    suscripción/liquidación se gestiona por separado (tasks 19-20), sin acoplar esa lógica aquí.
    """
    organization = db.query(Organization).filter(Organization.id == org_id).first()
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organización con ID {org_id} no encontrada",
        )

    old_mode = organization.billing_mode
    organization.billing_mode = payload.mode
    organization.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(organization)

    logger.info(
        "Modalidad de facturación actualizada: org=%s, %s -> %s, por user=%s",
        org_id,
        old_mode,
        organization.billing_mode,
        current_user.id,
    )

    # Auditoría del cambio de modalidad (Req 11.4). Tenant isolation por org_id.
    _audit_safe(
        db=db,
        action_type=ActionType.BILLING_MODE_CHANGE,
        entity_type="Organization",
        entity_id=str(organization.id),
        user_id=str(current_user.id),
        organization_id=str(organization.id),
        old_values={"billing_mode": old_mode},
        new_values={"billing_mode": organization.billing_mode},
        ip_address=get_client_ip(request),
    )
    return OrgModeResponse(
        organization_id=organization.id,
        billing_mode=organization.billing_mode,
    )
