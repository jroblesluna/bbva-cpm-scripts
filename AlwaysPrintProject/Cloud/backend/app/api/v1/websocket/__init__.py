"""
Endpoints WebSocket para comunicación en tiempo real.
"""

from app.api.v1.websocket import workstation, operator, rv_stream

__all__ = ["workstation", "operator", "rv_stream"]
