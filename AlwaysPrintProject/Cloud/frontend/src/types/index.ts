/**
 * Exportación centralizada de todos los tipos TypeScript.
 */

// User types
export * from './user'

// Organization types
export * from './organization'

// Workstation types
export * from './workstation'

// VLAN types
export * from './vlan'

// Device types
export * from './device'

// Config types
export * from './config'

// Message types
export * from './message'

// Audit types
export * from './audit'

// WebSocket types
export * from './websocket'

// Telemetry types
export * from './telemetry'

// ============================================================================
// TIPOS COMUNES
// ============================================================================

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  skip: number
  limit: number
}

export interface ApiError {
  detail: string
  status?: number
}

export interface SuccessResponse {
  message: string
}
