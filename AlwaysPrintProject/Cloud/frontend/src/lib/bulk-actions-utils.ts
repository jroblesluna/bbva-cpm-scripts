/**
 * Funciones utilitarias para la página de acciones masivas (Bulk On-Demand Actions).
 * Extraídas del componente para facilitar testing unitario.
 */

import type { BulkSessionStatus } from '@/types/bulk-actions';

/**
 * Formatea milisegundos a una representación legible.
 * @param ms - Tiempo en milisegundos
 * @returns String formateado (ej: "500ms", "1.5s", "1.5min")
 */
export function formatEstimatedTime(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}min`;
}

/**
 * Aplica la lógica de clamping al valor de delay_ms.
 * Rango permitido: [50, 10000] ms.
 * @param value - String del input numérico
 * @returns Valor numérico clamped dentro del rango válido
 */
export function clampDelayMs(value: string): number {
  const num = parseInt(value, 10);
  if (!isNaN(num)) {
    return Math.min(10000, Math.max(50, num));
  }
  return 50;
}

/**
 * Calcula el porcentaje de progreso de la ejecución masiva.
 * @param sent - Cantidad de envíos completados
 * @param total - Total de workstations target
 * @returns Porcentaje (0-100) redondeado
 */
export function calcProgressPercent(sent: number, total: number): number {
  return Math.round((sent / Math.max(total, 1)) * 100);
}

/**
 * Determina si una sesión está en estado de ejecución activa.
 */
export function isSessionRunning(status: BulkSessionStatus['status']): boolean {
  return status === 'running';
}

/**
 * Determina si una sesión ha finalizado (completada, cancelada o fallida).
 */
export function isSessionFinished(status: BulkSessionStatus['status']): boolean {
  return ['completed', 'cancelled', 'failed'].includes(status);
}

/**
 * Determina si el botón de cancelación debe mostrarse.
 * Solo se muestra cuando la sesión está en estado running.
 */
export function shouldShowCancelButton(status: BulkSessionStatus['status']): boolean {
  return status === 'running';
}

/**
 * Verifica si un rol de usuario tiene permisos para acceder a bulk actions.
 * Solo admin y operator pueden acceder.
 */
export function hasPermissionForBulkActions(role: string | undefined | null): boolean {
  return role === 'admin' || role === 'operator';
}

// ============================================================================
// ESTIMACIÓN DE TIEMPO RESTANTE Y ETA
// ============================================================================

/**
 * Calcula el tiempo restante estimado en milisegundos.
 * Fórmula: ((total - sent) / sent) * elapsedMs
 * Retorna null si sent === 0 (no hay datos para estimar).
 *
 * @param total - Total de workstations target
 * @param sent - Cantidad de envíos completados
 * @param elapsedMs - Tiempo transcurrido en milisegundos
 * @returns Tiempo restante estimado en ms, o null si no se puede calcular
 */
export function calcRemainingMs(total: number, sent: number, elapsedMs: number): number | null {
  if (sent === 0) return null
  return Math.round(((total - sent) / sent) * elapsedMs)
}

/**
 * Formatea milisegundos de tiempo restante a texto legible.
 * - Menos de 60s: "~45s"
 * - 60s o más: "~2m 30s"
 *
 * @param ms - Tiempo restante en milisegundos
 * @returns Texto formateado
 */
export function formatRemainingTime(ms: number): string {
  if (ms < 60000) {
    return `~${Math.round(ms / 1000)}s`
  }
  const min = Math.floor(ms / 60000)
  const sec = Math.round((ms % 60000) / 1000)
  return `~${min}m ${sec}s`
}

/**
 * Calcula la hora estimada de finalización (ETA).
 *
 * @param remainingMs - Tiempo restante estimado en milisegundos
 * @returns Date con la hora estimada de finalización
 */
export function calcETA(remainingMs: number): Date {
  return new Date(Date.now() + remainingMs)
}
