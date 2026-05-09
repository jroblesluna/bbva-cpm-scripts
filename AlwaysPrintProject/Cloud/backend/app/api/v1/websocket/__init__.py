"""
Endpoints WebSocket para comunicación en tiempo real.
"""

from app.api.v1.websocket import workstation, operator

__all__ = ["workstation", "operator"]
