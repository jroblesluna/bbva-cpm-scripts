"""
Servicio de gestión de sesiones de vista remota.

Este servicio implementa la lógica de negocio para:
- Creación de sesiones con control de exclusividad por workstation
- Gestión del ciclo de vida: pending_consent → active → closed/expired/rejected
- Consulta de sesiones activas por workstation y usuario
- Actualización de actividad (reset de timeout)
- Limpieza periódica de sesiones expiradas y timeouts de consentimiento
"""

from typing import Optional, List
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.remote_view import RemoteViewSession


class SessionManager:
    """
    Gestor de sesiones de vista remota.

    Proporciona métodos para:
    - Crear sesiones con exclusividad por workstation (solo 1 activa/pending por WS)
    - Aceptar/rechazar sesiones (flujo de consentimiento)
    - Finalizar sesiones con razón de cierre
    - Consultar sesiones activas por workstation o usuario
    - Actualizar actividad y modo
    - Limpiar sesiones expiradas periódicamente

    Patrón: instanciable, todos los métodos reciben `db: Session` como primer parámetro.
    Filtrado por organization_id para tenant isolation donde aplica.
    """

    # Estados que representan sesiones "ocupando" una workstation
    _ACTIVE_STATUSES = ("pending_consent", "active")

    def create_session(
        self,
        db: Session,
        workstation_id: str,
        user_id: str,
        org_id: str,
        mode: str = "screenshot",
    ) -> Optional[RemoteViewSession]:
        """
        Crea una nueva sesión de vista remota.

        Regla de exclusividad: solo UNA sesión con status 'pending_consent' o 'active'
        puede existir por workstation. Si ya existe una, retorna None (el caller
        maneja el error 409).

        Args:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation objetivo
            user_id: UUID del admin/operador que inicia la sesión
            org_id: UUID de la organización (tenant isolation)
            mode: Modo inicial de la sesión (screenshot, stream, interactive)

        Returns:
            RemoteViewSession creada, o None si ya existe una sesión activa/pending
            para esa workstation.
        """
        # Verificar exclusividad: no debe existir sesión activa/pending para esta WS
        existing = self.get_active_for_workstation(db, workstation_id)
        if existing is not None:
            return None

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        session = RemoteViewSession(
            id=uuid4(),
            workstation_id=workstation_id,
            user_id=user_id,
            organization_id=org_id,
            mode=mode,
            status="pending_consent",
            started_at=now,
            last_activity_at=now,
            created_at=now,
        )

        db.add(session)
        db.commit()
        db.refresh(session)

        return session

    def accept_session(
        self,
        db: Session,
        session_id: str,
    ) -> Optional[RemoteViewSession]:
        """
        Acepta una sesión pendiente de consentimiento.

        Transición: pending_consent → active.
        Registra consent_given=True.

        Args:
            db: Sesión de base de datos
            session_id: UUID de la sesión a aceptar

        Returns:
            RemoteViewSession actualizada, o None si no se encuentra o no está en pending_consent.
        """
        session = db.query(RemoteViewSession).filter(
            RemoteViewSession.id == session_id,
            RemoteViewSession.status == "pending_consent",
        ).first()

        if session is None:
            return None

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        session.status = "active"
        session.consent_given = True
        session.last_activity_at = now

        db.commit()
        db.refresh(session)

        return session

    def reject_session(
        self,
        db: Session,
        session_id: str,
        reason: str = "user_rejected",
    ) -> Optional[RemoteViewSession]:
        """
        Rechaza una sesión pendiente de consentimiento.

        Transición: pending_consent → rejected.
        Registra consent_given=False y el motivo del rechazo.

        Args:
            db: Sesión de base de datos
            session_id: UUID de la sesión a rechazar
            reason: Razón del rechazo (user_rejected, user_timeout)

        Returns:
            RemoteViewSession actualizada, o None si no se encuentra o no está en pending_consent.
        """
        session = db.query(RemoteViewSession).filter(
            RemoteViewSession.id == session_id,
            RemoteViewSession.status == "pending_consent",
        ).first()

        if session is None:
            return None

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        session.status = "rejected"
        session.consent_given = False
        session.end_reason = reason
        session.ended_at = now

        db.commit()
        db.refresh(session)

        return session

    def end_session(
        self,
        db: Session,
        session_id: str,
        end_reason: str = "admin_closed",
    ) -> Optional[RemoteViewSession]:
        """
        Finaliza una sesión activa o pendiente.

        Transición: active/pending_consent → closed.
        Registra ended_at y la razón de cierre.

        Args:
            db: Sesión de base de datos
            session_id: UUID de la sesión a finalizar
            end_reason: Razón de cierre (timeout, admin_closed, ws_disconnected,
                        user_rejected, user_timeout, admin_logout)

        Returns:
            RemoteViewSession actualizada, o None si no se encuentra o ya está cerrada.
        """
        session = db.query(RemoteViewSession).filter(
            RemoteViewSession.id == session_id,
            RemoteViewSession.status.in_(self._ACTIVE_STATUSES),
        ).first()

        if session is None:
            return None

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        session.status = "closed"
        session.end_reason = end_reason
        session.ended_at = now

        db.commit()
        db.refresh(session)

        return session

    def get_active_for_workstation(
        self,
        db: Session,
        workstation_id: str,
    ) -> Optional[RemoteViewSession]:
        """
        Obtiene la sesión activa o pendiente de consentimiento para una workstation.

        Solo puede haber UNA sesión con status IN ('pending_consent', 'active')
        por workstation (exclusividad).

        Args:
            db: Sesión de base de datos
            workstation_id: UUID de la workstation

        Returns:
            RemoteViewSession activa/pending, o None si no hay ninguna.
        """
        return db.query(RemoteViewSession).filter(
            RemoteViewSession.workstation_id == workstation_id,
            RemoteViewSession.status.in_(self._ACTIVE_STATUSES),
        ).first()

    def get_active_for_user(
        self,
        db: Session,
        user_id: str,
    ) -> List[RemoteViewSession]:
        """
        Obtiene todas las sesiones activas de un usuario (admin/operador).

        Útil para verificar el límite de max_concurrent_sessions.
        Solo cuenta sesiones con status='active' (no pending_consent).

        Args:
            db: Sesión de base de datos
            user_id: UUID del admin/operador

        Returns:
            Lista de sesiones activas del usuario.
        """
        return db.query(RemoteViewSession).filter(
            RemoteViewSession.user_id == user_id,
            RemoteViewSession.status == "active",
        ).all()

    def update_activity(
        self,
        db: Session,
        session_id: str,
    ) -> Optional[RemoteViewSession]:
        """
        Actualiza last_activity_at de una sesión activa.

        Se llama cada vez que el admin interactúa con la sesión
        (click en canvas, input, cambio de modo/resolución, etc.)
        para resetear el timer de inactividad.

        Args:
            db: Sesión de base de datos
            session_id: UUID de la sesión

        Returns:
            RemoteViewSession actualizada, o None si no se encuentra o no está activa.
        """
        session = db.query(RemoteViewSession).filter(
            RemoteViewSession.id == session_id,
            RemoteViewSession.status == "active",
        ).first()

        if session is None:
            return None

        session.last_activity_at = datetime.now(timezone.utc).replace(tzinfo=None)

        db.commit()
        db.refresh(session)

        return session

    def update_mode(
        self,
        db: Session,
        session_id: str,
        new_mode: str,
    ) -> Optional[RemoteViewSession]:
        """
        Actualiza el modo de una sesión activa.

        Transiciones válidas entre modos: screenshot ↔ stream ↔ interactive.
        No requiere nuevo consentimiento (cubierto por el consent inicial).

        Almacena el modo anterior en el atributo transitorio `_old_mode` del objeto
        retornado, para que los callers puedan registrar el cambio en audit trail.

        Args:
            db: Sesión de base de datos
            session_id: UUID de la sesión
            new_mode: Nuevo modo (screenshot, stream, interactive)

        Returns:
            RemoteViewSession actualizada (con _old_mode seteado),
            o None si no se encuentra o no está activa.
        """
        session = db.query(RemoteViewSession).filter(
            RemoteViewSession.id == session_id,
            RemoteViewSession.status == "active",
        ).first()

        if session is None:
            return None

        # Guardar modo anterior para audit trail
        old_mode = session.mode

        session.mode = new_mode
        session.last_activity_at = datetime.now(timezone.utc).replace(tzinfo=None)

        db.commit()
        db.refresh(session)

        # Atributo transitorio para que el caller pueda registrar el cambio
        session._old_mode = old_mode  # type: ignore[attr-defined]

        return session

    def cleanup_expired(
        self,
        db: Session,
        session_timeout_minutes: int = 5,
        consent_timeout_seconds: int = 35,
    ) -> List[RemoteViewSession]:
        """
        Limpia sesiones expiradas por timeout de inactividad y timeout de consentimiento.

        Se ejecuta periódicamente (cada 60s) para:
        1. Sesiones 'active' donde last_activity_at < NOW() - session_timeout_minutes
           → marca como 'expired' con end_reason='timeout'
        2. Sesiones 'pending_consent' donde started_at < NOW() - consent_timeout_seconds
           (30s consent + 5s grace = 35s por defecto)
           → marca como 'rejected' con end_reason='user_timeout'

        Args:
            db: Sesión de base de datos
            session_timeout_minutes: Minutos de inactividad antes de expirar (default: 5)
            consent_timeout_seconds: Segundos antes de timeout de consentimiento (default: 35)

        Returns:
            Lista de sesiones afectadas (expiradas + rechazadas por timeout).
            El caller usa esta lista para enviar remote_view_stop a las WS correspondientes.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        affected: List[RemoteViewSession] = []

        # 1. Sesiones activas expiradas por inactividad
        activity_cutoff = now - timedelta(minutes=session_timeout_minutes)
        expired_sessions = db.query(RemoteViewSession).filter(
            RemoteViewSession.status == "active",
            RemoteViewSession.last_activity_at < activity_cutoff,
        ).all()

        for session in expired_sessions:
            session.status = "expired"
            session.end_reason = "timeout"
            session.ended_at = now
            affected.append(session)

        # 2. Sesiones pending_consent expiradas por timeout de consentimiento
        consent_cutoff = now - timedelta(seconds=consent_timeout_seconds)
        timed_out_sessions = db.query(RemoteViewSession).filter(
            RemoteViewSession.status == "pending_consent",
            RemoteViewSession.started_at < consent_cutoff,
        ).all()

        for session in timed_out_sessions:
            session.status = "rejected"
            session.end_reason = "user_timeout"
            session.consent_given = False
            session.ended_at = now
            affected.append(session)

        if affected:
            db.commit()

        return affected
