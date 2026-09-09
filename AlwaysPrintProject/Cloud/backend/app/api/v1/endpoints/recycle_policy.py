"""
Endpoints de gestión de la Política de Reciclaje (recycle-policy-config, task 8.2) —
solo superadministrador.

Expone la lectura y edición de la Recycle_Policy del módulo Usage and Billing:
- GET  /billing/recycle-policy/global                  → lista las políticas Global_Default.
- PUT  /billing/recycle-policy/global                  → crea/reemplaza un Global_Default.
- GET  /billing/recycle-policy/org/{organization_id}   → lista los Org_Override de una org.
- PUT  /billing/recycle-policy/org/{organization_id}   → crea/reemplaza un Org_Override.

Permisos (Req 17.1/17.2): los cuatro endpoints exigen rol de superadministrador. En este
sistema el rol de mayor privilegio es `UserRole.ADMIN` (acceso global, `organization_id = None`);
se reutiliza la dependencia `require_admin` para enforcar el 403, igual que en `billing_rates.py`.
NO existe un símbolo `require_superadmin`.

Doble capa de validación (Req 7.6): el schema `RecyclePolicyIn` valida el FORMATO de la
Recycle_Rule y los rangos declarativos (año/mes, `ephemeral_hours`) devolviendo 422 antes de
llegar al handler; luego el servicio `recycle_policy_service.upsert_policy` RE-VALIDA la
semántica (orden `cutoff > cut1 >= cut2`, `cutoff >= +1`, offsets en `[-24, +1]`) vía
`validate_policy` y persiste. Ante violaciones de regla, el handler traduce la
`RecyclePolicyValidationException` a un 422 con una lista EXPLÍCITA de errores por regla
(Req 17.5).

Auditoría: `upsert_policy` registra el `BILLING_RECYCLE_POLICY_CHANGE` dentro de su propia
transacción (fail-closed). Por eso los handlers NO auditan de nuevo (no hay doble auditoría).

Aislamiento (tenant isolation): los Org_Override se leen/escriben SIEMPRE filtrando por
`organization_id`; el Global_Default se identifica con `organization_id IS NULL`.
"""

