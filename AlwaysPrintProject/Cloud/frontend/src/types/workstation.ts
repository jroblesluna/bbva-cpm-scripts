/**
 * Tipos relacionados con workstations (estaciones Windows).
 */

import type { Organization } from './organization'

export interface Workstation {
  id: string
  organization_id: string
  vlan_id: string | null
  ip_private: string
  hostname: string | null
  os_serial: string | null
  current_user: string | null
  is_online: boolean
  contingency_active: boolean
  forced_contingency: boolean
  worker_id: string | null
  last_connection: string | null
  first_seen: string
  created_at: string
  updated_at: string
  cidr: string | null
  tray_version: string | null
  action_config_name: string | null
  action_config_hash: string | null
  action_config_version: string | null
  default_printer_id: string | null
  organization?: Organization
  vlan?: VLANBasic | null
}

export interface License {
  id: string
  workstation_id: string
  license_key: string
  is_valid: boolean
  created_at: string
  updated_at: string
}

export interface VLANBasic {
  id: string
  name: string
  cidr: string
  forced_contingency: boolean
  contingency_inherited?: boolean | null
}

export interface WorkstationUpdate {
  hostname?: string | null
  os_serial?: string | null
  current_user?: string | null
  organization_id?: string | null
  vlan_id?: string | null
  default_printer_id?: string | null
}

export interface WorkstationStats {
  total: number
  online: number
  offline: number
  contingency_active: number
  by_vlan?: Record<string, number>
  by_organization?: Record<string, {
    name: string
    total: number
    online: number
    offline: number
    contingency: number
  }>
  workstations_with_config?: Array<{
    id: string
    ip_private: string
    hostname: string | null
    vlan_name: string | null
    config_name: string
  }>
}

export interface WorkstationFilter {
  organization_id?: string
  vlan_id?: string
  contingency_active?: boolean
  is_online?: boolean
  search?: string
  version_filter?: string
  has_specific_config?: boolean
  page?: number
  page_size?: number
}

export interface WorkstationListResponse {
  items: Workstation[]
  total: number
  skip: number
  limit: number
  online_count?: number
  offline_count?: number
}
