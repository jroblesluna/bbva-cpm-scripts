"""
Modelos SQLAlchemy para el módulo de facturación (Usage and Billing).

Este módulo define las tablas que sustentan la facturación por IP privada registrada:
- BillingRatePlan: tarifas por defecto del sistema (editables por superadmin).
- BillingOrgPlan: plan tarifario individual asignado a una organización por modalidad.
- BillingClosure: cabecera de cierre mensual (una por organización/año/mes).
- BillingClosureItem: detalle por IP de un cierre (sustento inmutable).
- BillingAnnualSubscription: suscripción anual y su liquidación informativa.
- BillingClosureReport: artefacto derivado (análisis IA + PDF cacheado) 1:1 por cierre.

Todas las tablas están aisladas por organización (tenant isolation) mediante organization_id.
Se reutiliza el tipo GUID definido en app.models.organization para compatibilidad
SQLite/PostgreSQL.
"""

import uuid
from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    JSON,
    Text,
    UniqueConstraint,
)

from app.core.database import Base
from app.models.organization import GUID  # Reutilizar tipo GUID para consistencia


class BillingRatePlan(Base):
    """
    Tarifas por defecto del sistema, editables únicamente por superadministradores.

    Almacena los tramos (tiers) serializados en JSON ordenados por rango:
    - monthly: [{"from": 1, "to": 100, "rate": 0.500}, ...]  (incremental por tramos)
    - annual:  [{"from": 1, "to": 100, "rate": 5.00, "free_growth_to": 200}, ...]
    """
    __tablename__ = "billing_rate_plans"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    mode = Column(String(16), nullable=False)  # 'monthly' | 'annual'
    is_default = Column(Boolean, nullable=False, default=True)  # plan por defecto del sistema
    name = Column(String(100), nullable=False)
    # Tramos serializados como JSON ordenado por rango
    tiers = Column(JSON, nullable=False)
    currency = Column(String(3), nullable=False, server_default="USD")
    # Para cambios programados de defaults (nullable = vigente de inmediato)
    effective_from = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<BillingRatePlan(id={self.id}, mode={self.mode}, is_default={self.is_default})>"


class BillingOrgPlan(Base):
    """
    Plan tarifario individual asignado a una organización por modalidad.

    Si una organización tiene un BillingOrgPlan para la modalidad, se usa este;
    si no, se usa el BillingRatePlan por defecto vigente. Los cambios de defaults NO
    sobrescriben planes de organización (Req 8.8). Para la modalidad anual, los tramos
    se congelan durante la vigencia de la suscripción.
    """
    __tablename__ = "billing_org_plans"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        GUID,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mode = Column(String(16), nullable=False)  # 'monthly' | 'annual'
    # Copia congelable del plan aplicado (tramos)
    tiers = Column(JSON, nullable=False)
    currency = Column(String(3), nullable=False, server_default="USD")
    # Para anual: la tarifa se congela; effective para próxima renovación
    effective_from = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<BillingOrgPlan(id={self.id}, organization_id={self.organization_id}, mode={self.mode})>"


class BillingClosure(Base):
    """
    Cabecera de cierre mensual (una por organización/año/mes).

    Contiene los totales por estado, el monto calculado y los tramos aplicados. El
    UniqueConstraint (organization_id, period_year, period_month) garantiza la idempotencia
    del cierre (Req 7.6): un mes ya cerrado no puede volver a cerrarse.
    """
    __tablename__ = "billing_closures"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        GUID,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_year = Column(Integer, nullable=False)
    period_month = Column(Integer, nullable=False)  # 1..12 (mes M cerrado)
    # 00:00 del día 1 de M+1 en tz org (guardado en UTC)
    cutoff_at = Column(DateTime, nullable=False)
    mode = Column(String(16), nullable=False)  # modalidad al momento del cierre
    timezone = Column(String(50), nullable=False)  # tz usada
    total_billable = Column(Integer, nullable=False)
    total_recycled = Column(Integer, nullable=False)
    total_archived = Column(Integer, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)  # monto del mes (0.00 si anual vigente)
    tiers_applied = Column(JSON, nullable=False)  # desglose por tramo
    is_retroactive = Column(Boolean, nullable=False, default=False)
    created_by_id = Column(GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "period_year",
            "period_month",
            name="uq_closure_org_period",
        ),  # idempotencia
    )

    def __repr__(self):
        return (
            f"<BillingClosure(id={self.id}, organization_id={self.organization_id}, "
            f"period={self.period_year}-{self.period_month:02d})>"
        )


