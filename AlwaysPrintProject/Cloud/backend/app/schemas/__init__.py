"""
Schemas Pydantic para validación y serialización.

Este módulo exporta todos los schemas del sistema para facilitar su importación.
"""

# === USER SCHEMAS ===
from app.schemas.user import (
    UserCreate,
    UserUpdate,
    UserPasswordUpdate,
    UserResponse,
    UserListResponse,
)

# === ACCOUNT SCHEMAS ===
from app.schemas.account import (
    AccountCreate,
    AccountUpdate,
    AccountResponse,
    AccountDetailResponse,
    AccountListResponse,
    PublicIPCreate,
    PublicIPResponse,
    PublicIPPendingResponse,
    PublicIPAuthorizeRequest,
)

# === WORKSTATION SCHEMAS ===
from app.schemas.workstation import (
    LicenseResponse,
    WorkstationResponse,
    WorkstationDetailResponse,
    WorkstationUpdate,
    WorkstationStatusUpdate,
    WorkstationListResponse,
    WorkstationStatsResponse,
    AccountBasicResponse,
)

# === VLAN SCHEMAS ===
from app.schemas.vlan import (
    VLANCreate,
    VLANUpdate,
    VLANResponse,
    VLANDetailResponse,
    VLANListResponse,
)

# === CONFIG SCHEMAS ===
from app.schemas.config import (
    GlobalConfigUpdate,
    GlobalConfigResponse,
    VLANConfigUpdate,
    VLANConfigResponse,
    WorkstationConfigUpdate,
    WorkstationConfigResponse,
    EffectiveConfigResponse,
)

# === MESSAGE SCHEMAS ===
from app.schemas.message import (
    MessageCreate,
    MessageResponse,
    MessageDetailResponse,
    MessageListResponse,
    MessageStatsResponse,
)

# === AUDIT SCHEMAS ===
from app.schemas.audit import (
    AuditLogResponse,
    AuditLogDetailResponse,
    AuditLogSearch,
    AuditLogListResponse,
    AuditLogStatsResponse,
)

# === WEBSOCKET SCHEMAS ===
from app.schemas.websocket import (
    # Workstation → Backend
    RegisterMessage,
    PongMessage,
    StatusUpdateMessage,
    ConfigChangeReportMessage,
    CommandResultMessage,
    # Backend → Workstation
    PingMessage,
    ConfigChangeMessage,
    CommandMessage,
    NotificationMessage,
    # Backend → Operator
    WorkstationConnectedNotification,
    WorkstationDisconnectedNotification,
    ContingencyToggleNotification,
    MessageDeliveredNotification,
    CommandResultNotification,
    ConnectionStatsMessage,
    # Genéricos
    WebSocketMessage,
    WebSocketError,
)

# === AUTH SCHEMAS ===
from app.schemas.auth import (
    LoginRequest,
    TokenResponse,
    TokenPayload,
    RefreshTokenRequest,
    PasswordResetRequest,
    PasswordResetConfirm,
)

__all__ = [
    # User
    "UserCreate",
    "UserUpdate",
    "UserPasswordUpdate",
    "UserResponse",
    "UserListResponse",
    # Account
    "AccountCreate",
    "AccountUpdate",
    "AccountResponse",
    "AccountDetailResponse",
    "AccountListResponse",
    "PublicIPCreate",
    "PublicIPResponse",
    "PublicIPPendingResponse",
    "PublicIPAuthorizeRequest",
    # Workstation
    "LicenseResponse",
    "WorkstationResponse",
    "WorkstationDetailResponse",
    "WorkstationUpdate",
    "WorkstationStatusUpdate",
    "WorkstationListResponse",
    "WorkstationStatsResponse",
    "AccountBasicResponse",
    # VLAN
    "VLANCreate",
    "VLANUpdate",
    "VLANResponse",
    "VLANDetailResponse",
    "VLANListResponse",
    # Config
    "GlobalConfigUpdate",
    "GlobalConfigResponse",
    "VLANConfigUpdate",
    "VLANConfigResponse",
    "WorkstationConfigUpdate",
    "WorkstationConfigResponse",
    "EffectiveConfigResponse",
    # Message
    "MessageCreate",
    "MessageResponse",
    "MessageDetailResponse",
    "MessageListResponse",
    "MessageStatsResponse",
    # Audit
    "AuditLogResponse",
    "AuditLogDetailResponse",
    "AuditLogSearch",
    "AuditLogListResponse",
    "AuditLogStatsResponse",
    # WebSocket
    "RegisterMessage",
    "PongMessage",
    "StatusUpdateMessage",
    "ConfigChangeReportMessage",
    "CommandResultMessage",
    "PingMessage",
    "ConfigChangeMessage",
    "CommandMessage",
    "NotificationMessage",
    "WorkstationConnectedNotification",
    "WorkstationDisconnectedNotification",
    "ContingencyToggleNotification",
    "MessageDeliveredNotification",
    "CommandResultNotification",
    "ConnectionStatsMessage",
    "WebSocketMessage",
    "WebSocketError",
    # Auth
    "LoginRequest",
    "TokenResponse",
    "TokenPayload",
    "RefreshTokenRequest",
    "PasswordResetRequest",
    "PasswordResetConfirm",
]