import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_admin
from app.models.billing import BillingRecyclePolicy
from app.models.organization import Organization
from app.models.user import User
from app.schemas.recycle_policy import RecyclePolicyIn, RecyclePolicyOut
from app.services.recycle_policy_service import (
    ClosedPeriodConflictError,
    RecyclePolicyResolutionError,
    RecyclePolicyValidationException,
    recycle_policy_service,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _raise_policy_errors(exc: Exception) -> None:
    """
    Traduce las excepciones fail-closed del servicio a `HTTPException` (Req 17.5/5.3).

    - `RecyclePolicyValidationException` → 422 con `detail={"errors": [{"rule", "message"}, ...]}`,
      es decir una lista EXPLÍCITA de errores, una por cada regla violada (Req 17.5). La
      política previamente persistida queda intacta (fail-closed, Req 7.9).
    - `ClosedPeriodConflictError` → 409: el cambio afectaría periodos ya cerrados e inmutables
      y por eso no se persiste (Req 5.3).
    - `RecyclePolicyResolutionError` → 409: estado ambiguo (empate en el tope efectivo) que
      impide resolver la política de forma inequívoca (Req 3.3).

    Se re-lanza siempre una `HTTPException`; el llamador solo tiene que invocar este helper
    dentro del `except`.
    """
    if isinstance(exc, RecyclePolicyValidationException):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "errors": [
                    {"rule": e.rule, "message": e.message} for e in exc.errors
                ]
            },
        )
    if isinstance(exc, ClosedPeriodConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    if isinstance(exc, RecyclePolicyResolutionError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    # Cualquier otra excepción se propaga sin traducir (fallo inesperado → 500).
    raise exc


# ── Global_Default (superadmin) ──────────────────────────────────────────────


@router.get(
    "/recycle-policy/global",
    response_model=List[RecyclePolicyOut],
    summary="Listar las políticas de reciclaje Global_Default (superadmin)",
)
def list_global_policies(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Lista todas las políticas Global_Default (`organization_id IS NULL`), Req 17.1/8.1.

    Se ordena por `effective_key` descendente para que la política más reciente (mayor periodo
    efectivo) aparezca primero, facilitando la visualización del versionado en la UI. Cada fila
    se serializa con `RecyclePolicyOut.from_model` (regla `"+1/-2/-3"`, `effective_from`
    `"AAAA-MM"`, Req 17.4). Solo accesible para superadministradores (Req 17.2).
    """
    rows = (
        db.query(BillingRecyclePolicy)
        .filter(BillingRecyclePolicy.organization_id.is_(None))
        .order_by(BillingRecyclePolicy.effective_key.desc())
        .all()
    )
    return [RecyclePolicyOut.from_model(p) for p in rows]


@router.put(
    "/recycle-policy/global",
    response_model=RecyclePolicyOut,
    summary="Crear/reemplazar la política de reciclaje Global_Default (superadmin)",
)
def upsert_global_policy(
    payload: RecyclePolicyIn,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Crea o reemplaza un Global_Default para un Effective_From_Period (Req 17.1/8.1).

    El schema ya validó el FORMATO de la regla y los rangos declarativos (422); aquí el servicio
    RE-VALIDA la semántica y persiste con auditoría transaccional (doble capa, Req 7.6). El
    `organization_id=None` marca el scope global. `upsert_policy` registra la auditoría por sí
    mismo (no se audita aquí de nuevo). Ante fallo fail-closed, se traduce a la respuesta HTTP
    correspondiente (422 con errores por regla, 409 por conflicto).
    """
    try:
        policy = recycle_policy_service.upsert_policy(
            db,
            organization_id=None,
            rule_or_offsets=payload.rule,
            ephemeral_hours=payload.ephemeral_hours,
            eff_year=payload.effective_from_year,
            eff_month=payload.effective_from_month,
            actor_id=str(current_user.id),
        )
    except (
        RecyclePolicyValidationException,
        ClosedPeriodConflictError,
        RecyclePolicyResolutionError,
    ) as exc:
        _raise_policy_errors(exc)

    logger.info(
        "Política de reciclaje Global_Default actualizada: id=%s, por user=%s",
        policy.id,
        current_user.id,
    )
    return RecyclePolicyOut.from_model(policy)


# ── Org_Override (superadmin) ────────────────────────────────────────────────


@router.get(
    "/recycle-policy/org/{organization_id}",
    response_model=List[RecyclePolicyOut],
    summary="Listar los Org_Override de reciclaje de una organización (superadmin)",
)
def list_org_policies(
    organization_id: UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Lista los Org_Override de reciclaje de una organización (Req 17.1/8.1).

    Verifica primero que la organización exista (404 si no). Luego lista sus políticas con
    tenant isolation (`organization_id == org.id`), ordenadas por `effective_key` descendente.
    Cada fila se serializa con `RecyclePolicyOut.from_model` (Req 17.4). Solo superadmin
    (Req 17.2).
    """
    organization = (
        db.query(Organization)
        .filter(Organization.id == organization_id)
        .first()
    )
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organización con ID {organization_id} no encontrada",
        )

    rows = (
        db.query(BillingRecyclePolicy)
        .filter(BillingRecyclePolicy.organization_id == organization_id)
        .order_by(BillingRecyclePolicy.effective_key.desc())
        .all()
    )
    return [RecyclePolicyOut.from_model(p) for p in rows]


@router.put(
    "/recycle-policy/org/{organization_id}",
    response_model=RecyclePolicyOut,
    summary="Crear/reemplazar un Org_Override de reciclaje (superadmin)",
)
def upsert_org_policy(
    organization_id: UUID,
    payload: RecyclePolicyIn,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Crea o reemplaza un Org_Override de reciclaje para una organización (Req 17.1/8.1/2.5).

    Verifica primero que la organización exista (404 si no). El schema ya validó formato/rangos
    (422); el servicio RE-VALIDA la semántica y persiste con auditoría transaccional (doble
    capa, Req 7.6). El `organization_id` fija el scope del override (tenant isolation).
    `upsert_policy` audita por sí mismo (no se audita aquí de nuevo). Ante fallo fail-closed se
    traduce a 422 (errores por regla) o 409 (conflicto con cierres).
    """
    organization = (
        db.query(Organization)
        .filter(Organization.id == organization_id)
        .first()
    )
    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organización con ID {organization_id} no encontrada",
        )

    try:
        policy = recycle_policy_service.upsert_policy(
            db,
            organization_id=str(organization_id),
            rule_or_offsets=payload.rule,
            ephemeral_hours=payload.ephemeral_hours,
            eff_year=payload.effective_from_year,
            eff_month=payload.effective_from_month,
            actor_id=str(current_user.id),
        )
    except (
        RecyclePolicyValidationException,
        ClosedPeriodConflictError,
        RecyclePolicyResolutionError,
    ) as exc:
        _raise_policy_errors(exc)

    logger.info(
        "Org_Override de reciclaje actualizado: org=%s, id=%s, por user=%s",
        organization_id,
        policy.id,
        current_user.id,
    )
    return RecyclePolicyOut.from_model(policy)
