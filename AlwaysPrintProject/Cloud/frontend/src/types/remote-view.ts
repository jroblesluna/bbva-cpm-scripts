/**
 * Tipos para la funcionalidad de Remote View (Vista Remota).
 */

// ============================================================================
// ESTADOS Y MODOS
// ============================================================================

/** Modos disponibles de visualización remota */
export type RemoteViewMode = 'screenshot' | 'stream' | 'interactive'

/** Estados posibles de una sesión de vista remota */
export type RemoteViewStatus =
  | 'pending_consent'
  | 'active'
  | 'paused'
  | 'disconnected'
  | 'expired'

// ============================================================================
// MODELOS PRINCIPALES
// ============================================================================

/** Información de un monitor reportado por la workstation */
export interface RemoteViewMonitor {
  index: number
  name: string
  width: number
  height: number
  primary: boolean
}

/** Representa un tab/sesión activa en la página de remote view */
export interface RemoteViewTab {
  sessionId: string
  workstationId: string
  ip: string
  hostname: string
  mode: RemoteViewMode
  status: RemoteViewStatus
  monitors: RemoteViewMonitor[]
  selectedMonitor: number
  startedAt: string
  resolution?: string
  targetWorkerId?: string  // Worker donde está la workstation (para stream affinity)
}

// ============================================================================
// DELTA TILES (Canvas-based streaming)
// ============================================================================

/** Tile individual dentro de un delta frame (TileStreamEngine) */
export interface DeltaTile {
  x: number
  y: number
  w: number
  h: number
  data: string // base64 JPEG
}

// ============================================================================
// MENSAJES WEBSOCKET (Remote View)
// ============================================================================

/** Admin → Backend → WS: Pausar sesión (tab inactivo) */
export interface RvPauseMessage {
  type: 'remote_view_pause'
  session_id: string
}

/** Admin → Backend → WS: Reanudar sesión (tab activo de nuevo) */
export interface RvResumeMessage {
  type: 'remote_view_resume'
  session_id: string
}

/** Admin → Backend → WS: Terminar sesión */
export interface RvStopMessage {
  type: 'remote_view_stop'
  session_id: string
  reason: string
}

/** WS → Backend → Admin: Sesión aceptada */
export interface RvAcceptedMessage {
  type: 'remote_view_accepted'
  session_id: string
  monitors: RemoteViewMonitor[]
}

/** WS → Backend → Admin: Sesión rechazada */
export interface RvRejectedMessage {
  type: 'remote_view_rejected'
  session_id: string
  reason: 'user_declined' | 'user_timeout'
}

/** WS → Backend → Admin: Frame JPEG (screenshot mode) */
export interface RvFrameMessage {
  type: 'rv_frame'
  session_id: string
  format: 'jpeg' | 'h264'
  width: number
  height: number
  data: string
}

/** Unión de todos los mensajes entrantes de remote view */
export type RemoteViewIncomingMessage =
  | RvAcceptedMessage
  | RvRejectedMessage
  | RvFrameMessage

// ============================================================================
// MENSAJES DE INPUT (Interactive Mode)
// ============================================================================

/** Botones de mouse soportados */
export type MouseButton = 'left' | 'right' | 'middle'

/** Modificadores de teclado activos */
export type KeyModifier = 'ctrl' | 'alt' | 'shift' | 'meta'

/** Evento de mouse move */
export interface RvInputMouseMove {
  type: 'rv_input'
  session_id: string
  event: 'mousemove'
  x: number
  y: number
}

/** Evento de mouse down/up */
export interface RvInputMouseButton {
  type: 'rv_input'
  session_id: string
  event: 'mousedown' | 'mouseup'
  x: number
  y: number
  button: MouseButton
}

/** Evento de wheel (scroll) */
export interface RvInputWheel {
  type: 'rv_input'
  session_id: string
  event: 'wheel'
  x: number
  y: number
  delta: number
}

/** Evento de teclado (keydown/keyup) */
export interface RvInputKey {
  type: 'rv_input'
  session_id: string
  event: 'keydown' | 'keyup'
  code: string
  key: string
  modifiers: KeyModifier[]
}

/** Evento Secure Attention Sequence (Ctrl+Alt+Del) */
export interface RvInputSas {
  type: 'rv_input'
  session_id: string
  event: 'sas'
}

/** Unión de todos los mensajes rv_input */
export type RvInputMessage =
  | RvInputMouseMove
  | RvInputMouseButton
  | RvInputWheel
  | RvInputKey
  | RvInputSas
