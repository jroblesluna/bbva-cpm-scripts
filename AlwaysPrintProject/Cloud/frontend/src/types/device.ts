/**
 * Tipos relacionados con dispositivos (impresoras).
 */

export interface Device {
  id: string
  organization_id: string
  vlan_id: string | null
  name: string
  ip_address: string
  description: string | null
  model: string | null
  location: string | null
  port: number
  is_active: boolean
  created_at: string
  updated_at: string
  vlan_name: string | null
}

export interface DeviceCreate {
  organization_id?: string
  vlan_id?: string | null
  name: string
  ip_address: string
  description?: string | null
  model?: string | null
  location?: string | null
  port?: number
  is_active?: boolean
}

export interface DeviceUpdate {
  vlan_id?: string | null
  name?: string
  ip_address?: string
  description?: string | null
  model?: string | null
  location?: string | null
  port?: number
  is_active?: boolean
}

export interface DeviceListResponse {
  total: number
  devices: Device[]
}

export interface DeviceFilter {
  organization_id?: string
  vlan_id?: string
  is_active?: boolean
  search?: string
}
