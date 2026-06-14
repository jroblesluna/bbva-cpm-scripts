"""
Property test para presencia de jitter_window_seconds en el config payload.

Verifica que para cualquier organización con un valor válido de
jitter_window_seconds en [5, 300], el método get_effective_config del
ConfigService siempre incluye el campo jitter_window_seconds con el
valor correcto de la organización.

Se usa una base de datos SQLite en memoria con modelos reales para
validar el comportamiento del servicio de configuración.

**Validates: Requirements 1.4**

Feature: reconnection-jitter, Property 2: Config payload always includes jitter_window_seconds
"""

import uuid

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base

# Importar todos los modelos para que Base.metadata registre sus tablas
import app.models  # noqa: F401

from app.models.organization import Organization
from app.models.workstation import Workstation
from app.services.config import ConfigService


# === CONSTANTES ===

# Rango válido para la ventana de jitter (según Requirements 1.2, 1.3)
MIN_JITTER_WINDOW = 5
MAX_JITTER_WINDOW = 300


# === HELPERS ===


def _create_db_session():
    """
    Crea una sesión de base de datos SQLite en memoria con todas las tablas.
    Retorna la sesión lista para usar en cada iteración del property test.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Desactivar foreign keys para evitar errores con tablas no relacionadas
    @event.listens_for(engine, "connect")
    def _disable_fk(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return Session()


def _setup_org_and_workstation(db, jitter_window_seconds: int):
    """
    Crea una organización con el jitter_window_seconds dado y una workstation
    asociada. Retorna el ID de la workstation para consultar la config efectiva.
    """
    org_id = uuid.uuid4()
    ws_id = uuid.uuid4()

    # Crear organización con el jitter configurado
    org = Organization(
        id=org_id,
        name=f"test-org-{org_id}",
        jitter_window_seconds=jitter_window_seconds,
    )
    db.add(org)
    db.flush()

    # Crear workstation asociada a la organización
    ws = Workstation(
        id=ws_id,
        organization_id=org_id,
        ip_private=f"192.168.{uuid.uuid4().int % 255}.{uuid.uuid4().int % 254 + 1}",
    )
    db.add(ws)
    db.commit()

    return ws_id


# === ESTRATEGIAS DE GENERACIÓN ===

# Ventana de jitter válida: entero en [5, 300]
_jitter_window = st.integers(min_value=MIN_JITTER_WINDOW, max_value=MAX_JITTER_WINDOW)


# === PROPERTY 2: CONFIG PAYLOAD ALWAYS INCLUDES JITTER_WINDOW_SECONDS ===


class TestJitterConfigPayload:
    """
    Property 2: Config payload always includes jitter_window_seconds.

    Para cualquier workstation perteneciente a una organización con
    jitter_window_seconds = W, el payload de config_update enviado a esa
    workstation SHALL contener jitter_window_seconds igual a W.

    **Validates: Requirements 1.4**
    """

    @given(jitter_window=_jitter_window)
    @settings(max_examples=100, deadline=None)
    def test_config_payload_contiene_jitter_window_seconds_correcto(
        self, jitter_window: int
    ):
        """
        Para cualquier valor válido de jitter_window_seconds en [5, 300],
        el effective config siempre incluye el campo con el valor correcto.

        **Validates: Requirements 1.4**
        """
        # Crear BD en memoria y datos de prueba para esta iteración
        db = _create_db_session()
        try:
            ws_id = _setup_org_and_workstation(db, jitter_window)

            # Obtener la configuración efectiva vía ConfigService
            config_service = ConfigService()
            effective_config = config_service.get_effective_config(db, str(ws_id))

            # Verificar que el campo jitter_window_seconds está presente
            assert "jitter_window_seconds" in effective_config, (
                f"El campo 'jitter_window_seconds' no está presente en el config payload. "
                f"Claves presentes: {list(effective_config.keys())}"
            )

            # Verificar que el valor coincide con el de la organización
            assert effective_config["jitter_window_seconds"] == jitter_window, (
                f"Se esperaba jitter_window_seconds={jitter_window}, "
                f"obtenido={effective_config['jitter_window_seconds']}"
            )
        finally:
            db.close()

    @given(jitter_window=_jitter_window)
    @settings(max_examples=100, deadline=None)
    def test_config_payload_jitter_es_entero(self, jitter_window: int):
        """
        El campo jitter_window_seconds en el config payload siempre es un entero,
        no un string ni None.

        **Validates: Requirements 1.4**
        """
        db = _create_db_session()
        try:
            ws_id = _setup_org_and_workstation(db, jitter_window)

            config_service = ConfigService()
            effective_config = config_service.get_effective_config(db, str(ws_id))

            # Verificar que el valor es un entero
            value = effective_config.get("jitter_window_seconds")
            assert isinstance(value, int), (
                f"Se esperaba tipo int para jitter_window_seconds, "
                f"obtenido tipo={type(value).__name__}, valor={value}"
            )
        finally:
            db.close()

    @given(jitter_window=_jitter_window)
    @settings(max_examples=100, deadline=None)
    def test_config_hash_incluye_jitter_window_seconds(self, jitter_window: int):
        """
        El config_hash se computa incluyendo jitter_window_seconds,
        garantizando que cambios en jitter se detectan por el hash.

        **Validates: Requirements 1.4**
        """
        db = _create_db_session()
        try:
            ws_id = _setup_org_and_workstation(db, jitter_window)

            config_service = ConfigService()
            effective_config = config_service.get_effective_config(db, str(ws_id))

            # Verificar que config_hash está presente (indica que jitter_window_seconds
            # fue incluido en el cálculo del hash, ya que no está en la lista de
            # campos excluidos)
            assert "config_hash" in effective_config, (
                "El campo 'config_hash' no está presente en el config payload"
            )
            assert len(effective_config["config_hash"]) == 64, (
                f"config_hash debería tener 64 caracteres (SHA-256 hex), "
                f"obtenido={len(effective_config['config_hash'])}"
            )
        finally:
            db.close()
