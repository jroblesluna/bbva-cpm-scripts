"""
Tests de integración para Remote View SessionManager.

Verifica los flujos completos del ciclo de vida de sesiones de vista remota:
1. Exclusividad: segunda sesión para misma WS retorna None (→ caller genera 409)
2. Session timeout: sesiones inactivas se marcan expired por cleanup
3. Consent flow: accept, reject, timeout automático
4. Max concurrent sessions: límite por usuario
5. Tenant isolation: operador no puede iniciar en WS de otra org
6. Mode change: update_mode registra old_mode para audit trail
7. WS disconnect: end_session cierra con razón correcta

**Validates: Requirements 2.2, 2.9, 3.4, 3.5, 7.1, 7.7, 11.4, 12.2**
"""

import uuid
from datetime import datetime, timezone, timedelta

import pytest

# Importar modelo explícitamente (no está en app/models/__init__.py)
from app.models.remote_view import RemoteViewSession  # noqa: F401
from app.services.remote_view_session import SessionManager


# === FIXTURES ===


@pytest.fixture
def session_manager():
    """Instancia de SessionManager para tests."""
    return SessionManager()


@pytest.fixture
def org_id():
    """UUID de organización para los tests."""
    return str(uuid.uuid4())


@pytest.fixture
def other_org_id():
    """UUID de otra organización (para tenant isolation)."""
    return str(uuid.uuid4())


@pytest.fixture
def user_id():
    """UUID de usuario operador."""
    return str(uuid.uuid4())


@pytest.fixture
def other_user_id():
    """UUID de otro usuario operador."""
    return str(uuid.uuid4())


@pytest.fixture
def workstation_id():
    """UUID de workstation."""
    return str(uuid.uuid4())


@pytest.fixture
def other_workstation_id():
    """UUID de otra workstation."""
    return str(uuid.uuid4())


# === TEST 1: EXCLUSIVIDAD — SEGUNDA SESIÓN RETORNA NONE (409) ===


class TestExclusividad:
    """
    Tests de exclusividad: solo UNA sesión activa/pending por workstation.

    Validates: Requirement 2.2
    """

    def test_segunda_sesion_misma_ws_retorna_none(
        self, db, session_manager, workstation_id, user_id, other_user_id, org_id
    ):
        """
        WHEN ya existe una sesión pending/active para una WS,
        THEN crear una segunda sesión retorna None (caller genera 409).
        """
        # Primera sesión se crea exitosamente
        session1 = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
            mode="screenshot",
        )
        assert session1 is not None
        assert session1.status == "pending_consent"

        # Segunda sesión para misma WS retorna None
        session2 = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=other_user_id,
            org_id=org_id,
            mode="stream",
        )
        assert session2 is None

    def test_sesion_cerrada_permite_nueva_sesion(
        self, db, session_manager, workstation_id, user_id, other_user_id, org_id
    ):
        """
        WHEN una sesión se cierra, THEN se puede crear una nueva para la misma WS.
        """
        # Crear y cerrar primera sesión
        session1 = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
        )
        session_manager.end_session(db, str(session1.id), "admin_closed")

        # Nueva sesión se crea exitosamente
        session2 = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=other_user_id,
            org_id=org_id,
        )
        assert session2 is not None
        assert str(session2.id) != str(session1.id)

    def test_ws_distintas_permiten_sesiones_independientes(
        self, db, session_manager, workstation_id, other_workstation_id, user_id, org_id
    ):
        """
        WHEN dos WS distintas tienen sesiones, THEN ambas coexisten sin conflicto.
        """
        session1 = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
        )
        session2 = session_manager.create_session(
            db=db,
            workstation_id=other_workstation_id,
            user_id=user_id,
            org_id=org_id,
        )
        assert session1 is not None
        assert session2 is not None


# === TEST 2: SESSION TIMEOUT (INACTIVIDAD → EXPIRED) ===


