/**
 * Tipos TypeScript para las métricas de escalabilidad del sistema.
 *
 * Corresponden a los schemas Pydantic del backend en:
 * app/schemas/scalability_metrics.py
 *
 * Estas métricas están orientadas a monitorear la capacidad del sistema
 * para soportar 5000 workstations concurrentes.
 */

// === MÉTRICAS DE CONEXIONES WEBSOCKET ===

/** Métricas de conexiones WebSocket activas (workstations + operadores) */
export interface WebSocketMetrics {
  workstation_count: number
  operator_count: number
  total: number
  workers: number
  detail: Record<string, WorkerDetail>
  data_available: boolean
}

/** Detalle de métricas de un worker individual */
export interface WorkerDetail {
  ws: number
  rss_mb: number
  fd: number
  pool_out: number
}

// === MÉTRICAS DE MEMORIA DEL PROCESO PYTHON ===

/** Métricas de memoria RSS del proceso Python y promedio por workstation */
export interface PythonMemoryMetrics {
  rss_mb: number | null
  container_total_mb: number | null
  avg_per_workstation_mb: number | null
}

// === MÉTRICAS DE FILE DESCRIPTORS ===

/** Métricas de file descriptors abiertos vs límite del sistema */
export interface FileDescriptorMetrics {
  open_count: number | null
  limit: number | null
  usage_percent: number | null
}

// === MÉTRICAS DE TRÁFICO DE RED ===

/** Métricas de tráfico de red del contenedor y tasas de transferencia */
export interface NetworkTrafficMetrics {
  rx_bytes: number | null
  tx_bytes: number | null
  rx_rate_bps: number | null
  tx_rate_bps: number | null
}

// === MÉTRICAS DEL POOL DE BASE DE DATOS ===

/** Métricas del pool SQLAlchemy y conexiones activas en PostgreSQL */
export interface DbPoolMetrics {
  checked_out: number | null
  idle: number | null
  pool_size: number | null
  overflow: number | null
  max_overflow: number | null
  pg_active_connections: number | null
  usage_percent: number | null
}

// === RESPUESTA COMPLETA DE MÉTRICAS DE ESCALABILIDAD ===

/** Respuesta completa del endpoint de métricas de escalabilidad */
export interface ScalabilityMetrics {
  websocket: WebSocketMetrics | null
  python_memory: PythonMemoryMetrics | null
  file_descriptors: FileDescriptorMetrics | null
  network: NetworkTrafficMetrics | null
  db_pool: DbPoolMetrics | null
  collected_at: string
}
