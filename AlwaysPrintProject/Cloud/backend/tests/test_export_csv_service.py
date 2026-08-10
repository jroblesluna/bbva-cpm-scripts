"""
Tests unitarios para CSVExportService.

Valida la generación correcta de archivos CSV para:
- Exportación de actividad de usuario (timeline)
- Exportación de inventario de workstations
- Codificación UTF-8 BOM para compatibilidad con Excel
- Serialización de campos JSON compactos

Requirements: 3.2, 4.2, 4.5
"""

import csv
import io
import json
from datetime import datetime, timezone

import pytest

from app.services.export_csv import CSVExportService


# === CONSTANTES DE PRUEBA ===

# Cabeceras esperadas para CSV de actividad
ACTIVITY_HEADERS = [
    "timestamp",
    "action_type",
    "entity_type",
    "entity_name",
    "old_values",
    "new_values",
    "ip_address",
]

# Cabeceras esperadas para CSV de workstations
WORKSTATION_HEADERS = [
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


# === DATOS DE PRUEBA ===

def _sample_activity_logs():
    """Genera datos de ejemplo de logs de actividad."""
    return [
        {
            "created_at": datetime(2026, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
            "action_type": "create",
            "entity_type": "workstation",
            "entity_id": "ws-001",
            "old_values": None,
            "new_values": {"hostname": "PC-001", "ip": "10.0.1.50"},
            "ip_address": "192.168.1.50",
        },
        {
            "created_at": datetime(2026, 6, 14, 8, 0, 0, tzinfo=timezone.utc),
            "action_type": "update",
            "entity_type": "user",
            "entity_id": "usr-002",
            "old_values": {"role": "operator"},
            "new_values": {"role": "admin"},
            "ip_address": "10.0.0.1",
        },
    ]


def _sample_entity_names():
    """Diccionario de mapeo entity_id → nombre legible."""
    return {
        "ws-001": "w01230p01",
        "usr-002": "Juan Pérez",
    }


def _sample_workstations():
    """Genera datos de ejemplo de workstations."""
    return [
        {
            "hostname": "w01230p01",
            "ip_private": "10.0.1.10",
            "current_user": "jperez",
            "organization_name": "BBVA Oficina 123",
            "tray_version": "2.1.0",
            "action_config_name": "CPM_Compliant",
            "last_connection": datetime(2026, 6, 15, 9, 45, 0, tzinfo=timezone.utc),
            "is_online": True,
            "vlan_name": "VLAN_IMPRESION",
        },
        {
            "hostname": "w04560p02",
            "ip_private": "10.0.2.20",
            "current_user": "mlopez",
            "organization_name": "BBVA Oficina 456",
            "tray_version": "2.0.5",
            "action_config_name": "LPM_Compliant",
            "last_connection": datetime(2026, 6, 14, 16, 30, 0, tzinfo=timezone.utc),
            "is_online": False,
            "vlan_name": "VLAN_ADMIN",
        },
    ]


# === HELPERS ===

def _parse_csv_output(rows_generator) -> list:
    """Concatena las filas del generador y las parsea con csv.reader."""
    full_csv = "".join(rows_generator)
    reader = csv.reader(io.StringIO(full_csv))
    return list(reader)


# === TESTS: utf8_bom() ===

class TestUtf8Bom:
    """Verifica que utf8_bom retorna los bytes BOM correctos."""

    def test_bom_returns_correct_bytes(self):
        """El BOM debe ser exactamente 0xEF 0xBB 0xBF."""
        bom = CSVExportService.utf8_bom()
        assert bom == b'\xef\xbb\xbf'

    def test_bom_is_bytes_type(self):
        """El retorno debe ser de tipo bytes."""
        bom = CSVExportService.utf8_bom()
        assert isinstance(bom, bytes)

    def test_bom_length_is_three(self):
        """El BOM UTF-8 tiene exactamente 3 bytes."""
        bom = CSVExportService.utf8_bom()
        assert len(bom) == 3


# === TESTS: generate_activity_csv() ===

class TestGenerateActivityCsv:
    """Verifica la generación de CSV de actividad de usuario."""

    def test_headers_are_correct(self):
        """Las cabeceras del CSV deben coincidir con las 7 columnas definidas."""
        rows = _parse_csv_output(
            CSVExportService.generate_activity_csv([], {})
        )
        assert len(rows) == 1  # Solo cabecera
        assert rows[0] == ACTIVITY_HEADERS

    def test_sample_data_produces_valid_csv(self):
        """Con datos de ejemplo, se generan filas válidas con 7 columnas cada una."""
        logs = _sample_activity_logs()
        entity_names = _sample_entity_names()
        rows = _parse_csv_output(
            CSVExportService.generate_activity_csv(logs, entity_names)
        )

        # Cabecera + 2 filas de datos
        assert len(rows) == 3
        # Cada fila de datos tiene exactamente 7 columnas
        for row in rows[1:]:
            assert len(row) == 7

    def test_timestamp_is_iso_format(self):
        """El timestamp se serializa como ISO 8601."""
        logs = _sample_activity_logs()
        entity_names = _sample_entity_names()
        rows = _parse_csv_output(
            CSVExportService.generate_activity_csv(logs, entity_names)
        )
        # Primera fila de datos
        timestamp_str = rows[1][0]
        assert "2026-06-15" in timestamp_str

    def test_entity_name_resolved_from_dict(self):
        """El entity_name se resuelve correctamente desde el diccionario."""
        logs = _sample_activity_logs()
        entity_names = _sample_entity_names()
        rows = _parse_csv_output(
            CSVExportService.generate_activity_csv(logs, entity_names)
        )
        # Primer log: entity_id=ws-001 → "w01230p01"
        assert rows[1][3] == "w01230p01"
        # Segundo log: entity_id=usr-002 → "Juan Pérez"
        assert rows[2][3] == "Juan Pérez"

    def test_json_fields_serialized_as_compact_json(self):
        """old_values y new_values se serializan como JSON compacto (sin espacios)."""
        logs = _sample_activity_logs()
        entity_names = _sample_entity_names()
        rows = _parse_csv_output(
            CSVExportService.generate_activity_csv(logs, entity_names)
        )

        # Primer log: old_values=None → vacío, new_values={"hostname":"PC-001","ip":"10.0.1.50"}
        assert rows[1][4] == ""  # old_values vacío
        new_vals_str = rows[1][5]
        parsed = json.loads(new_vals_str)
        assert parsed == {"hostname": "PC-001", "ip": "10.0.1.50"}
        # Verificar que es compacto (sin espacios después de separadores)
        assert " " not in new_vals_str.replace("PC-001", "PC001").replace("10.0.1.50", "x")

    def test_null_old_values_produce_empty_string(self):
        """Cuando old_values es None, el campo CSV debe ser cadena vacía."""
        logs = [_sample_activity_logs()[0]]  # Solo el primer log con old_values=None
        entity_names = _sample_entity_names()
        rows = _parse_csv_output(
            CSVExportService.generate_activity_csv(logs, entity_names)
        )
        assert rows[1][4] == ""

    def test_empty_data_produces_headers_only(self):
        """Con lista vacía de logs, el CSV solo contiene la fila de cabeceras."""
        rows = _parse_csv_output(
            CSVExportService.generate_activity_csv([], {})
        )
        assert len(rows) == 1
        assert rows[0] == ACTIVITY_HEADERS


# === TESTS: generate_workstation_csv() ===

class TestGenerateWorkstationCsv:
    """Verifica la generación de CSV de inventario de workstations."""

    def test_headers_are_correct(self):
        """Las cabeceras del CSV deben coincidir con las 9 columnas definidas."""
        rows = _parse_csv_output(
            CSVExportService.generate_workstation_csv([])
        )
        assert len(rows) == 1
        assert rows[0] == WORKSTATION_HEADERS

    def test_sample_data_produces_valid_csv(self):
        """Con datos de ejemplo, se generan filas válidas con 9 columnas cada una."""
        workstations = _sample_workstations()
        rows = _parse_csv_output(
            CSVExportService.generate_workstation_csv(workstations)
        )

        # Cabecera + 2 filas de datos
        assert len(rows) == 3
        # Cada fila tiene exactamente 9 columnas
        for row in rows[1:]:
            assert len(row) == 9

    def test_is_online_true_converts_to_online(self):
        """Cuando is_online=True, el campo CSV debe mostrar 'Online'."""
        workstations = [_sample_workstations()[0]]  # is_online=True
        rows = _parse_csv_output(
            CSVExportService.generate_workstation_csv(workstations)
        )
        # Columna is_online es la 8va (índice 7)
        assert rows[1][7] == "Online"

    def test_is_online_false_converts_to_offline(self):
        """Cuando is_online=False, el campo CSV debe mostrar 'Offline'."""
        workstations = [_sample_workstations()[1]]  # is_online=False
        rows = _parse_csv_output(
            CSVExportService.generate_workstation_csv(workstations)
        )
        assert rows[1][7] == "Offline"

    def test_last_connection_datetime_is_iso_format(self):
        """El campo last_connection se convierte a formato ISO cuando es datetime."""
        workstations = _sample_workstations()
        rows = _parse_csv_output(
            CSVExportService.generate_workstation_csv(workstations)
        )
        # Primera workstation: last_connection = 2026-06-15T09:45:00+00:00
        assert "2026-06-15" in rows[1][6]

    def test_empty_data_produces_headers_only(self):
        """Con lista vacía de workstations, el CSV solo contiene la fila de cabeceras."""
        rows = _parse_csv_output(
            CSVExportService.generate_workstation_csv([])
        )
        assert len(rows) == 1
        assert rows[0] == WORKSTATION_HEADERS

    def test_organization_name_included(self):
        """El nombre de la organización se incluye correctamente en el CSV."""
        workstations = _sample_workstations()
        rows = _parse_csv_output(
            CSVExportService.generate_workstation_csv(workstations)
        )
        # Columna organization_name es la 4ta (índice 3)
        assert rows[1][3] == "BBVA Oficina 123"
        assert rows[2][3] == "BBVA Oficina 456"

    def test_vlan_name_included(self):
        """El nombre de la VLAN se incluye correctamente en el CSV."""
        workstations = _sample_workstations()
        rows = _parse_csv_output(
            CSVExportService.generate_workstation_csv(workstations)
        )
        # Columna vlan_name es la última (índice 8)
        assert rows[1][8] == "VLAN_IMPRESION"
        assert rows[2][8] == "VLAN_ADMIN"
