/**
 * Hook para obtener el timezone efectivo del usuario actual.
 * 
 * Prioridad:
 * 1. Timezone del usuario (si está configurado)
 * 2. Timezone de la organización (si el usuario tiene organización)
 * 3. UTC (por defecto)
 */

'use client'

import { useAuth } from './useAuth'

export function useUserTimezone(): string {
  const { user } = useAuth()
  
  // Prioridad 1: Timezone del usuario
  if (user?.timezone) {
    return user.timezone
  }
  
  // Prioridad 2: Timezone de la organización
  if (user?.organization?.timezone) {
    return user.organization.timezone
  }
  
  // Prioridad 3: UTC por defecto
  return 'UTC'
}
