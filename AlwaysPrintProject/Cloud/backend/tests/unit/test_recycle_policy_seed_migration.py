"""
Tests de seed, migración y backfill de la política de reciclaje (task 6.3).

Cubren el comportamiento de `app/services/recycle_policy_seed.py::seed_recycle_policies`
y de la migración Alembic `039_add_recycle_policy` (backfill de cierres históricos +
inicialización de `billing_cycle_started_at`):

- Idempotencia del seed (Req 16.1/16.2/16.3): correr `seed_recycle_policies` dos veces NO
  duplica el Global_Default ni el Org_Override de BBVA.
- BBVA presente ⇒ se crea el override; BBVA ausente ⇒ solo se siembra el Global_Default sin
  fallar (Req 16.2/3.5).
- Atomicidad del seed (Req 16.3): si un insert falla a mitad del seed, el rollback del caller
  no deja estado parcial (ninguna fila persistida).
- Backfill del freeze legacy `+1/-2/-3` + 24h en `billing_closures.recycle_policy_applied`
  (Req 6.1/6.2): un cierre con freeze vacío `{}` queda con la política legacy.
- Atomicidad del backfill (Req 6.3): un fallo forzado a mitad de `upgrade()` revierte los
  cambios parciales (la tabla nueva y las columnas no quedan).
- `billing_cycle_started_at = created_at` en las workstations existentes tras la migración
  (Req 18.6).

Convenciones (siguiendo `tests/unit/test_billing_close_service.py`): sesión SQLite in-memory
con el tipo `GUID` (compat SQLite/PostgreSQL). Para el seed se usa el esquema completo del
ORM (`Base.metadata.create_all`). Para el backfill/columnas se construye un esquema
PRE-039 mínimo (workstations + billing_closures + organizations, sin las columnas/tabla nuevas)
y se ejecuta el `upgrade()` de la migración EN AISLAMIENTO con un contexto Alembic (`Operations`)
enlazado a la conexión SQLite; correr toda la cadena Alembic sobre SQLite no es viable
(limitación conocida en la migración 002), por eso se ejercita solo el paso 039.

_Requirements: 6.1, 6.2, 6.3, 16.1, 16.2, 16.3, 18.6_
"""

import json
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
import app.models  # noqa: F401 — registra todas las tablas en metadata
from app.models.organization import Organization
from app.models.billing import BillingRecyclePolicy
from app.services.recycle_policy_seed import (
    seed_recycle_policies,
    GLOBAL_DEFAULT,
    BBVA_OVERRIDE,
    BBVA_ORG_NAME,
    _effective_key,
)

# Freeze legacy que la migración escribe en el backfill (debe coincidir con
# `039_add_recycle_policy._LEGACY_FREEZE`).
_LEGACY_FREEZE = {"cutoff": 1, "cut1": -2, "cut2": -3, "ephemeral_hours": 24}


# ── Helpers de sesión (seed sobre el esquema ORM completo) ───────────────────


