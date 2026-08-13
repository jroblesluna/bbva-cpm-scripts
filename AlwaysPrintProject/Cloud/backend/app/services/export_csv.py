"""
Servicio de generación de archivos CSV para exportación.

Este servicio implementa la lógica de negocio para:
- Generación de CSV de actividad de usuario (timeline)
- Generación de CSV de inventario de workstations
- Codificación UTF-8 con BOM para compatibilidad con Excel
"""

import csv
import io
import json
from typing import Generator, List, Dict, Any, Optional


class CSVExportService:
    """
    Servicio compartido para generación de archivos CSV.

    Provee métodos estáticos para generar filas CSV correctamente
    escapadas usando el módulo csv de Python con io.StringIO.
    """

    @staticmethod
    def utf8_bom() -> bytes:
        """Retorna los bytes BOM de UTF-8 para compatibilidad con Excel."""
        return b'\xef\xbb\xbf'

    @staticmethod
    def generate_activity_csv(
        logs: List[Dict[str, Any]],
        entity_names: Dict[str, str]
    ) -> Generator[str, None, None]:
        """
        Genera filas CSV para exportación de actividad de usuario.

        Columnas: timestamp, action_type, entity_type, entity_name,
                  old_values, new_values, ip_address

        Args:
            logs: Lista de registros de auditoría (dicts o modelos con atributos).
            entity_names: Diccionario mapeando entity_id → nombre legible.

        Yields:
            Filas CSV como strings (incluyendo header y datos).
        """
        # Cabecera
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "timestamp",
            "action_type",
            "entity_type",
            "entity_name",
            "old_values",
            "new_values",
            "ip_address",
        ])
        yield output.getvalue()

        # Filas de datos
        for log in logs:
            output = io.StringIO()
            writer = csv.writer(output)

            # Extraer campos del log (soporta dict y objetos con atributos)
            if isinstance(log, dict):
                timestamp = log.get("created_at", "")
                action_type = log.get("action_type", "")
                entity_type = log.get("entity_type", "")
                entity_id = str(log.get("entity_id", ""))
                old_values = log.get("old_values")
                new_values = log.get("new_values")
                ip_address = log.get("ip_address", "")
            else:
                timestamp = getattr(log, "created_at", "")
                action_type = getattr(log, "action_type", "")
                entity_type = getattr(log, "entity_type", "")
                entity_id = str(getattr(log, "entity_id", ""))
                old_values = getattr(log, "old_values", None)
                new_values = getattr(log, "new_values", None)
                ip_address = getattr(log, "ip_address", "")

            # Convertir timestamp a string ISO si es datetime
            if hasattr(timestamp, "isoformat"):
                timestamp = timestamp.isoformat()

            # Convertir action_type enum a su valor string
            if hasattr(action_type, "value"):
                action_type = action_type.value

            # Resolver nombre de entidad
            entity_name = entity_names.get(entity_id, "")

            # Serializar campos JSON como strings compactos
            old_values_str = json.dumps(old_values, ensure_ascii=False, separators=(",", ":")) if old_values else ""
            new_values_str = json.dumps(new_values, ensure_ascii=False, separators=(",", ":")) if new_values else ""

            writer.writerow([
                timestamp,
                action_type,
                entity_type,
                entity_name,
                old_values_str,
                new_values_str,
                ip_address or "",
            ])
            yield output.getvalue()

    @staticmethod
    def generate_workstation_csv(
        workstations: List[Any]
    ) -> Generator[str, None, None]:
        """
        Genera filas CSV para exportación de inventario de workstations.

        Columnas: id, hostname, ip_private, cidr, vlan_name,
                  organization_name, tray_version, action_config_name,
                  current_user, last_connection, is_online, created_at,
                  updated_at

        Args:
            workstations: Lista de workstations (dicts o objetos con atributos).
                          Se espera que incluyan organization_name y vlan_name
                          (resueltos previamente via JOINs).

        Yields:
            Filas CSV como strings (incluyendo header y datos).
        """
        # Cabecera
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id",
            "hostname",
            "ip_private",
            "cidr",
            "vlan_name",
            "organization_name",
            "tray_version",
            "action_config_name",
            "current_user",
            "last_connection",
            "is_online",
            "created_at",
            "updated_at",
        ])
        yield output.getvalue()

        # Filas de datos
        for ws in workstations:
            output = io.StringIO()
            writer = csv.writer(output)

            # Extraer campos (soporta dict y objetos con atributos)
            if isinstance(ws, dict):
                ws_id = ws.get("id", "")
                hostname = ws.get("hostname", "")
                ip_private = ws.get("ip_private", "")
                cidr = ws.get("cidr", "")
                vlan_name = ws.get("vlan_name", "")
                organization_name = ws.get("organization_name", "")
                tray_version = ws.get("tray_version", "")
                action_config_name = ws.get("action_config_name", "")
                current_user = ws.get("current_user", "")
                last_connection = ws.get("last_connection", "")
                is_online = ws.get("is_online", False)
                created_at = ws.get("created_at", "")
                updated_at = ws.get("updated_at", "")
            else:
                ws_id = str(getattr(ws, "id", "")) or ""
                hostname = getattr(ws, "hostname", "") or ""
                ip_private = getattr(ws, "ip_private", "") or ""
                cidr = getattr(ws, "cidr", "") or ""
                vlan_name = getattr(ws, "vlan_name", "") or ""
                organization_name = getattr(ws, "organization_name", "") or ""
                tray_version = getattr(ws, "tray_version", "") or ""
                action_config_name = getattr(ws, "action_config_name", "") or ""
                current_user = getattr(ws, "current_user", "") or ""
                last_connection = getattr(ws, "last_connection", "")
                is_online = getattr(ws, "is_online", False)
                created_at = getattr(ws, "created_at", "")
                updated_at = getattr(ws, "updated_at", "")

            # Convertir last_connection a string ISO si es datetime
            if hasattr(last_connection, "isoformat"):
                last_connection = last_connection.isoformat()
            elif last_connection is None:
                last_connection = ""

            # Convertir created_at a string ISO si es datetime
            if hasattr(created_at, "isoformat"):
                created_at = created_at.isoformat()
            elif created_at is None:
                created_at = ""

            # Convertir updated_at a string ISO si es datetime
            if hasattr(updated_at, "isoformat"):
                updated_at = updated_at.isoformat()
            elif updated_at is None:
                updated_at = ""

            # Convertir booleano is_online a texto legible
            is_online_text = "Online" if is_online else "Offline"

            writer.writerow([
                ws_id or "",
                hostname or "",
                ip_private or "",
                cidr or "",
                vlan_name or "",
                organization_name or "",
                tray_version or "",
                action_config_name or "",
                current_user or "",
                last_connection or "",
                is_online_text,
                created_at or "",
                updated_at or "",
            ])
            yield output.getvalue()
