# Feature: stable-multi-worker-redis, Property 3: Session lifecycle — no DB held during WebSocket await
"""
Property test: Session lifecycle — no DB held during WebSocket await

Para cualquier secuencia de N mensajes procesados en el loop del endpoint workstation,
inmediatamente antes de cada llamada a `await websocket.receive_json()` e inmediatamente
después de procesar cada mensaje (antes de la siguiente iteración del loop), la variable
de sesión de BD DEBE ser None (cerrada).

Este test verifica via análisis AST e inspección de código fuente que el endpoint
workstation.py sigue las reglas de lifecycle de sesión:
1. Después del bloque de setup, `db` se cierra y se asigna a None
2. El loop principal comienza con `await websocket.receive_json()` sin retener sesión
3. Tras procesar cada mensaje, `db.close()` y `db = None` se ejecutan

Feature: stable-multi-worker-redis, Property 3: Session lifecycle — no DB held during WebSocket await
**Validates: Requirements 4.1, 4.2, 4.3**
"""

import ast
import re
from pathlib import Path
from typing import List, Tuple

from hypothesis import given, settings
from hypothesis import strategies as st


# === CONFIGURACIÓN ===

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
_WORKSTATION_FILE = _BACKEND_ROOT / "app" / "api" / "v1" / "websocket" / "workstation.py"

# Tipos de mensaje que el endpoint procesa en el loop
MSG_TYPES = [
    "register",
    "heartbeat",
    "pong",
    "status_update",
    "command_response",
    "log_chunk",
]


# === FUNCIONES DE INSPECCIÓN AST ===


def _get_workstation_source() -> str:
    """Lee el código fuente del endpoint workstation."""
    return _WORKSTATION_FILE.read_text(encoding="utf-8")


def _find_main_loop_body(source: str) -> ast.While:
    """
    Encuentra el nodo AST del loop `while True` principal del endpoint.
    Retorna el nodo While o None si no se encuentra.
    """
    tree = ast.parse(source)

    # Buscar dentro de la función workstation_websocket
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "workstation_websocket":
            # Buscar el while True dentro de la función
            for child in ast.walk(node):
                if isinstance(child, ast.While):
                    # Verificar que es `while True`
                    if isinstance(child.test, ast.Constant) and child.test.value is True:
                        return child
                    elif isinstance(child.test, ast.NameConstant) and child.test.value is True:
                        return child
    return None


def _find_db_close_and_none_before_loop(source: str) -> bool:
    """
    Verifica que antes del loop principal (while True), existe un patrón
    `db.close()` seguido de `db = None` para liberar la sesión del setup.

    Valida: Requirement 4.1 — cerrar sesión después del setup inicial.
    """
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "workstation_websocket":
            # Buscar el bloque try que contiene el setup y el loop
            for child in ast.walk(node):
                if isinstance(child, ast.Try):
                    body = child.body
                    # Buscar secuencia: db.close() → db = None → while True
                    for i in range(len(body) - 2):
                        # Verificar db.close()
                        is_db_close = _is_db_close_stmt(body[i])
                        # Verificar db = None
                        is_db_none = _is_db_assign_none(body[i + 1])
                        # Verificar while True
                        is_while_true = (
                            isinstance(body[i + 2], ast.While)
                            and _is_true_constant(body[i + 2].test)
                        )

                        if is_db_close and is_db_none and is_while_true:
                            return True
    return False


def _find_db_close_at_end_of_loop(source: str) -> bool:
    """
    Verifica que al final del cuerpo del while True, las últimas sentencias
    son `db.close()` y `db = None`.

    Valida: Requirement 4.3 — cerrar sesión antes del siguiente await.
    """
    loop = _find_main_loop_body(source)
    if loop is None:
        return False

    body = loop.body
    if len(body) < 2:
        return False

    # Las últimas dos sentencias deben ser db.close() y db = None
    last = body[-1]
    second_last = body[-2]

    # Podría ser un comentario como expresión (ast.Expr con ast.Constant str)
    # Verificar las últimas sentencias significativas
    return _is_db_close_stmt(second_last) and _is_db_assign_none(last)


def _find_receive_json_as_first_await_in_loop(source: str) -> bool:
    """
    Verifica que la primera sentencia del while True es
    `data = await websocket.receive_json()`.

    Esto garantiza que no hay sesión de BD abierta cuando se espera un mensaje.
    Valida: Requirement 4.2 — no retener sesión durante awaits.
    """
    loop = _find_main_loop_body(source)
    if loop is None:
        return False

    body = loop.body
    if not body:
        return False

    first_stmt = body[0]

    # Debe ser: data = await websocket.receive_json()
    if isinstance(first_stmt, ast.Assign):
        value = first_stmt.value
        if isinstance(value, ast.Await):
            call = value.value
            if isinstance(call, ast.Call):
                func = call.func
                if isinstance(func, ast.Attribute) and func.attr == "receive_json":
                    return True
    return False


def _find_session_creation_guard_in_loop(source: str) -> bool:
    """
    Verifica que dentro del loop, existe el patrón:
    `if db is None: db = SessionLocal()`

    Esto garantiza que la sesión se crea on-demand solo cuando llega un mensaje.
    Valida: Requirement 4.3 — crear sesión nueva para procesar cada mensaje.
    """
    loop = _find_main_loop_body(source)
    if loop is None:
        return False

    for stmt in loop.body:
        if isinstance(stmt, ast.If):
            # Verificar condición: db is None
            test = stmt.test
            if isinstance(test, ast.Compare):
                if (
                    isinstance(test.left, ast.Name)
                    and test.left.id == "db"
                    and len(test.ops) == 1
                    and isinstance(test.ops[0], ast.Is)
                    and len(test.comparators) == 1
                    and _is_none_constant(test.comparators[0])
                ):
                    # Verificar cuerpo: db = SessionLocal()
                    for if_stmt in stmt.body:
                        if isinstance(if_stmt, ast.Assign):
                            for target in if_stmt.targets:
                                if isinstance(target, ast.Name) and target.id == "db":
                                    return True
    return False


