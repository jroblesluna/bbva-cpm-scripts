"""
Tests de propiedades (Hypothesis) para la funcionalidad de actividad de usuario.

Feature: user-activity-export

Este archivo contiene property-based tests que verifican propiedades universales
del sistema de actividad de usuario: filtrado, ordenamiento, aislamiento de tenant,
inclusión de tipos de acción y completitud del CSV exportado.
"""

import csv
import io
import uuid
import enum
from datetime import datetime, timedelta
from typing import List, Dict, Any

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.export_csv import CSVExportService


# === ENUMS Y CONSTANTES ===

class ActionType(str, enum.Enum):
    """Réplica del enum ActionType de app.models.audit para tests sin BD."""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    CONFIG_CHANGE = "config_change"
    CONTINGENCY_TOGGLE = "contingency_toggle"
    MESSAGE_SENT = "message_sent"
    COMMAND_SENT = "command_sent"
    CERT_GENERATED = "cert_generated"
    CERT_ROTATED = "cert_rotated"
    ONDEMAND_EXECUTED = "ondemand_executed"
    REMOTE_VIEW_START = "REMOTE_VIEW_START"
    REMOTE_VIEW_STOP = "REMOTE_VIEW_STOP"
    REMOTE_VIEW_MODE_CHANGE = "REMOTE_VIEW_MODE_CHANGE"
    LOGIN = "login"
    LOGIN_FAILED = "login_failed"


ENTITY_TYPES = ["workstation", "user", "organization", "vlan", "action_config", "certificate"]


# === ESTRATEGIAS DE GENERACIÓN ===

# IDs tipo UUID (eficiente)
uuid_strategy = st.uuids().map(str)

# Timestamps realistas dentro de un rango razonable (2024-2026)
timestamp_strategy = st.datetimes(
    min_value=datetime(2024, 1, 1),
    max_value=datetime(2026, 12, 31),
)

# Tipo de acción
action_type_strategy = st.sampled_from(list(ActionType))

# Tipo de entidad
entity_type_strategy = st.sampled_from(ENTITY_TYPES)

# IP address
ip_strategy = st.one_of(
    st.just(None),
    st.tuples(
        st.integers(min_value=1, max_value=255),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=1, max_value=254),
    ).map(lambda t: f"{t[0]}.{t[1]}.{t[2]}.{t[3]}"),
)

# Valores JSON simples para old_values/new_values
json_values_strategy = st.one_of(
    st.just(None),
    st.dictionaries(
        keys=st.sampled_from(["hostname", "status", "email", "role", "name"]),
        values=st.one_of(
            st.text(min_size=1, max_size=15, alphabet=st.characters(categories=("L", "N"))),
            st.booleans(),
            st.integers(min_value=0, max_value=1000),
        ),
        min_size=1,
        max_size=3,
    ),
)


@st.composite
def audit_log_strategy(draw, user_id=None, action_type=None, created_at=None):
    """
    Genera un registro de auditoría simulado (dict).

    Permite fijar user_id, action_type o created_at para tests específicos.
    """
    return {
        "id": draw(uuid_strategy),
        "user_id": user_id or draw(uuid_strategy),
        "workstation_id": draw(st.one_of(st.just(None), uuid_strategy)),
        "organization_id": draw(uuid_strategy),
        "action_type": action_type or draw(action_type_strategy),
        "entity_type": draw(entity_type_strategy),
        "entity_id": draw(uuid_strategy),
        "old_values": draw(json_values_strategy),
        "new_values": draw(json_values_strategy),
        "ip_address": draw(ip_strategy),
        "created_at": created_at or draw(timestamp_strategy),
    }


