/**
 * Evaluación de umbrales para métricas de escalabilidad.
 *
 * Define los colores del indicador visual (verde/amarillo/rojo) según
 * el valor de cada métrica y sus límites operativos configurados.
 *
 * Regla de inclusividad: un valor exactamente en el límite pertenece
 * a la zona inferior (comparación ≤).
 */

/** Color del indicador de umbral */
export type ThresholdColor = 'green' | 'yellow' | 'red'

/** Configuración de umbral para una métrica */
export interface ThresholdConfig {
  /** Valor máximo para zona verde (valor <= greenMax → verde) */
  greenMax: number
  /** Valor máximo para zona amarilla (greenMax < valor <= yellowMax → amarillo) */
  yellowMax: number
  // valor > yellowMax → rojo
}

/**
 * Evalúa el color de umbral para un valor dado según la configuración.
 *
 * @param value - Valor numérico a evaluar, o null si no disponible
 * @param config - Configuración con los límites greenMax y yellowMax
 * @returns Color del umbral ('green' | 'yellow' | 'red'), o null si el valor es null
 */
export function evaluateThreshold(
  value: number | null,
  config: ThresholdConfig
): ThresholdColor | null {
  if (value === null) return null
  if (value <= config.greenMax) return 'green'
  if (value <= config.yellowMax) return 'yellow'
  return 'red'
}

// === CONSTANTES DE UMBRAL POR MÉTRICA ===

/** Umbral para total de conexiones WebSocket (workstations + operadores) */
export const WS_TOTAL_THRESHOLD: ThresholdConfig = {
  greenMax: 8000,
  yellowMax: 12000,
}

/** Umbral para memoria Python promedio por workstation (MB/ws) */
export const MEMORY_PER_WS_THRESHOLD: ThresholdConfig = {
  greenMax: 2,
  yellowMax: 4,
}

/** Umbral para porcentaje de uso de file descriptors (%) */
export const FD_USAGE_THRESHOLD: ThresholdConfig = {
  greenMax: 60,
  yellowMax: 80,
}

/** Umbral para porcentaje de uso del pool de base de datos (%) */
export const DB_POOL_USAGE_THRESHOLD: ThresholdConfig = {
  greenMax: 60,
  yellowMax: 80,
}

/** Umbral para tasa de transmisión de red (MB/s) */
export const TX_RATE_THRESHOLD: ThresholdConfig = {
  greenMax: 50,
  yellowMax: 80,
}
