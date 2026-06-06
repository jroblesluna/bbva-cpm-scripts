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

# === ORGANIZATION SCHEMAS ===
from app.schemas.organization import (
    OrganizationBase,
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationResponse,
    OrganizationDetailResponse,
    OrganizationListResponse,
    PublicIPCreate,
    PublicIPResponse,
    PublicIPPendingResponse,
    PublicIPAuthorizeRequest,
    AutoUpdateToggleRequest,
    AutoUpdateToggleResponse,
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
    VLANSummaryItem,
    OrganizationInfo,
    WorkstationConfigItem,
    OrganizationBasicResponse,
    WorkstationRegisterRequest,
    WorkstationRegisterResponse,
    WorkstationRegisterPendingResponse,
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
    ConnectivityCheckItem,
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
    MessageDeliveryResponse,
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
    # Workstation → Backend (Telemetría y Conectividad)
    DisconnectionEventSchema,
    TelemetryMessage,
    ConnectivityResultMessage,
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

# === TELEMETRY SCHEMAS ===
from app.schemas.telemetry import (
    DisconnectionEventPayload,
    TelemetryMessagePayload,
    ConnectivityResultPayload,
    TelemetryLogResponse,
    ConnectivityResultResponse,
    QueueStatusSummary,
    TelemetryStatsResponse,
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

# === ACTION CONFIG SCHEMAS ===
from app.schemas.action_config import (
    ActionConfigUpload,
    ActionConfigUpdate,
    ActionConfigInfo,
    ActionConfigDetail,
    ActionConfigDownloadInfo,
    ActionConfigSyncStatus,
    calculate_config_hash,
)

# === LOG ANALYSIS SCHEMAS ===
from app.schemas.log_analysis import (
    LogAnalysisResponse,
    LogAnalysisTodayCheckResponse,
    LogAnalysisListResponse,
)

# === DEVICE SCHEMAS ===
from app.schemas.device import (
    DeviceCreate,
    DeviceUpdate,
    DeviceResponse,
    DeviceListResponse,
)

# === SYSTEM STATUS SCHEMAS ===
from app.schemas.system_status import (
    HistoryQueryParams,
    OsMetricsResponse,
    ContainerMetricsResponse,
    HealthCheckResponse,
    AlertResponse,
    StatusSnapshotResponse,
    HistoryDataPoint,
    MetricStats,
    HistoryResponse,
    ServiceUptimeResponse,
)

# === SCALABILITY METRICS SCHEMAS ===
from app.schemas.scalability_metrics import (
    WebSocketMetricsResponse,
    PythonMemoryResponse,
    FileDescriptorResponse,
    NetworkTrafficResponse,
    DbPoolResponse,
    ScalabilityMetricsResponse,
)

# === UPDATE SCHEMAS ===
from app.schemas.updates import (
    UpdateCheckResponse,
)

__all__ = [
    # User
    "UserCreate",
    "UserUpdate",
    "UserPasswordUpdate",
    "UserResponse",
    "UserListResponse",
    # Organization
    "OrganizationBase",
    "OrganizationCreate",
    "OrganizationUpdate",
    "OrganizationResponse",
    "OrganizationDetailResponse",
    "OrganizationListResponse",
    "PublicIPCreate",
    "PublicIPResponse",
    "PublicIPPendingResponse",
    "PublicIPAuthorizeRequest",
    "AutoUpdateToggleRequest",
    "AutoUpdateToggleResponse",
    # Workstation
    "LicenseResponse",
    "WorkstationResponse",
    "WorkstationDetailResponse",
    "WorkstationUpdate",
    "WorkstationStatusUpdate",
    "WorkstationListResponse",
    "WorkstationStatsResponse",
    "OrganizationInfo",
    "OrganizationBasicResponse",
    "WorkstationRegisterRequest",
    "WorkstationRegisterResponse",
    "WorkstationRegisterPendingResponse",
    # VLAN
    "VLANCreate",
    "VLANUpdate",
    "VLANResponse",
    "VLANDetailResponse",
    "VLANListResponse",
    # Config
    "ConnectivityCheckItem",
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
    "MessageDeliveryResponse",
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
    "DisconnectionEventSchema",
    "TelemetryMessage",
    "ConnectivityResultMessage",
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
    # Telemetry
    "DisconnectionEventPayload",
    "TelemetryMessagePayload",
    "ConnectivityResultPayload",
    "TelemetryLogResponse",
    "ConnectivityResultResponse",
    "QueueStatusSummary",
    "TelemetryStatsResponse",
    # Auth
    "LoginRequest",
    "TokenResponse",
    "TokenPayload",
    "RefreshTokenRequest",
    "PasswordResetRequest",
    "PasswordResetConfirm",
    # Action Config
    "ActionConfigUpload",
    "ActionConfigUpdate",
    "ActionConfigInfo",
    "ActionConfigDetail",
    "ActionConfigDownloadInfo",
    "ActionConfigSyncStatus",
    "calculate_config_hash",
    # Updates
    "UpdateCheckResponse",
    # Log Analysis
    "LogAnalysisResponse",
    "LogAnalysisTodayCheckResponse",
    "LogAnalysisListResponse",
    # Device
    "DeviceCreate",
    "DeviceUpdate",
    "DeviceResponse",
    "DeviceListResponse",
    # System Status
    "HistoryQueryParams",
    "OsMetricsResponse",
    "ContainerMetricsResponse",
    "HealthCheckResponse",
    "AlertResponse",
    "StatusSnapshotResponse",
    "HistoryDataPoint",
    "MetricStats",
    "HistoryResponse",
    "ServiceUptimeResponse",
    # Scalability Metrics
    "WebSocketMetricsResponse",
    "PythonMemoryResponse",
    "FileDescriptorResponse",
    "NetworkTrafficResponse",
    "DbPoolResponse",
    "ScalabilityMetricsResponse",
]