@st.composite
def audit_log_dataset_strategy(draw, min_users=2, max_users=5, min_logs=5, max_logs=30):
    """
    Genera un dataset de logs de auditoría con múltiples usuarios.

    Garantiza al menos min_users usuarios distintos y min_logs registros.
    """
    # Generar user_ids distintos
    num_users = draw(st.integers(min_value=min_users, max_value=max_users))
    user_ids = [draw(uuid_strategy) for _ in range(num_users)]
    # Asegurar que sean distintos
    user_ids = list(set(user_ids))
    assume(len(user_ids) >= min_users)

    # Generar logs con distribución aleatoria entre usuarios
    num_logs = draw(st.integers(min_value=min_logs, max_value=max_logs))
    logs = []
    for _ in range(num_logs):
        uid = draw(st.sampled_from(user_ids))
        log = draw(audit_log_strategy(user_id=uid))
        logs.append(log)

    return user_ids, logs


# === FUNCIONES DE LÓGICA PURA (simulan el comportamiento del endpoint) ===

def filter_logs_by_user(logs: List[Dict[str, Any]], user_id: str) -> List[Dict[str, Any]]:
    """Filtra logs por user_id y ordena por created_at DESC (lógica del endpoint)."""
    filtered = [log for log in logs if log["user_id"] == user_id]
    filtered.sort(key=lambda x: x["created_at"], reverse=True)
    return filtered


def filter_logs_by_date_range(
    logs: List[Dict[str, Any]],
    start_date: datetime = None,
    end_date: datetime = None,
) -> List[Dict[str, Any]]:
    """Filtra logs por rango de fechas (lógica del endpoint)."""
    result = logs
    if start_date:
        result = [log for log in result if log["created_at"] >= start_date]
    if end_date:
        result = [log for log in result if log["created_at"] <= end_date]
    return result


def check_operator_access(operator_org_id: str, target_user_org_id: str) -> bool:
    """
    Verifica si un operador tiene acceso al usuario objetivo.

    Retorna True si tiene acceso (misma org), False si debe denegar (403).
    """
    return operator_org_id == target_user_org_id


# === PROPERTY TESTS ===


# Feature: user-activity-export, Property 1: User activity filter returns only target user's logs
class TestUserActivityFilter:
    """
    Property 1: User activity filter returns only target user's logs.

    Para cualquier conjunto de logs de auditoría y cualquier user_id válido,
    el endpoint de actividad SHALL retornar solo logs donde log.user_id == user_id,
    y todos los logs retornados SHALL estar ordenados por created_at descendente.

    **Validates: Requirements 1.1**
    """

    @settings(max_examples=100, deadline=None)
    @given(data=audit_log_dataset_strategy())
    def test_filter_returns_only_target_user_logs(self, data):
        """
        Verifica que el filtro por user_id retorna SOLO logs del usuario objetivo
        y que están ordenados por created_at DESC.

        **Validates: Requirements 1.1**
        """
        user_ids, logs = data
        # Seleccionar un usuario objetivo
        target_user_id = user_ids[0]

        # Aplicar la lógica de filtrado (simula el endpoint)
        result = filter_logs_by_user(logs, target_user_id)

        # Propiedad 1a: Todos los logs retornados pertenecen al usuario objetivo
        for log in result:
            assert log["user_id"] == target_user_id, (
                f"Log con user_id='{log['user_id']}' no debería estar en resultados "
                f"filtrados para user_id='{target_user_id}'"
            )

        # Propiedad 1b: No se pierden logs del usuario objetivo
        expected_count = sum(1 for log in logs if log["user_id"] == target_user_id)
        assert len(result) == expected_count, (
            f"Se esperaban {expected_count} logs para user_id='{target_user_id}' "
            f"pero se obtuvieron {len(result)}"
        )

        # Propiedad 1c: Orden descendente por created_at
        for i in range(len(result) - 1):
            assert result[i]["created_at"] >= result[i + 1]["created_at"], (
                f"Los logs no están ordenados por created_at DESC: "
                f"log[{i}].created_at={result[i]['created_at']} < "
                f"log[{i+1}].created_at={result[i+1]['created_at']}"
            )


