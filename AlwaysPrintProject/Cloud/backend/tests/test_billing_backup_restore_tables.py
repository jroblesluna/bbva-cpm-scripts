"""
Tests del backup/restore de las tablas de facturación (Usage and Billing).

Verifica el contrato de la Task 34: las 5 tablas nuevas de facturación deben
estar incluidas tanto en el backup como en el restore, y en un orden seguro
respecto de las FK (billing_closures antes de billing_closure_items).

Validates: Requirements 6.4
"""

from app.services.backup_service import (
    TABLE_MODEL_MAP as BACKUP_MAP,
    OPTIONAL_TABLES,
)
from app.services.restore_service import (
    TABLE_MODEL_MAP as RESTORE_MAP,
    TABLE_ORDER as RESTORE_ORDER,
)

# Las 5 tablas nuevas de facturación (definidas en app/models/billing.py)
BILLING_TABLES = [
    "billing_rate_plans",
    "billing_org_plans",
    "billing_closures",
    "billing_closure_items",
    "billing_annual_subscriptions",
]

BACKUP_ORDER = [name for name, _ in BACKUP_MAP]


def test_billing_tables_present_in_backup():
    """Las 5 tablas de facturación deben estar en el listado de backup."""
    for table in BILLING_TABLES:
        assert table in BACKUP_ORDER, f"{table} falta en TABLE_MODEL_MAP de backup"


def test_billing_tables_present_in_restore():
    """Las 5 tablas de facturación deben estar en el listado de restore."""
    for table in BILLING_TABLES:
        assert table in RESTORE_ORDER, f"{table} falta en TABLE_MODEL_MAP de restore"


def test_closure_items_restored_after_closures():
    """
    billing_closure_items tiene FK → billing_closures, por lo que debe ir
    DESPUÉS de billing_closures en el orden de restore (y de backup).
    """
    for order, label in ((RESTORE_ORDER, "restore"), (BACKUP_ORDER, "backup")):
        assert order.index("billing_closures") < order.index(
            "billing_closure_items"
        ), f"billing_closures debe ir antes de billing_closure_items en {label}"


def test_billing_tables_not_optional():
    """
    Las tablas de facturación son estado operativo (no historial/telemetría),
    por lo que NO deben marcarse como opcionales — siempre deben respaldarse.
    """
    for table in BILLING_TABLES:
        assert table not in OPTIONAL_TABLES, f"{table} no debería ser opcional"


def test_backup_and_restore_orders_match():
    """
    El orden de backup y restore debe ser idéntico para las tablas de
    facturación (misma dependencia FK en ambos flujos).
    """
    backup_billing = [t for t in BACKUP_ORDER if t in BILLING_TABLES]
    restore_billing = [t for t in RESTORE_ORDER if t in BILLING_TABLES]
    assert backup_billing == restore_billing


def test_billing_org_plans_after_organizations():
    """
    billing_org_plans, billing_closures y billing_annual_subscriptions tienen
    FK → organizations, que debe restaurarse antes.
    """
    for order in (RESTORE_ORDER, BACKUP_ORDER):
        org_idx = order.index("organizations")
        for table in (
            "billing_org_plans",
            "billing_closures",
            "billing_annual_subscriptions",
        ):
            assert org_idx < order.index(
                table
            ), f"organizations debe ir antes de {table}"
