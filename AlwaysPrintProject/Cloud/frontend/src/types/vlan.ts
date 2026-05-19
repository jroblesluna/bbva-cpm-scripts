/**
 * Tipos relacionados con VLANs (segmentos de red).
 */

export interface VLAN {
  id: string
  organization_id: string
  name: string
  description: string | null
  cidr_ranges: string[]
  forced_contingency: boolean
  created_at: string
  updated_at: string
}

export interface VLANDetail extends VLAN {
  workstation_count: number
}

export interface VLANCreate {
  organization_id?: string  // Opcional para operadores (se usa su organización automáticamente)
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