# Feature: user-activity-export, Property 2: Date range filtering preserves bounds
class TestDateRangeFiltering:
    """
    Property 2: Date range filtering preserves bounds.

    Para cualquier consulta con start_date y/o end_date, todos los logs
    retornados SHALL tener created_at >= start_date (cuando start_date se provee)
    AND created_at <= end_date (cuando end_date se provee).

    **Validates: Requirements 1.2, 1.3**
    """

    @settings(max_examples=100, deadline=None)
    @given(
        logs=st.lists(audit_log_strategy(), min_size=5, max_size=30),
        start_date=timestamp_strategy,
        end_date=timestamp_strategy,
    )
    def test_date_range_bounds_are_preserved(self, logs, start_date, end_date):
        """
        Verifica que el filtro de rango de fechas respeta los límites definidos.

        **Validates: Requirements 1.2, 1.3**
        """
        # Asegurar que start_date <= end_date (condición válida)
        if start_date > end_date:
            start_date, end_date = end_date, start_date

        # Aplicar filtro de fechas
        result = filter_logs_by_date_range(logs, start_date=start_date, end_date=end_date)

        # Propiedad 2a: Todos los logs retornados tienen created_at >= start_date
        for log in result:
            assert log["created_at"] >= start_date, (
                f"Log con created_at={log['created_at']} viola el límite inferior "
                f"start_date={start_date}"
            )

        # Propiedad 2b: Todos los logs retornados tienen created_at <= end_date
        for log in result:
            assert log["created_at"] <= end_date, (
                f"Log con created_at={log['created_at']} viola el límite superior "
                f"end_date={end_date}"
            )

        # Propiedad 2c: No se excluyen logs que están dentro del rango
        expected_count = sum(
            1 for log in logs
            if log["created_at"] >= start_date and log["created_at"] <= end_date
        )
        assert len(result) == expected_count, (
            f"Se esperaban {expected_count} logs dentro del rango "
            f"[{start_date}, {end_date}] pero se obtuvieron {len(result)}"
        )


# Feature: user-activity-export, Property 3: Operator tenant isolation
class TestOperatorTenantIsolation:
    """
    Property 3: Operator tenant isolation.

    Para cualquier Operator y cualquier user_id objetivo donde la organización
    del usuario objetivo difiere de la organización del Operator, los endpoints
    de actividad SHALL retornar HTTP 403 Forbidden.

    **Validates: Requirements 1.4, 3.5, 4.3**
    """

    @settings(max_examples=100, deadline=None)
    @given(
        operator_org_id=uuid_strategy,
        target_org_id=uuid_strategy,
    )
    def test_different_org_denies_access(self, operator_org_id, target_org_id):
        """
        Verifica que un Operator NO tiene acceso a usuarios de otra organización.

        **Validates: Requirements 1.4, 3.5, 4.3**
        """
        # Asegurar que las organizaciones son diferentes
        assume(operator_org_id != target_org_id)

        # La lógica de control de acceso debe denegar
        has_access = check_operator_access(operator_org_id, target_org_id)

        assert has_access is False, (
            f"Operator con org_id='{operator_org_id}' NO debería tener acceso "
            f"a un usuario con org_id='{target_org_id}' (organizaciones diferentes). "
            f"El endpoint debe retornar 403 Forbidden."
        )

    @settings(max_examples=100, deadline=None)
    @given(org_id=uuid_strategy)
    def test_same_org_allows_access(self, org_id):
        """
        Verifica que un Operator SÍ tiene acceso a usuarios de su misma organización.

        **Validates: Requirements 1.4**
        """
        # Misma organización → acceso permitido
        has_access = check_operator_access(org_id, org_id)

        assert has_access is True, (
            f"Operator con org_id='{org_id}' debería tener acceso "
            f"a un usuario de la misma organización."
        )


