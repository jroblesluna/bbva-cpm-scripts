/**
 * Tipos TypeScript compartidos
 */

// TODO: Definir tipos según los schemas del backend
export type User = {
  id: string
  email: string
  role: 'admin' | 'operator' | 'readonly'
  accountId?: string
}

export type Account = {
  id: string
  name: string
  description: string
  isActive: boolean
}

export type Workstation = {
  id: string
  accountId: string
  vlanId?: string
  ipPrivate: string
  hostname?: string
  osSerial?: string
  currentUser?: string
  isOnline: boolean
  contingencyActive: boolean
  lastConnection?: string
  firstSeen: string
}