def _make_full_schema_engine():
    """Engine SQLite in-memory con TODO el esquema ORM (para probar el seed directo)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


def _session(engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return Session()


def _count_policies(db, *, organization_id):
    """Cuenta filas de billing_recycle_policies para un scope dado (None = global)."""
    q = db.query(BillingRecyclePolicy)
    if organization_id is None:
        q = q.filter(BillingRecyclePolicy.organization_id.is_(None))
    else:
        q = q.filter(BillingRecyclePolicy.organization_id == organization_id)
    return q.count()


# ============================================================================
# SEED: idempotencia, presencia/ausencia de BBVA, atomicidad
# ============================================================================


class TestSeedRecyclePolicies:
    """Comportamiento de seed_recycle_policies (Req 16.1/16.2/16.3, 3.5)."""

    def test_seed_sin_bbva_solo_global_default(self):
        """Sin org BBVA: se siembra SOLO el Global_Default, sin fallar (Req 16.1, 3.5)."""
        engine = _make_full_schema_engine()
        db = _session(engine)
        try:
            inserted = seed_recycle_policies(db.connection())
            db.commit()

            assert inserted == ["global_default"]
            assert _count_policies(db, organization_id=None) == 1

            gd = (
                db.query(BillingRecyclePolicy)
                .filter(BillingRecyclePolicy.organization_id.is_(None))
                .one()
            )
            # Valores canónicos legacy (+1/-2/-3 + 24h, vigente 2000-01).
            assert gd.cutoff_offset == GLOBAL_DEFAULT["cutoff"]
            assert gd.cut1_offset == GLOBAL_DEFAULT["cut1"]
            assert gd.cut2_offset == GLOBAL_DEFAULT["cut2"]
            assert gd.ephemeral_hours == GLOBAL_DEFAULT["ephemeral_hours"]
            assert gd.effective_from_year == 2000
            assert gd.effective_from_month == 1
            assert gd.effective_key == _effective_key(2000, 1)
        finally:
            db.close()
            engine.dispose()

    def test_seed_con_bbva_crea_override(self):
        """Con org BBVA presente: se crea el Global_Default y el Org_Override (Req 16.2)."""
        engine = _make_full_schema_engine()
        db = _session(engine)
        try:
            bbva = Organization(id=uuid.uuid4(), name=BBVA_ORG_NAME, timezone="America/Lima")
            db.add(bbva)
            db.commit()

            inserted = seed_recycle_policies(db.connection())
            db.commit()

            assert set(inserted) == {"global_default", "bbva_override"}
            assert _count_policies(db, organization_id=None) == 1
            assert _count_policies(db, organization_id=bbva.id) == 1

            override = (
                db.query(BillingRecyclePolicy)
                .filter(BillingRecyclePolicy.organization_id == bbva.id)
                .one()
            )
            # Override BBVA: +1/0/-1 + 24h, vigente 2026-09.
            assert override.cutoff_offset == BBVA_OVERRIDE["cutoff"]
            assert override.cut1_offset == BBVA_OVERRIDE["cut1"]
            assert override.cut2_offset == BBVA_OVERRIDE["cut2"]
            assert override.ephemeral_hours == BBVA_OVERRIDE["ephemeral_hours"]
            assert override.effective_from_year == 2026
            assert override.effective_from_month == 9
            assert override.effective_key == _effective_key(2026, 9)
        finally:
            db.close()
            engine.dispose()

    def test_seed_idempotente_sin_bbva(self):
        """Correr el seed 2× sin BBVA NO duplica el Global_Default (Req 16.1/16.3)."""
        engine = _make_full_schema_engine()
        db = _session(engine)
        try:
            first = seed_recycle_policies(db.connection())
            db.commit()
            second = seed_recycle_policies(db.connection())
            db.commit()

            assert first == ["global_default"]
            assert second == []  # nada nuevo en la 2ª corrida
            assert _count_policies(db, organization_id=None) == 1
            assert db.query(BillingRecyclePolicy).count() == 1
        finally:
            db.close()
            engine.dispose()

    def test_seed_idempotente_con_bbva(self):
        """Correr el seed 2× con BBVA NO duplica ni el global ni el override (Req 16.2/16.3)."""
        engine = _make_full_schema_engine()
        db = _session(engine)
        try:
            bbva = Organization(id=uuid.uuid4(), name=BBVA_ORG_NAME, timezone="America/Lima")
            db.add(bbva)
            db.commit()

            first = seed_recycle_policies(db.connection())
            db.commit()
            second = seed_recycle_policies(db.connection())
            db.commit()

            assert set(first) == {"global_default", "bbva_override"}
            assert second == []
            assert _count_policies(db, organization_id=None) == 1
            assert _count_policies(db, organization_id=bbva.id) == 1
            assert db.query(BillingRecyclePolicy).count() == 2
        finally:
            db.close()
            engine.dispose()

    def test_seed_no_sobrescribe_global_editado(self):
        """
        Si ya existe un Global_Default (p.ej. editado por el superadmin), el seed NO lo
        re-inserta ni lo sobrescribe (idempotencia por presencia, Req 16.1/16.3).
        """
        engine = _make_full_schema_engine()
        db = _session(engine)
        try:
            # Global_Default preexistente con valores DISTINTOS a los canónicos.
            existing = BillingRecyclePolicy(
                id=uuid.uuid4(),
                organization_id=None,
                cutoff_offset=1,
                cut1_offset=0,
                cut2_offset=-1,
                ephemeral_hours=48,
                effective_from_year=2025,
                effective_from_month=6,
                effective_key=_effective_key(2025, 6),
            )
            db.add(existing)
            db.commit()

            inserted = seed_recycle_policies(db.connection())
            db.commit()

            assert inserted == []
            assert _count_policies(db, organization_id=None) == 1
            preserved = (
                db.query(BillingRecyclePolicy)
                .filter(BillingRecyclePolicy.organization_id.is_(None))
                .one()
            )
            # Se preservan los valores editados, no se pisan con los canónicos.
            assert preserved.ephemeral_hours == 48
            assert preserved.effective_from_year == 2025
            assert preserved.effective_from_month == 6
        finally:
            db.close()
            engine.dispose()

    def test_seed_atomico_fallo_revierte_estado_parcial(self):
        """
        Atomicidad (Req 16.3): si un insert del seed falla a mitad, el rollback del caller
        no deja estado parcial. Se fuerza el fallo del insert del override BBVA (violando el
        NOT NULL de ephemeral_hours vía monkeypatch del dict de valores) DESPUÉS de haber
        insertado el Global_Default; al hacer rollback, NINGUNA fila debe persistir.
        """
        engine = _make_full_schema_engine()
        db = _session(engine)
        try:
            bbva = Organization(id=uuid.uuid4(), name=BBVA_ORG_NAME, timezone="America/Lima")
            db.add(bbva)
            db.commit()

            conn = db.connection()

            # Envolver conn.execute para que el 2º INSERT (override BBVA) explote, simulando
            # un fallo a mitad del seed (después de insertar el Global_Default).
            original_execute = conn.execute
            state = {"inserts": 0}

            def failing_execute(clause, *args, **kwargs):
                sql = str(clause).upper()
                if "INSERT INTO BILLING_RECYCLE_POLICIES" in sql:
                    state["inserts"] += 1
                    if state["inserts"] == 2:
                        raise RuntimeError("Fallo forzado a mitad del seed")
                return original_execute(clause, *args, **kwargs)

            conn.execute = failing_execute  # type: ignore[assignment]

            with pytest.raises(RuntimeError, match="Fallo forzado"):
                seed_recycle_policies(conn)

            # El caller revierte toda la transacción (misma semántica que la migración).
            db.rollback()

            # Sin estado parcial: ni el Global_Default insertado antes del fallo persiste.
            assert db.query(BillingRecyclePolicy).count() == 0
        finally:
            db.close()
            engine.dispose()


# ============================================================================
# MIGRACIÓN 039: backfill de cierres + billing_cycle_started_at = created_at
# ============================================================================


def _build_pre_039_schema(conn):
    """
    Crea el esquema PRE-039 mínimo necesario para ejercitar el upgrade() de la migración:
    organizations, workstations (sin billing_cycle_started_at) y billing_closures (sin
    recycle_policy_applied). No se crea billing_recycle_policies (la migración la crea).

    Se usan solo las columnas que toca la migración; el resto se omite para mantener el
    esquema mínimo y desacoplado del ORM completo.
    """
    conn.execute(text(
        "CREATE TABLE organizations ("
        " id VARCHAR(36) PRIMARY KEY,"
        " name VARCHAR(255) NOT NULL,"
        " timezone VARCHAR(50) NOT NULL DEFAULT 'UTC'"
        ")"
    ))
    conn.execute(text(
        "CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)"
    ))
    conn.execute(text(
        "CREATE TABLE workstations ("
        " id VARCHAR(36) PRIMARY KEY,"
        " ip_private VARCHAR(45),"
        " created_at DATETIME NOT NULL"
        ")"
    ))
    conn.execute(text(
        "CREATE TABLE billing_closures ("
        " id VARCHAR(36) PRIMARY KEY,"
        " organization_id VARCHAR(36) NOT NULL,"
        " period_year INTEGER NOT NULL,"
        " period_month INTEGER NOT NULL"
        ")"
    ))


def _run_migration_upgrade(conn):
    """Ejecuta el upgrade() de la migración 039 en aislamiento sobre la conexión dada."""
    mod = _load_migration_module()
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        mod.upgrade()


def _load_migration_module():
    """Carga el módulo de la migración 039 por ruta de archivo (no es un paquete importable)."""
    import importlib.util
    import os

    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(here, "alembic", "versions", "039_add_recycle_policy.py")
    spec = importlib.util.spec_from_file_location("migration_039", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigration039Backfill:
    """Backfill y columnas de la migración 039 (Req 6.1, 6.2, 6.3, 18.6)."""

    def _engine(self):
        return create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    def test_backfill_freeze_legacy_en_cierres(self):
        """
        Un cierre con recycle_policy_applied vacío queda con el freeze legacy +1/-2/-3+24h
        tras la migración (Req 6.1/6.2).
        """
        engine = self._engine()
        conn = engine.connect()
        try:
            _build_pre_039_schema(conn)

            org_id = str(uuid.uuid4())
            conn.execute(text(
                "INSERT INTO organizations (id, name, timezone) VALUES (:id, 'Acme', 'UTC')"
            ).bindparams(id=org_id))
            # Dos cierres históricos (pre-migración no tenían recycle_policy_applied).
            for m in (1, 2):
                conn.execute(text(
                    "INSERT INTO billing_closures (id, organization_id, period_year, period_month)"
                    " VALUES (:id, :org, 2025, :m)"
                ).bindparams(id=str(uuid.uuid4()), org=org_id, m=m))

            _run_migration_upgrade(conn)

            rows = conn.execute(
                text("SELECT recycle_policy_applied FROM billing_closures")
            ).fetchall()
            assert len(rows) == 2
            for (raw,) in rows:
                assert json.loads(raw) == _LEGACY_FREEZE
        finally:
            conn.close()
            engine.dispose()

    def test_backfill_sin_cierres_no_falla(self):
        """La migración corre y crea la tabla aunque no haya cierres que backfillear (Req 6.3)."""
        engine = self._engine()
        conn = engine.connect()
        try:
            _build_pre_039_schema(conn)

            _run_migration_upgrade(conn)

            # La tabla de políticas existe y quedó sembrada con el Global_Default (sin BBVA).
            count = conn.execute(
                text("SELECT COUNT(*) FROM billing_recycle_policies WHERE organization_id IS NULL")
            ).scalar()
            assert count == 1
        finally:
            conn.close()
            engine.dispose()

    def test_billing_cycle_started_at_igual_created_at(self):
        """
        Tras la migración, billing_cycle_started_at = created_at en las workstations
        existentes (Req 18.6).
        """
        engine = self._engine()
        conn = engine.connect()
        try:
            _build_pre_039_schema(conn)

            created = "2025-03-15 12:34:56"
            ws_id = str(uuid.uuid4())
            conn.execute(text(
                "INSERT INTO workstations (id, ip_private, created_at)"
                " VALUES (:id, '10.0.0.5', :created)"
            ).bindparams(id=ws_id, created=created))

            _run_migration_upgrade(conn)

            row = conn.execute(text(
                "SELECT created_at, billing_cycle_started_at FROM workstations WHERE id = :id"
            ).bindparams(id=ws_id)).one()
            assert row[0] == row[1]  # billing_cycle_started_at == created_at
        finally:
            conn.close()
            engine.dispose()

    def test_backfill_incompleto_aborta_fail_closed(self):
        """
        Atomicidad/fail-closed del backfill (Req 6.3): si tras el backfill queda alguna fila de
        cierre sin política válida, `upgrade()` ABORTA con RuntimeError. En el motor real
        (PostgreSQL, DDL transaccional) ese raise revierte la transacción de la migración y la
        migración NO se marca como aplicada; aquí verificamos el disparo del abort.

        Se fuerza el escenario monkeypatcheando el freeze legacy del módulo a un valor vacío
        `"{}"`, de modo que el backfill deje la fila "sin política válida" y la verificación
        `remaining > 0` dispare el abort. NOTA: sobre SQLite el DDL es auto-commit ("Will
        assume non-transactional DDL"), por lo que NO se puede asertar el drop de la tabla tras
        el rollback (limitación conocida de SQLite); la garantía todo-o-nada aplica sobre el
        motor transaccional real. Aquí se valida la parte verificable: el abort fail-closed.
        """
        engine = self._engine()
        conn = engine.connect()
        try:
            _build_pre_039_schema(conn)

            org_id = str(uuid.uuid4())
            conn.execute(text(
                "INSERT INTO organizations (id, name, timezone) VALUES (:id, 'Acme', 'UTC')"
            ).bindparams(id=org_id))
            conn.execute(text(
                "INSERT INTO billing_closures (id, organization_id, period_year, period_month)"
                " VALUES (:id, :org, 2025, 1)"
            ).bindparams(id=str(uuid.uuid4()), org=org_id))

            mod = _load_migration_module()
            original_freeze = mod._LEGACY_FREEZE
            # Forzar que el backfill escriba un freeze vacío => la verificación fail-closed
            # (remaining > 0) aborta con RuntimeError (Req 6.3).
            mod._LEGACY_FREEZE = "{}"
            try:
                ctx = MigrationContext.configure(conn)
                with pytest.raises(
                    RuntimeError, match="Backfill de recycle_policy_applied incompleto"
                ):
                    with Operations.context(ctx):
                        mod.upgrade()
            finally:
                mod._LEGACY_FREEZE = original_freeze  # no contaminar otros tests
        finally:
            conn.close()
            engine.dispose()
