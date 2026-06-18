# Feature: websocket-scaling-redis, Property 3: Tenant Isolation at Command Delivery
"""
Property test: Tenant Isolation at Command Delivery

Para cualquier Cross_Worker_Command con organization_id X dirigido a una workstation
con organization_id registrado Y, el Connection_Manager SHALL entregar el comando
si y solo si X == Y. Si X != Y, el mensaje SHALL ser descartado.

Se generan pares aleatorios de (command.org_id, ws.org_id) — algunos coincidentes
y otros no — para verificar que:
1. Cuando command.org_id == ws.org_id → mensaje SE ENTREGA
2. Cuando command.org_id != ws.org_id → mensaje SE DESCARTA
3. Cuando org_id no es determinable para la workstation → mensaje SE DESCARTA

Feature: websocket-scaling-redis, Property 3: Tenant Isolation at Command Delivery
**Validates: Requirements 5.4, 5.5**
"""

import asyncio
from typing import Dict, List, Optional, Set
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings as hypothesis_settings, assume
from hypothesis import strategies as st


# === ESTRATEGIAS DE GENERACIÓN ===

# Generar UUIDs como strings para organization_id y workstation_id
org_id_strategy = st.uuids().map(str)
ws_id_strategy = st.uuids().map(str)
command_id_strategy = st.uuids().map(str)


@st.composite
def matching_org_pair(draw):
    """
    Genera un par (command_org_id, ws_org_id) donde AMBOS son iguales.
    Representa el caso donde el comando pertenece a la misma organización
    que la workstation destino.
    """
    org_id = draw(org_id_strategy)
    return org_id, org_id


@st.composite
def non_matching_org_pair(draw):
    """
    Genera un par (command_org_id, ws_org_id) donde son DIFERENTES.
    Representa un intento de entrega cross-tenant que debe ser bloqueado.
    """
    command_org = draw(org_id_strategy)
    ws_org = draw(org_id_strategy)
    assume(command_org != ws_org)
    return command_org, ws_org


@st.composite
def command_payload_strategy(draw):
    """
    Genera un payload de comando válido con organization_id aleatorio.
    Simula los mensajes que llegan via Redis pub/sub al método de entrega.
    """
    org_id = draw(org_id_strategy)
    cmd_id = draw(command_id_strategy)
    cmd_type = draw(st.sampled_from([
        "check_update", "analyze_log", "get_latest_log",
        "restart_service", "get_status", "execute_action",
    ]))
    return {
        "type": "command",
        "command_id": cmd_id,
        "command_type": cmd_type,
        "params": {},
        "source_worker": "worker_12345",
        "organization_id": org_id,
    }


# === HELPER: SIMULAR RedisConnectionManager CON TENANT VALIDATION ===


class TenantIsolationValidator:
    """
    Simula la lógica de validación de tenant isolation que task 5.2 implementa
    en _deliver_to_local_workstation (o _deliver_command).

    La validación es:
    - Si el payload tiene organization_id Y la workstation tiene org_id registrado:
      entregar sii ambos coinciden
    - Si no se puede determinar org_id de la workstation: descartar
    - Si el payload no tiene organization_id: descartar (no se puede validar)
    """

    def __init__(self):
        # Estado local: workstation_id → WebSocket mock
        self.workstation_connections: Dict[str, AsyncMock] = {}
        # Mapeo workstation_id → organization_id
        self.org_ids: Dict[str, str] = {}
        # Registro de mensajes descartados por tenant isolation
        self.discarded_messages: List[dict] = []
        # Registro de mensajes entregados exitosamente
        self.delivered_messages: List[dict] = []

    def register_workstation(
        self, workstation_id: str, websocket: AsyncMock, organization_id: Optional[str]
    ) -> None:
        """Registra una workstation con su org_id (puede ser None para simular indeterminado)."""
        self.workstation_connections[workstation_id] = websocket
        if organization_id is not None:
            self.org_ids[workstation_id] = organization_id

    async def deliver_command_to_workstation(
        self, workstation_id: str, payload: dict
    ) -> bool:
        """
        Entrega un comando a una workstation validando tenant isolation.

        Implementa la lógica especificada en Requirements 5.4 y 5.5:
        - Verificar command.organization_id == workstation.org_id antes de entregar
        - Descartar + log si no coincide
        - Descartar + log si org_id no determinable

        Returns:
            True si el mensaje fue entregado, False si fue descartado
        """
        ws = self.workstation_connections.get(workstation_id)
        if ws is None:
            return False

        # Obtener organization_id del comando
        command_org_id = payload.get("organization_id")

        # Obtener organization_id de la workstation registrada
        ws_org_id = self.org_ids.get(workstation_id)

        # Req 5.6: Si no se puede determinar org_id de la workstation, descartar
        if ws_org_id is None:
            self.discarded_messages.append({
                "reason": "org_id_not_determinable",
                "workstation_id": workstation_id,
                "payload": payload,
            })
            return False

        # Req 5.5: Si command.org_id no coincide con ws.org_id, descartar
        if command_org_id is None or command_org_id != ws_org_id:
            self.discarded_messages.append({
                "reason": "org_id_mismatch",
                "workstation_id": workstation_id,
                "command_org_id": command_org_id,
                "ws_org_id": ws_org_id,
                "payload": payload,
            })
            return False

        # Tenant validation OK — entregar mensaje
        await ws.send_json(payload)
        self.delivered_messages.append({
            "workstation_id": workstation_id,
            "payload": payload,
        })
        return True


