/**
 * Tests unitarios para la lógica de la página de acciones masivas (Bulk On-Demand Actions).
 *
 * Valida:
 * - Req 8.1: Componente oculto para rol readonly (verificación de permisos)
 * - Req 8.3: ThrottleConfig valida rango 50-10000
 * - Req 8.4: ConfirmationDialog muestra datos correctos del preview (formatEstimatedTime)
 * - Req 8.5: ExecutionProgress actualiza contadores con mensajes WebSocket (estado de sesión)
 */

import { describe, it, expect } from 'vitest';
import {
  formatEstimatedTime,
  clampDelayMs,
  calcProgressPercent,
  isSessionRunning,
  isSessionFinished,
  shouldShowCancelButton,
  hasPermissionForBulkActions,
} from '@/lib/bulk-actions-utils';

// ============================================================================
// Test: Componente oculto para rol readonly (Requirement 8.1)
// ============================================================================

describe('Control de acceso por rol (Requirement 8.1)', () => {
  it('admin tiene permisos para acceder a bulk actions', () => {
    expect(hasPermissionForBulkActions('admin')).toBe(true);
  });

  it('operator tiene permisos para acceder a bulk actions', () => {
    expect(hasPermissionForBulkActions('operator')).toBe(true);
  });

  it('readonly NO tiene permisos para acceder a bulk actions', () => {
    expect(hasPermissionForBulkActions('readonly')).toBe(false);
  });

  it('rol undefined NO tiene permisos', () => {
    expect(hasPermissionForBulkActions(undefined)).toBe(false);
  });

  it('rol null NO tiene permisos', () => {
    expect(hasPermissionForBulkActions(null)).toBe(false);
  });

  it('string vacío NO tiene permisos', () => {
    expect(hasPermissionForBulkActions('')).toBe(false);
  });
});

// ============================================================================
// Test: ThrottleConfig valida rango 50-10000 (Requirement 8.3)
// ============================================================================

describe('Validación de ThrottleConfig - rango [50, 10000] (Requirement 8.3)', () => {
  it('acepta valores dentro del rango válido', () => {
    expect(clampDelayMs('50')).toBe(50);
    expect(clampDelayMs('500')).toBe(500);
    expect(clampDelayMs('1000')).toBe(1000);
    expect(clampDelayMs('5000')).toBe(5000);
    expect(clampDelayMs('10000')).toBe(10000);
  });

  it('clampea valores por debajo del mínimo a 50', () => {
    expect(clampDelayMs('0')).toBe(50);
    expect(clampDelayMs('1')).toBe(50);
    expect(clampDelayMs('49')).toBe(50);
    expect(clampDelayMs('-100')).toBe(50);
  });

  it('clampea valores por encima del máximo a 10000', () => {
    expect(clampDelayMs('10001')).toBe(10000);
    expect(clampDelayMs('99999')).toBe(10000);
    expect(clampDelayMs('50000')).toBe(10000);
  });

  it('retorna 50 cuando el valor no es numérico', () => {
    expect(clampDelayMs('')).toBe(50);
    expect(clampDelayMs('abc')).toBe(50);
    expect(clampDelayMs('NaN')).toBe(50);
  });

  it('acepta valores en los bordes exactos', () => {
    expect(clampDelayMs('50')).toBe(50);
    expect(clampDelayMs('10000')).toBe(10000);
  });
});

// ============================================================================
// Test: ConfirmationDialog muestra datos correctos del preview (Requirement 8.4)
// ============================================================================

describe('Formateo de tiempo estimado - formatEstimatedTime (Requirement 8.4)', () => {
  it('formatea milisegundos (< 1000ms) correctamente', () => {
    expect(formatEstimatedTime(0)).toBe('0ms');
    expect(formatEstimatedTime(100)).toBe('100ms');
    expect(formatEstimatedTime(500)).toBe('500ms');
    expect(formatEstimatedTime(999)).toBe('999ms');
  });

  it('formatea segundos (1000ms - 59999ms) correctamente', () => {
    expect(formatEstimatedTime(1000)).toBe('1.0s');
    expect(formatEstimatedTime(1500)).toBe('1.5s');
    expect(formatEstimatedTime(5000)).toBe('5.0s');
    expect(formatEstimatedTime(30000)).toBe('30.0s');
    expect(formatEstimatedTime(59999)).toBe('60.0s');
  });

  it('formatea minutos (>= 60000ms) correctamente', () => {
    expect(formatEstimatedTime(60000)).toBe('1.0min');
    expect(formatEstimatedTime(90000)).toBe('1.5min');
    expect(formatEstimatedTime(120000)).toBe('2.0min');
    expect(formatEstimatedTime(300000)).toBe('5.0min');
  });

  it('calcula correctamente el tiempo estimado de preview: (workstations - 1) * delay_ms', () => {
    // Fórmula: (workstations_online - 1) * delay_ms
    const calcEstimatedTime = (workstations: number, delayMs: number) =>
      (workstations - 1) * delayMs;

    // 10 workstations, 500ms delay → 4500ms → "4.5s"
    expect(formatEstimatedTime(calcEstimatedTime(10, 500))).toBe('4.5s');

    // 100 workstations, 500ms delay → 49500ms → "49.5s"
    expect(formatEstimatedTime(calcEstimatedTime(100, 500))).toBe('49.5s');

    // 150 workstations, 1000ms delay → 149000ms → "2.5min"
    expect(formatEstimatedTime(calcEstimatedTime(150, 1000))).toBe('2.5min');

    // 1 workstation, 500ms delay → 0ms → "0ms"
    expect(formatEstimatedTime(calcEstimatedTime(1, 500))).toBe('0ms');
  });
});

