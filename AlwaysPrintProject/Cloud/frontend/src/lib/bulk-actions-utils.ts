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