# Feature: user-activity-export, Property 5: All action types are included without filtering
class TestActionTypeInclusion:
    """
    Property 5: All action types are included without filtering.

    Para cualquier usuario que tiene logs con todos los valores posibles de
    ActionType, el endpoint de actividad SHALL retornar logs de todos los
    action_types sin filtrar ninguno.

    **Validates: Requirements 1.6**
    """

    @settings(max_examples=100, deadline=None)
    @given(
        user_id=uuid_strategy,
        extra_logs=st.lists(audit_log_strategy(), min_size=0, max_size=10),
    )
    def test_all_action_types_preserved_after_filter(self, user_id, extra_logs):
        """
        Verifica que ningún tipo de acción es filtrado al consultar la actividad
        de un usuario.

        **Validates: Requirements 1.6**
        """
        # Crear un log por cada ActionType para el usuario objetivo
        logs = []
        for action_type in ActionType:
            log = {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "workstation_id": None,
                "organization_id": str(uuid.uuid4()),
                "action_type": action_type,
                "entity_type": "workstation",
                "entity_id": str(uuid.uuid4()),
                "old_values": None,
                "new_values": {"test": True},
                "ip_address": "192.168.1.1",
                "created_at": datetime(2025, 6, 15, 10, 0, 0) + timedelta(minutes=len(logs)),
            }
            logs.append(log)

        # Agregar logs de otros usuarios para añadir ruido
        for extra_log in extra_logs:
            extra_log["user_id"] = str(uuid.uuid4())  # Asegurar otro usuario
            logs.append(extra_log)

        # Aplicar filtro por usuario (simula el endpoint)
        result = filter_logs_by_user(logs, user_id)

        # Propiedad 5: Todos los ActionType del usuario están presentes
        result_action_types = {log["action_type"] for log in result}
        all_action_types = set(ActionType)

        assert result_action_types == all_action_types, (
            f"Se esperaban todos los ActionTypes ({len(all_action_types)}) pero solo se "
            f"obtuvieron {len(result_action_types)}. "
            f"Faltantes: {all_action_types - result_action_types}"
        )


# Feature: user-activity-export, Property 7: Activity CSV column completeness
class TestActivityCSVColumnCompleteness:
    """
    Property 7: Activity CSV column completeness.

    Para cualquier archivo CSV de actividad exportado, cada fila SHALL contener
    exactamente las columnas: timestamp, action_type, entity_type, entity_name,
    old_values, new_values, ip_address.

    **Validates: Requirements 3.2**
    """

    EXPECTED_HEADERS = [
        "timestamp",
        "action_type",
        "entity_type",
        "entity_name",
        "old_values",
        "new_values",
        "ip_address",
    ]

    @settings(max_examples=100, deadline=None)
    @given(logs=st.lists(audit_log_strategy(), min_size=1, max_size=20))
    def test_csv_has_correct_headers_and_column_count(self, logs):
        """
        Verifica que el CSV generado tiene las cabeceras correctas y cada fila
        tiene exactamente 7 columnas.

        **Validates: Requirements 3.2**
        """
        # Construir entity_names a partir de los logs
        entity_names = {
            log["entity_id"]: f"entity_{log['entity_type']}_{i}"
            for i, log in enumerate(logs)
        }

        # Generar CSV usando el servicio real
        csv_rows = list(CSVExportService.generate_activity_csv(logs, entity_names))

        # Debe tener al menos header + 1 fila de datos
        assert len(csv_rows) >= 2, (
            f"Se esperaban al menos 2 filas CSV (header + datos) pero se obtuvieron {len(csv_rows)}"
        )

        # Parsear el CSV completo
        csv_content = "".join(csv_rows)
        reader = csv.reader(io.StringIO(csv_content))
        rows = list(reader)

        # Propiedad 7a: Las cabeceras son las correctas
        headers = rows[0]
        assert headers == self.EXPECTED_HEADERS, (
            f"Cabeceras CSV incorrectas.\n"
            f"Esperado: {self.EXPECTED_HEADERS}\n"
            f"Obtenido: {headers}"
        )

        # Propiedad 7b: Cada fila de datos tiene exactamente 7 columnas
        data_rows = rows[1:]
        assert len(data_rows) == len(logs), (
            f"Se esperaban {len(logs)} filas de datos pero se obtuvieron {len(data_rows)}"
        )

        for i, row in enumerate(data_rows):
            assert len(row) == 7, (
                f"Fila {i+1} tiene {len(row)} columnas en vez de 7. "
                f"Contenido: {row}"
            )
