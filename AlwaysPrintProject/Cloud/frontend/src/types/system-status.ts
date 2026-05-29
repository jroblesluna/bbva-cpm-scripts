/**
 * Tipos TypeScript para el módulo de monitoreo de estado del sistema.
 *
 * Corresponden a los schemas Pydantic del backend en:
 * app/schemas/system_status.py
 */

// === MÉTRICAS DEL SISTEMA OPERATIVO ===

export interface OsMetrics {
  memory_total_mb: number
  memory_used_mb: number
  memory_available_mb: number
  memory_percent: number
  disk_total_mb: number
  disk_used_mb: number
  disk_available_mb: number
  disk_percent: number
  cpu_percent: number
  swap_total_mb: number
  swap_used_mb: number
  swap_available_mb: number
  uptime_seconds: number
}

// === MÉTRICAS DE CONTENEDORES DOCKER ===

export interface ContainerMetrics {
  name: string
  status: 'running' | 'stopped' | 'restarting'
  cpu_percent: number
  memory_used_mb: number
  memory_limit_mb: number
  network_rx_bytes: number
  network_tx_bytes: number
  uptime_seconds: number
}

// === HEALTH CHECKS ===

export interface HealthCheck {
  service_name: string
  is_available: boolean
  latency_ms: number | null
  error_message: string | null
  details: Record<string, unknown> | null
}

// === ALERTAS ===

export interface Alert {
  metric_name: string
  current_value: number
  threshold: number
  severity: 'warning' | 'critical'
}

// === SNAPSHOT COMPLETO ===

export interface StatusSnapshot {
  id: string
  timestamp: string
  overall_status: 'healthy' | 'degraded' | 'critical'
  os_metrics: OsMetrics
  docker_metrics: ContainerMetrics[]
  health_checks: HealthCheck[]
  alerts: Alert[]
}

// === HISTORIAL DE MÉTRICAS ===

export interface HistoryDataPoint {
  timestamp: string
  value: number
}

export interface MetricStats {
  average: number
  maximum: number
  minimum: number
  data_coverage_percent: number
}

export interface HistoryResponse {
  metric: string
  unit: string
  data_points: HistoryDataPoint[]
  stats: MetricStats
}

// === UPTIME DE SERVICIOS ===

export interface ServiceUptime {
  service_name: string
  uptime_percent: number
  total_checks: number
  successful_checks: number
}
