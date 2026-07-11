"""
Property test: Active session tenant isolation.

**Validates: Requirements 2.2, 2.3**

Para operador: solo ve sesiones de su organización.
Para admin: ve sesiones de cualquier organización.
"""

import uuid
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.schemas.bulk_actions import ActiveSessionInfo


# Estrategia: generar org_ids
org_id_st = st.uuids().map(str)


@st.composite
def tenant_scenario(draw):
    """
    Genera un escenario con:
    - user_org_id: la org del usuario operador
    - active_session_org_id: la org que tiene sesión activa
    - session_id: ID de la sesión activa
    """
    user_org_id = draw(org_id_st)
    # 50% de chance que la sesión sea de la misma org del usuario
    same_org = draw(st.booleans())
    if same_org:
        active_session_org_id = user_org_id
    else:
        active_session_org_id = draw(org_id_st.filter(lambda x: x != user_org_id))
    session_id = str(draw(st.uuids()))
    return {
        "user_org_id": user_org_id,
        "active_session_org_id": active_session_org_id,
        "session_id": session_id,
        "same_org": same_org,
    }


class TestActiveSessionTenantIsolation:
    """Property tests para tenant isolation en get_active_session."""

    @given(scenario=tenant_scenario())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_operator_only_sees_own_org_sessions(self, scenario):
        """
        Operador: solo ve sesiones de su propia organización.

        **Validates: Requirements 2.2**
        """
        user_org_id = scenario["user_org_id"]
        active_session_org_id = scenario["active_session_org_id"]
        session_id = scenario["session_id"]
        same_org = scenario["same_org"]

        # Mock user como operador
        mock_user = MagicMock()
        mock_user.role = "operator"
        mock_user.organization_id = user_org_id

        # Mock Redis client
        mock_redis = AsyncMock()

        if same_org:
            # La sesión activa es de la misma org → operador la ve
            mock_redis.get = AsyncMock(return_value=session_id)
            mock_redis.hgetall = AsyncMock(return_value={
                "status": "running",
                "org_id": active_session_org_id,
                "label": "TestAction",
                "started_at": "2026-01-01T00:00:00",
                "total": "100",
                "sent": "50",
            })
        else:
            # La sesión activa es de otra org → operador NO la ve
            mock_redis.get = AsyncMock(return_value=None)

        mock_redis.aclose = AsyncMock()

        with patch("app.services.bulk_execution.BulkExecutionService._get_redis_client", return_value=mock_redis):
            with patch("app.services.bulk_execution.SessionLocal") as mock_session_cls:
                mock_db = MagicMock()
                mock_session_cls.return_value = mock_db
                mock_db.query.return_value.filter.return_value.first.return_value = None

                from app.services.bulk_execution import BulkExecutionService
                service = BulkExecutionService()
                result = await service.get_active_session(mock_user)

                if same_org:
                    assert result.is_active is True
                    assert result.org_id == active_session_org_id
                else:
                    assert result.is_active is False

    @given(scenario=tenant_scenario())
    @settings(max_examples=100, deadline=None)
    @pytest.mark.asyncio
    async def test_admin_sees_any_org_session(self, scenario):
        """
        Admin: ve sesiones de cualquier organización.

        **Validates: Requirements 2.3**
        """
        active_session_org_id = scenario["active_session_org_id"]
        session_id = scenario["session_id"]

        # Mock user como admin
        mock_user = MagicMock()
        mock_user.role = "admin"
        mock_user.organization_id = str(uuid.uuid4())  # Otra org distinta

        # Mock Redis: simular SCAN que encuentra una key
        mock_redis = AsyncMock()
        # SCAN retorna la key bulk:running:{active_org}
        mock_redis.scan = AsyncMock(return_value=(0, [f"bulk:running:{active_session_org_id}"]))
        mock_redis.get = AsyncMock(return_value=session_id)
        mock_redis.hgetall = AsyncMock(return_value={
            "status": "running",
            "org_id": active_session_org_id,
            "label": "TestAction",
            "started_at": "2026-01-01T00:00:00",
            "total": "100",
            "sent": "50",
        })
        mock_redis.aclose = AsyncMock()

        with patch("app.services.bulk_execution.BulkExecutionService._get_redis_client", return_value=mock_redis):
            with patch("app.services.bulk_execution.SessionLocal") as mock_session_cls:
                mock_db = MagicMock()
                mock_session_cls.return_value = mock_db
                mock_db.query.return_value.filter.return_value.first.return_value = None

                from app.services.bulk_execution import BulkExecutionService
                service = BulkExecutionService()
                result = await service.get_active_session(mock_user)

                # Admin siempre ve la sesión activa de cualquier org
                assert result.is_active is True
                assert result.org_id == active_session_org_id

    @pytest.mark.asyncio
    async def test_operator_no_active_session_returns_false(self):
        """Operador sin sesión activa retorna is_active=False."""
        mock_user = MagicMock()
        mock_user.role = "operator"
        mock_user.organization_id = str(uuid.uuid4())

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.aclose = AsyncMock()

        with patch("app.services.bulk_execution.BulkExecutionService._get_redis_client", return_value=mock_redis):
            from app.services.bulk_execution import BulkExecutionService
            service = BulkExecutionService()
            result = await service.get_active_session(mock_user)

            assert result.is_active is False
            assert result.session_id is None

    @pytest.mark.asyncio
    async def test_admin_no_active_session_returns_false(self):
        """Admin sin sesiones activas en ninguna org retorna is_active=False."""
        mock_user = MagicMock()
        mock_user.role = "admin"
        mock_user.organization_id = str(uuid.uuid4())

        mock_redis = AsyncMock()
        # SCAN no encuentra ninguna key
        mock_redis.scan = AsyncMock(return_value=(0, []))
        mock_redis.aclose = AsyncMock()

        with patch("app.services.bulk_execution.BulkExecutionService._get_redis_client", return_value=mock_redis):
            from app.services.bulk_execution import BulkExecutionService
            service = BulkExecutionService()
            result = await service.get_active_session(mock_user)

            assert result.is_active is False
            assert result.session_id is None
