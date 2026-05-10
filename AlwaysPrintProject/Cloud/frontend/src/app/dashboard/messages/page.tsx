/**
 * Página de gestión de mensajes a workstations.
 * 
 * Permite enviar mensajes a:
 * - Workstation específica
 * - Todas las workstations de una VLAN
 * - Todas las workstations de la organización
 */

'use client'

import { useState, useEffect } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  MessageSquare,
  Plus,
  Search,
  Send,
  CheckCircle,
  Clock,
  Filter,
} from 'lucide-react'
import type { Message, MessageCreate, MessageStats, TargetType } from '@/types/message'
import type { Workstation } from '@/types/workstation'
import type { VLAN } from '@/types/vlan'
import { formatDateWithTimezone } from '@/lib/dateUtils'
import { useUserTimezone } from '@/hooks/useUserTimezone'

export default function MessagesPage() {
  const { user, getAuthHeaders } = useAuth()
  const timezone = useUserTimezone()
  const [messages, setMessages] = useState<Message[]>([])
  const [stats, setStats] = useState<MessageStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [filterDelivered, setFilterDelivered] = useState<boolean | null>(null)
  const [filterTargetType, setFilterTargetType] = useState<TargetType | null>(null)
  const [showSendModal, setShowSendModal] = useState(false)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const pageSize = 50

  // Cargar mensajes y estadísticas
  useEffect(() => {
    loadMessages()
    loadStats()
  }, [page, filterDelivered, filterTargetType])

  const loadMessages = async () => {
    try {
      setLoading(true)

      const params = new URLSearchParams({
        page: page.toString(),
        page_size: pageSize.toString(),
      })

      if (filterDelivered !== null) {
        params.append('is_delivered', filterDelivered.toString())
      }

      if (filterTargetType) {
        params.append('target_type', filterTargetType)
      }

      const response = await fetch(
        `http://localhost:8000/api/v1/messages/?${params.toString()}`,
        {
          headers: getAuthHeaders(),
        }
      )

      if (!response.ok) throw new Error('Error al cargar mensajes')

      const data = await response.json()
      setMessages(data.messages || [])
      setTotal(data.total || 0)
    } catch (error) {
      console.error('Error:', error)
      alert('Error al cargar mensajes')
    } finally {
      setLoading(false)
    }
  }

  const loadStats = async () => {
    try {
      const response = await fetch('http://localhost:8000/api/v1/messages/stats', {
        headers: getAuthHeaders(),
      })

      if (!response.ok) throw new Error('Error al cargar estadísticas')

      const data = await response.json()
      setStats(data)
    } catch (error) {
      console.error('Error:', error)
    }
  }

  // Filtrar mensajes por búsqueda
  const filteredMessages = messages.filter((message) => {
    const searchLower = searchTerm.toLowerCase()
    return message.content.toLowerCase().includes(searchLower)
  })

  const getTargetTypeLabel = (type: TargetType): string => {
    switch (type) {
      case 'workstation':
        return 'Estación'
      case 'vlan':
        return 'VLAN'
      case 'account':
        return 'Organización'
      default:
        return type
    }
  }

  const getTargetTypeBadgeColor = (type: TargetType): string => {
    switch (type) {
      case 'workstation':
        return 'bg-blue-100 text-blue-800'
      case 'vlan':
        return 'bg-purple-100 text-purple-800'
      case 'account':
        return 'bg-green-100 text-green-800'
      default:
        return 'bg-gray-100 text-gray-800'
    }
  }

  if (loading && page === 1) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Cargando mensajes...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Mensajes</h1>
          <p className="mt-2 text-gray-600">
            Envía mensajes a workstations, VLANs o toda la organización
          </p>
        </div>
        <Button onClick={() => setShowSendModal(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Enviar Mensaje
        </Button>
      </div>

      {/* Estadísticas */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="p-3 bg-blue-100 rounded-lg">
                <Send className="h-6 w-6 text-blue-600" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">Total Enviados</p>
                <p className="text-2xl font-bold text-gray-900">{stats.total_sent}</p>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="p-3 bg-green-100 rounded-lg">
                <CheckCircle className="h-6 w-6 text-green-600" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">Entregados</p>
                <p className="text-2xl font-bold text-gray-900">{stats.total_delivered}</p>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="p-3 bg-yellow-100 rounded-lg">
                <Clock className="h-6 w-6 text-yellow-600" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">Pendientes</p>
                <p className="text-2xl font-bold text-gray-900">{stats.total_pending}</p>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="p-3 bg-purple-100 rounded-lg">
                <MessageSquare className="h-6 w-6 text-purple-600" />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">Tasa de Entrega</p>
                <p className="text-2xl font-bold text-gray-900">
                  {stats.delivery_rate.toFixed(1)}%
                </p>
              </div>
            </div>
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
              placeholder="Buscar en contenido..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-10"
            />
          </div>

          {/* Filtro por estado */}
          <select
            value={filterDelivered === null ? 'all' : filterDelivered.toString()}
            onChange={(e) => {
              const value = e.target.value
              setFilterDelivered(value === 'all' ? null : value === 'true')
              setPage(1)
            }}
            className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">Todos los estados</option>
            <option value="true">Entregados</option>
            <option value="false">Pendientes</option>
          </select>

          {/* Filtro por tipo */}
          <select
            value={filterTargetType || 'all'}
            onChange={(e) => {
              const value = e.target.value
              setFilterTargetType(value === 'all' ? null : (value as TargetType))
              setPage(1)
            }}
            className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">Todos los tipos</option>
            <option value="workstation">Estación</option>
            <option value="vlan">VLAN</option>
            <option value="account">Organización</option>
          </select>
        </div>
      </div>

      {/* Lista de mensajes */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        {filteredMessages.length === 0 ? (
          <div className="text-center py-12">
            <MessageSquare className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-2 text-sm font-medium text-gray-900">No hay mensajes</h3>
            <p className="mt-1 text-sm text-gray-500">
              {searchTerm
                ? 'No se encontraron mensajes con ese criterio'
                : 'Comienza enviando un mensaje a tus workstations'}
            </p>
            {!searchTerm && (
              <div className="mt-6">
                <Button onClick={() => setShowSendModal(true)}>
                  <Plus className="mr-2 h-4 w-4" />
                  Enviar Mensaje
                </Button>
              </div>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Tipo
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Contenido
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Estado
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Enviado
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Entregado
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {filteredMessages.map((message) => (
                  <tr key={message.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <Badge className={getTargetTypeBadgeColor(message.target_type)}>
                        {getTargetTypeLabel(message.target_type)}
                      </Badge>
                    </td>
                    <td className="px-6 py-4">
                      <p className="text-sm text-gray-900 line-clamp-2">{message.content}</p>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {message.is_delivered ? (
                        <Badge className="bg-green-100 text-green-800">
                          <CheckCircle className="mr-1 h-3 w-3" />
                          Entregado
                        </Badge>
                      ) : (
                        <Badge className="bg-yellow-100 text-yellow-800">
                          <Clock className="mr-1 h-3 w-3" />
                          Pendiente
                        </Badge>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {formatDateWithTimezone(message.sent_at, timezone)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {message.delivered_at
                        ? formatDateWithTimezone(message.delivered_at, timezone)
                        : '-'}
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
                  de <span className="font-medium">{total}</span> mensajes
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

      {/* Modal de Enviar */}
      {showSendModal && (
        <SendMessageModal
          onClose={() => setShowSendModal(false)}
          onSuccess={() => {
            setShowSendModal(false)
            loadMessages()
            loadStats()
          }}
        />
      )}
    </div>
  )
}

// Modal de Enviar Mensaje
function SendMessageModal({
  onClose,
  onSuccess,
}: {
  onClose: () => void
  onSuccess: () => void
}) {
  const { getAuthHeaders } = useAuth()
  const [loading, setLoading] = useState(false)
  const [targetType, setTargetType] = useState<TargetType>('account')
  const [targetId, setTargetId] = useState<string>('')
  const [content, setContent] = useState('')
  const [workstations, setWorkstations] = useState<Workstation[]>([])
  const [vlans, setVlans] = useState<VLAN[]>([])

  // Cargar workstations y VLANs
  useEffect(() => {
    loadWorkstations()
    loadVlans()
  }, [])

  const loadWorkstations = async () => {
    try {
      const response = await fetch('http://localhost:8000/api/v1/workstations/', {
        headers: getAuthHeaders(),
      })
      if (response.ok) {
        const data = await response.json()
        setWorkstations(data.items || [])
      }
    } catch (error) {
      console.error('Error al cargar workstations:', error)
    }
  }

  const loadVlans = async () => {
    try {
      const response = await fetch('http://localhost:8000/api/v1/vlans/', {
        headers: getAuthHeaders(),
      })
      if (response.ok) {
        const data = await response.json()
        setVlans(data.vlans || [])
      }
    } catch (error) {
      console.error('Error al cargar VLANs:', error)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!content.trim()) {
      alert('El contenido del mensaje es requerido')
      return
    }

    if (targetType !== 'account' && !targetId) {
      alert('Debe seleccionar un destinatario')
      return
    }

    try {
      setLoading(true)

      const messageData: MessageCreate = {
        target_type: targetType,
        target_id: targetType === 'account' ? null : targetId,
        content: content.trim(),
      }

      const response = await fetch('http://localhost:8000/api/v1/messages/', {
        method: 'POST',
        headers: {
          ...getAuthHeaders(),
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(messageData),
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Error al enviar mensaje')
      }

      onSuccess()
    } catch (error: any) {
      console.error('Error:', error)
      alert(error.message || 'Error al enviar mensaje')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="p-6">
          <h2 className="text-2xl font-bold text-gray-900 mb-4">Enviar Mensaje</h2>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Tipo de destinatario */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Enviar a *
              </label>
              <select
                value={targetType}
                onChange={(e) => {
                  setTargetType(e.target.value as TargetType)
                  setTargetId('')
                }}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="account">Toda la organización</option>
                <option value="vlan">VLAN específica</option>
                <option value="workstation">Estación específica</option>
              </select>
            </div>

            {/* Selector de VLAN */}
            {targetType === 'vlan' && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Seleccionar VLAN *
                </label>
                <select
                  value={targetId}
                  onChange={(e) => setTargetId(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  required
                >
                  <option value="">-- Seleccionar VLAN --</option>
                  {vlans.map((vlan) => (
                    <option key={vlan.id} value={vlan.id}>
                      {vlan.name}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Selector de Workstation */}
            {targetType === 'workstation' && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Seleccionar Estación *
                </label>
                <select
                  value={targetId}
                  onChange={(e) => setTargetId(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  required
                >
                  <option value="">-- Seleccionar Estación --</option>
                  {workstations.map((ws) => (
                    <option key={ws.id} value={ws.id}>
                      {ws.hostname || ws.ip_private} - {ws.current_user || 'Sin usuario'}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Contenido */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Mensaje *
              </label>
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="Escribe tu mensaje aquí..."
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                rows={6}
                maxLength={5000}
                required
              />
              <p className="mt-1 text-xs text-gray-500">
                {content.length} / 5000 caracteres
              </p>
            </div>

            {/* Botones */}
            <div className="flex justify-end gap-3 pt-4">
              <Button type="button" variant="outline" onClick={onClose} disabled={loading}>
                Cancelar
              </Button>
              <Button type="submit" disabled={loading}>
                <Send className="mr-2 h-4 w-4" />
                {loading ? 'Enviando...' : 'Enviar Mensaje'}
              </Button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
