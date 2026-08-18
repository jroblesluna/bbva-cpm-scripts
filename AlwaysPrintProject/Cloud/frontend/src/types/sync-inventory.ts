/**
 * Tipos para la sección de Sincronización de Inventario.
 */

export interface StepResult {
  step: number
  name: string
  success: boolean
  output: string
  error?: string
}

export interface SyncExecutionResponse {
  success: boolean
  dry_run: boolean
  steps_executed: StepResult[]
  total_output: string
}
