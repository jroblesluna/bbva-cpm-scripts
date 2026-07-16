"""
WebSocket dedicado para streaming de Remote View con worker affinity.

Este endpoint es usado exclusivamente por el DeltaStreamViewer del frontend.
Su propósito es garantizar que el viewer esté conectado al mismo worker
donde está la workstation, eliminando la necesidad de relay cross-worker
para frames de alta frecuencia (25 FPS tiles).

Protocolo:
1. Frontend conecta a /ws/rv-stream?session={id}&token={jwt}
2. Backend responde con {"type": "rv_stream_connected", "worker_id": "worker_XXXX"}
3. Frontend compara worker_id con target_worker_id:
   - Si coincide → listo, recibirá frames directamente
   - Si no coincide → cierra y reintenta (round-robin caerá en otro worker)
4. Una vez conectado al worker correcto, recibe rv_frame push directamente

Los frames NO se envían via send_to_operator. Se envían directo al WS
registrado aquí (mismo worker, sin Redis intermediario).
"""

import os
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import decode_access_token
from app.core.logging import get_logger
from app.services.remote_view_relay import remote_view_relay

logger = get_logger(__name__)

router = APIRouter()

# Registro local: session_id → WebSocket del viewer (solo en este worker)
_stream_viewers: dict[str, WebSocket] = {}


def get_stream_viewer(session_id: str) -> Optional[WebSocket]:
    """Obtiene el WebSocket del viewer de streaming para una sesión (local al worker)."""
    return _stream_viewers.get(session_id)


@router.websocket("/ws/rv-stream")
async def rv_stream_websocket(
    websocket: WebSocket,
    session: Optional[str] = None,
    token: Optional[str] = None,
):
    """
    WebSocket dedicado para recibir frames de Remote View.

    Query params:
        session: UUID de la sesión de Remote View
        token: JWT del operador

    Protocolo:
        1. Conecta y valida token + sesión
        2. Responde con worker_id para que el frontend verifique affinity
        3. Mantiene conexión abierta para recibir frames push
        4. También acepta mensajes del viewer (rv_request_frame, rv_viewer_alive)
    """
    user_id: Optional[str] = None
    session_id: Optional[str] = session

    try:
        # Validar parámetros
        if not token or not session_id:
            await websocket.close(code=1008, reason="Missing token or session")
            return

        # Validar JWT
        try:
            payload = decode_access_token(token)
            user_id = payload.get("sub")
            if not user_id:
                await websocket.close(code=1008, reason="Invalid token")
                return
        except Exception:
            await websocket.close(code=1008, reason="Invalid token")
            return

        # Verificar que la sesión existe en el relay
        rv_session = remote_view_relay.get_session(session_id)
        if not rv_session:
            # Intentar lazy register desde BD
            from app.api.v1.websocket.workstation import _lazy_register_rv_session
            _lazy_register_rv_session(session_id)
            rv_session = remote_view_relay.get_session(session_id)

        if not rv_session:
            await websocket.close(code=1008, reason="Session not found")
            return

        # Verificar que el usuario es el dueño de la sesión
        if rv_session["user_id"] != user_id:
            await websocket.close(code=1008, reason="Not session owner")
            return

        # Aceptar conexión
        await websocket.accept()

        # Obtener worker_id de este proceso
        worker_id = f"worker_{os.getpid()}"

        # Registrar viewer en el mapping local
        _stream_viewers[session_id] = websocket

        logger.info(
            "rv_stream.connected",
            session_id=session_id,
            user_id=user_id,
            worker_id=worker_id,
        )

        # Enviar confirmación con worker_id para affinity check
        await websocket.send_json({
            "type": "rv_stream_connected",
            "worker_id": worker_id,
            "session_id": session_id,
        })

        # Loop de recepción (viewer puede enviar rv_request_frame, rv_viewer_alive)
        while True:
            data = await websocket.receive_json()
            message_type = data.get("type")

            if message_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif message_type in ("rv_request_frame", "rv_viewer_alive"):
                # Relay al workstation
                data["session_id"] = session_id
                await remote_view_relay.relay_to_workstation(session_id, data)

            elif message_type == "rv_stream_disconnect":
                # Cierre voluntario del viewer
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(
            "rv_stream.error",
            session_id=session_id,
            error=str(e),
        )
    finally:
        # Limpiar registro
        if session_id and session_id in _stream_viewers:
            del _stream_viewers[session_id]
            logger.info(
                "rv_stream.disconnected",
                session_id=session_id,
            )
