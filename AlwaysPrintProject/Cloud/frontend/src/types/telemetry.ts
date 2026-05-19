/**
 * Tipos relacionados con telemetría y conectividad de workstations.
 */

/**
 * Entrada de telemetría reportada por una workstation.
 * Representa un snapshot periódico del estado operativo.
 */
export interface TelemetryEntry {
  id: string
  workstation_id: string
  queue_status: 'ok' | 'missing' | 'error'
  contingency_active: boolean
  jobs_identified: number
  avg_release_time_ms: number | null
  disconnection_count: number
  recorded_at: string // ISO 8601
}

/**
 * Resultado de un check de conectividad ejecutado por una workstation.
 */
export interface ConnectivityResult {
  id: string
  workstation_id: string
  check_id: string
  check_type: 'http' | 'tcp' | 'ping' | 'dns'
  success: boolean
  latency_ms: number | null
  error: string | null
  recorded_at: string // ISO 8601
}

/**
 * Resumen de estado de colas por tipo.
 */
export interface QueueStatusSummary {
  ok: number
  missing: number
  error: number
}

/**
 * Estadísticas agregadas de telemetría a nivel de cuenta.
 * Calculadas sobre los registros de las últimas 24 horas.
 */
export interface TelemetryStats {
  total_workstations: number
  workstations_reporting: number
  avg_jobs_identified: number
  contingency_active_count: number
  queue_status_summary: QueueStatusSummary
  last_updated: string | null
}

/**
 * Respuesta batch con la última telemetría de cada workstation.
 * Mapa workstation_id → última entrada de telemetría (o null si no tiene).
 */
export interface TelemetryLatestBatch {
  items: Record<string, TelemetryEntry | null>
}
