"""
Property test: Backward compatibility of failed workstations response.

Validates: Requirements 1.5

Para cualquier sesión con failed workstations, verificar que failed_workstations
(list[str]) y failed_workstation_details[*].id contienen los mismos IDs.
"""

import uuid
from datetime import datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.schemas.bulk_actions import (
    BulkSessionStatus,
    FailedWorkstationDetail,
)


# Estrategia: generar lista de failed workstation IDs
failed_ws_ids_st = st.lists(
    st.uuids().map(str),
    min_size=0,
    max_size=20,
    unique=True,
)

# Estrategia: generar FailedWorkstationDetail a partir de un ID
def detail_from_id(ws_id: str) -> FailedWorkstationDetail:
    """Crea un FailedWorkstationDetail con datos aleatorios pero ID fijo."""
    return FailedWorkstationDetail(
        id=ws_id,
        hostname=None,  # Puede ser cualquier valor, lo importante es el id
        ip_private="unknown",
    )


@st.composite
def session_status_scenario(draw):
    """Genera un BulkSessionStatus válido con failed workstations."""
    ws_ids = draw(failed_ws_ids_st)
    details = [detail_from_id(ws_id) for ws_id in ws_ids]

    total = draw(st.integers(min_value=max(1, len(ws_ids)), max_value=1000))
    sent = draw(st.integers(min_value=len(ws_ids), max_value=total))

    return {
        "failed_workstations": ws_ids,
        "failed_workstation_details": details,
        "total": total,
        "sent": sent,
    }


class TestBackwardCompatibilityProperty:
    """Property tests para backward compatibility de BulkSessionStatus."""

    @given(scenario=session_status_scenario())
    @settings(max_examples=200)
    def test_failed_workstations_ids_match_details_ids(self, scenario):
        """
        El set de IDs en failed_workstations coincide exactamente
        con el set de IDs en failed_workstation_details[*].id.
        """
        status = BulkSessionStatus(
            session_id=uuid.uuid4(),
            status="completed",
            total=scenario["total"],
            sent=scenario["sent"],
            success=scenario["sent"] - len(scenario["failed_workstations"]),
            errors=len(scenario["failed_workstations"]),
            failed_workstations=scenario["failed_workstations"],
            failed_workstation_details=scenario["failed_workstation_details"],
            started_at=datetime.now(),
            elapsed_ms=5000,
        )

        # Set de IDs en failed_workstations (campo legacy)
        legacy_ids = set(status.failed_workstations)

        # Set de IDs en failed_workstation_details (campo nuevo)
        detail_ids = set(d.id for d in status.failed_workstation_details)

        # Deben ser iguales
        assert legacy_ids == detail_ids

    @given(scenario=session_status_scenario())
    @settings(max_examples=200)
    def test_both_fields_have_same_length(self, scenario):
        """Ambos campos tienen la misma longitud."""
        status = BulkSessionStatus(
            session_id=uuid.uuid4(),
            status="completed",
            total=scenario["total"],
            sent=scenario["sent"],
            success=scenario["sent"] - len(scenario["failed_workstations"]),
            errors=len(scenario["failed_workstations"]),
            failed_workstations=scenario["failed_workstations"],
            failed_workstation_details=scenario["failed_workstation_details"],
            started_at=datetime.now(),
            elapsed_ms=5000,
        )

        assert len(status.failed_workstations) == len(status.failed_workstation_details)

    @given(scenario=session_status_scenario())
    @settings(max_examples=200)
    def test_both_fields_present_when_serialized(self, scenario):
        """Al serializar, ambos campos están presentes en el output."""
        status = BulkSessionStatus(
            session_id=uuid.uuid4(),
            status="completed",
            total=scenario["total"],
            sent=scenario["sent"],
            success=scenario["sent"] - len(scenario["failed_workstations"]),
            errors=len(scenario["failed_workstations"]),
            failed_workstations=scenario["failed_workstations"],
            failed_workstation_details=scenario["failed_workstation_details"],
            started_at=datetime.now(),
            elapsed_ms=5000,
        )

        serialized = status.model_dump()

        assert "failed_workstations" in serialized
        assert "failed_workstation_details" in serialized
        assert isinstance(serialized["failed_workstations"], list)
        assert isinstance(serialized["failed_workstation_details"], list)

    def test_empty_failed_workstations_backward_compatible(self):
        """Sin workstations fallidas, ambos campos son listas vacías."""
        status = BulkSessionStatus(
            session_id=uuid.uuid4(),
            status="completed",
            total=10,
            sent=10,
            success=10,
            errors=0,
            failed_workstations=[],
            failed_workstation_details=[],
            started_at=datetime.now(),
            elapsed_ms=5000,
        )

        assert status.failed_workstations == []
        assert status.failed_workstation_details == []
