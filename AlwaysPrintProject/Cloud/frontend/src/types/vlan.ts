/**
 * Tipos relacionados con VLANs (segmentos de red).
 */

export interface VLAN {
  id: string
  account_id: string
  name: string
  description: string | null
  cidr_ranges: string[]
  created_at: string
  updated_at: string
}

export interface VLANDetail extends VLAN {
  workstation_count: number
}

export interface VLANCreate {
  account_id?: string  // Opcional para operadores (se usa su cuenta automáticamente)
  name: string
  description?: string | null
  cidr_ranges: string[]
}

export interface VLANUpdate {
  name?: string
  description?: string | null
  cidr_ranges?: string[]
}

export interface VLANListResponse {
  total: number
  vlans: VLAN[]
}
