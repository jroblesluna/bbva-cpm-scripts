"""
Property test: Failed workstation enrichment correctness.

**Validates: Requirements 1.1, 1.3**

Para cualquier set de IDs (existentes y no existentes en BD), verificar que
_enrich_failed_workstations produce lista con mismo largo, preserva orden,
y aplica hostname/ip_private correcto según existencia en BD.
"""

import uuid
from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.schemas.bulk_actions import FailedWorkstationDetail


# Estrategia: generar un conjunto de workstation IDs "existentes" con datos
@st.composite
def workstation_data(draw):
    """Genera datos de workstations que 'existen en BD'."""
    ws_id = str(draw(st.uuids()))
    hostname = draw(st.one_of(
        st.none(),
        st.text(min_size=3, max_size=20, alphabet=st.characters(whitelist_categories=('L', 'N')))
    ))
    ip_private = draw(st.one_of(
        st.none(),
        st.from_regex(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", fullmatch=True),
    ))
    return {"id": ws_id, "hostname": hostname, "ip_private": ip_private}


@st.composite
def enrichment_scenario(draw):
    """
    Genera un escenario de enriquecimiento:
    - existing_ws: workstations que existen en BD (con datos)
    - missing_ids: IDs que NO existen en BD
    - input_order: lista mezclada de IDs (existentes + no existentes) en orden aleatorio
    """
    existing = draw(st.lists(workstation_data(), min_size=0, max_size=10))
    num_missing = draw(st.integers(min_value=0, max_value=5))
    missing_ids = [str(draw(st.uuids())) for _ in range(num_missing)]

    # Garantizar que missing_ids no coincidan con existing
    existing_ids = {ws["id"] for ws in existing}
    missing_ids = [mid for mid in missing_ids if mid not in existing_ids]

    # Crear lista de input mezclando ambos
    all_ids = [ws["id"] for ws in existing] + missing_ids
    # Shuffle preservando determinismo de Hypothesis
    shuffled = draw(st.permutations(all_ids))

    return {
        "existing": existing,
        "missing_ids": missing_ids,
        "input_order": list(shuffled),
    }


class TestEnrichmentProperty:
    """Property tests para _enrich_failed_workstations."""

    @given(scenario=enrichment_scenario())
    @settings(max_examples=100, deadline=None)
    def test_output_length_equals_input_length(self, scenario):
        """
        La lista de salida tiene el mismo largo que la de entrada.

        **Validates: Requirements 1.1, 1.3**
        """
        existing = scenario["existing"]
        input_order = scenario["input_order"]

        # Mock de la BD
        with patch("app.services.bulk_execution.SessionLocal") as mock_session_cls:
            mock_db = MagicMock()
            mock_session_cls.return_value = mock_db

            # Simular query results
            mock_rows = []
            for ws in existing:
                row = MagicMock()
                row.id = uuid.UUID(ws["id"])
                row.hostname = ws["hostname"]
                row.ip_private = ws["ip_private"]
                mock_rows.append(row)

            mock_db.query.return_value.filter.return_value.all.return_value = mock_rows

            from app.services.bulk_execution import BulkExecutionService
            result = BulkExecutionService._enrich_failed_workstations(input_order)

            assert len(result) == len(input_order)

    @given(scenario=enrichment_scenario())
    @settings(max_examples=100, deadline=None)
    def test_preserves_input_order(self, scenario):
        """
        Los IDs en la salida están en el mismo orden que en la entrada.

        **Validates: Requirements 1.1, 1.3**
        """
        existing = scenario["existing"]
        input_order = scenario["input_order"]

        with patch("app.services.bulk_execution.SessionLocal") as mock_session_cls:
            mock_db = MagicMock()
            mock_session_cls.return_value = mock_db

            mock_rows = []
            for ws in existing:
                row = MagicMock()
                row.id = uuid.UUID(ws["id"])
                row.hostname = ws["hostname"]
                row.ip_private = ws["ip_private"]
                mock_rows.append(row)

            mock_db.query.return_value.filter.return_value.all.return_value = mock_rows

            from app.services.bulk_execution import BulkExecutionService
            result = BulkExecutionService._enrich_failed_workstations(input_order)

            result_ids = [detail.id for detail in result]
            assert result_ids == input_order

    @given(scenario=enrichment_scenario())
    @settings(max_examples=100, deadline=None)
    def test_existing_ws_have_correct_data(self, scenario):
        """
        Workstations existentes en BD retornan hostname e ip_private reales.

        **Validates: Requirements 1.1, 1.3**
        """
        existing = scenario["existing"]
        input_order = scenario["input_order"]

        with patch("app.services.bulk_execution.SessionLocal") as mock_session_cls:
            mock_db = MagicMock()
            mock_session_cls.return_value = mock_db

            mock_rows = []
            for ws in existing:
                row = MagicMock()
                row.id = uuid.UUID(ws["id"])
                row.hostname = ws["hostname"]
                row.ip_private = ws["ip_private"]
                mock_rows.append(row)

            mock_db.query.return_value.filter.return_value.all.return_value = mock_rows

            from app.services.bulk_execution import BulkExecutionService
            result = BulkExecutionService._enrich_failed_workstations(input_order)

            existing_map = {ws["id"]: ws for ws in existing}
            for detail in result:
                if detail.id in existing_map:
                    ws_data = existing_map[detail.id]
                    assert detail.hostname == ws_data["hostname"]
                    expected_ip = ws_data["ip_private"] or "unknown"
                    assert detail.ip_private == expected_ip

    @given(scenario=enrichment_scenario())
    @settings(max_examples=100, deadline=None)
    def test_missing_ws_have_null_hostname_and_unknown_ip(self, scenario):
        """
        Workstations NO existentes retornan hostname=None, ip_private='unknown'.

        **Validates: Requirements 1.1, 1.3**
        """
        existing = scenario["existing"]
        input_order = scenario["input_order"]
        missing_ids = set(scenario["missing_ids"])

        with patch("app.services.bulk_execution.SessionLocal") as mock_session_cls:
            mock_db = MagicMock()
            mock_session_cls.return_value = mock_db

            mock_rows = []
            for ws in existing:
                row = MagicMock()
                row.id = uuid.UUID(ws["id"])
                row.hostname = ws["hostname"]
                row.ip_private = ws["ip_private"]
                mock_rows.append(row)

            mock_db.query.return_value.filter.return_value.all.return_value = mock_rows

            from app.services.bulk_execution import BulkExecutionService
            result = BulkExecutionService._enrich_failed_workstations(input_order)

            for detail in result:
                if detail.id in missing_ids:
                    assert detail.hostname is None
                    assert detail.ip_private == "unknown"

    def test_empty_input_returns_empty_list(self):
        """Lista vacía de entrada retorna lista vacía."""
        from app.services.bulk_execution import BulkExecutionService
        result = BulkExecutionService._enrich_failed_workstations([])
        assert result == []
