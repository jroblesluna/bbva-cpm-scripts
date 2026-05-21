/**
 * Tipos relacionados con mensajes a workstations.
 */

export type TargetType = 'workstation' | 'vlan' | 'account'
export type DeliveryMode = 'all' | 'only_connected'
export type DeliveryStatus = 'pending' | 'sent' | 'skipped'

export interface Message {
  id: string
  organization_id: string
  sender_id: string | null
  sender_name: string | null
  target_type: TargetType
  target_id: string | null
  content: string
  delivery_mode: DeliveryMode
  is_delivered: boolean
  sent_at: string
  delivered_at: string | null
  // Resumen de entregas
  total_deliveries: number | null
  sent_deliveries: number | null
  pending_deliveries: number | null
  skipped_deliveries: number | null
}

export interface MessageDelivery {
  id: string
  message_id: string
  workstation_id: string
  status: DeliveryStatus
  delivered_at: string | null
  workstation_hostname: string | null
  workstation_ip: string | null
  workstation_is_online: boolean | null
}

export interface MessageDetail extends Message {
  sender_name: string | null
  sender_email: string | null
  deliveries: MessageDelivery[] | null
}

export interface MessageCreate {
  target_type: TargetType
  target_id?: string | null
  content: string
  delivery_mode?: DeliveryMode
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
