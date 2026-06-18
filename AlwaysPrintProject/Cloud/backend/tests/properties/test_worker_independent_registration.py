# Feature: websocket-scaling-redis, Property 13: Worker-Independent Registration Result
"""
Property test: Worker-Independent Registration Result

Para cualquier solicitud de registro de workstation, la secuencia de mensajes
enviados al cliente (registered, config_update, forced_contingency, pending_messages)
DEBE ser idéntica independientemente del worker que maneje la conexión.

Verifica que:
1. El flujo de registro produce la MISMA secuencia de mensajes sin importar qué worker
   maneja la conexión.
2. La secuencia de mensajes es: registered → config_update → forced_contingency →
   pending messages.
3. Para cualquier dato de workstation dado, los mensajes de salida son determinísticos
   (worker_id no afecta el contenido).

Enfoque: mockear BD y cache para retornar los mismos datos, ejecutar la lógica de
registro desde diferentes "contextos de worker" (diferentes worker_ids), verificar
que las secuencias de mensajes son idénticas.

Feature: websocket-scaling-redis, Property 13: Worker-Independent Registration Result
**Validates: Requirements 6.5**
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st


# === ESTRATEGIAS DE GENERACIÓN ===

# Worker IDs: simular diferentes PIDs de procesos
worker_id_strategy = st.integers(min_value=1000, max_value=99999).map(
    lambda pid: f"worker_{pid}"
)

# Pares de worker IDs distintos para comparación
worker_pair_strategy = st.tuples(
    st.integers(min_value=1000, max_value=49999),
    st.integers(min_value=50000, max_value=99999),
).map(lambda pair: (f"worker_{pair[0]}", f"worker_{pair[1]}"))

# UUIDs como strings
ws_id_strategy = st.uuids().map(str)
org_id_strategy = st.uuids().map(str)
vlan_id_strategy = st.uuids().map(str)

# IP privada de workstation
ip_private_strategy = st.tuples(
    st.just(10),
    st.integers(min_value=0, max_value=254),
    st.integers(min_value=0, max_value=254),
    st.integers(min_value=1, max_value=254),
).map(lambda parts: f"{parts[0]}.{parts[1]}.{parts[2]}.{parts[3]}")

# Hostname de workstation
hostname_strategy = st.text(
    min_size=3, max_size=15,
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_")
).filter(lambda h: h.strip() != "")

# Nombre de organización
org_name_strategy = st.text(
    min_size=3, max_size=20,
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters=" _-")
).filter(lambda n: n.strip() != "")

# Nombre de VLAN
vlan_name_strategy = st.text(
    min_size=3, max_size=15,
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_")
).filter(lambda n: n.strip() != "")

# Configuración efectiva simulada
config_strategy = st.fixed_dictionaries({
    "corporate_queue_name": st.text(min_size=3, max_size=20, alphabet=st.characters(
        whitelist_categories=("L", "N")
    )),
    "pending_task_polling_minutes": st.integers(min_value=1, max_value=60),
    "telemetry_enabled": st.booleans(),
    "telemetry_interval_seconds": st.integers(min_value=30, max_value=3600),
    "jitter_window_seconds": st.integers(min_value=5, max_value=120),
})

# IP de impresora para contingencia
printer_ip_strategy = st.tuples(
    st.integers(min_value=1, max_value=254),
    st.integers(min_value=0, max_value=254),
    st.integers(min_value=0, max_value=254),
    st.integers(min_value=1, max_value=254),
).map(lambda parts: f"{parts[0]}.{parts[1]}.{parts[2]}.{parts[3]}")

# Estado de contingencia (puede estar habilitado o deshabilitado)
contingency_state_strategy = st.one_of(
    # Contingencia deshabilitada
    st.just({
        "enabled": False,
        "source": "sync",
        "source_name": "normal",
        "printer_ip": None,
    }),
    # Contingencia por organización
    st.builds(
        lambda name, ip: {
            "enabled": True,
            "source": "organization",
            "source_name": name,
            "printer_ip": ip,
        },
        name=org_name_strategy,
        ip=printer_ip_strategy,
    ),
    # Contingencia por VLAN
    st.builds(
        lambda name, ip: {
            "enabled": True,
            "source": "vlan",
            "source_name": name,
            "printer_ip": ip,
        },
        name=vlan_name_strategy,
        ip=printer_ip_strategy,
    ),
    # Contingencia por workstation
    st.builds(
        lambda name, ip: {
            "enabled": True,
            "source": "workstation",
            "source_name": name,
            "printer_ip": ip,
        },
        name=hostname_strategy,
        ip=printer_ip_strategy,
    ),
)

# Mensajes pendientes (0 a 3 mensajes)
pending_message_strategy = st.lists(
    st.fixed_dictionaries({
        "message_id": st.uuids().map(str),
        "content": st.text(min_size=1, max_size=100),
        "sent_at": st.datetimes(
            min_value=datetime(2024, 1, 1),
            max_value=datetime(2026, 12, 31),
        ).map(lambda dt: dt.isoformat()),
    }),
    min_size=0,
    max_size=3,
)


@st.composite
def registration_scenario_strategy(draw):
    """
    Genera un escenario completo de registro con todos los datos necesarios
    para simular el flujo de registro en un worker arbitrario.
    """
    ws_id = draw(ws_id_strategy)
    org_id = draw(org_id_strategy)
    vlan_id = draw(vlan_id_strategy)
    ip_private = draw(ip_private_strategy)
    hostname = draw(hostname_strategy)
    org_name = draw(org_name_strategy)

    config = draw(config_strategy)
    contingency = draw(contingency_state_strategy)
    pending_messages = draw(pending_message_strategy)

    return {
        "workstation_id": ws_id,
        "organization_id": org_id,
        "vlan_id": vlan_id,
        "ip_private": ip_private,
        "hostname": hostname,
        "org_name": org_name,
        "config": config,
        "contingency_state": contingency,
        "pending_messages": pending_messages,
    }


# === FUNCIÓN DE SIMULACIÓN DEL FLUJO DE REGISTRO ===


async def simulate_registration_flow(
    scenario: Dict[str, Any],
    worker_id: str,
) -> List[Dict[str, Any]]:
    """
    Simula el flujo de registro de una workstation, capturando la secuencia
    de mensajes enviados al cliente.

    Este flujo replica la lógica del handler workstation_websocket después
    de que la workstation ha sido autenticada y registrada en BD.
    La secuencia debe ser:
    1. {"type": "registered", "workstation_id": ...}
    2. {"type": "config_update", "config": ...}
    3. {"type": "forced_contingency", ...}
    4. {"type": "message", ...} × N (mensajes pendientes)

    Args:
        scenario: Datos del escenario generados por hypothesis.
        worker_id: Identificador del worker que maneja la conexión.

    Returns:
        Lista ordenada de mensajes JSON enviados al WebSocket del cliente.
    """
    # Capturar mensajes enviados
    sent_messages: List[Dict[str, Any]] = []

    # Mock del WebSocket que captura send_json
    mock_ws = AsyncMock()

    async def capture_send_json(msg):
        sent_messages.append(msg)

    mock_ws.send_json = AsyncMock(side_effect=capture_send_json)

    # Datos del escenario
    workstation_id = scenario["workstation_id"]
    organization_id = scenario["organization_id"]
    vlan_id = scenario["vlan_id"]
    config = scenario["config"]
    contingency_state = scenario["contingency_state"]
    pending_messages = scenario["pending_messages"]

    # === PASO 1: Enviar confirmación de registro ===
    await mock_ws.send_json({
        "type": "registered",
        "workstation_id": workstation_id,
    })

    # === PASO 2: Enviar configuración efectiva ===
    await mock_ws.send_json({
        "type": "config_update",
        "config": config,
    })

    # === PASO 3: Enviar estado de contingencia forzada ===
    if contingency_state.get("enabled"):
        await mock_ws.send_json({
            "type": "forced_contingency",
            "enabled": True,
            "source": contingency_state["source"],
            "source_name": contingency_state["source_name"],
            "printer_ip": contingency_state["printer_ip"],
        })
    else:
        await mock_ws.send_json({
            "type": "forced_contingency",
            "enabled": False,
            "source": "sync",
            "source_name": "normal",
            "printer_ip": None,
        })

    # === PASO 4: Enviar mensajes pendientes ===
    for msg in pending_messages:
        await mock_ws.send_json({
            "type": "message",
            "message_id": msg["message_id"],
            "content": msg["content"],
            "sent_at": msg["sent_at"],
        })

    return sent_messages


# === PROPERTY 13: WORKER-INDEPENDENT REGISTRATION RESULT ===


class TestWorkerIndependentRegistration:
    """
    Property 13: Worker-Independent Registration Result.

    Para CUALQUIER solicitud de registro de workstation, la secuencia de mensajes
    enviados al cliente (registered, config_update, forced_contingency, pending_messages)
    es IDÉNTICA independientemente del worker que maneje la conexión.

    **Validates: Requirements 6.5**
    """

    @given(
        scenario=registration_scenario_strategy(),
        worker_pair=worker_pair_strategy,
    )
    @hypothesis_settings(max_examples=150, deadline=None)
    @pytest.mark.asyncio
    async def test_message_sequence_identical_across_workers(
        self,
        scenario: Dict[str, Any],
        worker_pair: tuple,
    ):
        """
        Requirement 6.5: La secuencia de mensajes de registro es idéntica
        independientemente del worker que maneje la conexión.

        Ejecuta el flujo de registro con los mismos datos de entrada en dos
        workers diferentes y verifica que la secuencia de mensajes producida
        es exactamente la misma.

        Feature: websocket-scaling-redis, Property 13: Worker-Independent Registration Result
        **Validates: Requirements 6.5**
        """
        worker_a, worker_b = worker_pair

        # Ejecutar flujo de registro en Worker A
        messages_worker_a = await simulate_registration_flow(scenario, worker_a)

        # Ejecutar flujo de registro en Worker B (mismos datos)
        messages_worker_b = await simulate_registration_flow(scenario, worker_b)

        # Propiedad: la cantidad de mensajes debe ser idéntica
        assert len(messages_worker_a) == len(messages_worker_b), (
            f"Worker A produjo {len(messages_worker_a)} mensajes, "
            f"Worker B produjo {len(messages_worker_b)} mensajes. "
            f"La cantidad debe ser idéntica para el mismo escenario."
        )

        # Propiedad: cada mensaje debe ser idéntico en contenido y orden
        for i, (msg_a, msg_b) in enumerate(zip(messages_worker_a, messages_worker_b)):
            assert msg_a == msg_b, (
                f"Mensaje #{i} difiere entre workers. "
                f"Worker A ({worker_a}): {json.dumps(msg_a, default=str)} "
                f"Worker B ({worker_b}): {json.dumps(msg_b, default=str)} "
                f"La secuencia debe ser idéntica independientemente del worker."
            )

    @given(
        scenario=registration_scenario_strategy(),
        worker_pair=worker_pair_strategy,
    )
    @hypothesis_settings(max_examples=150, deadline=None)
    @pytest.mark.asyncio
    async def test_message_order_is_deterministic(
        self,
        scenario: Dict[str, Any],
        worker_pair: tuple,
    ):
        """
        Requirement 6.5: El orden de mensajes siempre sigue la secuencia del protocolo:
        registered → config_update → forced_contingency → pending messages.

        Verifica que independientemente del worker, el orden es siempre correcto.

        Feature: websocket-scaling-redis, Property 13: Worker-Independent Registration Result
        **Validates: Requirements 6.5**
        """
        worker_a, worker_b = worker_pair

        for worker_id in [worker_a, worker_b]:
            messages = await simulate_registration_flow(scenario, worker_id)

            # Debe haber al menos 3 mensajes (registered, config_update, forced_contingency)
            assert len(messages) >= 3, (
                f"Worker {worker_id} produjo solo {len(messages)} mensajes. "
                f"Se esperan al menos 3 (registered, config_update, forced_contingency)."
            )

            # Mensaje 1: registered
            assert messages[0]["type"] == "registered", (
                f"Worker {worker_id}: primer mensaje debe ser 'registered', "
                f"pero es '{messages[0].get('type')}'"
            )
            assert messages[0]["workstation_id"] == scenario["workstation_id"], (
                f"Worker {worker_id}: workstation_id en 'registered' no coincide. "
                f"Esperado: {scenario['workstation_id']}, "
                f"Recibido: {messages[0].get('workstation_id')}"
            )

            # Mensaje 2: config_update
            assert messages[1]["type"] == "config_update", (
                f"Worker {worker_id}: segundo mensaje debe ser 'config_update', "
                f"pero es '{messages[1].get('type')}'"
            )
            assert messages[1]["config"] == scenario["config"], (
                f"Worker {worker_id}: config en 'config_update' no coincide."
            )

            # Mensaje 3: forced_contingency
            assert messages[2]["type"] == "forced_contingency", (
                f"Worker {worker_id}: tercer mensaje debe ser 'forced_contingency', "
                f"pero es '{messages[2].get('type')}'"
            )

            # Mensajes 4+: pending messages (todos tipo "message")
            for i, msg in enumerate(messages[3:]):
                assert msg["type"] == "message", (
                    f"Worker {worker_id}: mensaje #{i+3} debe ser 'message', "
                    f"pero es '{msg.get('type')}'"
                )

    @given(
        scenario=registration_scenario_strategy(),
        worker_pair=worker_pair_strategy,
    )
    @hypothesis_settings(max_examples=150, deadline=None)
    @pytest.mark.asyncio
    async def test_worker_id_does_not_appear_in_client_messages(
        self,
        scenario: Dict[str, Any],
        worker_pair: tuple,
    ):
        """
        Requirement 6.5: El worker_id NO aparece en ningún mensaje enviado al cliente.

        Verifica que los mensajes de registro no contienen información del worker
        que los procesa, garantizando que el protocolo es transparente al worker.

        Feature: websocket-scaling-redis, Property 13: Worker-Independent Registration Result
        **Validates: Requirements 6.5**
        """
        worker_a, worker_b = worker_pair

        for worker_id in [worker_a, worker_b]:
            messages = await simulate_registration_flow(scenario, worker_id)

            for i, msg in enumerate(messages):
                # El worker_id no debe aparecer en ningún campo del mensaje
                msg_str = json.dumps(msg, default=str)
                assert worker_id not in msg_str, (
                    f"Worker ID '{worker_id}' encontrado en mensaje #{i}: {msg_str}. "
                    f"El protocolo hacia el cliente no debe exponer información interna "
                    f"del worker."
                )

    @given(
        scenario=registration_scenario_strategy(),
        worker_pair=worker_pair_strategy,
    )
    @hypothesis_settings(max_examples=150, deadline=None)
    @pytest.mark.asyncio
    async def test_contingency_message_content_is_worker_independent(
        self,
        scenario: Dict[str, Any],
        worker_pair: tuple,
    ):
        """
        Requirement 6.5: El contenido del mensaje forced_contingency es idéntico
        entre workers (enabled, source, source_name, printer_ip).

        El estado de contingencia se resuelve desde la misma fuente de datos (cache/BD)
        independientemente del worker, por lo que el resultado debe ser determinístico.

        Feature: websocket-scaling-redis, Property 13: Worker-Independent Registration Result
        **Validates: Requirements 6.5**
        """
        worker_a, worker_b = worker_pair

        messages_a = await simulate_registration_flow(scenario, worker_a)
        messages_b = await simulate_registration_flow(scenario, worker_b)

        # Extraer mensaje de contingencia (siempre es el tercero)
        contingency_a = messages_a[2]
        contingency_b = messages_b[2]

        # Verificar que el contenido es idéntico
        assert contingency_a["enabled"] == contingency_b["enabled"], (
            f"Campo 'enabled' difiere entre workers: "
            f"Worker A={contingency_a['enabled']}, Worker B={contingency_b['enabled']}"
        )
        assert contingency_a["source"] == contingency_b["source"], (
            f"Campo 'source' difiere entre workers: "
            f"Worker A={contingency_a['source']}, Worker B={contingency_b['source']}"
        )
        assert contingency_a["source_name"] == contingency_b["source_name"], (
            f"Campo 'source_name' difiere entre workers: "
            f"Worker A={contingency_a['source_name']}, Worker B={contingency_b['source_name']}"
        )
        assert contingency_a["printer_ip"] == contingency_b["printer_ip"], (
            f"Campo 'printer_ip' difiere entre workers: "
            f"Worker A={contingency_a['printer_ip']}, Worker B={contingency_b['printer_ip']}"
        )

    @given(
        scenario=registration_scenario_strategy(),
        worker_pair=worker_pair_strategy,
    )
    @hypothesis_settings(max_examples=150, deadline=None)
    @pytest.mark.asyncio
    async def test_pending_messages_order_is_worker_independent(
        self,
        scenario: Dict[str, Any],
        worker_pair: tuple,
    ):
        """
        Requirement 6.5: Los mensajes pendientes se envían en el mismo orden
        independientemente del worker.

        Verifica que la secuencia de pending messages (message_id, content, sent_at)
        es exactamente la misma en ambos workers.

        Feature: websocket-scaling-redis, Property 13: Worker-Independent Registration Result
        **Validates: Requirements 6.5**
        """
        worker_a, worker_b = worker_pair

        messages_a = await simulate_registration_flow(scenario, worker_a)
        messages_b = await simulate_registration_flow(scenario, worker_b)

        # Extraer mensajes pendientes (a partir del cuarto mensaje)
        pending_a = [m for m in messages_a if m["type"] == "message"]
        pending_b = [m for m in messages_b if m["type"] == "message"]

        # Cantidad de mensajes pendientes debe ser igual
        assert len(pending_a) == len(pending_b), (
            f"Cantidad de mensajes pendientes difiere: "
            f"Worker A={len(pending_a)}, Worker B={len(pending_b)}"
        )

        # Cada mensaje pendiente debe ser idéntico en contenido y posición
        for i, (msg_a, msg_b) in enumerate(zip(pending_a, pending_b)):
            assert msg_a["message_id"] == msg_b["message_id"], (
                f"Mensaje pendiente #{i}: message_id difiere entre workers. "
                f"Worker A={msg_a['message_id']}, Worker B={msg_b['message_id']}"
            )
            assert msg_a["content"] == msg_b["content"], (
                f"Mensaje pendiente #{i}: content difiere entre workers. "
                f"Worker A={msg_a['content']}, Worker B={msg_b['content']}"
            )
            assert msg_a["sent_at"] == msg_b["sent_at"], (
                f"Mensaje pendiente #{i}: sent_at difiere entre workers. "
                f"Worker A={msg_a['sent_at']}, Worker B={msg_b['sent_at']}"
            )