# === HELPERS AST ===


def _is_db_close_stmt(node: ast.stmt) -> bool:
    """Verifica si un nodo AST es `db.close()`."""
    if isinstance(node, ast.Expr):
        call = node.value
        if isinstance(call, ast.Call):
            func = call.func
            if isinstance(func, ast.Attribute):
                if (
                    isinstance(func.value, ast.Name)
                    and func.value.id == "db"
                    and func.attr == "close"
                ):
                    return True
    return False


def _is_db_assign_none(node: ast.stmt) -> bool:
    """Verifica si un nodo AST es `db = None`."""
    if isinstance(node, ast.Assign):
        if len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "db":
                return _is_none_constant(node.value)
    return False


def _is_none_constant(node: ast.expr) -> bool:
    """Verifica si un nodo AST es la constante None."""
    # Python 3.8+: ast.Constant con value=None
    if isinstance(node, ast.Constant) and node.value is None:
        return True
    # Python 3.7: ast.NameConstant
    if hasattr(ast, "NameConstant") and isinstance(node, ast.NameConstant) and node.value is None:
        return True
    return False


def _is_true_constant(node: ast.expr) -> bool:
    """Verifica si un nodo AST es la constante True."""
    if isinstance(node, ast.Constant) and node.value is True:
        return True
    if hasattr(ast, "NameConstant") and isinstance(node, ast.NameConstant) and node.value is True:
        return True
    return False


# === PROPERTY TESTS ===


@settings(max_examples=100)
@given(msg_sequence=st.lists(st.sampled_from(MSG_TYPES), min_size=1, max_size=20))
def test_property_session_closed_before_each_receive(msg_sequence: List[str]):
    """
    Propiedad: Para cualquier secuencia de mensajes procesada en el loop,
    la sesión de BD se cierra (db = None) al final de cada iteración,
    garantizando que no hay conexión de pool retenida durante receive_json().

    Verificamos vía análisis AST que el patrón de código cumple:
    - Al final del loop: db.close() seguido de db = None
    - El receive_json() es la primera operación del loop (db es None en ese punto)
    - La sesión se crea on-demand con `if db is None: db = SessionLocal()`

    La secuencia de mensajes generada por Hypothesis representa cualquier
    combinación de tipos de mensaje que un cliente podría enviar. Para cada
    combinación, el invariante de lifecycle debe mantenerse.

    Feature: stable-multi-worker-redis, Property 3: Session lifecycle
    **Validates: Requirements 4.1, 4.2, 4.3**
    """
    source = _get_workstation_source()

    # Verificación 1: db.close() + db = None al final del loop (antes del siguiente receive_json)
    assert _find_db_close_at_end_of_loop(source), (
        f"VIOLACIÓN DE LIFECYCLE: El loop while True en workstation.py NO termina con "
        f"'db.close()' seguido de 'db = None'. Esto significa que la sesión de BD se "
        f"retiene durante el siguiente await websocket.receive_json(), causando "
        f"retención de conexiones del pool. "
        f"Secuencia de mensajes que expone el problema: {msg_sequence}"
    )

    # Verificación 2: receive_json() es la primera operación en el loop
    assert _find_receive_json_as_first_await_in_loop(source), (
        f"VIOLACIÓN DE LIFECYCLE: La primera sentencia del loop while True NO es "
        f"'data = await websocket.receive_json()'. El loop debería iniciar con el "
        f"await de recepción para garantizar que db=None en ese punto. "
        f"Secuencia de mensajes: {msg_sequence}"
    )

    # Verificación 3: Existe el guard `if db is None: db = SessionLocal()`
    assert _find_session_creation_guard_in_loop(source), (
        f"VIOLACIÓN DE LIFECYCLE: No se encontró el patrón "
        f"'if db is None: db = SessionLocal()' dentro del loop. "
        f"Cada mensaje debe crear una sesión on-demand y liberarla después. "
        f"Secuencia de mensajes: {msg_sequence}"
    )


@settings(max_examples=100)
@given(msg_sequence=st.lists(st.sampled_from(MSG_TYPES), min_size=0, max_size=15))
def test_property_session_released_after_setup(msg_sequence: List[str]):
    """
    Propiedad: Independientemente de la secuencia de mensajes que se procese
    después, la sesión del bloque de setup se libera (db.close() + db = None)
    ANTES de entrar al loop while True.

    Esto garantiza que el registro, config, contingencia y mensajes pendientes
    no retienen una conexión del pool durante toda la vida del WebSocket.

    Feature: stable-multi-worker-redis, Property 3: Session lifecycle
    **Validates: Requirements 4.1, 4.2, 4.3**
    """
    source = _get_workstation_source()

    # Verificar que existe db.close() + db = None justo antes del while True
    assert _find_db_close_and_none_before_loop(source), (
        f"VIOLACIÓN DE LIFECYCLE: No se encontró 'db.close()' seguido de 'db = None' "
        f"inmediatamente antes del 'while True' en workstation.py. "
        f"La sesión de setup DEBE liberarse antes de entrar al loop de recepción. "
        f"Sin esto, la sesión se retiene durante toda la vida del WebSocket "
        f"(potencialmente horas), agotando el pool de conexiones PostgreSQL. "
        f"Secuencia de mensajes post-setup: {msg_sequence}"
    )
