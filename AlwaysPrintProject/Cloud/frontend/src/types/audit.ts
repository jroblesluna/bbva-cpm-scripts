/**
 * Tipos relacionados con auditoría.
 */

export type ActionType =
  | 'create'
  | 'update'
  | 'delete'
  | 'config_change'
  | 'contingency_toggle'
  | 'message_sent'
  | 'command_sent'

export interface AuditLog {
  id: string
  user_id: string | null
  workstation_id: string | null
  account_id: string | null
  action_type: ActionType
  entity_type: string
  entity_id: string
  entity_name: string | null
  old_values: Record<string, any> | null
  new_values: Record<string, any> | null
  ip_address: string | null
  created_at: string
}

export interface AuditLogDetail extends AuditLog {
  user_name: string | null
  user_email: string | null
  workstation_ip: string | null
}

export interface AuditLogSearch {
  user_id?: string
  workstation_id?: string
  account_id?: string
  action_type?: ActionType
  entity_type?: string
  entity_id?: string
  start_date?: string
  end_date?: string
  page?: number
  page_size?: number
}

export interface AuditLogListResponse {
  total: number
  page: number
  page_size: number
  logs: AuditLog[]
}

export interface AuditLogStats {
  total_actions: number
  actions_by_type: Record<string, number>
  most_active_users: Array<{
    user_id: string
    action_count: number
  }>
  recent_activity_count: number
}
