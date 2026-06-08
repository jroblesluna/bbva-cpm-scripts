/**
 * Tipos relacionados con organizaciones multi-tenant.
 */

export interface Organization {
  id: string
  name: string
  description?: string | null
  is_active: boolean
  timezone: string
  language: string
  auto_update_enabled: boolean
  target_version: string | null
  auto_reregister_enabled: boolean
  forced_contingency: boolean
  action_config_mandatory: boolean
  offline_timeout_minutes: number
  llm_model_id?: string | null
  openai_api_key?: string | null
  created_at: string
  updated_at: string
  public_ips?: PublicIP[]
}

export interface PublicIP {
  id: string
  organization_id: string
  ip_address: string
  description: string | null
  created_at: string
}

export interface OrganizationCreate {
  name: string
  description?: string | null
  is_active?: boolean
  timezone?: string
  language?: string
  offline_timeout_minutes?: number
}

export interface OrganizationUpdate {
  name?: string
  description?: string | null
  is_active?: boolean
  timezone?: string
  language?: string
  offline_timeout_minutes?: number
  llm_model_id?: string | null
  openai_api_key?: string | null
}

export interface PublicIPCreate {
  ip_address: string
  description?: string | null
}

export interface OrganizationStats {
  total_workstations: number
  online_workstations: number
  total_vlans: number
  total_users: number
}

