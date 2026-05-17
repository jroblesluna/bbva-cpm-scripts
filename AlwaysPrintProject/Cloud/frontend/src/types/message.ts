/**
 * Tipos relacionados con mensajes a workstations.
 */

export type TargetType = 'workstation' | 'vlan' | 'account'

export interface Message {
  id: string
  organization_id: string
  sender_id: string | null
  target_type: TargetType
  target_id: string | null
  content: string
  is_delivered: boolean
  sent_at: string
  delivered_at: string | null
}

export interface MessageDetail extends Message {
  sender_name: string | null
  sender_email: string | null
}

export interface MessageCreate {
  target_type: TargetType
  target_id?: string | null
  content: string
}

export interface MessageListResponse {
  total: number
  page: number
  page_size: number
  messages: Message[]
}

export interface MessageStats {
  total_sent: number
  total_delivered: number
  total_pending: number
  delivery_rate: number
}
