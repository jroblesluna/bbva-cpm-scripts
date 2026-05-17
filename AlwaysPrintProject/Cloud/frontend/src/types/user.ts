/**
 * Tipos relacionados con usuarios del sistema.
 */

export enum UserRole {
  ADMIN = 'admin',
  OPERATOR = 'operator',
}

export interface User {
  id: string
  email: string
  full_name: string
  role: UserRole
  organization_id: string | null
  timezone?: string | null
  language: string
  is_active: boolean
  created_at: string
  updated_at: string
  organization?: {
    id: string
    name: string
    timezone: string
    language: string
  }
}

export interface UserCreate {
  email: string
  password: string
  full_name: string
  role: UserRole
  organization_id?: string | null
  timezone?: string | null
  language?: string
}

export interface UserUpdate {
  email?: string
  full_name?: string
  role?: UserRole
  organization_id?: string | null
  is_active?: boolean
  timezone?: string | null
  language?: string
}

export interface UserPasswordChange {
  current_password: string
  new_password: string
}

export interface LoginRequest {
  email: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
}

export interface PasswordResetRequest {
  email: string
}
