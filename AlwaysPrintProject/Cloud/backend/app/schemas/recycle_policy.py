"""
Schemas Pydantic para la Política de Reciclaje (recycle-policy-config, task 8.1).

Definen la validación de entrada/salida de los endpoints de gestión de la Recycle_Policy
(solo Superadmin, task 8.2):
- `RecyclePolicyIn`: payload de edición del Global_Default o de un Org_Override.
- `RecyclePolicyOut`: representación de lectura de una política persistida.

Esta es la PRIMERA capa de validación (Req 7.6): el schema valida el formato de la
Recycle_Rule y los rangos declarativos (`ephemeral_hours`, año y mes del
Effective_From_Period) ANTES de invocar al servicio, que RE-VALIDA de forma independiente
con `validate_policy` (Req 7.6/7.9). Por eso el `field_validator` de `rule` solo comprueba
el FORMATO (tres enteros con signo explícito separados por "/"), reutilizando
`parse_recycle_rule` del servicio; las reglas semánticas (orden `cutoff > cut1 >= cut2`,
`cutoff >= +1`, offsets en `[-24, +1]`) las agrega `validate_policy` en el servicio para
poder reportar TODAS las violaciones juntas (Req 7.7).

Nota de imports: `recycle_policy_service` solo importa de `app.core`, `app.models` y
SQLAlchemy, por lo que reutilizar `parse_recycle_rule`/`format_recycle_rule` aquí no
introduce un ciclo de imports (el servicio no importa schemas).
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.services.recycle_policy_service import (
    RecyclePolicyValidationException,
    format_recycle_rule,
    parse_recycle_rule,
)


class RecyclePolicyIn(BaseModel):
    """
    Payload de edición de una Recycle_Policy (Global_Default u Org_Override).

    La Recycle_Rule se recibe como string tipo `"+1/-2/-3"` (tres enteros con signo explícito
    separados por "/", Req 1.3/7.1) y se valida de FORMATO en el schema; el servicio la
    re-parsea y valida su semántica (orden, rangos) antes de persistir (Req 7.6). El
    Effective_From_Period se recibe descompuesto en año/mes con sus rangos declarativos
    (Req 3.1/7.8) y el umbral de uso efímero en horas (Req 7.5).

    Atributos:
        rule: Recycle_Rule string `"+1/-2/-3"` (formato validado por `parse_recycle_rule`).
        ephemeral_hours: umbral de uso efímero en horas, en `[1, 168]` (Req 7.5).
        effective_from_year: año del Effective_From_Period, en `[2000, 2999]` (Req 3.1/7.8).
        effective_from_month: mes del Effective_From_Period, en `[1, 12]` (Req 3.1/7.8).
    """

    rule: str = Field(
        ...,
        description='Recycle_Rule con signo explícito, formato "+1/-2/-3"',
    )
    ephemeral_hours: int = Field(
        ...,
        ge=1,
        le=168,
        description="Umbral de uso efímero en horas [1, 168]",
    )
    effective_from_year: int = Field(
        ...,
        ge=2000,
        le=2999,
        description="Año del Effective_From_Period [2000, 2999]",
    )
    effective_from_month: int = Field(
        ...,
        ge=1,
        le=12,
        description="Mes del Effective_From_Period [1, 12]",
    )

    @field_validator("rule")
    @classmethod
    def _check_rule_format(cls, v: str) -> str:
        """
        Valida SOLO el formato de la Recycle_Rule (tres enteros con signo explícito, Req 7.1).

        Reutiliza `parse_recycle_rule` del servicio (única fuente de verdad del formato). Si el
        string no parsea, traduce la `RecyclePolicyValidationException` a un `ValueError` para
        que Pydantic devuelva un 422 con el mensaje de la regla de formato. La semántica (orden,
        rangos de offset) NO se valida aquí: la agrega `validate_policy` en el servicio para
        reportar todas las violaciones juntas (Req 7.6/7.7).
        """
        try:
            parse_recycle_rule(v)
        except RecyclePolicyValidationException as exc:
            # exc.errors trae un único error rule="format"; se expone su mensaje en español.
            raise ValueError(exc.errors[0].message) from exc
        return v


class RecyclePolicyOut(BaseModel):
    """
    Representación de lectura de una Recycle_Policy persistida (Req 1.4/3.1/17.4).

    La Recycle_Rule se expone en formato string `"+1/-2/-3"` (Req 1.4) y el
    Effective_From_Period como `"AAAA-MM"` (Req 17.4). El `scope` deriva de `organization_id`:
    `"global"` cuando es NULL (Global_Default) u `"org"` cuando pertenece a una organización
    (Org_Override). Se construye con `from_model` a partir de una fila `BillingRecyclePolicy`.

    Atributos:
        id: id de la política (str).
        scope: "global" (Global_Default) | "org" (Org_Override).
        organization_id: id de la organización del Org_Override, o None para el Global_Default.
        rule: Recycle_Rule formateada `"+1/-2/-3"`.
        ephemeral_hours: umbral de uso efímero en horas.
        effective_from: Effective_From_Period como `"AAAA-MM"`.
        created_at: fecha de creación de la política.
    """

    id: str
    scope: str
    organization_id: Optional[str] = None
    rule: str
    ephemeral_hours: int
    effective_from: str
    created_at: datetime

    @classmethod
    def from_model(cls, policy) -> "RecyclePolicyOut":
        """
        Construye el schema de salida desde una fila `BillingRecyclePolicy`.

        Deriva el `scope` de `organization_id` (NULL => "global", si no => "org"), formatea la
        Recycle_Rule con `format_recycle_rule` (round-trip con `parse_recycle_rule`, Req 1.4) y
        arma el Effective_From_Period como `f"{year:04d}-{month:02d}"` (Req 17.4).

        Args:
            policy: fila `BillingRecyclePolicy` (modelo SQLAlchemy) ya persistida.

        Returns:
            La `RecyclePolicyOut` correspondiente.
        """
        is_global = policy.organization_id is None
        return cls(
            id=str(policy.id),
            scope="global" if is_global else "org",
            organization_id=None if is_global else str(policy.organization_id),
            rule=format_recycle_rule(
                policy.cutoff_offset,
                policy.cut1_offset,
                policy.cut2_offset,
            ),
            ephemeral_hours=policy.ephemeral_hours,
            effective_from=(
                f"{policy.effective_from_year:04d}-{policy.effective_from_month:02d}"
            ),
            created_at=policy.created_at,
        )
