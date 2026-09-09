# Feature: recycle-policy-config, Property 11: billing_cycle_started_at se inicializa igual a created_at
"""
Property test de la inicialización de `billing_cycle_started_at` al registrar una workstation
(Req 18.2).

Al crear una nueva workstation, el sistema DEBE inicializar `billing_cycle_started_at` con el
MISMO instante que `created_at`. `WorkstationService.register_workstation` asigna un único
`now` a `created_at` y `billing_cycle_started_at` en el constructor del modelo (igual que
`last_seen == first_seen`), sin tocar `created_at` como columna con semántica histórica.

Este test ejercita el flujo real de registro sobre una base SQLite en memoria (con el tipo
`GUID` compat SQLite/PostgreSQL), sembrando una `Organization` activa y una `PublicIP`
autorizada, de modo que `register_workstation` llegue a la rama de creación. Genera IPs
privadas, hostnames, seriales y CIDRs variados con Hypothesis y verifica el invariante
`billing_cycle_started_at == created_at` para cada workstation recién creada.

Se construye una sesión SQLite nueva dentro de cada ejemplo (no se usa el fixture `db` con
scope de función, incompatible con `@given` de Hypothesis) para garantizar aislamiento total
entre ejemplos.

**Validates: Requirements 18.2**
"""

import uuid
import warnings

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, event
from sqlalchemy.exc import SAWarning
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
import app.models  # noqa: F401  (registra todas las tablas en Base.metadata)
from app.models.organization import Organization, PublicIP
from app.services.workstation import WorkstationService


# === ESTRATEGIAS DE GENERACIÓN ===

# IPs privadas variadas dentro de rangos RFC1918 para el registro.
private_ip_strategy = st.builds(
    lambda a, b, c, d: f"{a}.{b}.{c}.{d}",
    st.sampled_from([10, 172, 192]),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=1, max_value=254),
)

hostname_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Nd"), whitelist_characters="-"),
    min_size=1,
    max_size=15,
).map(lambda s: f"WS-{s}")

os_serial_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Nd")),
    min_size=4,
    max_size=12,
)

# CIDR opcional: la mitad de los casos registra sin CIDR (fallback por IP), la otra con CIDR.
cidr_strategy = st.one_of(
    st.none(),
    st.sampled_from(["10.0.0.0/24", "172.16.0.0/16", "192.168.1.0/24", "192.168.10.0/24"]),
)


def _new_session():
    """
    Crea una sesión SQLite en memoria aislada (mismo patrón que `tests/conftest.py::db`),
    con foreign keys desactivadas para evitar problemas al crear/eliminar tablas.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _disable_fk(dbapi_conn, connection_record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, TestingSession()


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    ip_private=private_ip_strategy,
    hostname=hostname_strategy,
    os_serial=os_serial_strategy,
    cidr=cidr_strategy,
)
def test_billing_cycle_started_at_igual_a_created_at_al_registrar(
    ip_private: str, hostname: str, os_serial: str, cidr
):
    """
    Req 18.2 — Al registrar una workstation nueva, `billing_cycle_started_at` DEBE quedar
    inicializado exactamente al mismo instante que `created_at`.

    Ejercita el flujo real `WorkstationService.register_workstation` (rama de creación) contra
    una BD SQLite en memoria con una organización activa y su IP pública autorizada.

    **Validates: Requirements 18.2**
    """
    engine, session = _new_session()
    try:
        public_ip = "203.0.113.10"

        # Semilla: organización activa + IP pública autorizada apuntando a ella.
        org = Organization(id=uuid.uuid4(), name=f"Org-{uuid.uuid4().hex[:8]}", is_active=True)
        session.add(org)
        session.flush()

        session.add(
            PublicIP(
                id=uuid.uuid4(),
                organization_id=org.id,
                ip_address=public_ip,
                is_authorized=True,
            )
        )
        session.commit()

        service = WorkstationService()
        workstation, is_new, status = service.register_workstation(
            session,
            ip_private=ip_private,
            public_ip=public_ip,
            hostname=hostname,
            os_serial=os_serial,
            cidr=cidr,
        )

        assert status == "authorized", f"El registro debió ser autorizado, se obtuvo: {status}"
        assert is_new is True, "La workstation debió crearse como nueva"
        assert workstation is not None

        assert workstation.billing_cycle_started_at == workstation.created_at, (
            "Al crear la workstation, billing_cycle_started_at debe ser igual a created_at "
            f"(Req 18.2); se obtuvo billing_cycle_started_at="
            f"{workstation.billing_cycle_started_at!r} vs created_at={workstation.created_at!r}."
        )
    finally:
        session.close()
        # Drop de la BD en memoria. Se silencia el SAWarning por el ciclo de FK conocido
        # (devices <-> vlans): SQLite no soporta ALTER para ordenar el DROP, pero es una BD
        # efímera en memoria que se descarta igual (mismo criterio que el fixture `db` del
        # conftest, que desactiva las FKs). No afecta la validez del test.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=SAWarning)
            Base.metadata.drop_all(bind=engine)
        engine.dispose()
