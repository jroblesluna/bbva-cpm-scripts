/**
 * Tipos relacionados con configuración jerárquica.
 */

export interface SearchTargets {
  ips?: string[]
  ranges?: string[]
}

/**
 * Check de conectividad configurado para una workstation.
 * Los campos opcionales dependen del tipo de check.
 */
export interface ConnectivityCheck {
  id: string
  type: 'http' | 'tcp' | 'ping' | 'dns'
  url?: string
  host?: string
  hostname?: string
  port?: number
  timeout_ms: number
}

export interface GlobalConfig {
  id: string | null  // null indica que no existe en BD (valores por defecto)
  organization_id: string
  corporate_queue_name: string
  search_targets: SearchTargets | null
  pending_task_polling_minutes: number
  bootstrap_domains: string
  created_at: string
  updated_at: string
}

export interface GlobalConfigUpdate {
  corporate_queue_name?: string
  search_targets?: SearchTargets | null
  pending_task_polling_minutes?: number
  bootstrap_domains?: string
  connectivity_checks?: ConnectivityCheck[]
  locale?: string
  telemetry_enabled?: boolean
  telemetry_interval_seconds?: number
}

export interface VLANConfig {
  id: string
  vlan_id: string
  corporate_queue_name: string | null
  search_targets: SearchTargets | null
  pending_task_polling_minutes: number | null
  bootstrap_domains: string | null
  created_at: string
  updated_at: string
}

export interface VLANConfigUpdate {
  corporate_queue_name?: string | null
  search_targets?: SearchTargets | null
  pending_task_polling_minutes?: number | null
  bootstrap_domains?: string | null
  connectivity_checks?: ConnectivityCheck[] | null
  locale?: string | null
  telemetry_enabled?: boolean | null
  telemetry_interval_seconds?: number | null
}

export interface WorkstationConfig {
  id: string
  workstation_id: string
  corporate_queue_name: string | null
  search_targets: SearchTargets | null
  pending_task_polling_minutes: number | null
  bootstrap_domains: string | null
  created_at: string
  updated_at: string
}

export interface WorkstationConfigUpdate {
  corporate_queue_name?: string | null
  search_targets?: SearchTargets | null
  pending_task_polling_minutes?: number | null
  bootstrap_domains?: string | null
  connectivity_checks?: ConnectivityCheck[] | null
  locale?: string | null
  telemetry_enabled?: boolean | null
  telemetry_interval_seconds?: number | null
}

export interface EffectiveConfig {
  corporate_queue_name: string
  search_targets: SearchTargets | null
  pending_task_polling_minutes: number
  bootstrap_domains: string
  connectivity_checks: ConnectivityCheck[]
  locale: string
  telemetry_enabled: boolean
  telemetry_interval_seconds: number
  config_hash: string
  source: {
    corporate_queue_name: 'global' | 'vlan' | 'workstation'
    search_targets: 'global' | 'vlan' | 'workstation'
    pending_task_polling_minutes: 'global' | 'vlan' | 'workstation'
    bootstrap_domains: 'global' | 'vlan' | 'workstation'
  }
}