class TestSessionTimeout:
    """
    Tests de timeout por inactividad.

    Validates: Requirement 7.1
    """

    def test_sesion_inactiva_se_marca_expired(
        self, db, session_manager, workstation_id, user_id, org_id
    ):
        """
        WHEN una sesión active tiene last_activity_at < NOW() - timeout,
        THEN cleanup_expired la marca como 'expired' con end_reason='timeout'.
        """
        # Crear sesión y aceptarla
        session = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
        )
        session_manager.accept_session(db, str(session.id))

        # Simular inactividad: poner last_activity_at hace 10 minutos
        session.last_activity_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=10)
        db.commit()

        # Ejecutar cleanup con timeout de 5 minutos
        affected = session_manager.cleanup_expired(db, session_timeout_minutes=5)

        assert len(affected) == 1
        assert affected[0].status == "expired"
        assert affected[0].end_reason == "timeout"
        assert affected[0].ended_at is not None

    def test_sesion_activa_reciente_no_se_expira(
        self, db, session_manager, workstation_id, user_id, org_id
    ):
        """
        WHEN una sesión active tiene last_activity_at reciente,
        THEN cleanup_expired NO la afecta.
        """
        # Crear sesión y aceptarla
        session = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
        )
        session_manager.accept_session(db, str(session.id))

        # last_activity_at es NOW (reciente)
        affected = session_manager.cleanup_expired(db, session_timeout_minutes=5)

        assert len(affected) == 0
        db.refresh(session)
        assert session.status == "active"


# === TEST 3: CONSENT FLOW (ACCEPT, REJECT, TIMEOUT) ===


class TestConsentFlow:
    """
    Tests del flujo de consentimiento.

    Validates: Requirements 3.4, 3.5
    """

    def test_accept_session_transiciona_a_active(
        self, db, session_manager, workstation_id, user_id, org_id
    ):
        """
        WHEN el usuario de la WS acepta la sesión,
        THEN status transiciona pending_consent → active, consent_given=True.
        """
        session = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
        )
        assert session.status == "pending_consent"

        accepted = session_manager.accept_session(db, str(session.id))

        assert accepted is not None
        assert accepted.status == "active"
        assert accepted.consent_given is True

    def test_reject_session_transiciona_a_rejected(
        self, db, session_manager, workstation_id, user_id, org_id
    ):
        """
        WHEN el usuario de la WS rechaza la sesión,
        THEN status transiciona pending_consent → rejected, consent_given=False.
        """
        session = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
        )

        rejected = session_manager.reject_session(db, str(session.id), reason="user_rejected")

        assert rejected is not None
        assert rejected.status == "rejected"
        assert rejected.consent_given is False
        assert rejected.end_reason == "user_rejected"
        assert rejected.ended_at is not None

    def test_consent_timeout_cierra_sesion_pending(
        self, db, session_manager, workstation_id, user_id, org_id
    ):
        """
        WHEN una sesión pending_consent supera el consent_timeout (35s),
        THEN cleanup_expired la marca como 'rejected' con end_reason='user_timeout'.
        """
        session = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
        )

        # Simular que empezó hace 40 segundos (supera 35s de consent timeout)
        session.started_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=40)
        db.commit()

        affected = session_manager.cleanup_expired(db, consent_timeout_seconds=35)

        assert len(affected) == 1
        assert affected[0].status == "rejected"
        assert affected[0].end_reason == "user_timeout"
        assert affected[0].consent_given is False

    def test_consent_timeout_no_afecta_sesion_reciente(
        self, db, session_manager, workstation_id, user_id, org_id
    ):
        """
        WHEN una sesión pending_consent fue creada hace 10s (< 35s timeout),
        THEN cleanup_expired NO la afecta.
        """
        session = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
        )
        # started_at es NOW (reciente), no supera timeout
        affected = session_manager.cleanup_expired(db, consent_timeout_seconds=35)

        assert len(affected) == 0
        db.refresh(session)
        assert session.status == "pending_consent"

    def test_accept_sesion_no_pending_retorna_none(
        self, db, session_manager, workstation_id, user_id, org_id
    ):
        """
        WHEN se intenta aceptar una sesión que ya no está en pending_consent,
        THEN retorna None (idempotencia).
        """
        session = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
        )
        # Aceptar la primera vez
        session_manager.accept_session(db, str(session.id))
        # Intentar aceptar de nuevo
        result = session_manager.accept_session(db, str(session.id))
        assert result is None


# === TEST 4: MAX CONCURRENT SESSIONS ===


