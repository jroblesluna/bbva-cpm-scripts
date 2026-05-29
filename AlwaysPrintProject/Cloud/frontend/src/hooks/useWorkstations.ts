/**
 * Hook para gestión de workstations.
 * 
 * Proporciona:
 * - Listado de workstations con filtros
 * - Estadísticas
 * - Actualización en tiempo real vía WebSocket
 * - Integración con React Query
 */

'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { workstationsApi } from '@/lib/api'
import { useAuth } from '@/components/providers/AuthProvider'
import type {
  Workstation,
  WorkstationUpdate,
  WorkstationStats,
  WorkstationFilter,
  WorkstationConfigUpdate,
  EffectiveConfig,
} from '@/types'

/**
 * Hook para listar workstations con filtros.
 */
export function useWorkstations(filters?: WorkstationFilter) {
  const { isOperator } = useAuth()

  return useQuery({
    queryKey: ['workstations', filters],
    queryFn: () => isOperator() ? workstationsApi.listMine(filters) : workstationsApi.list(filters),
  })
}

/**
 * Hook para obtener estadísticas de workstations.
 */
export function useWorkstationStats() {
  return useQuery({
    queryKey: ['workstations', 'stats'],
    queryFn: () => workstationsApi.stats(),
    refetchInterval: 30000, // Refrescar cada 30s
  })
}

/**
 * Hook para obtener una workstation específica.
 */
export function useWorkstation(id: string) {
  return useQuery({
    queryKey: ['workstations', id],
    queryFn: () => workstationsApi.get(id),
    enabled: !!id,
  })
}

/**
 * Hook para actualizar una workstation.
 */
export function useUpdateWorkstation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: WorkstationUpdate }) =>
      workstationsApi.update(id, data),
    onSuccess: (updatedWorkstation) => {
      // Invalidar queries relacionadas
      queryClient.invalidateQueries({ queryKey: ['workstations'] })
      queryClient.setQueryData(['workstations', updatedWorkstation.id], updatedWorkstation)
    },
  })
}

/**
 * Hook para obtener configuración efectiva de workstation.
 */
export function useWorkstationConfig(id: string) {
  return useQuery({
    queryKey: ['workstations', id, 'config'],
    queryFn: () => workstationsApi.getConfig(id),
    enabled: !!id,
  })
}

/**
 * Hook para actualizar configuración de workstation.
 */
export function useUpdateWorkstationConfig() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: WorkstationConfigUpdate }) =>
      workstationsApi.updateConfig(id, data),
    onSuccess: (_, variables) => {
      // Invalidar configuración de la workstation
      queryClient.invalidateQueries({ queryKey: ['workstations', variables.id, 'config'] })
    },
  })
}

/**
 * Hook para eliminar configuración de workstation.
 */
export function useDeleteWorkstationConfig() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (id: string) => workstationsApi.deleteConfig(id),
    onSuccess: (_, id) => {
      // Invalidar configuración de la workstation
      queryClient.invalidateQueries({ queryKey: ['workstations', id, 'config'] })
    },
  })
}
