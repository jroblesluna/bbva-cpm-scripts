/**
 * Exportación centralizada de todos los tipos TypeScript.
 */

// User types
export * from './user'

// Account types
export * from './account'

// Workstation types
export * from './workstation'

// VLAN types
export * from './vlan'

// Config types
export * from './config'

// Message types
export * from './message'

// Audit types
export * from './audit'

// WebSocket types
export * from './websocket'

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