class TestMaxConcurrentSessions:
    """
    Tests de límite de sesiones concurrentes por usuario.

    Validates: Requirement 2.9
    """

    def test_get_active_for_user_cuenta_sesiones_activas(
        self, db, session_manager, user_id, org_id
    ):
        """
        WHEN un usuario tiene N sesiones activas,
        THEN get_active_for_user retorna lista con N elementos.
        """
        # Crear 3 sesiones en workstations distintas y aceptarlas
        for i in range(3):
            ws_id = str(uuid.uuid4())
            session = session_manager.create_session(
                db=db,
                workstation_id=ws_id,
                user_id=user_id,
                org_id=org_id,
            )
            session_manager.accept_session(db, str(session.id))

        active_sessions = session_manager.get_active_for_user(db, user_id)
        assert len(active_sessions) == 3

    def test_sesiones_pending_no_cuentan_para_limite(
        self, db, session_manager, user_id, org_id
    ):
        """
        WHEN un usuario tiene sesiones pending_consent,
        THEN get_active_for_user NO las cuenta (solo status='active').
        """
        # Crear 2 sesiones sin aceptar (pending_consent)
        for i in range(2):
            ws_id = str(uuid.uuid4())
            session_manager.create_session(
                db=db,
                workstation_id=ws_id,
                user_id=user_id,
                org_id=org_id,
            )

        active_sessions = session_manager.get_active_for_user(db, user_id)
        assert len(active_sessions) == 0

    def test_sesiones_cerradas_no_cuentan_para_limite(
        self, db, session_manager, user_id, org_id
    ):
        """
        WHEN un usuario tiene sesiones cerradas/expired,
        THEN get_active_for_user NO las cuenta.
        """
        # Crear, aceptar y cerrar sesión
        ws_id = str(uuid.uuid4())
        session = session_manager.create_session(
            db=db,
            workstation_id=ws_id,
            user_id=user_id,
            org_id=org_id,
        )
        session_manager.accept_session(db, str(session.id))
        session_manager.end_session(db, str(session.id), "admin_closed")

        active_sessions = session_manager.get_active_for_user(db, user_id)
        assert len(active_sessions) == 0


# === TEST 5: TENANT ISOLATION ===


class TestTenantIsolation:
    """
    Tests de aislamiento por organización.

    El filtro de org se aplica en el endpoint (no en SessionManager directamente),
    pero verificamos que create_session registra correctamente el organization_id
    para que las queries de tenant isolation funcionen.

    Validates: Requirement 12.2
    """

    def test_sesion_registra_organization_id_correctamente(
        self, db, session_manager, workstation_id, user_id, org_id
    ):
        """
        WHEN se crea una sesión, THEN registra organization_id para tenant isolation.
        """
        session = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
        )
        assert str(session.organization_id) == org_id

    def test_sesiones_de_distintas_orgs_son_independientes(
        self, db, session_manager, user_id, other_user_id, org_id, other_org_id
    ):
        """
        WHEN dos orgs crean sesiones para WS distintas,
        THEN cada usuario solo ve sus propias sesiones activas.
        """
        # Usuario A en org A
        ws_a = str(uuid.uuid4())
        session_a = session_manager.create_session(
            db=db,
            workstation_id=ws_a,
            user_id=user_id,
            org_id=org_id,
        )
        session_manager.accept_session(db, str(session_a.id))

        # Usuario B en org B
        ws_b = str(uuid.uuid4())
        session_b = session_manager.create_session(
            db=db,
            workstation_id=ws_b,
            user_id=other_user_id,
            org_id=other_org_id,
        )
        session_manager.accept_session(db, str(session_b.id))

        # Cada usuario ve solo SU sesión activa
        user_a_sessions = session_manager.get_active_for_user(db, user_id)
        user_b_sessions = session_manager.get_active_for_user(db, other_user_id)

        assert len(user_a_sessions) == 1
        assert str(user_a_sessions[0].organization_id) == org_id

        assert len(user_b_sessions) == 1
        assert str(user_b_sessions[0].organization_id) == other_org_id

    def test_exclusividad_es_por_workstation_no_por_org(
        self, db, session_manager, workstation_id, user_id, other_user_id, org_id, other_org_id
    ):
        """
        WHEN una WS tiene sesión activa (sin importar org),
        THEN nadie puede iniciar otra sesión en esa WS.
        Exclusividad global por WS, no por org.
        """
        # Primer usuario crea sesión
        session1 = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
        )
        assert session1 is not None

        # Segundo usuario de otra org intenta crear sesión en la misma WS
        session2 = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=other_user_id,
            org_id=other_org_id,
        )
        assert session2 is None


# === TEST 6: MODE CHANGE REGISTRA AUDIT ENTRY ===


