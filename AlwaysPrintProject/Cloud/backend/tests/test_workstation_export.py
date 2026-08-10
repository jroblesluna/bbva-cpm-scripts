"""
Property tests para exportación de workstations y codificación BOM.

Verifica que el CSV de inventario de workstations contiene las columnas
correctas y que la codificación UTF-8 BOM es compatible con Excel.

Feature: user-activity-export, Property 9: Workstation CSV column completeness
Feature: user-activity-export, Property 10: UTF-8 BOM encoding for Excel compatibility

**Validates: Requirements 4.2, 4.5**
"""

import csv
import io
from datetime import datetime

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.services.export_csv import CSVExportService


# === Estrategias de generación ===

# Texto genérico para campos de workstation (letras ASCII y dígitos, rápido de generar)
_text_field = st.text(
    alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-"),
    min_size=0,
    max_size=20,
)

# IP privada (formato tipo IP)
_ip_field = st.builds(
    lambda a, b, c, d: f"{a}.{b}.{c}.{d}",
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
)

# Versión del tray (formato semver simple)
_version_field = st.builds(
    lambda major, minor, patch: f"{major}.{minor}.{patch}",
    st.integers(min_value=0, max_value=9),
    st.integers(min_value=0, max_value=9),
    st.integers(min_value=0, max_value=99),
)

# Datetime o None para last_connection
_datetime_or_none = st.one_of(
    st.none(),
    st.datetimes(
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2030, 12, 31),
    ),
)

# Estrategia completa para un registro de workstation (dict)
_workstation_strategy = st.fixed_dictionaries({
    "hostname": _text_field,
    "ip_private": _ip_field,
    "current_user": _text_field,
    "organization_name": _text_field,
    "tray_version": _version_field,
    "action_config_name": _text_field,
    "last_connection": _datetime_or_none,
    "is_online": st.booleans(),
    "vlan_name": _text_field,
})

# Lista de workstations (1 a 20 registros)
_workstation_list = st.lists(_workstation_strategy, min_size=1, max_size=20)


# === Cabeceras esperadas ===

EXPECTED_WORKSTATION_HEADERS = [
    "hostname",
    "ip_private",
    "current_user",
    "organization_name",
    "tray_version",
    "action_config_name",
    "last_connection",
    "is_online",
    "vlan_name",
]

EXPECTED_ACTIVITY_HEADERS = [
    "timestamp",
    "action_type",
    "entity_type",
    "entity_name",
    "old_values",
    "new_values",
    "ip_address",
]


# === PROPERTY 9: WORKSTATION CSV COLUMN COMPLETENESS ===
# Feature: user-activity-export, Property 9: Workstation CSV column completeness


class TestWorkstationCSVColumnCompleteness:
    """
    Property 9: Workstation CSV column completeness.

    Para cualquier conjunto de datos de workstation generado aleatoriamente,
    el CSV producido por generate_workstation_csv() debe tener exactamente
    9 columnas con las cabeceras correctas, y el campo is_online debe
    contener únicamente "Online" u "Offline".

    Feature: user-activity-export, Property 9: Workstation CSV column completeness

    **Validates: Requirements 4.2**
    """

    @given(workstations=_workstation_list)
    @settings(max_examples=100, deadline=None)
    def test_csv_has_correct_headers_and_column_count(self, workstations):
        """Verifica que todas las filas tienen exactamente 9 columnas con cabeceras correctas."""
        # Generar CSV completo
        csv_rows = list(CSVExportService.generate_workstation_csv(workstations))

        # Unir todas las filas en un solo string para parsear
        csv_content = "".join(csv_rows)
        reader = csv.reader(io.StringIO(csv_content))
        rows = list(reader)

        # Debe haber cabecera + N filas de datos
        assert len(rows) == len(workstations) + 1, (
            f"Se esperaban {len(workstations) + 1} filas (cabecera + datos), "
            f"se obtuvieron {len(rows)}"
        )

        # Verificar cabeceras
        header = rows[0]
        assert header == EXPECTED_WORKSTATION_HEADERS, (
            f"Cabeceras incorrectas: {header}"
        )

        # Verificar que cada fila de datos tiene exactamente 9 columnas
        for i, row in enumerate(rows[1:], start=1):
            assert len(row) == 9, (
                f"Fila {i} tiene {len(row)} columnas, se esperan 9: {row}"
            )

    @given(workstations=_workstation_list)
    @settings(max_examples=100, deadline=None)
    def test_is_online_column_only_online_or_offline(self, workstations):
        """Verifica que la columna is_online contiene solo 'Online' u 'Offline'."""
        csv_rows = list(CSVExportService.generate_workstation_csv(workstations))
        csv_content = "".join(csv_rows)
        reader = csv.DictReader(io.StringIO(csv_content))

        for row in reader:
            assert row["is_online"] in ("Online", "Offline"), (
                f"Valor inesperado en is_online: '{row['is_online']}'. "
                f"Solo se permiten 'Online' u 'Offline'."
            )


