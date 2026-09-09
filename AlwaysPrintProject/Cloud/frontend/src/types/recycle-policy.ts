/**
 * Tipos de la Política de Reciclaje (recycle-policy-config, task 9.3).
 *
 * Reflejan los schemas Pydantic del backend (`RecyclePolicyIn`/`RecyclePolicyOut`):
 * la Recycle_Rule viaja como string `"+1/-2/-3"` (tres enteros con signo explícito),
 * el `ephemeral_hours` en horas, y el Effective_From_Period descompuesto en año/mes a la
 * entrada y ya formateado como `"AAAA-MM"` en la salida.
 */

/**
 * Payload de edición de una Recycle_Policy (Global_Default u Org_Override).
 * Corresponde a `RecyclePolicyIn` del backend.
 */
export interface RecyclePolicyIn {
  /** Recycle_Rule con signo explícito, formato "+1/-2/-3". */
  rule: string
  /** Umbral de uso efímero en horas [1, 168]. */
  ephemeral_hours: number
  /** Año del Effective_From_Period [2000, 2999]. */
  effective_from_year: number
  /** Mes del Effective_From_Period [1, 12]. */
  effective_from_month: number
}

/**
 * Alcance de una política: global (Global_Default) u org (Org_Override).
 */
export type RecyclePolicyScope = 'global' | 'org'

/**
 * Representación de lectura de una Recycle_Policy persistida.
 * Corresponde a `RecyclePolicyOut` del backend.
 */
export interface RecyclePolicyOut {
  id: string
  scope: RecyclePolicyScope
  /** ID de la organización del Org_Override, o null para el Global_Default. */
  organization_id: string | null
  /** Recycle_Rule formateada "+1/-2/-3". */
  rule: string
  ephemeral_hours: number
  /** Effective_From_Period como "AAAA-MM". */
  effective_from: string
  created_at: string
}

/**
 * Error por regla devuelto por el backend en la respuesta 422 de validación
 * (`detail.errors = [{ rule, message }, ...]`, Req 17.5).
 */
export interface RecyclePolicyRuleError {
  rule: string
  message: string
}
