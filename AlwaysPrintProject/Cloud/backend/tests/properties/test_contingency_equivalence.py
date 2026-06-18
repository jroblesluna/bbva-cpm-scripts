"""
Property test para equivalencia de contingencia single-query vs secuencial.

# Feature: websocket-scaling-redis, Property 12: Single-Query Contingency Equivalence

Para cualquier workstation con cualquier combinación de flags forced_contingency
a nivel de organización, VLAN y workstation, la resolución optimizada (single-query
con JOINs) SHALL producir el mismo resultado (enabled, source, source_name, printer_ip)
que el enfoque secuencial de 3 queries.

**Validates: Requirements 4.5**
"""

import uuid
from datetime import datetime, timezone
from itertools import product
from typing import Dict, Any, Optional

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.organization import Organization, GUID
from app.models.vlan import VLAN
from app.models.workstation import Workstation
from app.models.device import Device
from app.services.registration_cache import RegistrationCache

# Importar todos los modelos para registrar tablas en Base.metadata
from app import models as _all_models  # noqa: F401


# === CONFIGURACIÓN DE BASE DE DATOS EN MEMORIA PARA TESTS ===

SQLALCHEMY_TEST_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_TEST_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


# Desactivar foreign keys para evitar errores de dependencia circular al hacer drop_all
@event.listens_for(engine, "connect")
def _disable_fk_for_tests(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=OFF")
    cursor.close()


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# === ENFOQUE SECUENCIAL DE REFERENCIA (3 queries independientes) ===


def _resolve_contingency_sequential(
    workstation_id: str,
    organization_id: str,
    vlan_id: Optional[str],
    db: Session,
) -> Optional[Dict[str, Any]]:
    """
    Resuelve el estado de contingencia forzada de forma secuencial (3 queries).

    Este es el enfoque de referencia que simula el comportamiento previo
    a la optimización: consultar org, luego VLAN, luego workstation por separado.
    La prioridad es: organización > VLAN > workstation.
    """
    # Query 1: Obtener datos de la organización
    org = db.query(Organization).filter(
        Organization.id == organization_id
    ).first()
    if not org:
        return None

    # Query 2: Obtener datos de la workstation
    ws = db.query(Workstation).filter(
        Workstation.id == workstation_id,
        Workstation.organization_id == organization_id,
    ).first()
    if not ws:
        return None

    # Query 3: Obtener datos de la VLAN (si aplica)
    vlan = None
    if ws.vlan_id:
        vlan = db.query(VLAN).filter(VLAN.id == ws.vlan_id).first()

    # Resolver prioridad de contingencia forzada
    forced_contingency_enabled = False
    forced_source = None
    forced_source_name = None

    # Prioridad 1: Organización
    if org.forced_contingency:
        forced_contingency_enabled = True
        forced_source = "organization"
        forced_source_name = org.name

    # Prioridad 2: VLAN (solo si la workstation tiene VLAN asignada)
    if not forced_contingency_enabled and vlan and vlan.forced_contingency:
        forced_contingency_enabled = True
        forced_source = "vlan"
        forced_source_name = vlan.name

    # Prioridad 3: Workstation individual
    if not forced_contingency_enabled and ws.forced_contingency:
        forced_contingency_enabled = True
        forced_source = "workstation"
        forced_source_name = ws.hostname or str(ws.ip_private)

    # Resolver printer_ip si hay contingencia activa
    printer_ip = None
    if forced_contingency_enabled:
        printer_ip = _resolve_printer_ip_sequential(ws, vlan, db)

    return {
        "enabled": forced_contingency_enabled,
        "source": forced_source if forced_contingency_enabled else "sync",
        "source_name": forced_source_name if forced_contingency_enabled else "normal",
        "printer_ip": printer_ip,
    }


def _resolve_printer_ip_sequential(
    ws: Workstation,
    vlan: Optional[VLAN],
    db: Session,
) -> Optional[str]:
    """
    Resuelve la IP de impresora usando queries secuenciales.

    Prioridad:
    1. Impresora predeterminada de la workstation
    2. Impresora predeterminada de la VLAN
    3. Primera impresora activa de la VLAN
    """
    # 1. Impresora predeterminada de la workstation
    if ws.default_printer_id:
        device = db.query(Device).filter(Device.id == ws.default_printer_id).first()
        if device and device.ip_address:
            return device.ip_address

    # 2. Impresora predeterminada de la VLAN
    if vlan and vlan.default_device_id:
        device = db.query(Device).filter(Device.id == vlan.default_device_id).first()
        if device and device.ip_address:
            return device.ip_address

    # 3. Primera impresora activa de la VLAN
    if ws.vlan_id:
        first_device = (
            db.query(Device)
            .filter(
                Device.vlan_id == ws.vlan_id,
                Device.organization_id == ws.organization_id,
                Device.is_active == True,
            )
            .order_by(Device.ip_address)
            .first()
        )
        if first_device:
            return first_device.ip_address

    return None


# === ESTRATEGIAS DE GENERACIÓN ===


@st.composite
def contingency_flags_strategy(draw):
    """
    Genera todas las combinaciones de flags de contingencia forzada.

    Produce una tupla (org_forced, vlan_forced, ws_forced) que representa
    las 8 combinaciones posibles de los 3 flags booleanos.
    """
    org_forced = draw(st.booleans())
    vlan_forced = draw(st.booleans())
    ws_forced = draw(st.booleans())
    return org_forced, vlan_forced, ws_forced


@st.composite
def printer_scenario_strategy(draw):
    """
    Genera escenarios de impresoras para la resolución de printer_ip.

    Escenarios:
    - sin_impresora: workstation sin default_printer, VLAN sin default ni activas
    - ws_tiene_printer: workstation con impresora predeterminada
    - vlan_tiene_default: VLAN con impresora predeterminada
    - vlan_tiene_activa: VLAN sin default pero con impresora activa
    """
    scenario = draw(st.sampled_from([
        "sin_impresora",
        "ws_tiene_printer",
        "vlan_tiene_default",
        "vlan_tiene_activa",
    ]))
    return scenario


@st.composite
def full_contingency_scenario_strategy(draw):
    """
    Genera un escenario completo de contingencia: flags + impresoras.

    Combina los flags booleanos (8 combinaciones) con los escenarios de impresora
    (4 variantes) para cubrir exhaustivamente el espacio de inputs.
    """
    org_forced, vlan_forced, ws_forced = draw(contingency_flags_strategy())
    printer_scenario = draw(printer_scenario_strategy())

    # Generar IP aleatoria para la impresora
    ip_parts = [draw(st.integers(min_value=1, max_value=254)) for _ in range(4)]
    printer_ip = ".".join(str(p) for p in ip_parts)

    # Nombre de organización
    org_name = draw(st.text(
        min_size=3, max_size=20,
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_- ")
    ))
    assume(org_name.strip() != "")

    # Nombre de VLAN
    vlan_name = draw(st.text(
        min_size=3, max_size=20,
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_- ")
    ))
    assume(vlan_name.strip() != "")

    # Hostname de workstation
    ws_hostname = draw(st.text(
        min_size=3, max_size=15,
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-")
    ))
    assume(ws_hostname.strip() != "")

    # IP privada de la workstation
    ws_ip = f"10.{draw(st.integers(min_value=0, max_value=254))}.{draw(st.integers(min_value=0, max_value=254))}.{draw(st.integers(min_value=1, max_value=254))}"

    return {
        "org_forced": org_forced,
        "vlan_forced": vlan_forced,
        "ws_forced": ws_forced,
        "printer_scenario": printer_scenario,
        "printer_ip": printer_ip,
        "org_name": org_name,
        "vlan_name": vlan_name,
        "ws_hostname": ws_hostname,
        "ws_ip": ws_ip,
    }


# === HELPERS PARA CREAR DATOS EN BD ===


def _create_test_scenario(db: Session, scenario: Dict[str, Any]) -> Dict[str, Any]:
    """
    Crea los objetos en BD para un escenario de test dado.

    Retorna un dict con los IDs creados para usarlos en las queries.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Crear organización
    org_id = uuid.uuid4()
    org = Organization(
        id=org_id,
        name=f"{scenario['org_name']}-{org_id}",
        is_active=True,
        forced_contingency=scenario["org_forced"],
        created_at=now,
        updated_at=now,
    )
    db.add(org)
    db.flush()

    # Crear VLAN
    vlan_id = uuid.uuid4()
    vlan = VLAN(
        id=vlan_id,
        organization_id=org_id,
        name=scenario["vlan_name"],
        cidr_ranges=["10.0.0.0/24"],
        forced_contingency=scenario["vlan_forced"],
        default_device_id=None,  # Se asigna según escenario
        created_at=now,
        updated_at=now,
    )
    db.add(vlan)
    db.flush()

    # Crear impresora(s) según escenario
    ws_default_printer_id = None
    printer_ip = scenario["printer_ip"]

    if scenario["printer_scenario"] == "ws_tiene_printer":
        # Workstation tiene impresora predeterminada
        device_id = uuid.uuid4()
        device = Device(
            id=device_id,
            organization_id=org_id,
            vlan_id=vlan_id,
            name="Printer-WS-Default",
            ip_address=printer_ip,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(device)
        db.flush()
        ws_default_printer_id = device_id

    elif scenario["printer_scenario"] == "vlan_tiene_default":
        # VLAN tiene impresora predeterminada
        device_id = uuid.uuid4()
        device = Device(
            id=device_id,
            organization_id=org_id,
            vlan_id=vlan_id,
            name="Printer-VLAN-Default",
            ip_address=printer_ip,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(device)
        db.flush()
        # Asignar la impresora como default de la VLAN
        vlan.default_device_id = device_id
        db.flush()

    elif scenario["printer_scenario"] == "vlan_tiene_activa":
        # VLAN tiene impresora activa (pero no asignada como default)
        device_id = uuid.uuid4()
        device = Device(
            id=device_id,
            organization_id=org_id,
            vlan_id=vlan_id,
            name="Printer-VLAN-Activa",
            ip_address=printer_ip,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(device)
        db.flush()

    # En "sin_impresora": no se crea ningún dispositivo

    # Crear workstation
    ws_id = uuid.uuid4()
    workstation = Workstation(
        id=ws_id,
        organization_id=org_id,
        vlan_id=vlan_id,
        ip_private=f"{scenario['ws_ip']}-{ws_id}",  # Hacer único para evitar colisiones
        hostname=scenario["ws_hostname"],
        is_online=True,
        forced_contingency=scenario["ws_forced"],
        default_printer_id=ws_default_printer_id,
        first_seen=now,
        created_at=now,
        updated_at=now,
    )
    db.add(workstation)
    db.commit()

    return {
        "org_id": org_id,
        "vlan_id": vlan_id,
        "ws_id": ws_id,
    }


# === PROPERTY 12: SINGLE-QUERY CONTINGENCY EQUIVALENCE ===


class TestContingencyEquivalence:
    """
    Property 12: Single-Query Contingency Equivalence.

    Para TODAS las combinaciones de (org.forced_contingency, vlan.forced_contingency,
    ws.forced_contingency) + escenarios de impresora, la query optimizada (JOIN)
    produce el mismo resultado que el enfoque secuencial de 3 queries.

    **Validates: Requirements 4.5**
    """

    @given(scenario=full_contingency_scenario_strategy())
    @hypothesis_settings(max_examples=120, deadline=None)
    @pytest.mark.asyncio
    async def test_optimized_equals_sequential_for_all_flag_combinations(
        self, scenario: Dict[str, Any]
    ):
        """
        Requirement 4.5: La resolución optimizada (single query con JOIN) produce
        el mismo resultado que el enfoque secuencial para todas las combinaciones
        de flags de contingencia forzada.

        Verifica equivalencia en los 4 campos de resultado:
        - enabled: booleano indicando si hay contingencia activa
        - source: "organization", "vlan", "workstation", o "sync"
        - source_name: nombre del nivel que activó la contingencia
        - printer_ip: IP de la impresora asignada (o None)

        **Validates: Requirements 4.5**
        """
        # Crear tablas frescas
        Base.metadata.create_all(bind=engine)

        db = TestingSessionLocal()
        try:
            # Crear escenario en BD
            ids = _create_test_scenario(db, scenario)
            ws_id = str(ids["ws_id"])
            org_id = str(ids["org_id"])
            vlan_id = str(ids["vlan_id"])

            # Resultado 1: Enfoque secuencial (referencia)
            resultado_secuencial = _resolve_contingency_sequential(
                workstation_id=ws_id,
                organization_id=org_id,
                vlan_id=vlan_id,
                db=db,
            )

            # Resultado 2: Enfoque optimizado (single-query con JOINs)
            cache = RegistrationCache(redis=None, ttl_seconds=300)
            resultado_optimizado = cache._fetch_forced_contingency_state(
                workstation_id=ws_id,
                organization_id=org_id,
                vlan_id=vlan_id,
                db=db,
            )

            # Propiedad: ambos resultados deben ser no-None
            assert resultado_secuencial is not None, (
                f"El enfoque secuencial retornó None para el escenario: {scenario}"
            )
            assert resultado_optimizado is not None, (
                f"El enfoque optimizado retornó None para el escenario: {scenario}"
            )

            # Propiedad: campo 'enabled' debe ser igual
            assert resultado_optimizado["enabled"] == resultado_secuencial["enabled"], (
                f"Campo 'enabled' difiere. "
                f"Optimizado: {resultado_optimizado['enabled']}, "
                f"Secuencial: {resultado_secuencial['enabled']}. "
                f"Flags: org={scenario['org_forced']}, vlan={scenario['vlan_forced']}, "
                f"ws={scenario['ws_forced']}"
            )

            # Propiedad: campo 'source' debe ser igual
            assert resultado_optimizado["source"] == resultado_secuencial["source"], (
                f"Campo 'source' difiere. "
                f"Optimizado: {resultado_optimizado['source']}, "
                f"Secuencial: {resultado_secuencial['source']}. "
                f"Flags: org={scenario['org_forced']}, vlan={scenario['vlan_forced']}, "
                f"ws={scenario['ws_forced']}"
            )

            # Propiedad: campo 'source_name' debe ser igual
            assert resultado_optimizado["source_name"] == resultado_secuencial["source_name"], (
                f"Campo 'source_name' difiere. "
                f"Optimizado: {resultado_optimizado['source_name']}, "
                f"Secuencial: {resultado_secuencial['source_name']}. "
                f"Flags: org={scenario['org_forced']}, vlan={scenario['vlan_forced']}, "
                f"ws={scenario['ws_forced']}"
            )

            # Propiedad: campo 'printer_ip' debe ser igual
            assert resultado_optimizado["printer_ip"] == resultado_secuencial["printer_ip"], (
                f"Campo 'printer_ip' difiere. "
                f"Optimizado: {resultado_optimizado['printer_ip']}, "
                f"Secuencial: {resultado_secuencial['printer_ip']}. "
                f"Flags: org={scenario['org_forced']}, vlan={scenario['vlan_forced']}, "
                f"ws={scenario['ws_forced']}, escenario_printer={scenario['printer_scenario']}"
            )

        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    @given(scenario=full_contingency_scenario_strategy())
    @hypothesis_settings(max_examples=120, deadline=None)
    @pytest.mark.asyncio
    async def test_priority_org_over_vlan_over_ws(self, scenario: Dict[str, Any]):
        """
        Requirement 4.5: La prioridad de contingencia se aplica correctamente.

        Verifica que la prioridad org > vlan > ws se respeta:
        - Si org.forced_contingency=True → source="organization", enabled=True
        - Si solo vlan.forced_contingency=True → source="vlan", enabled=True
        - Si solo ws.forced_contingency=True → source="workstation", enabled=True
        - Si todos son False → enabled=False

        **Validates: Requirements 4.5**
        """
        # Crear tablas frescas
        Base.metadata.create_all(bind=engine)

        db = TestingSessionLocal()
        try:
            # Crear escenario en BD
            ids = _create_test_scenario(db, scenario)
            ws_id = str(ids["ws_id"])
            org_id = str(ids["org_id"])
            vlan_id = str(ids["vlan_id"])

            # Ejecutar método optimizado
            cache = RegistrationCache(redis=None, ttl_seconds=300)
            resultado = cache._fetch_forced_contingency_state(
                workstation_id=ws_id,
                organization_id=org_id,
                vlan_id=vlan_id,
                db=db,
            )

            assert resultado is not None, (
                f"_fetch_forced_contingency_state retornó None para el escenario: {scenario}"
            )

            # Verificar prioridad según combinación de flags
            org_forced = scenario["org_forced"]
            vlan_forced = scenario["vlan_forced"]
            ws_forced = scenario["ws_forced"]

            if org_forced:
                # Prioridad 1: organización siempre gana
                assert resultado["enabled"] is True, (
                    f"enabled debería ser True cuando org.forced_contingency=True"
                )
                assert resultado["source"] == "organization", (
                    f"source debería ser 'organization' cuando org.forced=True, "
                    f"pero es '{resultado['source']}'"
                )
            elif vlan_forced:
                # Prioridad 2: VLAN gana si organización no está activa
                assert resultado["enabled"] is True, (
                    f"enabled debería ser True cuando vlan.forced_contingency=True "
                    f"y org.forced_contingency=False"
                )
                assert resultado["source"] == "vlan", (
                    f"source debería ser 'vlan' cuando vlan.forced=True y org.forced=False, "
                    f"pero es '{resultado['source']}'"
                )
            elif ws_forced:
                # Prioridad 3: workstation solo si org y vlan están desactivados
                assert resultado["enabled"] is True, (
                    f"enabled debería ser True cuando ws.forced_contingency=True "
                    f"y org.forced=False y vlan.forced=False"
                )
                assert resultado["source"] == "workstation", (
                    f"source debería ser 'workstation' cuando ws.forced=True y org/vlan=False, "
                    f"pero es '{resultado['source']}'"
                )
            else:
                # Ningún flag activo: contingencia deshabilitada
                assert resultado["enabled"] is False, (
                    f"enabled debería ser False cuando todos los flags son False"
                )
                assert resultado["source"] == "sync", (
                    f"source debería ser 'sync' cuando enabled=False, "
                    f"pero es '{resultado['source']}'"
                )
                assert resultado["source_name"] == "normal", (
                    f"source_name debería ser 'normal' cuando enabled=False, "
                    f"pero es '{resultado['source_name']}'"
                )

        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)

    @given(scenario=full_contingency_scenario_strategy())
    @hypothesis_settings(max_examples=120, deadline=None)
    @pytest.mark.asyncio
    async def test_result_always_has_correct_fields(self, scenario: Dict[str, Any]):
        """
        Requirement 4.5: El resultado siempre contiene los 4 campos requeridos.

        Verifica que el resultado de la query optimizada siempre retorna:
        - enabled: bool
        - source: str (uno de los valores válidos)
        - source_name: str (no None)
        - printer_ip: str o None

        **Validates: Requirements 4.5**
        """
        # Crear tablas frescas
        Base.metadata.create_all(bind=engine)

        db = TestingSessionLocal()
        try:
            # Crear escenario en BD
            ids = _create_test_scenario(db, scenario)
            ws_id = str(ids["ws_id"])
            org_id = str(ids["org_id"])
            vlan_id = str(ids["vlan_id"])

            # Ejecutar método optimizado
            cache = RegistrationCache(redis=None, ttl_seconds=300)
            resultado = cache._fetch_forced_contingency_state(
                workstation_id=ws_id,
                organization_id=org_id,
                vlan_id=vlan_id,
                db=db,
            )

            assert resultado is not None, (
                f"_fetch_forced_contingency_state retornó None para el escenario: {scenario}"
            )

            # Propiedad: el resultado siempre tiene los 4 campos
            assert "enabled" in resultado, "Falta campo 'enabled' en resultado"
            assert "source" in resultado, "Falta campo 'source' en resultado"
            assert "source_name" in resultado, "Falta campo 'source_name' en resultado"
            assert "printer_ip" in resultado, "Falta campo 'printer_ip' en resultado"

            # Propiedad: tipos correctos
            assert isinstance(resultado["enabled"], bool), (
                f"'enabled' debe ser bool, es {type(resultado['enabled'])}"
            )
            assert isinstance(resultado["source"], str), (
                f"'source' debe ser str, es {type(resultado['source'])}"
            )
            assert isinstance(resultado["source_name"], str), (
                f"'source_name' debe ser str, es {type(resultado['source_name'])}"
            )
            assert resultado["printer_ip"] is None or isinstance(resultado["printer_ip"], str), (
                f"'printer_ip' debe ser str o None, es {type(resultado['printer_ip'])}"
            )

            # Propiedad: source es uno de los valores válidos
            valid_sources = {"organization", "vlan", "workstation", "sync"}
            assert resultado["source"] in valid_sources, (
                f"source '{resultado['source']}' no es un valor válido. "
                f"Esperado uno de: {valid_sources}"
            )

            # Propiedad: si enabled=True, printer_ip puede ser None (sin impresora disponible)
            # pero source debe ser organization, vlan, o workstation
            if resultado["enabled"]:
                assert resultado["source"] in {"organization", "vlan", "workstation"}, (
                    f"Cuando enabled=True, source debe ser 'organization', 'vlan' o 'workstation', "
                    f"pero es '{resultado['source']}'"
                )

            # Propiedad: si enabled=False, printer_ip debe ser None
            if not resultado["enabled"]:
                assert resultado["printer_ip"] is None, (
                    f"Cuando enabled=False, printer_ip debe ser None, "
                    f"pero es '{resultado['printer_ip']}'"
                )

        finally:
            db.close()
            Base.metadata.drop_all(bind=engine)
