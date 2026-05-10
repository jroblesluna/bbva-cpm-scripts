/**
 * Página de auditoría del sistema.
 * 
 * Muestra un registro completo de todas las acciones realizadas:
 * - Creación, actualización y eliminación de entidades
 * - Cambios de configuración
 * - Logins y logouts
 * - Mensajes enviados
 * - Registro de workstations
 * - Autorización/rechazo de IPs
 */

'use client'

import { useState, useEffect } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  FileText,
  Search,
  Filter,
  Calendar,
  User,
  Activity,
  TrendingUp,
} from 'lucide-react'
import type { AuditLog, AuditLogStats, ActionType } from '@/types/audit'
import { formatDateWithTimezone } from '@/lib/dateUtils'
import { useUserTimezone } from '@/hooks/useUserTimezone'

export default function AuditPage() {
  const { user, getAuthHeaders } = useAuth()
  const { timezone } = useUserTimezone()
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [stats, setStats] = useState<AuditLogStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [filterActionType, setFilterActionType] = useState<ActionType | null>(null)
  const [filterEntityType, setFilterEntityType] = useState<string>('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const pageSize = 50

  // Cargar logs y estadísticas
  useEffect(() => {
    loadLogs()
    loadStats()
  }, [page, filterActionType, filterEntityType])

  const loadLogs = async () => {
    try {
      setLoading(true)

      const params = new URLSearchParams({
        page: page.toString(),
        page_size: pageSize.toString(),
      })

      if (filterActionType) {
        params.append('action_type', filterActionType)
      }

      if (filterEntityType) {
        params.append('entity_type', filterEntityType)
      }

      const response = await fetch(
        `http://localhost:8000/api/v1/audit/?${params.toString()}`,
        {
          headers: getAuthHeaders(),
        }
      )

      if (!response.ok) throw new Error('Error al cargar logs de auditoría')

      const data = await response.json()
      setLogs(data.logs || [])
      setTotal(data.total || 0)
    } catch (error) {
      console.error('Error:', error)
      alert('Error al cargar logs de auditoría')
    } finally {
      setLoading(false)
    }
  }

  const loadStats = async () => {
    try {
      const response = await fetch('http://localhost:8000/api/v1/audit/stats', {
        headers: getAuthHeaders(),
      })

      if (!response.ok) throw new Error('Error al cargar estadísticas')

      const data = await response.json()
      setStats(data)
    } catch (error) {
      console.error('Error:', error)
    }
  }

  // Filtrar logs por búsqueda
  const filteredLogs = logs.filter((log) => {
    const searchLower = searchTerm.toLowerCase()
    return (
      log.entity_type.toLowerCase().includes(searchLower) ||
      log.action_type.toLowerCase().includes(searchLower) ||
      log.entity_id.toLowerCase().includes(searchLower)
    )
  })

  const getActionTypeLabel = (type: ActionType): string => {
    const labels: Record<ActionType, string> = {
      create: 'Crear',
      update: 'Actualizar',
      delete: 'Eliminar',
      login: 'Login',
      logout: 'Logout',
      config_change: 'Cambio Config',
      message_sent: 'Mensaje Enviado',
      workstation_registered: 'Estación Registrada',
      ip_authorized: 'IP Autorizada',
      ip_rejected: 'IP Rechazada',
    }
    return labels[type] || type
  }

  const getActionTypeBadgeColor = (type: ActionType): string => {
    const colors: Record<ActionType, string> = {
      create: 'bg-green-100 text-green-800',
      update: 'bg-blue-100 text-blue-800',
      delete: 'bg-red-100 text-red-800',
      login: 'bg-purple-100 text-purple-800',
      logout: 'bg-gray-100 text-gray-800',
      config_change: 'bg-yellow-100 text-yellow-800',
      message_sent: 'bg-indigo-100 text-indigo-800',
      workstation_registered: 'bg-teal-100 text-teal-800',
      ip_authorized: 'bg-green-100 text-green-800',
      ip_rejected: 'bg-red-100 text-red-800',
    }
    return colors[type] || 'bg-gray-100 text-gray-800'
  }

  if (loading && page === 1) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Cargando auditoría...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Auditoría</h1>
        <p className="mt-2 text-gray-600">
          Registro completo de todas las acciones realizadas en el sistema
        </p>
      </div>

      {/* Estadísticas */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="p-3 bg-blue-100 rounded-lg">
                <FileText className="h-6 w-6 text-blue-600" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">Total Acciones</p>
                <p className="text-2xl font-bold text-gray-900">{stats.total_actions}</p>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="p-3 bg-green-100 rounded-lg">
                <Activity className="h-6 w-6 text-green-600" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">Últimas 24h</p>
                <p className="text-2xl font-bold text-gray-900">
                  {stats.recent_activity_count}
                </p>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="p-3 bg-purple-100 rounded-lg">
                <User className="h-6 w-6 text-purple-600" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">Usuarios Activos</p>
                <p className="text-2xl font-bold text-gray-900">
                  {stats.most_active_users.length}
                </p>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="p-3 bg-yellow-100 rounded-lg">
                <TrendingUp className="h-6 w-6 text-yellow-600" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">Tipos de Acción</p>
                <p className="text-2xl font-bold text-gray-900">
                  {Object.keys(stats.actions_by_type).length}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Distribución por tipo de acción */}
      {stats && Object.keys(stats.actions_by_type).length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-medium text-gray-900 mb-4">
            Distribución por Tipo de Acción
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            {Object.entries(stats.actions_by_type).map(([type, count]) => (
              <div key={type} className="text-center">
                <Badge className={getActionTypeBadgeColor(type as ActionType)}>
                  {getActionTypeLabel(type as ActionType)}
                </Badge>
                <p className="mt-2 text-2xl font-bold text-gray-900">{count}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Filtros */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Búsqueda */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-gray-400" />
            <Input
              type="text"
              placeholder="Buscar en logs..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-10"
            />
          </div>

          {/* Filtro por tipo de acción */}
          <select
            value={filterActionType || 'all'}
            onChange={(e) => {
              const value = e.target.value
              setFilterActionType(value === 'all' ? null : (value as ActionType))
              setPage(1)
            }}
            className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">Todos los tipos de acción</option>
            <option value="create">Crear</option>
            <option value="update">Actualizar</option>
            <option value="delete">Eliminar</option>
            <option value="login">Login</option>
            <option value="logout">Logout</option>
            <option value="config_change">Cambio Config</option>
            <option value="message_sent">Mensaje Enviado</option>
            <option value="workstation_registered">Estación Registrada</option>
            <option value="ip_authorized">IP Autorizada</option>
            <option value="ip_rejected">IP Rechazada</option>
          </select>

          {/* Filtro por tipo de entidad */}
          <Input
            type="text"
            placeholder="Filtrar por tipo de entidad..."
            value={filterEntityType}
            onChange={(e) => {
              setFilterEntityType(e.target.value)
              setPage(1)
            }}
          />
        </div>
      </div>

      {/* Lista de logs */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        {filteredLogs.length === 0 ? (
          <div className="text-center py-12">
            <FileText className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-2 text-sm font-medium text-gray-900">No hay registros</h3>
            <p className="mt-1 text-sm text-gray-500">
              {searchTerm || filterActionType || filterEntityType
                ? 'No se encontraron registros con ese criterio'
                : 'Aún no hay actividad registrada'}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Fecha
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Acción
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Entidad
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    ID Entidad
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    IP
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {filteredLogs.map((log) => (
                  <tr key={log.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {formatDateWithTimezone(log.created_at, timezone)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <Badge className={getActionTypeBadgeColor(log.action_type)}>
                        {getActionTypeLabel(log.action_type)}
                      </Badge>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="text-sm text-gray-900">{log.entity_type}</span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="text-sm text-gray-500 font-mono">
                        {log.entity_id.substring(0, 8)}...
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {log.ip_address || '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Paginación */}
        {total > pageSize && (
          <div className="bg-white px-4 py-3 flex items-center justify-between border-t border-gray-200 sm:px-6">
            <div className="flex-1 flex justify-between sm:hidden">
              <Button
                variant="outline"
                onClick={() => setPage(page - 1)}
                disabled={page === 1}
              >
                Anterior
              </Button>
              <Button
                variant="outline"
                onClick={() => setPage(page + 1)}
                disabled={page * pageSize >= total}
              >
                Siguiente
              </Button>
            </div>
            <div className="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between">
              <div>
                <p className="text-sm text-gray-700">
                  Mostrando <span className="font-medium">{(page - 1) * pageSize + 1}</span> a{' '}
                  <span className="font-medium">
                    {Math.min(page * pageSize, total)}
                  </span>{' '}
                  de <span className="font-medium">{total}</span> registros
                </p>
              </div>
              <div>
                <nav className="relative z-0 inline-flex rounded-md shadow-sm -space-x-px">
                  <Button
                    variant="outline"
                    onClick={() => setPage(page - 1)}
                    disabled={page === 1}
                  >
                    Anterior
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => setPage(page + 1)}
                    disabled={page * pageSize >= total}
                    className="ml-2"
                  >
                    Siguiente
                  </Button>
                </nav>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
