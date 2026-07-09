/**
 * Tipos TypeScript para el sistema de acciones masivas (Bulk On-Demand Actions).
 * Definen las interfaces para comunicación con la API REST y mensajes WebSocket.
 */

// ============================================================================
// MODELOS DE DATOS
// ============================================================================

/** Acción OnDemand disponible en el alwaysconfig activo de la organización. */
export interface OnDemandAction {
  label: string
  description: string | null
}

/** Respuesta de preview con estimación de tiempo y conteo de workstations. */
export interface BulkPreview {
  action_label: string
  action_description: string | null
  workstations_online: number
  estimated_time_ms: number
}

/** Estado actual de una sesión de ejecución masiva. */
export interface BulkSessionStatus {
  session_id: string
  status: 'running' | 'completed' | 'cancelled' | 'failed'
  total: number
  sent: number
  success: number
  errors: number
  failed_workstations: string[]
  started_at: string
  elapsed_ms: number | null
}

// ============================================================================
// MENSAJES WEBSOCKET
// ============================================================================

/** Mensaje de progreso enviado por WebSocket durante la ejecución masiva. */
export interface BulkProgressMessage {
  type: 'bulk_progress'
  session_id: string
  status: 'running' | 'completed' | 'cancelled'
  total: number
  sent: number
  success: number
  errors: number
  failed_workstations: string[]
  elapsed_ms: number
}

// ============================================================================
// SOLICITUDES (REQUEST BODIES)
// ============================================================================

/** Solicitud para iniciar una ejecución masiva. */
export interface BulkStartRequest {
  label: string
  delay_ms: number
}

/** Solicitud de preview de ejecución masiva. */
export interface BulkPreviewRequest {
  label: string
  delay_ms: number
}
