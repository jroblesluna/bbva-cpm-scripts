"""
Property tests para aislamiento multi-tenant en queries de LogAnalysisService.

Verifica que todos los métodos de consulta (get_today_analysis, get_analysis_history,
get_analysis_by_id) filtran por organization_id, garantizando que una consulta con
organization_id=A nunca retorne registros pertenecientes a organization_id=B.

- Property 16: Tenant isolation in queries

**Validates: Requirements 12.9**
"""

import uuid
from contextlib import contextmanager
from datetime import date, timedelta

from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base

# Importar todos los modelos para que Base.metadata conozca todas las tablas
import app.models  # noqa: F401

from app.models.log_analysis import LogAnalysis
from app.models.organization import Organization
from app.models.workstation import Workstation
from app.services.log_analysis import LogAnalysisService


# === CONFIGURACIÓN DE BD EN MEMORIA ===


@contextmanager
def create_test_session():
    """
    Context manager que crea una sesión SQLite en memoria aislada.

    Crea todas las tablas, proporciona una sesión limpia y
    limpia los recursos al finalizar.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Habilitar foreign keys en SQLite
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _crear_organizacion(session: Session, org_id: str, name: str) -> Organization:
    """
    Crea una organización en la BD de test.

    Parámetros:
        session: Sesión SQLAlchemy
        org_id: UUID de la organización (string)
        name: Nombre de la organización

    Retorna:
        Organization creada
    """
    org = Organization(id=org_id, name=name, is_active=True)
    session.add(org)
    session.flush()
    return org


def _crear_workstation(
    session: Session, ws_id: str, org_id: str, ip_private: str
) -> Workstation:
    """
    Crea una workstation en la BD de test.

    Parámetros:
        session: Sesión SQLAlchemy
        ws_id: UUID de la workstation (string)
        org_id: UUID de la organización (string)
        ip_private: IP privada única de la workstation

    Retorna:
        Workstation creada
    """
    ws = Workstation(
        id=ws_id,
        organization_id=org_id,
        ip_private=ip_private,
    )
    session.add(ws)
    session.flush()
    return ws


def _crear_log_analysis(
    session: Session,
    ws_id: str,
    org_id: str,
    analysis_date: date,
    analysis_id: str | None = None,
) -> LogAnalysis:
    """
    Crea un registro de LogAnalysis en la BD de test.

    Parámetros:
        session: Sesión SQLAlchemy
        ws_id: UUID de la workstation (string)
        org_id: UUID de la organización (string)
        analysis_date: Fecha del análisis
        analysis_id: UUID del análisis (opcional, se genera si no se proporciona)

    Retorna:
        LogAnalysis creado
    """
    if analysis_id is None:
        analysis_id = str(uuid.uuid4())

    analysis = LogAnalysis(
        id=analysis_id,
        workstation_id=ws_id,
        organization_id=org_id,
        analysis_date=analysis_date,
        analysis_text="Análisis de prueba para tenant isolation",
        processing_path="direct",
        log_size_bytes=1024,
        processing_duration_ms=500,
        original_filename="AlwaysPrint_2024-01-15.log",
    )
    session.add(analysis)
    session.flush()
    return analysis


# === ESTRATEGIAS DE GENERACIÓN ===


@st.composite
def tenant_scenario(draw):
    """
    Genera un escenario de dos organizaciones con análisis en fechas variadas.

    Produce IDs únicos para dos organizaciones (A y B), cada una con
    su propia workstation y un número variable de análisis en distintas fechas.
    """
    org_a_id = str(uuid.uuid4())
    org_b_id = str(uuid.uuid4())
    assume(org_a_id != org_b_id)

    ws_a_id = str(uuid.uuid4())
    ws_b_id = str(uuid.uuid4())

    # Número de análisis por organización (al menos 1 cada una)
    num_analyses_a = draw(st.integers(min_value=1, max_value=5))
    num_analyses_b = draw(st.integers(min_value=1, max_value=5))

    # Generar offsets de días para los análisis (últimos 30 días)
    day_offsets_a = [
        draw(st.integers(min_value=0, max_value=29))
        for _ in range(num_analyses_a)
    ]
    day_offsets_b = [
        draw(st.integers(min_value=0, max_value=29))
        for _ in range(num_analyses_b)
    ]

    return {
        "org_a_id": org_a_id,
        "org_b_id": org_b_id,
        "ws_a_id": ws_a_id,
        "ws_b_id": ws_b_id,
        "day_offsets_a": day_offsets_a,
        "day_offsets_b": day_offsets_b,
    }


# === PROPERTY 16: TENANT ISOLATION IN QUERIES ===


class TestLogAnalysisTenantIsolation:
    """
    Property 16: Tenant isolation in queries.

    Todos los métodos de consulta (get_today_analysis, get_analysis_history,
    get_analysis_by_id) filtran por organization_id. Una consulta con
    organization_id=A nunca retorna registros pertenecientes a organization_id=B.

    **Validates: Requirements 12.9**
    """

    @given(data=st.data())
    @settings(max_examples=50, deadline=None)
    def test_get_today_analysis_no_retorna_datos_de_otro_tenant(
        self, data: st.DataObject
    ):
        """
        get_today_analysis con organization_id=A nunca retorna un análisis
        que pertenece a organization_id=B, incluso si la workstation tiene
        un análisis del día actual en otra organización.

        **Validates: Requirements 12.9**
        """
        org_a_id = str(uuid.uuid4())
        org_b_id = str(uuid.uuid4())
        assume(org_a_id != org_b_id)
        ws_a_id = str(uuid.uuid4())
        ws_b_id = str(uuid.uuid4())

        with create_test_session() as session:
            # Crear organizaciones y workstations
            _crear_organizacion(session, org_a_id, f"Org A {org_a_id[:8]}")
            _crear_organizacion(session, org_b_id, f"Org B {org_b_id[:8]}")
            _crear_workstation(session, ws_a_id, org_a_id, f"10.0.1.{data.draw(st.integers(1, 254))}")
            _crear_workstation(session, ws_b_id, org_b_id, f"10.0.2.{data.draw(st.integers(1, 254))}")

            # Crear análisis de hoy para org_b
            _crear_log_analysis(session, ws_b_id, org_b_id, date.today())
            session.commit()

            # Consultar con org_a — no debe retornar el análisis de org_b
            service = LogAnalysisService()
            resultado = service.get_today_analysis(session, ws_b_id, org_a_id)

            assert resultado is None, (
                f"get_today_analysis retornó un análisis de org_b ({org_b_id[:8]}) "
                f"cuando se consultó con org_a ({org_a_id[:8]}). "
                f"Violación de tenant isolation."
            )

    @given(data=st.data())
    @settings(max_examples=50, deadline=None)
    def test_get_today_analysis_retorna_datos_del_mismo_tenant(
        self, data: st.DataObject
    ):
        """
        get_today_analysis con organization_id=A retorna correctamente
        el análisis que pertenece a organization_id=A.

        **Validates: Requirements 12.9**
        """
        org_a_id = str(uuid.uuid4())
        org_b_id = str(uuid.uuid4())
        assume(org_a_id != org_b_id)
        ws_a_id = str(uuid.uuid4())
        ws_b_id = str(uuid.uuid4())

        with create_test_session() as session:
            # Crear organizaciones y workstations
            _crear_organizacion(session, org_a_id, f"Org A {org_a_id[:8]}")
            _crear_organizacion(session, org_b_id, f"Org B {org_b_id[:8]}")
            _crear_workstation(session, ws_a_id, org_a_id, f"10.0.1.{data.draw(st.integers(1, 254))}")
            _crear_workstation(session, ws_b_id, org_b_id, f"10.0.2.{data.draw(st.integers(1, 254))}")

            # Crear análisis de hoy para org_a
            _crear_log_analysis(session, ws_a_id, org_a_id, date.today())
            # Crear análisis de hoy para org_b (ruido)
            _crear_log_analysis(session, ws_b_id, org_b_id, date.today())
            session.commit()

            # Consultar con org_a — debe retornar solo el análisis de org_a
            service = LogAnalysisService()
            resultado = service.get_today_analysis(session, ws_a_id, org_a_id)

            assert resultado is not None, (
                f"get_today_analysis no retornó el análisis de org_a ({org_a_id[:8]}) "
                f"cuando se consultó correctamente con org_a."
            )
            assert str(resultado.organization_id) == org_a_id, (
                f"El análisis retornado pertenece a org {resultado.organization_id}, "
                f"pero se esperaba org_a ({org_a_id[:8]})."
            )

    @given(scenario=tenant_scenario())
    @settings(max_examples=50, deadline=None)
    def test_get_analysis_history_no_retorna_datos_de_otro_tenant(
        self, scenario: dict
    ):
        """
        get_analysis_history con organization_id=A nunca incluye registros
        que pertenecen a organization_id=B en los resultados paginados.

        **Validates: Requirements 12.9**
        """
        org_a_id = scenario["org_a_id"]
        org_b_id = scenario["org_b_id"]
        ws_a_id = scenario["ws_a_id"]
        ws_b_id = scenario["ws_b_id"]
        day_offsets_b = scenario["day_offsets_b"]

        with create_test_session() as session:
            # Crear organizaciones y workstations
            _crear_organizacion(session, org_a_id, f"Org A {org_a_id[:8]}")
            _crear_organizacion(session, org_b_id, f"Org B {org_b_id[:8]}")
            _crear_workstation(session, ws_a_id, org_a_id, f"10.1.0.{hash(ws_a_id) % 254 + 1}")
            _crear_workstation(session, ws_b_id, org_b_id, f"10.2.0.{hash(ws_b_id) % 254 + 1}")

            # Crear análisis para org_b
            base_date = date.today()
            for offset in day_offsets_b:
                _crear_log_analysis(
                    session, ws_b_id, org_b_id, base_date - timedelta(days=offset)
                )

            session.commit()

            # Consultar historial de ws_b con org_a — no debe retornar nada
            service = LogAnalysisService()
            items, total = service.get_analysis_history(session, ws_b_id, org_a_id)

            assert total == 0, (
                f"get_analysis_history retornó total={total} registros de org_b "
                f"({org_b_id[:8]}) cuando se consultó con org_a ({org_a_id[:8]}). "
                f"Violación de tenant isolation."
            )
            assert len(items) == 0, (
                f"get_analysis_history retornó {len(items)} items de org_b "
                f"cuando se consultó con org_a. Violación de tenant isolation."
            )

    @given(scenario=tenant_scenario())
    @settings(max_examples=50, deadline=None)
    def test_get_analysis_history_solo_retorna_datos_del_mismo_tenant(
        self, scenario: dict
    ):
        """
        get_analysis_history con organization_id=A retorna solo registros
        de organization_id=A, sin mezclar datos de otros tenants.

        **Validates: Requirements 12.9**
        """
        org_a_id = scenario["org_a_id"]
        org_b_id = scenario["org_b_id"]
        ws_a_id = scenario["ws_a_id"]
        ws_b_id = scenario["ws_b_id"]
        day_offsets_a = scenario["day_offsets_a"]
        day_offsets_b = scenario["day_offsets_b"]

        with create_test_session() as session:
            # Crear organizaciones y workstations
            _crear_organizacion(session, org_a_id, f"Org A {org_a_id[:8]}")
            _crear_organizacion(session, org_b_id, f"Org B {org_b_id[:8]}")
            _crear_workstation(session, ws_a_id, org_a_id, f"10.1.0.{hash(ws_a_id) % 254 + 1}")
            _crear_workstation(session, ws_b_id, org_b_id, f"10.2.0.{hash(ws_b_id) % 254 + 1}")

            # Crear análisis para ambas organizaciones
            base_date = date.today()
            for offset in day_offsets_a:
                _crear_log_analysis(
                    session, ws_a_id, org_a_id, base_date - timedelta(days=offset)
                )
            for offset in day_offsets_b:
                _crear_log_analysis(
                    session, ws_b_id, org_b_id, base_date - timedelta(days=offset)
                )

            session.commit()

            # Consultar historial de ws_a con org_a
            service = LogAnalysisService()
            items, total = service.get_analysis_history(session, ws_a_id, org_a_id)

            # Todos los resultados deben pertenecer a org_a
            for item in items:
                assert str(item.organization_id) == org_a_id, (
                    f"get_analysis_history retornó un análisis de org "
                    f"{item.organization_id} cuando se consultó con org_a "
                    f"({org_a_id[:8]}). Violación de tenant isolation."
                )

            # El total debe coincidir con los análisis creados para org_a
            assert total == len(day_offsets_a), (
                f"get_analysis_history retornó total={total}, pero se crearon "
                f"{len(day_offsets_a)} análisis para org_a."
            )

    @given(data=st.data())
    @settings(max_examples=50, deadline=None)
    def test_get_analysis_by_id_no_retorna_datos_de_otro_tenant(
        self, data: st.DataObject
    ):
        """
        get_analysis_by_id con organization_id=A nunca retorna un análisis
        que pertenece a organization_id=B, incluso conociendo el ID exacto.

        **Validates: Requirements 12.9**
        """
        org_a_id = str(uuid.uuid4())
        org_b_id = str(uuid.uuid4())
        assume(org_a_id != org_b_id)
        ws_b_id = str(uuid.uuid4())
        analysis_b_id = str(uuid.uuid4())

        with create_test_session() as session:
            # Crear organizaciones y workstations
            _crear_organizacion(session, org_a_id, f"Org A {org_a_id[:8]}")
            _crear_organizacion(session, org_b_id, f"Org B {org_b_id[:8]}")
            _crear_workstation(session, ws_b_id, org_b_id, f"10.2.0.{data.draw(st.integers(1, 254))}")

            # Crear análisis en org_b con ID conocido
            _crear_log_analysis(
                session, ws_b_id, org_b_id, date.today(), analysis_id=analysis_b_id
            )
            session.commit()

            # Intentar acceder al análisis de org_b usando org_a
            service = LogAnalysisService()
            resultado = service.get_analysis_by_id(session, analysis_b_id, org_a_id)

            assert resultado is None, (
                f"get_analysis_by_id retornó el análisis {analysis_b_id[:8]} de org_b "
                f"({org_b_id[:8]}) cuando se consultó con org_a ({org_a_id[:8]}). "
                f"Violación de tenant isolation: acceso cross-tenant por ID."
            )

    @given(data=st.data())
    @settings(max_examples=50, deadline=None)
    def test_get_analysis_by_id_retorna_datos_del_mismo_tenant(
        self, data: st.DataObject
    ):
        """
        get_analysis_by_id con organization_id=A retorna correctamente
        un análisis que pertenece a organization_id=A.

        **Validates: Requirements 12.9**
        """
        org_a_id = str(uuid.uuid4())
        org_b_id = str(uuid.uuid4())
        assume(org_a_id != org_b_id)
        ws_a_id = str(uuid.uuid4())
        ws_b_id = str(uuid.uuid4())
        analysis_a_id = str(uuid.uuid4())
        analysis_b_id = str(uuid.uuid4())

        with create_test_session() as session:
            # Crear organizaciones y workstations
            _crear_organizacion(session, org_a_id, f"Org A {org_a_id[:8]}")
            _crear_organizacion(session, org_b_id, f"Org B {org_b_id[:8]}")
            _crear_workstation(session, ws_a_id, org_a_id, f"10.1.0.{data.draw(st.integers(1, 254))}")
            _crear_workstation(session, ws_b_id, org_b_id, f"10.2.0.{data.draw(st.integers(1, 254))}")

            # Crear análisis en ambas organizaciones
            _crear_log_analysis(
                session, ws_a_id, org_a_id, date.today(), analysis_id=analysis_a_id
            )
            _crear_log_analysis(
                session, ws_b_id, org_b_id, date.today(), analysis_id=analysis_b_id
            )
            session.commit()

            # Acceder al análisis de org_a con org_a — debe funcionar
            service = LogAnalysisService()
            resultado = service.get_analysis_by_id(session, analysis_a_id, org_a_id)

            assert resultado is not None, (
                f"get_analysis_by_id no retornó el análisis {analysis_a_id[:8]} "
                f"de org_a ({org_a_id[:8]}) cuando se consultó correctamente."
            )
            assert str(resultado.organization_id) == org_a_id, (
                f"El análisis retornado pertenece a org {resultado.organization_id}, "
                f"pero se esperaba org_a ({org_a_id[:8]})."
            )
            assert str(resultado.id) == analysis_a_id, (
                f"El análisis retornado tiene id={resultado.id}, "
                f"pero se esperaba {analysis_a_id[:8]}."
            )
