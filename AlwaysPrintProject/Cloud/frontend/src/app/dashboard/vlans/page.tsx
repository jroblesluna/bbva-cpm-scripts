/**
 * Página de gestión de VLANs (segmentos de red).
 * 
 * Permite a los administradores y operadores:
 * - Ver lista de VLANs de su organización
 * - Crear nuevas VLANs con rangos CIDR
 * - Editar VLANs existentes
 * - Eliminar VLANs
 * - Ver workstations por VLAN
 */

'use client'

import { useState, useEffect } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  Network,
  Plus,
  Search,
  Edit,
  Trash2,
  Monitor,
  X,
} from 'lucide-react'
import type { VLAN, VLANCreate, VLANUpdate, VLANDetail } from '@/types/vlan'
import { formatDateWithTimezone } from '@/lib/dateUtils'
import { useUserTimezone } from '@/hooks/useUserTimezone'

export default function VLANsPage() {
  const { user, getAuthHeaders } = useAuth()
  const { timezone } = useUserTimezone()
  const [vlans, setVlans] = useState<VLAN[]>([])
  const [accounts, setAccounts] = useState<Array<{ id: string; name: string }>>([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [filterAccountId, setFilterAccountId] = useState<string | undefined>(undefined)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showEditModal, setShowEditModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [selectedVlan, setSelectedVlan] = useState<VLAN | null>(null)
  const [vlanDetail, setVlanDetail] = useState<VLANDetail | null>(null)

  // Cargar cuentas (solo para Admin)
  useEffect(() => {
    if (user?.role === 'admin') {
      loadAccounts()
    }
  }, [user])

  // Cargar VLANs
  useEffect(() => {
    loadVlans()
  }, [filterAccountId])

  const loadAccounts = async () => {
    try {
      const response = await fetch('http://localhost:8000/api/v1/accounts/?skip=0&limit=1000', {
        headers: getAuthHeaders(),
      })

      if (!response.ok) throw new Error('Error al cargar organizaciones')

      const data = await response.json()
      setAccounts(data.items || [])
    } catch (error) {
      console.error('Error:', error)
      alert('Error al cargar organizaciones')
    }
  }

  const loadVlans = async () => {
    try {
      setLoading(true)
      
      // Construir URL con filtro de cuenta si está seleccionado
      let url = 'http://localhost:8000/api/v1/vlans/'
      if (filterAccountId) {
        url += `?account_id=${filterAccountId}`
      }
      
      const response = await fetch(url, {
        headers: getAuthHeaders(),
      })

      if (!response.ok) throw new Error('Error al cargar VLANs')

      const data = await response.json()
      setVlans(data.vlans || [])
    } catch (error) {
      console.error('Error:', error)
      alert('Error al cargar VLANs')
    } finally {
      setLoading(false)
    }
  }

  // Filtrar VLANs por búsqueda
  const filteredVlans = vlans.filter((vlan) => {
    const searchLower = searchTerm.toLowerCase()
    return (
      vlan.name.toLowerCase().includes(searchLower) ||
      vlan.description?.toLowerCase().includes(searchLower) ||
      vlan.cidr_ranges.some((cidr) => cidr.includes(searchLower))
    )
  })

  // Abrir modal de edición
  const handleEdit = async (vlan: VLAN) => {
    try {
      // Cargar detalles de la VLAN
      const response = await fetch(`http://localhost:8000/api/v1/vlans/${vlan.id}`, {
        headers: getAuthHeaders(),
      })

      if (!response.ok) throw new Error('Error al cargar detalles')

      const detail = await response.json()
      setVlanDetail(detail)
      setSelectedVlan(vlan)
      setShowEditModal(true)
    } catch (error) {
      console.error('Error:', error)
      alert('Error al cargar detalles de la VLAN')
    }
  }

  // Abrir modal de eliminación
  const handleDelete = (vlan: VLAN) => {
    setSelectedVlan(vlan)
    setShowDeleteModal(true)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Cargando VLANs...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">VLANs</h1>
          <p className="mt-2 text-gray-600">
            Gestiona los segmentos de red de tu organización
          </p>
        </div>
        <Button onClick={() => setShowCreateModal(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Crear VLAN
        </Button>
      </div>

      {/* Estadísticas */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center">
            <div className="p-3 bg-blue-100 rounded-lg">
              <Network className="h-6 w-6 text-blue-600" />
            </div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-600">Total VLANs</p>
              <p className="text-2xl font-bold text-gray-900">{vlans.length}</p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center">
            <div className="p-3 bg-green-100 rounded-lg">
              <Monitor className="h-6 w-6 text-green-600" />
            </div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-600">Estaciones</p>
              <p className="text-2xl font-bold text-gray-900">
                {vlans.reduce((acc, v) => acc + (v as any).workstation_count || 0, 0)}
              </p>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center">
            <div className="p-3 bg-purple-100 rounded-lg">
              <Network className="h-6 w-6 text-purple-600" />
            </div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-600">Rangos CIDR</p>
              <p className="text-2xl font-bold text-gray-900">
                {vlans.reduce((acc, v) => acc + v.cidr_ranges.length, 0)}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Filtros */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Búsqueda */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-gray-400" />
            <Input
              type="text"
              placeholder="Buscar por nombre, descripción o CIDR..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-10"
            />
          </div>

          {/* Filtro por cuenta (solo para Admin) */}
          {user?.role === 'admin' && (
            <div>
              <select
                value={filterAccountId || 'all'}
                onChange={(e) => {
                  const value = e.target.value
                  setFilterAccountId(value === 'all' ? undefined : value)
                }}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="all">Todas las organizaciones</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {/* Botón para limpiar filtros */}
        {(searchTerm || filterAccountId) && (
          <div className="mt-4">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setSearchTerm('')
                setFilterAccountId(undefined)
              }}
            >
              <X className="mr-2 h-4 w-4" />
              Limpiar filtros
            </Button>
          </div>
        )}
      </div>

      {/* Lista de VLANs */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        {filteredVlans.length === 0 ? (
          <div className="text-center py-12">
            <Network className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-2 text-sm font-medium text-gray-900">No hay VLANs</h3>
            <p className="mt-1 text-sm text-gray-500">
              {searchTerm ? 'No se encontraron VLANs con ese criterio' : 'Comienza creando una nueva VLAN'}
            </p>
            {!searchTerm && (
              <div className="mt-6">
                <Button onClick={() => setShowCreateModal(true)}>
                  <Plus className="mr-2 h-4 w-4" />
                  Crear VLAN
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
                    Nombre
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Descripción
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Rangos CIDR
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Creado
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Acciones
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {filteredVlans.map((vlan) => (
                  <tr key={vlan.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        <Network className="h-5 w-5 text-gray-400 mr-2" />
                        <span className="text-sm font-medium text-gray-900">{vlan.name}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-sm text-gray-500">
                        {vlan.description || '-'}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex flex-wrap gap-1">
                        {vlan.cidr_ranges.map((cidr, idx) => (
                          <Badge key={idx} variant="secondary">
                            {cidr}
                          </Badge>
                        ))}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {formatDateWithTimezone(vlan.created_at, timezone)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleEdit(vlan)}
                      >
                        <Edit className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDelete(vlan)}
                        className="text-red-600 hover:text-red-700"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modal de Crear */}
      {showCreateModal && (
        <CreateVLANModal
          onClose={() => setShowCreateModal(false)}
          onSuccess={() => {
            setShowCreateModal(false)
            loadVlans()
          }}
        />
      )}

      {/* Modal de Editar */}
      {showEditModal && selectedVlan && vlanDetail && (
        <EditVLANModal
          vlan={selectedVlan}
          detail={vlanDetail}
          onClose={() => {
            setShowEditModal(false)
            setSelectedVlan(null)
            setVlanDetail(null)
          }}
          onSuccess={() => {
            setShowEditModal(false)
            setSelectedVlan(null)
            setVlanDetail(null)
            loadVlans()
          }}
        />
      )}

      {/* Modal de Eliminar */}
      {showDeleteModal && selectedVlan && (
        <DeleteVLANModal
          vlan={selectedVlan}
          onClose={() => {
            setShowDeleteModal(false)
            setSelectedVlan(null)
          }}
          onSuccess={() => {
            setShowDeleteModal(false)
            setSelectedVlan(null)
            loadVlans()
          }}
        />
      )}
    </div>
  )
}

// Modal de Crear VLAN
function CreateVLANModal({
  onClose,
  onSuccess,
}: {
  onClose: () => void
  onSuccess: () => void
}) {
  const { getAuthHeaders, user, isAdmin } = useAuth()
  const [loading, setLoading] = useState(false)
  const [accounts, setAccounts] = useState<Array<{ id: string; name: string }>>([])
  const [formData, setFormData] = useState<VLANCreate>({
    account_id: user?.account_id || '',
    name: '',
    description: '',
    cidr_ranges: [''],
  })

  // Cargar organizaciones (solo para admin)
  useEffect(() => {
    if (!isAdmin()) return

    const loadAccounts = async () => {
      try {
        const response = await fetch('http://localhost:8000/api/v1/accounts/', {
          headers: getAuthHeaders(),
        })
        if (response.ok) {
          const data = await response.json()
          // El backend retorna { items, total, skip, limit }
          setAccounts(data.items || [])
        }
      } catch (error) {
        console.error('Error al cargar organizaciones:', error)
      }
    }

    loadAccounts()
  }, [isAdmin, getAuthHeaders])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    // Validar
    if (!formData.name.trim()) {
      alert('El nombre es requerido')
      return
    }

    if (!formData.account_id) {
      alert('Debe seleccionar una organización')
      return
    }

    const validCidrs = formData.cidr_ranges.filter((c) => c.trim())
    if (validCidrs.length === 0) {
      alert('Debe agregar al menos un rango CIDR')
      return
    }

    try {
      setLoading(true)

      const response = await fetch('http://localhost:8000/api/v1/vlans/', {
        method: 'POST',
        headers: {
          ...getAuthHeaders(),
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          ...formData,
          cidr_ranges: validCidrs,
        }),
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Error al crear VLAN')
      }

      onSuccess()
    } catch (error: any) {
      console.error('Error:', error)
      alert(error.message || 'Error al crear VLAN')
    } finally {
      setLoading(false)
    }
  }

  const addCidrField = () => {
    setFormData({
      ...formData,
      cidr_ranges: [...formData.cidr_ranges, ''],
    })
  }

  const removeCidrField = (index: number) => {
    setFormData({
      ...formData,
      cidr_ranges: formData.cidr_ranges.filter((_, i) => i !== index),
    })
  }

  const updateCidrField = (index: number, value: string) => {
    const newCidrs = [...formData.cidr_ranges]
    newCidrs[index] = value
    setFormData({ ...formData, cidr_ranges: newCidrs })
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="p-6">
          <h2 className="text-2xl font-bold text-gray-900 mb-4">Crear VLAN</h2>

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Organización (solo para admin) */}
            {isAdmin() && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Organización *
                </label>
                <select
                  value={formData.account_id || ''}
                  onChange={(e) => setFormData({ ...formData, account_id: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  required
                >
                  <option value="">-- Seleccionar Organización --</option>
                  {accounts.map((account) => (
                    <option key={account.id} value={account.id}>
                      {account.name}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Nombre */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Nombre *
              </label>
              <Input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                placeholder="Ej: VLAN Oficina Principal"
                required
              />
            </div>

            {/* Descripción */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Descripción
              </label>
              <textarea
                value={formData.description || ''}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                placeholder="Descripción opcional de la VLAN"
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                rows={3}
              />
            </div>

            {/* Rangos CIDR */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Rangos CIDR *
              </label>
              <div className="space-y-2">
                {formData.cidr_ranges.map((cidr, index) => (
                  <div key={index} className="flex gap-2">
                    <Input
                      type="text"
                      value={cidr}
                      onChange={(e) => updateCidrField(index, e.target.value)}
                      placeholder="Ej: 192.168.1.0/24"
                      className="flex-1"
                    />
                    {formData.cidr_ranges.length > 1 && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => removeCidrField(index)}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    )}
                  </div>
                ))}
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={addCidrField}
                className="mt-2"
              >
                <Plus className="mr-2 h-4 w-4" />
                Agregar rango
              </Button>
              <p className="mt-1 text-xs text-gray-500">
                Formato: dirección/máscara (ej: 192.168.1.0/24, 10.0.0.0/16)
              </p>
            </div>

            {/* Botones */}
            <div className="flex justify-end gap-3 pt-4">
              <Button type="button" variant="outline" onClick={onClose} disabled={loading}>
                Cancelar
              </Button>
              <Button type="submit" disabled={loading}>
                {loading ? 'Creando...' : 'Crear VLAN'}
              </Button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

// Modal de Editar VLAN
function EditVLANModal({
  vlan,
  detail,
  onClose,
  onSuccess,
}: {
  vlan: VLAN
  detail: VLANDetail
  onClose: () => void
  onSuccess: () => void
}) {
  const { getAuthHeaders } = useAuth()
  const [loading, setLoading] = useState(false)
  const [formData, setFormData] = useState<VLANUpdate>({
    name: vlan.name,
    description: vlan.description,
    cidr_ranges: [...vlan.cidr_ranges],
  })

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    // Validar
    if (!formData.name?.trim()) {
      alert('El nombre es requerido')
      return
    }

    const validCidrs = formData.cidr_ranges?.filter((c) => c.trim()) || []
    if (validCidrs.length === 0) {
      alert('Debe agregar al menos un rango CIDR')
      return
    }

    try {
      setLoading(true)

      const response = await fetch(`http://localhost:8000/api/v1/vlans/${vlan.id}`, {
        method: 'PUT',
        headers: {
          ...getAuthHeaders(),
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          ...formData,
          cidr_ranges: validCidrs,
        }),
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Error al actualizar VLAN')
      }

      onSuccess()
    } catch (error: any) {
      console.error('Error:', error)
      alert(error.message || 'Error al actualizar VLAN')
    } finally {
      setLoading(false)
    }
  }

  const addCidrField = () => {
    setFormData({
      ...formData,
      cidr_ranges: [...(formData.cidr_ranges || []), ''],
    })
  }

  const removeCidrField = (index: number) => {
    setFormData({
      ...formData,
      cidr_ranges: formData.cidr_ranges?.filter((_, i) => i !== index) || [],
    })
  }

  const updateCidrField = (index: number, value: string) => {
    const newCidrs = [...(formData.cidr_ranges || [])]
    newCidrs[index] = value
    setFormData({ ...formData, cidr_ranges: newCidrs })
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="p-6">
          <h2 className="text-2xl font-bold text-gray-900 mb-4">Editar VLAN</h2>

          {/* Info de workstations */}
          {detail.workstation_count > 0 && (
            <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-md">
              <p className="text-sm text-blue-800">
                <Monitor className="inline h-4 w-4 mr-1" />
                Esta VLAN tiene {detail.workstation_count} estación(es) asignada(s)
              </p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Nombre */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Nombre *
              </label>
              <Input
                type="text"
                value={formData.name || ''}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                placeholder="Ej: VLAN Oficina Principal"
                required
              />
            </div>

            {/* Descripción */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Descripción
              </label>
              <textarea
                value={formData.description || ''}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                placeholder="Descripción opcional de la VLAN"
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                rows={3}
              />
            </div>

            {/* Rangos CIDR */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Rangos CIDR *
              </label>
              <div className="space-y-2">
                {(formData.cidr_ranges || []).map((cidr, index) => (
                  <div key={index} className="flex gap-2">
                    <Input
                      type="text"
                      value={cidr}
                      onChange={(e) => updateCidrField(index, e.target.value)}
                      placeholder="Ej: 192.168.1.0/24"
                      className="flex-1"
                    />
                    {(formData.cidr_ranges?.length || 0) > 1 && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => removeCidrField(index)}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    )}
                  </div>
                ))}
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={addCidrField}
                className="mt-2"
              >
                <Plus className="mr-2 h-4 w-4" />
                Agregar rango
              </Button>
            </div>

            {/* Botones */}
            <div className="flex justify-end gap-3 pt-4">
              <Button type="button" variant="outline" onClick={onClose} disabled={loading}>
                Cancelar
              </Button>
              <Button type="submit" disabled={loading}>
                {loading ? 'Actualizando...' : 'Actualizar'}
              </Button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

// Modal de Eliminar VLAN
function DeleteVLANModal({
  vlan,
  onClose,
  onSuccess,
}: {
  vlan: VLAN
  onClose: () => void
  onSuccess: () => void
}) {
  const { getAuthHeaders } = useAuth()
  const [loading, setLoading] = useState(false)

  const handleDelete = async () => {
    try {
      setLoading(true)

      const response = await fetch(`http://localhost:8000/api/v1/vlans/${vlan.id}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Error al eliminar VLAN')
      }

      onSuccess()
    } catch (error: any) {
      console.error('Error:', error)
      alert(error.message || 'Error al eliminar VLAN')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
        <div className="p-6">
          <h2 className="text-xl font-bold text-gray-900 mb-4">Eliminar VLAN</h2>

          <p className="text-gray-600 mb-6">
            ¿Estás seguro de que deseas eliminar la VLAN <strong>{vlan.name}</strong>?
            Esta acción no se puede deshacer.
          </p>

          <div className="flex justify-end gap-3">
            <Button variant="outline" onClick={onClose} disabled={loading}>
              Cancelar
            </Button>
            <Button
              onClick={handleDelete}
              disabled={loading}
              className="bg-red-600 hover:bg-red-700"
            >
              {loading ? 'Eliminando...' : 'Eliminar'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