class BillingClosureItem(Base):
    """
    Detalle por IP de un cierre (sustento inmutable).

    Una fila por workstation incluida en el corte. workstation_id es nullable porque la
    workstation puede eliminarse físicamente después del cierre; ip_private y el resto de
    datos se conservan como sustento histórico.
    """
    __tablename__ = "billing_closure_items"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    closure_id = Column(
        GUID,
        ForeignKey("billing_closures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workstation_id = Column(GUID, nullable=True)  # nullable: puede borrarse la ws luego
    ip_private = Column(String(45), nullable=False)
    created_at_ws = Column(DateTime, nullable=False)  # created_at de la workstation
    last_seen_capped = Column(DateTime, nullable=False)  # last_seen capado a M+1
    billing_status = Column(String(16), nullable=False)  # estado en ESE cierre
    tier_index = Column(Integer, nullable=True)  # tramo aplicado (mensual)
    amount = Column(Numeric(12, 4), nullable=False, server_default="0")  # aporte de esta IP

    def __repr__(self):
        return (
            f"<BillingClosureItem(id={self.id}, closure_id={self.closure_id}, "
            f"ip_private={self.ip_private}, billing_status={self.billing_status})>"
        )


class BillingAnnualSubscription(Base):
    """
    Suscripción anual y su liquidación informativa.

    Registra el volumen declarado y la tarifa/tramo congelados al inicio de la vigencia. La
    liquidación (crédito/cargo) se calcula en el aniversario y se guarda en settlement; su
    aplicación requiere confirmación manual del superadministrador (status pasa a 'settled').
    """
    __tablename__ = "billing_annual_subscriptions"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    organization_id = Column(
        GUID,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_date = Column(DateTime, nullable=False)  # created_at del primer registro
    end_date = Column(DateTime, nullable=False)  # 1 día antes del aniversario
    declared_volume = Column(Integer, nullable=False)  # input manual superadmin
    tier_rate = Column(Numeric(12, 4), nullable=False)  # tarifa congelada del tramo
    tier_from = Column(Integer, nullable=False)
    tier_to = Column(Integer, nullable=True)  # null = último tramo (sin tope superior de tramo)
    tier_cap = Column(Integer, nullable=True)  # tope contabilizable (ej. 10000)
    status = Column(String(16), nullable=False, server_default="active")  # active|settled
    settlement = Column(JSON, nullable=True)  # {declared, real, diff, credit, charge}
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return (
            f"<BillingAnnualSubscription(id={self.id}, "
            f"organization_id={self.organization_id}, status={self.status})>"
        )


class BillingClosureReport(Base):
    """
    Artefacto derivado del cierre (análisis IA + PDF cacheado), 1:1 con el cierre.

    Se modela como tabla auxiliar (no como columnas sobre billing_closures) para NO
    contaminar el sustento inmutable de la factura con datos derivados/mutables: el
    análisis IA puede regenerarse y el PDF puede recomputarse. Regenerar hace UPDATE/UPSERT
    aquí, nunca sobre el cierre (evita reescrituras/locks sobre la tabla de facturación).

    El UniqueConstraint sobre closure_id garantiza la relación 1:1 y la FK ON DELETE CASCADE
    asegura que borrar el cierre padre elimine su reporte. organization_id se desnormaliza
    (indexado) para tenant isolation y tareas de limpieza. ai_analysis NULL significa que la
    IA no está disponible (fail-safe): un fallo del LLM nunca bloquea la generación del PDF.
    """
    __tablename__ = "billing_closure_reports"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    closure_id = Column(
        GUID,
        ForeignKey("billing_closures.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # relación 1:1 con el cierre
    )
    organization_id = Column(
        GUID,
        nullable=False,
        index=True,  # desnormalizado para tenant isolation / limpieza
    )
    ai_analysis = Column(Text, nullable=True)  # NULL = IA no disponible (fail-safe)
    ai_model = Column(String(100), nullable=True)  # id del modelo LLM usado (bedrock/openai)
    ai_generated_at = Column(DateTime, nullable=True)
    pdf_s3_key = Column(String(512), nullable=True)  # key determinista cacheada
    pdf_generated_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return (
            f"<BillingClosureReport(id={self.id}, closure_id={self.closure_id}, "
            f"organization_id={self.organization_id})>"
        )
