/**
 * Tipos relacionados con configuración jerárquica.
 */

export interface SearchTargets {
  ips?: string[]
  ranges?: string[]
}

export interface GlobalConfig {
  id: string | null  // null indica que no existe en BD (valores por defecto)
  account_id: string
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
}

export interface EffectiveConfig {
  corporate_queue_name: string
  search_targets: SearchTargets | null
  pending_task_polling_minutes: number
  bootstrap_domains: string
  source: {
    corporate_queue_name: 'global' | 'vlan' | 'workstation'
    search_targets: 'global' | 'vlan' | 'workstation'
    pending_task_polling_minutes: 'global' | 'vlan' | 'workstation'
    bootstrap_domains: 'global' | 'vlan' | 'workstation'
  }
}