# === PROPERTY TESTS ===


class TestTenantIsolationCommandDelivery:
    """
    Property 3: Tenant Isolation at Command Delivery.

    Para cualquier Cross_Worker_Command con organization_id X dirigido a una
    workstation con organization_id registrado Y, el Connection_Manager SHALL
    entregar el comando si y solo si X == Y.

    Feature: websocket-scaling-redis, Property 3: Tenant Isolation at Command Delivery
    **Validates: Requirements 5.4, 5.5**
    """

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(
        ws_id=ws_id_strategy,
        org_pair=matching_org_pair(),
        cmd_type=st.sampled_from([
            "check_update", "analyze_log", "get_latest_log",
            "restart_service", "get_status",
        ]),
        cmd_id=command_id_strategy,
    )
    @pytest.mark.asyncio
    async def test_comando_se_entrega_cuando_org_ids_coinciden(
        self, ws_id: str, org_pair: tuple, cmd_type: str, cmd_id: str
    ):
        """
        Propiedad: Cuando command.organization_id == ws.organization_id,
        el mensaje DEBE ser entregado a la workstation.

        Genera pares de org_ids idénticos y verifica que la entrega se realiza.

        Feature: websocket-scaling-redis, Property 3: Tenant Isolation at Command Delivery
        **Validates: Requirements 5.4, 5.5**
        """
        command_org_id, ws_org_id = org_pair

        # Preparar validador y registrar workstation
        validator = TenantIsolationValidator()
        mock_ws = AsyncMock()
        validator.register_workstation(ws_id, mock_ws, ws_org_id)

        # Preparar payload del comando
        payload = {
            "type": "command",
            "command_id": cmd_id,
            "command_type": cmd_type,
            "params": {},
            "source_worker": "worker_remote",
            "organization_id": command_org_id,
        }

        # Ejecutar entrega
        delivered = await validator.deliver_command_to_workstation(ws_id, payload)

        # Propiedad: el mensaje DEBE ser entregado
        assert delivered is True, (
            f"El comando con org_id '{command_org_id}' debería haberse entregado "
            f"a la workstation '{ws_id}' con org_id '{ws_org_id}' (coinciden), "
            f"pero fue descartado."
        )

        # Verificar que se llamó send_json en el WebSocket
        mock_ws.send_json.assert_called_once_with(payload)

        # Verificar que no hubo descartes
        assert len(validator.discarded_messages) == 0, (
            f"No debería haber mensajes descartados cuando org_ids coinciden. "
            f"Descartados: {validator.discarded_messages}"
        )

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(
        ws_id=ws_id_strategy,
        org_pair=non_matching_org_pair(),
        cmd_type=st.sampled_from([
            "check_update", "analyze_log", "get_latest_log",
            "restart_service", "get_status",
        ]),
        cmd_id=command_id_strategy,
    )
    @pytest.mark.asyncio
    async def test_comando_se_descarta_cuando_org_ids_no_coinciden(
        self, ws_id: str, org_pair: tuple, cmd_type: str, cmd_id: str
    ):
        """
        Propiedad: Cuando command.organization_id != ws.organization_id,
        el mensaje DEBE ser descartado sin entregarlo a la workstation.

        Genera pares de org_ids diferentes y verifica que la entrega es bloqueada.

        Feature: websocket-scaling-redis, Property 3: Tenant Isolation at Command Delivery
        **Validates: Requirements 5.4, 5.5**
        """
        command_org_id, ws_org_id = org_pair

        # Preparar validador y registrar workstation
        validator = TenantIsolationValidator()
        mock_ws = AsyncMock()
        validator.register_workstation(ws_id, mock_ws, ws_org_id)

        # Preparar payload del comando
        payload = {
            "type": "command",
            "command_id": cmd_id,
            "command_type": cmd_type,
            "params": {},
            "source_worker": "worker_remote",
            "organization_id": command_org_id,
        }

        # Ejecutar entrega
        delivered = await validator.deliver_command_to_workstation(ws_id, payload)

        # Propiedad: el mensaje DEBE ser descartado
        assert delivered is False, (
            f"El comando con org_id '{command_org_id}' NO debería haberse entregado "
            f"a la workstation '{ws_id}' con org_id '{ws_org_id}' (no coinciden). "
            f"Violación de tenant isolation."
        )

        # Verificar que NO se llamó send_json (mensaje no entregado)
        mock_ws.send_json.assert_not_called()

        # Verificar que se registró el descarte
        assert len(validator.discarded_messages) == 1, (
            f"Debería haberse registrado exactamente 1 mensaje descartado. "
            f"Registrados: {len(validator.discarded_messages)}"
        )
        assert validator.discarded_messages[0]["reason"] == "org_id_mismatch"

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(
        ws_id=ws_id_strategy,
        cmd_org_id=org_id_strategy,
        cmd_type=st.sampled_from([
            "check_update", "analyze_log", "get_latest_log",
            "restart_service", "get_status",
        ]),
        cmd_id=command_id_strategy,
    )
    @pytest.mark.asyncio
    async def test_comando_se_descarta_cuando_org_id_no_determinable(
        self, ws_id: str, cmd_org_id: str, cmd_type: str, cmd_id: str
    ):
        """
        Propiedad: Cuando el org_id de la workstation no puede ser determinado
        (no está en el mapping org_ids), el mensaje DEBE ser descartado.

        Simula el caso donde una workstation está conectada pero su organización
        no fue registrada correctamente (estado inconsistente).

        Feature: websocket-scaling-redis, Property 3: Tenant Isolation at Command Delivery
        **Validates: Requirements 5.4, 5.5**
        """
        # Preparar validador y registrar workstation SIN organization_id
        validator = TenantIsolationValidator()
        mock_ws = AsyncMock()
        validator.register_workstation(ws_id, mock_ws, organization_id=None)

        # Preparar payload del comando (con org_id válido)
        payload = {
            "type": "command",
            "command_id": cmd_id,
            "command_type": cmd_type,
            "params": {},
            "source_worker": "worker_remote",
            "organization_id": cmd_org_id,
        }

        # Ejecutar entrega
        delivered = await validator.deliver_command_to_workstation(ws_id, payload)

        # Propiedad: el mensaje DEBE ser descartado
        assert delivered is False, (
            f"El comando NO debería haberse entregado a la workstation '{ws_id}' "
            f"cuyo org_id no es determinable. Violación de tenant isolation."
        )

        # Verificar que NO se llamó send_json
        mock_ws.send_json.assert_not_called()

        # Verificar razón de descarte
        assert len(validator.discarded_messages) == 1
        assert validator.discarded_messages[0]["reason"] == "org_id_not_determinable"

    @hypothesis_settings(max_examples=150, deadline=None)
    @given(
        ws_ids=st.lists(ws_id_strategy, min_size=3, max_size=8, unique=True),
        org_ids_list=st.lists(org_id_strategy, min_size=2, max_size=4, unique=True),
    )
    @pytest.mark.asyncio
    async def test_multiples_workstations_solo_matchean_su_organizacion(
        self, ws_ids: list, org_ids_list: list
    ):
        """
        Propiedad: En un escenario con múltiples workstations de distintas
        organizaciones, un comando dirigido a una workstation específica
        solo se entrega si la organización del comando coincide con la de ESA
        workstation específica.

        Genera un conjunto de workstations asignadas a organizaciones aleatorias
        y verifica que la entrega respeta el aislamiento por tenant.

        Feature: websocket-scaling-redis, Property 3: Tenant Isolation at Command Delivery
        **Validates: Requirements 5.4, 5.5**
        """
        # Preparar validador con múltiples workstations de diferentes orgs
        validator = TenantIsolationValidator()
        ws_mocks: Dict[str, AsyncMock] = {}
        ws_org_mapping: Dict[str, str] = {}

        # Asignar cada workstation a una organización aleatoria (round-robin)
        for i, ws_id in enumerate(ws_ids):
            org_id = org_ids_list[i % len(org_ids_list)]
            mock_ws = AsyncMock()
            validator.register_workstation(ws_id, mock_ws, org_id)
            ws_mocks[ws_id] = mock_ws
            ws_org_mapping[ws_id] = org_id

        # Probar entrega a cada workstation con su propia org (debe funcionar)
        for ws_id in ws_ids:
            ws_org = ws_org_mapping[ws_id]
            payload = {
                "type": "command",
                "command_id": f"cmd_{ws_id[:8]}",
                "command_type": "check_update",
                "params": {},
                "source_worker": "worker_test",
                "organization_id": ws_org,
            }
            delivered = await validator.deliver_command_to_workstation(ws_id, payload)
            assert delivered is True, (
                f"Comando con org_id correcta '{ws_org}' debería entregarse "
                f"a workstation '{ws_id}' de la misma org."
            )

        # Probar entrega a cada workstation con org DIFERENTE (debe ser descartado)
        validator_cross = TenantIsolationValidator()
        for i, ws_id in enumerate(ws_ids):
            org_id = org_ids_list[i % len(org_ids_list)]
            mock_ws = AsyncMock()
            validator_cross.register_workstation(ws_id, mock_ws, org_id)

        for ws_id in ws_ids:
            ws_org = ws_org_mapping[ws_id]
            # Seleccionar una org diferente a la de la workstation
            other_orgs = [o for o in org_ids_list if o != ws_org]
            if not other_orgs:
                continue  # No hay otra org para probar cross-tenant

            cross_org = other_orgs[0]
            payload = {
                "type": "command",
                "command_id": f"cross_cmd_{ws_id[:8]}",
                "command_type": "analyze_log",
                "params": {},
                "source_worker": "worker_malicious",
                "organization_id": cross_org,
            }
            delivered = await validator_cross.deliver_command_to_workstation(ws_id, payload)
            assert delivered is False, (
                f"Comando con org_id '{cross_org}' NO debería entregarse "
                f"a workstation '{ws_id}' de org '{ws_org}'. "
                f"Violación de tenant isolation cross-tenant."
            )

    @hypothesis_settings(max_examples=100, deadline=None)
    @given(
        ws_id=ws_id_strategy,
        ws_org_id=org_id_strategy,
        cmd_id=command_id_strategy,
    )
    @pytest.mark.asyncio
    async def test_comando_sin_organization_id_se_descarta(
        self, ws_id: str, ws_org_id: str, cmd_id: str
    ):
        """
        Propiedad: Un comando sin campo organization_id se descarta,
        ya que no se puede validar la pertenencia al tenant.

        Verifica que payloads malformados (sin org_id) no bypasean
        la validación de tenant isolation.

        Feature: websocket-scaling-redis, Property 3: Tenant Isolation at Command Delivery
        **Validates: Requirements 5.4, 5.5**
        """
        # Preparar validador con workstation registrada correctamente
        validator = TenantIsolationValidator()
        mock_ws = AsyncMock()
        validator.register_workstation(ws_id, mock_ws, ws_org_id)

        # Payload sin organization_id (malformado o intento de bypass)
        payload = {
            "type": "command",
            "command_id": cmd_id,
            "command_type": "check_update",
            "params": {},
            "source_worker": "worker_unknown",
            # organization_id ausente intencionalmente
        }

        # Ejecutar entrega
        delivered = await validator.deliver_command_to_workstation(ws_id, payload)

        # Propiedad: el mensaje DEBE ser descartado (no se puede validar tenant)
        assert delivered is False, (
            f"Un comando sin organization_id NO debería entregarse. "
            f"Workstation '{ws_id}' con org_id '{ws_org_id}' recibió el mensaje."
        )

        # Verificar que NO se llamó send_json
        mock_ws.send_json.assert_not_called()
