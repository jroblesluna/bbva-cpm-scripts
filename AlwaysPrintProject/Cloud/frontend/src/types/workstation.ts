/**
 * Tipos relacionados con workstations (estaciones Windows).
 */

import type { Account } from './account'

export interface Workstation {
  id: string
  account_id: string
  vlan_id: string | null
  ip_private: string
  hostname: string | null
  os_serial: string | null
  current_user: string | null
  is_online: boolean
  contingency_active: boolean
  last_connection: string | null
  first_seen: string
  created_at: string
  updated_at: string
  account?: Account
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
}

export interface WorkstationUpdate {
  hostname?: string | null
  os_serial?: string | null
  current_user?: string | null
  account_id?: string | null
  vlan_id?: string | null
}

export interface WorkstationStats {
  total: number
  online: number
  offline: number
  contingency_active: number
  by_vlan?: Record<string, number>
  by_account?: Record<string, {
    name: string
    total: number
    online: number
    offline: number
    contingency: number
  }>
}

export interface WorkstationFilter {
  account_id?: string
  vlan_id?: string
  contingency_active?: boolean
  is_online?: boolean
  search?: string
  page?: number
  page_size?: number
}

export interface WorkstationListResponse {
  items: Workstation[]
  total: number
  skip: number
  limit: number
}