# === PROPERTY 10: UTF-8 BOM ENCODING FOR EXCEL COMPATIBILITY ===
# Feature: user-activity-export, Property 10: UTF-8 BOM encoding for Excel compatibility


class TestUTF8BOMEncoding:
    """
    Property 10: UTF-8 BOM encoding for Excel compatibility.

    Para cualquier exportación CSV (actividad o workstation), al anteponer
    el resultado de utf8_bom(), el contenido del archivo debe comenzar
    con los bytes BOM (0xEF, 0xBB, 0xBF).

    Feature: user-activity-export, Property 10: UTF-8 BOM encoding for Excel compatibility

    **Validates: Requirements 4.5**
    """

    @given(workstations=_workstation_list)
    @settings(max_examples=100, deadline=None)
    def test_workstation_csv_with_bom_starts_with_bom_bytes(self, workstations):
        """Verifica que el CSV de workstations con BOM comienza con los bytes correctos."""
        # Generar CSV y prepend BOM
        csv_rows = list(CSVExportService.generate_workstation_csv(workstations))
        csv_content = "".join(csv_rows)

        # Construir contenido final como lo haría el endpoint (BOM + CSV)
        bom = CSVExportService.utf8_bom()
        file_bytes = bom + csv_content.encode("utf-8")

        # Verificar que comienza con BOM
        assert file_bytes[:3] == b'\xef\xbb\xbf', (
            f"El archivo no comienza con BOM. Primeros 3 bytes: {file_bytes[:3]!r}"
        )

    @given(
        logs=st.lists(
            st.fixed_dictionaries({
                "created_at": st.datetimes(
                    min_value=datetime(2020, 1, 1),
                    max_value=datetime(2030, 12, 31),
                ),
                "action_type": st.sampled_from([
                    "CREATE", "UPDATE", "DELETE", "LOGIN", "LOGOUT",
                ]),
                "entity_type": st.sampled_from([
                    "workstation", "user", "organization", "vlan",
                ]),
                "entity_id": st.uuids().map(str),
                "old_values": st.none(),
                "new_values": st.none(),
                "ip_address": _ip_field,
            }),
            min_size=1,
            max_size=10,
        )
    )
    @settings(max_examples=100, deadline=None)
    def test_activity_csv_with_bom_starts_with_bom_bytes(self, logs):
        """Verifica que el CSV de actividad con BOM comienza con los bytes correctos."""
        # Preparar entity_names vacío (no afecta la verificación de BOM)
        entity_names = {}

        # Generar CSV y prepend BOM
        csv_rows = list(CSVExportService.generate_activity_csv(logs, entity_names))
        csv_content = "".join(csv_rows)

        # Construir contenido final como lo haría el endpoint
        bom = CSVExportService.utf8_bom()
        file_bytes = bom + csv_content.encode("utf-8")

        # Verificar que comienza con BOM
        assert file_bytes[:3] == b'\xef\xbb\xbf', (
            f"El archivo no comienza con BOM. Primeros 3 bytes: {file_bytes[:3]!r}"
        )

    def test_utf8_bom_returns_correct_bytes(self):
        """Verificación directa de que utf8_bom() retorna exactamente los 3 bytes esperados."""
        bom = CSVExportService.utf8_bom()
        assert bom == b'\xef\xbb\xbf'
        assert len(bom) == 3