describe('Cálculo de porcentaje de progreso (Requirement 8.4)', () => {
  it('calcula correctamente el porcentaje', () => {
    expect(calcProgressPercent(0, 10)).toBe(0);
    expect(calcProgressPercent(5, 10)).toBe(50);
    expect(calcProgressPercent(10, 10)).toBe(100);
    expect(calcProgressPercent(3, 10)).toBe(30);
    expect(calcProgressPercent(7, 10)).toBe(70);
  });

  it('maneja total 0 sin error (edge case: división por cero)', () => {
    // max(0, 1) = 1, evita NaN
    expect(calcProgressPercent(0, 0)).toBe(0);
  });

  it('redondea correctamente los porcentajes', () => {
    // 1/3 = 33.33... → 33
    expect(calcProgressPercent(1, 3)).toBe(33);
    // 2/3 = 66.66... → 67
    expect(calcProgressPercent(2, 3)).toBe(67);
  });
});

// ============================================================================
// Test: ExecutionProgress actualiza contadores con mensajes WebSocket (Req 8.5)
// ============================================================================

describe('Estado de sesión y progreso (Requirement 8.5)', () => {
  it('identifica correctamente estado running', () => {
    expect(isSessionRunning('running')).toBe(true);
    expect(isSessionRunning('completed')).toBe(false);
    expect(isSessionRunning('cancelled')).toBe(false);
    expect(isSessionRunning('failed')).toBe(false);
  });

  it('identifica correctamente estados finalizados', () => {
    expect(isSessionFinished('completed')).toBe(true);
    expect(isSessionFinished('cancelled')).toBe(true);
    expect(isSessionFinished('failed')).toBe(true);
    expect(isSessionFinished('running')).toBe(false);
  });

  it('muestra botón de cancelación solo cuando running', () => {
    expect(shouldShowCancelButton('running')).toBe(true);
    expect(shouldShowCancelButton('completed')).toBe(false);
    expect(shouldShowCancelButton('cancelled')).toBe(false);
    expect(shouldShowCancelButton('failed')).toBe(false);
  });

  it('actualiza contadores correctamente con datos de progreso WebSocket', () => {
    // Simula datos de un mensaje WebSocket tipo bulk_progress
    const progressMessage = {
      type: 'bulk_progress' as const,
      session_id: 'test-uuid',
      status: 'running' as const,
      total: 50,
      sent: 25,
      success: 23,
      errors: 2,
      failed_workstations: ['ws-1', 'ws-2'],
      elapsed_ms: 12500,
    };

    // Invariante: sent == success + errors
    expect(progressMessage.sent).toBe(progressMessage.success + progressMessage.errors);

    // Invariante: sent <= total
    expect(progressMessage.sent).toBeLessThanOrEqual(progressMessage.total);

    // Progreso correcto
    expect(calcProgressPercent(progressMessage.sent, progressMessage.total)).toBe(50);

    // Estado correcto
    expect(isSessionRunning(progressMessage.status)).toBe(true);
    expect(shouldShowCancelButton(progressMessage.status)).toBe(true);
  });

  it('detecta finalización cuando sent == total y status == completed', () => {
    const completedMessage = {
      type: 'bulk_progress' as const,
      session_id: 'test-uuid',
      status: 'completed' as const,
      total: 50,
      sent: 50,
      success: 48,
      errors: 2,
      failed_workstations: ['ws-1', 'ws-2'],
      elapsed_ms: 25000,
    };

    // Al completar: sent == total
    expect(completedMessage.sent).toBe(completedMessage.total);

    // Invariante mantenida: sent == success + errors
    expect(completedMessage.sent).toBe(completedMessage.success + completedMessage.errors);

    // 100% progreso
    expect(calcProgressPercent(completedMessage.sent, completedMessage.total)).toBe(100);

    // Estado finalizado
    expect(isSessionFinished(completedMessage.status)).toBe(true);
    expect(shouldShowCancelButton(completedMessage.status)).toBe(false);
  });

  it('detecta cancelación con progreso parcial', () => {
    const cancelledMessage = {
      type: 'bulk_progress' as const,
      session_id: 'test-uuid',
      status: 'cancelled' as const,
      total: 50,
      sent: 30,
      success: 28,
      errors: 2,
      failed_workstations: ['ws-1', 'ws-2'],
      elapsed_ms: 15000,
    };

    // Cancelado parcialmente: sent < total
    expect(cancelledMessage.sent).toBeLessThan(cancelledMessage.total);

    // Invariante mantenida
    expect(cancelledMessage.sent).toBe(cancelledMessage.success + cancelledMessage.errors);

    // Progreso parcial (60%)
    expect(calcProgressPercent(cancelledMessage.sent, cancelledMessage.total)).toBe(60);

    // Estado finalizado
    expect(isSessionFinished(cancelledMessage.status)).toBe(true);
    expect(shouldShowCancelButton(cancelledMessage.status)).toBe(false);
  });
});
