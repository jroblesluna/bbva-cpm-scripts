/**
 * Tipos relacionados con mensajes WebSocket.
 */

// ============================================================================
// MENSAJES WORKSTATION → BACKEND
// ============================================================================

export interface RegisterMessage {
  type: 'register'
  ip_private: string
  hostname: string
  os_version?: string
  service_version?: string
  tray_version?: string
}

export interface PongMessage {
  type: 'pong'
}

export interface StatusUpdateMessage {
  type: 'status_update'
  is_contingency_active: boolean
  ip_public?: string
}

export interface ConfigChangeReportMessage {
  type: 'config_change_report'
  success: boolean
  error?: string
}

export interface CommandResultMessage {
  type: 'command_result'
  command_id: string
  success: boolean
  result?: any
  error?: string
}

export type WorkstationMessage =
  | RegisterMessage
  | PongMessage
  | StatusUpdateMessage
  | ConfigChangeReportMessage
  | CommandResultMessage

// ============================================================================
// MENSAJES BACKEND → WORKSTATION
// ============================================================================

export interface PingMessage {
  type: 'ping'
}

export interface ConfigChangeMessage {
  type: 'config_change'
  config: {
    corporate_queue_name: string
    search_targets: Record<string, any> | null
    pending_task_polling_minutes: number
    bootstrap_domains: string
  }
}

export interface CommandMessage {
  type: 'command'
  command_id: string
  command: string
  params?: Record<string, any>
}

export interface NotificationMessage {
  type: 'notification'
  title: string
  message: string
  level: 'info' | 'warning' | 'error'
}

export type BackendToWorkstationMessage =
  | PingMessage
  | ConfigChangeMessage
  | CommandMessage
  | NotificationMessage

// ============================================================================
// MENSAJES BACKEND → OPERATOR (Frontend)
// ============================================================================

export interface WorkstationConnectedMessage {
  type: 'workstation_connected'
  workstation_id: string
  hostname: string
  ip_private: string
}

export interface WorkstationDisconnectedMessage {
  type: 'workstation_disconnected'
  workstation_id: string
  hostname: string
}

export interface ContingencyToggleMessage {
  type: 'contingency_toggle'
  workstation_id: string
  hostname: string
  is_active: boolean
}

export interface MessageDeliveredMessage {
  type: 'message_delivered'
  message_id: string
  workstation_id: string
}

export interface CommandResultNotification {
  type: 'command_result'
  workstation_id: string
  command_id: string
  success: boolean
  result?: any
  error?: string
}

export interface ConnectionStatsMessage {
  type: 'connection_stats'
  total_connections: number
  by_account: Record<string, number>
}

export interface TelemetryReceivedMessage {
  type: 'telemetry_received'
  workstation_id: string
  queue_status: string
  contingency_active: boolean
  jobs_identified: number
  avg_release_time_ms: number | null
  disconnection_count: number
}

export interface ConnectivityResultReceivedMessage {
  type: 'connectivity_result'
  workstation_id: string
  check_id: string
  check_type: string
  success: boolean
  latency_ms: number | null
  error: string | null
}

export type OperatorMessage =
  | WorkstationConnectedMessage
  | WorkstationDisconnectedMessage
  | ContingencyToggleMessage
  | MessageDeliveredMessage
  | CommandResultNotification
  | ConnectionStatsMessage
  | TelemetryReceivedMessage
  | ConnectivityResultReceivedMessage

// ============================================================================
// ESTADO DE CONEXIÓN
// ============================================================================

export enum WebSocketStatus {
  CONNECTING = 'connecting',
  CONNECTED = 'connected',
  DISCONNECTED = 'disconnected',
  ERROR = 'error',
}

export interface WebSocketState {
  status: WebSocketStatus
  error: string | null
  reconnectAttempts: number
}
