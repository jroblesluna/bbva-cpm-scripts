"""
Verificación de la migración 036 (Usage and Billing) en una BD de prueba/dev.

Corresponde a la Task 4 del spec `usage-and-billing` (parte de prueba de migración).
Ejecuta la migración 036 sobre una BD SQLite aislada, sembrada con datos
representativos (perfil similar a PROD/BBVA: ~6,315 IPs distribuidas may–sep 2026,
una mezcla con y sin `last_connection`), y verifica el backfill:

  - last_seen poblado vía COALESCE(last_connection, first_seen)
  - billing_status = 'new' en TODAS las filas existentes
  - NOT NULL efectivo en last_seen y billing_status
  - CHECK constraints activos (ck_ws_billing_status, ck_org_billing_mode)
  - organizations.billing_mode con default 'monthly'
  - 5 tablas nuevas creadas (rate_plans, org_plans, closures, closure_items, annual_subscriptions)
  - Seed de planes tarifarios por defecto (monthly + annual)

Uso:
    python scripts/verify_036_usage_billing.py

Estrategia:
    La suite de tests del proyecto construye el esquema con
    `Base.metadata.create_all()` y NO ejecuta la cadena completa de Alembic
    (varias migraciones antiguas —p.ej. 002— no son compatibles con el modo
    batch de SQLite). Por eso este script construye a mano el esquema *pre-036*
    de las tablas que 036 toca (organizations, workstations, users), hace `stamp`
    en 035 y luego ejecuta SOLO la migración 036 con la API real de Alembic
    (command.upgrade). Así se prueba exactamente el código de la migración 036.

Este script NO toca PROD. Es solo-local (SQLite en archivo temporal).
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

BACKEND = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, BACKEND)

# BD SQLite aislada en archivo temporal.
_TMP = tempfile.NamedTemporaryFile(prefix="verify_036_", suffix=".db", delete=False)
DB_PATH = _TMP.name
_TMP.close()
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"

# Distribución representativa (mismo perfil que PROD/BBVA a sep-2026):
#   mes -> (n_con_last_connection, n_sin_last_connection[usa first_seen])
SEED = {
    "2026-05": (8, 5),        # 13
    "2026-06": (400, 172),    # 572
    "2026-07": (1800, 751),   # 2551
    "2026-08": (2200, 950),   # 3150
    "2026-09": (20, 9),       # 29
}

FAILS = []


def check(cond, msg):
    print(f"  [{'OK ' if cond else 'FALLO'}] {msg}")
    if not cond:
        FAILS.append(msg)


def build_pre036_schema(conn):
    """Crear el esquema mínimo pre-036 de las tablas que la migración 036 toca."""
    cur = conn.cursor()
    cur.execute("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, email VARCHAR(255))")
    cur.execute(
        "CREATE TABLE organizations ("
        "  id VARCHAR(36) PRIMARY KEY,"
        "  name VARCHAR(255) NOT NULL,"
        "  is_active BOOLEAN NOT NULL DEFAULT 1,"
        "  timezone VARCHAR(50) NOT NULL DEFAULT 'UTC',"
        "  language VARCHAR(2) NOT NULL DEFAULT 'en',"
        "  created_at DATETIME NOT NULL,"
        "  updated_at DATETIME NOT NULL"
        ")"
    )
    cur.execute(
        "CREATE TABLE workstations ("
        "  id VARCHAR(36) PRIMARY KEY,"
        "  organization_id VARCHAR(36) NOT NULL,"
        "  ip_private VARCHAR(45) NOT NULL UNIQUE,"
        "  hostname VARCHAR(255),"
        "  is_online BOOLEAN NOT NULL DEFAULT 0,"
        "  contingency_active BOOLEAN NOT NULL DEFAULT 0,"
        "  last_connection DATETIME,"
        "  first_seen DATETIME NOT NULL,"
        "  created_at DATETIME NOT NULL,"
        "  updated_at DATETIME NOT NULL"
        ")"
    )
    conn.commit()


def seed_data(conn):
    cur = conn.cursor()
    org_id = "11111111-1111-1111-1111-111111111111"
    cur.execute(
        "INSERT INTO organizations (id,name,is_active,timezone,language,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (org_id, "BBVA-TEST", 1, "America/Lima", "es",
         "2026-05-01 00:00:00", "2026-05-01 00:00:00"),
    )
    total = exp_lc = exp_fs = n = 0
    for mes, (with_lc, without_lc) in SEED.items():
        y, m = mes.split("-")
        base = f"{y}-{m}-15 10:00:00"
        first_seen = f"{y}-{m}-10 08:00:00"
        last_conn = f"{y}-{m}-20 12:00:00"
        rows = []
        for _ in range(with_lc):
            n += 1
            rows.append((f"{n:08d}-0000-0000-0000-000000000000", org_id,
                         f"10.{n // 256 % 256}.{n % 256}.1", 0, 0, first_seen, base, base, last_conn))
            exp_lc += 1
            total += 1
        for _ in range(without_lc):
            n += 1
            rows.append((f"{n:08d}-0000-0000-0000-000000000000", org_id,
                         f"10.{n // 256 % 256}.{n % 256}.2", 0, 0, first_seen, base, base, None))
            exp_fs += 1
            total += 1
        cur.executemany(
            "INSERT INTO workstations (id,organization_id,ip_private,is_online,"
            "contingency_active,first_seen,created_at,updated_at,last_connection) "
            "VALUES (?,?,?,?,?,?,?,?,?)", rows,
        )
    conn.commit()
    print(f"  Sembradas {total} workstations ({exp_lc} con last_connection, {exp_fs} sin).")
    return total, exp_lc, exp_fs


def main():
    print("== Paso 1: construir esquema pre-036 y sembrar datos representativos ==")
    raw = sqlite3.connect(DB_PATH)
    build_pre036_schema(raw)
    total, exp_lc, exp_fs = seed_data(raw)
    cols = [r[1] for r in raw.execute("PRAGMA table_info(workstations)").fetchall()]
    assert "last_seen" not in cols and "billing_status" not in cols
    raw.close()

    print("== Paso 2: marcar (stamp) la BD en 035 y aplicar upgrade a 036 ==")
    from alembic.config import Config
    from alembic import command
    cfg = Config(os.path.join(BACKEND, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND, "alembic"))
    command.stamp(cfg, "035_add_remote_cmd_audit")
    command.upgrade(cfg, "036_add_usage_and_billing")

    print("== Paso 3: verificaciones ==")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    org_id = "11111111-1111-1111-1111-111111111111"

    cols = [r[1] for r in cur.execute("PRAGMA table_info(workstations)").fetchall()]
    check("last_seen" in cols, "workstations.last_seen existe")
    check("billing_status" in cols, "workstations.billing_status existe")

    n_null_ls = cur.execute("SELECT count(*) FROM workstations WHERE last_seen IS NULL").fetchone()[0]
    check(n_null_ls == 0, f"last_seen sin NULLs (nulls={n_null_ls})")

    n_ls_from_lc = cur.execute(
        "SELECT count(*) FROM workstations WHERE last_connection IS NOT NULL "
        "AND last_seen = last_connection").fetchone()[0]
    n_ls_from_fs = cur.execute(
        "SELECT count(*) FROM workstations WHERE last_connection IS NULL "
        "AND last_seen = first_seen").fetchone()[0]
    check(n_ls_from_lc == exp_lc, f"last_seen=last_connection cuando existe ({n_ls_from_lc}/{exp_lc})")
    check(n_ls_from_fs == exp_fs, f"last_seen=first_seen cuando NULL ({n_ls_from_fs}/{exp_fs})")

    n_total = cur.execute("SELECT count(*) FROM workstations").fetchone()[0]
    n_new = cur.execute("SELECT count(*) FROM workstations WHERE billing_status='new'").fetchone()[0]
    check(n_new == n_total == total, f"billing_status='new' en todas ({n_new}/{n_total}, sembradas={total})")

    ok = False
    try:
        cur.execute("INSERT INTO workstations (id,organization_id,ip_private,is_online,"
                    "contingency_active,first_seen,created_at,updated_at,last_seen,billing_status) "
                    "VALUES ('ffffffff-0000-0000-0000-000000000000',?,'9.9.9.9',0,0,"
                    "'2026-01-01','2026-01-01','2026-01-01',NULL,'new')", (org_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        ok = True
        conn.rollback()
    check(ok, "NOT NULL efectivo en last_seen (insert NULL rechazado)")

    ok = False
    try:
        cur.execute("INSERT INTO workstations (id,organization_id,ip_private,is_online,"
                    "contingency_active,first_seen,created_at,updated_at,last_seen,billing_status) "
                    "VALUES ('eeeeeeee-0000-0000-0000-000000000000',?,'9.9.9.8',0,0,"
                    "'2026-01-01','2026-01-01','2026-01-01','2026-01-01','invalido')", (org_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        ok = True
        conn.rollback()
    check(ok, "CHECK ck_ws_billing_status activo (valor invalido rechazado)")

    ocols = [r[1] for r in cur.execute("PRAGMA table_info(organizations)").fetchall()]
    check("billing_mode" in ocols, "organizations.billing_mode existe")
    n_mode = cur.execute("SELECT count(*) FROM organizations WHERE billing_mode='monthly'").fetchone()[0]
    check(n_mode >= 1, f"billing_mode default 'monthly' ({n_mode} orgs)")
    ok = False
    try:
        cur.execute("INSERT INTO organizations (id,name,is_active,timezone,language,created_at,updated_at,billing_mode) "
                    "VALUES ('dddddddd-0000-0000-0000-000000000000','X',1,'UTC','es','2026-01-01','2026-01-01','xxx')")
        conn.commit()
    except sqlite3.IntegrityError:
        ok = True
        conn.rollback()
    check(ok, "CHECK ck_org_billing_mode activo (valor invalido rechazado)")

    expected = ["billing_rate_plans", "billing_org_plans", "billing_closures",
                "billing_closure_items", "billing_annual_subscriptions"]
    existing = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for t in expected:
        check(t in existing, f"tabla '{t}' creada")

    n_m = cur.execute("SELECT count(*) FROM billing_rate_plans WHERE mode='monthly' AND is_default=1").fetchone()[0]
    n_a = cur.execute("SELECT count(*) FROM billing_rate_plans WHERE mode='annual' AND is_default=1").fetchone()[0]
    check(n_m >= 1, f"plan default 'monthly' sembrado ({n_m})")
    check(n_a >= 1, f"plan default 'annual' sembrado ({n_a})")

    ver = cur.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    check(ver == "036_add_usage_and_billing", f"alembic_version = {ver}")

    conn.close()

    # Limpieza del archivo temporal.
    try:
        os.remove(DB_PATH)
    except OSError:
        pass

    print("\n== Resultado ==")
    if FAILS:
        print(f"FALLARON {len(FAILS)} verificaciones:")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print(f"TODAS las verificaciones pasaron (total workstations={total}).")


if __name__ == "__main__":
    main()
