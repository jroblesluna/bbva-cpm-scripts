/**
 * Tipos relacionados con cuentas multi-tenant.
 */

export interface Account {
  id: string
  name: string
  description?: string | null
  is_active: boolean
  timezone: string
  language: string
  created_at: string
  updated_at: string
  public_ips?: PublicIP[]
}

export interface PublicIP {
  id: string
  account_id: string
  ip_address: string
  description: string | null
  created_at: string
}

export interface AccountCreate {
  name: string
  description?: string | null
  is_active?: boolean
  timezone?: string
  language?: string
}

export interface AccountUpdate {
  name?: string
  description?: string | null
  is_active?: boolean
  timezone?: string
  language?: string
}

export interface PublicIPCreate {
  ip_address: string
  description?: string | null
}

export interface AccountStats {
  total_workstations: number
  online_workstations: number
  total_vlans: number
  total_users: number
}