class TestModeChange:
    """
    Tests de cambio de modo con registro para audit trail.

    Validates: Requirement 11.4
    """

    def test_update_mode_cambia_modo_y_guarda_old_mode(
        self, db, session_manager, workstation_id, user_id, org_id
    ):
        """
        WHEN se cambia el modo de una sesión activa,
        THEN se actualiza mode y se expone _old_mode para audit.
        """
        session = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
            mode="screenshot",
        )
        session_manager.accept_session(db, str(session.id))

        updated = session_manager.update_mode(db, str(session.id), "stream")

        assert updated is not None
        assert updated.mode == "stream"
        assert updated._old_mode == "screenshot"  # type: ignore[attr-defined]

    def test_update_mode_sesion_no_activa_retorna_none(
        self, db, session_manager, workstation_id, user_id, org_id
    ):
        """
        WHEN se intenta cambiar modo de una sesión pending_consent,
        THEN retorna None (solo funciona en sesiones active).
        """
        session = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
        )
        # Sesión está en pending_consent, no active
        result = session_manager.update_mode(db, str(session.id), "stream")
        assert result is None

    def test_update_mode_actualiza_last_activity(
        self, db, session_manager, workstation_id, user_id, org_id
    ):
        """
        WHEN se cambia el modo, THEN last_activity_at se actualiza (reset timer).
        """
        session = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
        )
        session_manager.accept_session(db, str(session.id))

        # Simular inactividad previa
        old_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=3)
        session.last_activity_at = old_time
        db.commit()

        updated = session_manager.update_mode(db, str(session.id), "interactive")

        assert updated is not None
        # last_activity_at debe ser más reciente que old_time
        assert updated.last_activity_at > old_time


# === TEST 7: WS DISCONNECT → SESSION CLOSES ===


class TestEndSession:
    """
    Tests de cierre de sesión (simulando WS disconnect).

    Validates: Requirement 7.7
    """

    def test_end_session_cierra_con_razon_ws_disconnected(
        self, db, session_manager, workstation_id, user_id, org_id
    ):
        """
        WHEN la WS se desconecta y se llama end_session con razón ws_disconnected,
        THEN la sesión se marca como 'closed' con end_reason correcto.
        """
        session = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
        )
        session_manager.accept_session(db, str(session.id))

        ended = session_manager.end_session(db, str(session.id), "ws_disconnected")

        assert ended is not None
        assert ended.status == "closed"
        assert ended.end_reason == "ws_disconnected"
        assert ended.ended_at is not None

    def test_end_session_permite_nueva_sesion_despues(
        self, db, session_manager, workstation_id, user_id, other_user_id, org_id
    ):
        """
        WHEN una sesión se cierra por WS disconnect,
        THEN otra sesión puede crearse para la misma WS.
        """
        session = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
        )
        session_manager.accept_session(db, str(session.id))
        session_manager.end_session(db, str(session.id), "ws_disconnected")

        # Nueva sesión se puede crear
        new_session = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=other_user_id,
            org_id=org_id,
        )
        assert new_session is not None

    def test_end_session_ya_cerrada_retorna_none(
        self, db, session_manager, workstation_id, user_id, org_id
    ):
        """
        WHEN se intenta cerrar una sesión ya cerrada,
        THEN retorna None (idempotencia).
        """
        session = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
        )
        session_manager.accept_session(db, str(session.id))
        session_manager.end_session(db, str(session.id), "admin_closed")

        # Intentar cerrar de nuevo
        result = session_manager.end_session(db, str(session.id), "ws_disconnected")
        assert result is None

    def test_end_session_admin_closed(
        self, db, session_manager, workstation_id, user_id, org_id
    ):
        """
        WHEN el admin cierra la sesión manualmente,
        THEN se marca con end_reason='admin_closed'.
        """
        session = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
        )
        session_manager.accept_session(db, str(session.id))

        ended = session_manager.end_session(db, str(session.id), "admin_closed")

        assert ended.status == "closed"
        assert ended.end_reason == "admin_closed"

    def test_end_session_pending_consent(
        self, db, session_manager, workstation_id, user_id, org_id
    ):
        """
        WHEN se cierra una sesión que aún está en pending_consent,
        THEN se cierra correctamente (sesión aún no fue aceptada).
        """
        session = session_manager.create_session(
            db=db,
            workstation_id=workstation_id,
            user_id=user_id,
            org_id=org_id,
        )
        # No aceptamos la sesión — sigue en pending_consent

        ended = session_manager.end_session(db, str(session.id), "admin_closed")

        assert ended is not None
        assert ended.status == "closed"
        assert ended.end_reason == "admin_closed"
