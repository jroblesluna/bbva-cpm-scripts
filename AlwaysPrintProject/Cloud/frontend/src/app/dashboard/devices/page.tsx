/**
 * Página de gestión de dispositivos (impresoras).
 */

'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  Printer,
  Plus,
  Search,
  Edit,
  Trash2,
  X,
  CheckCircle,
  XCircle,
  Eye,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  AlertTriangle,
} from 'lucide-react'
import { apiClient } from '@/lib/api'
import { useToast } from '@/hooks/use-toast'
import type { Device, DeviceCreate, DeviceUpdate } from '@/types/device'
import type { VLAN } from '@/types/vlan'
import { formatDateWithTimezone } from '@/lib/dateUtils'
import { useUserTimezone } from '@/hooks/useUserTimezone'
import { SearchableSelect, type SearchableSelectOption } from '@/components/ui/searchable-select'

export default function DevicesPage() {
  const { user } = useAuth()
  const timezone = useUserTimezone()
  const t = useTranslations('devices')
  const tCommon = useTranslations('common')
  const [devices, setDevices] = useState<Device[]>([])
  const [accounts, setAccounts] = useState<Array<{ id: string; name: string }>>([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [filterOrgId, setFilterOrgId] = useState<string | undefined>(undefined)
  const [filterVlanId, setFilterVlanId] = useState<string | undefined>(undefined)
  const [filterActive, setFilterActive] = useState<string>('all')
  const [filterWithVlan, setFilterWithVlan] = useState(false)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showEditModal, setShowEditModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [showDetailsModal, setShowDetailsModal] = useState(false)
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null)
  const [page, setPage] = useState(1)
  const pageSize = 20
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date())
  const [refreshing, setRefreshing] = useState(false)
  const initialLoadDone = useRef(false)

  useEffect(() => {
    if (!user) return
    const silent = initialLoadDone.current
    initialLoadDone.current = true
    if (user.role === 'admin') loadAccounts()
    loadDevices(silent)
  }, [user, filterOrgId, filterVlanId, filterActive])

  const loadAccounts = async () => {
    try {
      const response = await apiClient.get('/organizations/?skip=0&limit=1000')
      setAccounts(response.data.items || [])
    } catch (error) {
      console.error('Error cargando organizaciones:', error)
    }
  }

  const loadVlanOptions = useCallback(async (params: { search: string; skip: number; limit: number }): Promise<{ options: SearchableSelectOption[]; total: number }> => {
    try {
      const queryParams: Record<string, string> = {}
      if (filterOrgId) queryParams.organization_id = filterOrgId
      if (params.search) queryParams.search = params.search
      if (params.limit > 0) {
        queryParams.skip = String(params.skip)
        queryParams.limit = String(params.limit)
      }
      const queryString = new URLSearchParams(queryParams).toString()
      const url = queryString ? `/vlans/?${queryString}` : '/vlans/'
      const response = await apiClient.get(url)
      const vlans: VLAN[] = response.data.vlans || []
      const total: number = response.data.total || 0
      return {
        options: vlans.map((v) => ({ value: v.id, label: v.name })),
        total,
      }
    } catch (error) {
      console.error('Error cargando VLANs:', error)
      return { options: [], total: 0 }
    }
  }, [filterOrgId])

  const loadDevices = async (silent = false) => {
    try {
      if (!silent) setLoading(true)
      const params: Record<string, string> = {}
      if (filterOrgId) params.organization_id = filterOrgId
      if (filterVlanId) params.vlan_id = filterVlanId
      if (filterActive !== 'all') params.is_active = filterActive
      const queryString = new URLSearchParams(params).toString()
      const url = queryString ? `/devices/?${queryString}` : '/devices/'
      const response = await apiClient.get(url)
      setDevices(response.data.devices || [])
      setLastUpdated(new Date())
    } catch (error) {
      console.error('Error cargando dispositivos:', error)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    await loadDevices()
  }

  const filteredDevices = devices.filter((device) => {
    const s = searchTerm.toLowerCase()
    const matchesSearch = (
      device.name.toLowerCase().includes(s) ||
      device.ip_address.includes(s) ||
      device.description?.toLowerCase().includes(s) ||
      device.model?.toLowerCase().includes(s) ||
      device.location?.toLowerCase().includes(s)
    )
    const matchesVlan = !filterWithVlan || !device.vlan_id
    return matchesSearch && matchesVlan
  })

  const totalFiltered = filteredDevices.length
  const totalPages = Math.ceil(totalFiltered / pageSize)
  const paginatedDevices = filteredDevices.slice((page - 1) * pageSize, page * pageSize)
  const paginationStart = (page - 1) * pageSize + 1
  const paginationEnd = Math.min(page * pageSize, totalFiltered)

  const activeCount = devices.filter((d) => d.is_active).length
  const inactiveCount = devices.filter((d) => !d.is_active).length
  const noVlanCount = devices.filter((d) => !d.vlan_id).length

  const handleEdit = (device: Device) => {
    setSelectedDevice(device)
    setShowEditModal(true)
  }

  const handleDelete = (device: Device) => {
    setSelectedDevice(device)
    setShowDeleteModal(true)
  }

  const handleViewDetails = (device: Device) => {
    setSelectedDevice(device)
    setShowDetailsModal(true)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">{tCommon('loading')}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-screen-2xl mx-auto space-y-6">
      {/* Encabezado */}
      <div className="flex flex-col gap-2 mt-2">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <h1 className="text-3xl font-bold text-gray-900">{t('title')}</h1>
          <Button onClick={() => setShowCreateModal(true)}>
            <Plus className="mr-2 h-4 w-4" />
            {t('create')}
          </Button>
        </div>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between">
          <p className="text-gray-600">{t('subtitle')}</p>
          <div className="flex items-center gap-1">
            <span className="text-xs text-gray-400">
              {tCommon('lastUpdated', { time: formatDateWithTimezone(lastUpdated, timezone) })}
            </span>
            <Button variant="ghost" size="sm" onClick={handleRefresh} disabled={refreshing} className="h-6 w-6 p-0 text-gray-400 hover:text-gray-600">
              <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </div>
      </div>

      {/* Estadísticas */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center">
            <div className="p-3 bg-blue-100 rounded-lg"><Printer className="h-6 w-6 text-blue-600" /></div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-600">{t('totalDevices')}</p>
              <p className="text-2xl font-bold text-gray-900">{devices.length}</p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center">
            <div className="p-3 bg-green-100 rounded-lg"><CheckCircle className="h-6 w-6 text-green-600" /></div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-600">{t('activeDevices')}</p>
              <p className="text-2xl font-bold text-gray-900">{activeCount}</p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center">
            <div className="p-3 bg-gray-100 rounded-lg"><XCircle className="h-6 w-6 text-gray-500" /></div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-600">{t('inactiveDevices')}</p>
              <p className="text-2xl font-bold text-gray-900">{inactiveCount}</p>
            </div>
          </div>
        </div>
        <div className={`bg-white rounded-lg shadow p-6 ${noVlanCount > 0 ? 'border border-orange-200 bg-orange-50' : ''}`}>
          <div className="flex items-center">
            <div className={`p-3 rounded-lg ${noVlanCount > 0 ? 'bg-orange-100' : 'bg-gray-100'}`}>
              <AlertTriangle className={`h-6 w-6 ${noVlanCount > 0 ? 'text-orange-600' : 'text-gray-400'}`} />
            </div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-600">{t('noVlanDevices')}</p>
              <p className="text-2xl font-bold text-gray-900">{noVlanCount}</p>
            </div>
          </div>
        </div>
      </div>

      {/* Filtros */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-gray-400" />
            <Input
              type="text"
              placeholder={t('searchPlaceholder')}
              value={searchTerm}
              onChange={(e) => { setSearchTerm(e.target.value); setPage(1) }}
              className="pl-10"
            />
          </div>
          {user?.role === 'admin' && (
            <select
              value={filterOrgId || 'all'}
              onChange={(e) => {
                setFilterOrgId(e.target.value === 'all' ? undefined : e.target.value)
                setFilterVlanId(undefined)
              }}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">{t('allOrganizations')}</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>{account.name}</option>
              ))}
            </select>
          )}
          <SearchableSelect
            value={filterVlanId}
            onChange={(val) => setFilterVlanId(val)}
            placeholder={t('allVlans')}
            loadOptions={loadVlanOptions}
            searchPlaceholder={t('searchVlanPlaceholder')}
            searchButtonTitle={t('searchVlanBtn')}
            prevLabel={tCommon('previous')}
            nextLabel={tCommon('next')}
            pageSize={5}
            className="w-full"
          />
          <select
            value={filterActive}
            onChange={(e) => setFilterActive(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">{t('allStatuses')}</option>
            <option value="true">{t('statusActive')}</option>
            <option value="false">{t('statusInactive')}</option>
          </select>
        </div>
        <div className="flex items-center justify-between mt-4">
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={filterWithVlan}
              onChange={(e) => { setFilterWithVlan(e.target.checked); setPage(1) }}
              className="w-4 h-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            <span className="text-sm text-gray-700">{t('filterWithVlan')}</span>
          </label>
          {(searchTerm || filterOrgId || filterVlanId || filterActive !== 'all' || filterWithVlan) && (
            <Button variant="outline" size="sm" onClick={() => { setSearchTerm(''); setFilterOrgId(undefined); setFilterVlanId(undefined); setFilterActive('all'); setFilterWithVlan(false); setPage(1) }}>
              <X className="mr-2 h-4 w-4" />
              {tCommon('clearFilters')}
            </Button>
          )}
        </div>
      </div>

      {/* Tabla de dispositivos */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        {filteredDevices.length === 0 ? (
          <div className="text-center py-12">
            <Printer className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-2 text-sm font-medium text-gray-900">{t('emptyTitle')}</h3>
            <p className="mt-1 text-sm text-gray-500">
              {searchTerm || filterOrgId || filterVlanId || filterActive !== 'all' ? t('emptyMessage') : t('emptyCreate')}
            </p>
            {!searchTerm && !filterOrgId && !filterVlanId && filterActive === 'all' && (
              <div className="mt-6">
                <Button onClick={() => setShowCreateModal(true)}>
                  <Plus className="mr-2 h-4 w-4" />
                  {t('create')}
                </Button>
              </div>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colName')}</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colIp')}</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colModel')}</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colVlan')}</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colLocation')}</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colStatus')}</th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colActions')}</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {paginatedDevices.map((device) => (
                  <tr key={device.id} className={`hover:bg-gray-50 ${!device.vlan_id ? 'bg-orange-50 border-l-4 border-l-orange-400' : ''}`}>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        <Printer className={`h-5 w-5 mr-2 ${!device.vlan_id ? 'text-orange-500' : 'text-gray-400'}`} />
                        <div>
                          <span className="text-sm font-medium text-gray-900">{device.name}</span>
                          {device.description && (
                            <p className="text-xs text-gray-500">{device.description}</p>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="text-sm font-mono text-gray-700">{device.ip_address}:{device.port}</span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="text-sm text-gray-500">{device.model || '-'}</span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {device.vlan_name ? (
                        <Badge variant="secondary">{device.vlan_name}</Badge>
                      ) : (
                        <Badge variant="outline" className="border-orange-300 text-orange-700 bg-orange-50">
                          <AlertTriangle className="w-3 h-3 mr-1" />
                          {t('noVlan')}
                        </Badge>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="text-sm text-gray-500">{device.location || '-'}</span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <Badge variant={device.is_active ? 'default' : 'secondary'}>
                        {device.is_active ? t('statusActive') : t('statusInactive')}
                      </Badge>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <Button variant="ghost" size="sm" onClick={() => handleViewDetails(device)} title={t('viewDetails')}>
                        <Eye className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => handleEdit(device)}>
                        <Edit className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => handleDelete(device)} className="text-red-600 hover:text-red-700">
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

      {/* Paginación */}
      {totalFiltered > 0 && totalPages > 1 && (
        <div className="bg-white rounded-lg shadow px-4 py-3 flex items-center justify-between border border-gray-200 sm:px-6">
          <div className="flex-1 flex items-center justify-between">
            <p className="text-sm text-gray-700">
              {t('pagination', { start: paginationStart, end: paginationEnd, total: totalFiltered })}
            </p>
            <div className="flex items-center gap-2">
              {page > 1 && (
                <Button variant="outline" size="sm" onClick={() => setPage(1)}>
                  {tCommon('first')}
                </Button>
              )}
              <Button variant="outline" size="sm" onClick={() => setPage(page - 1)} disabled={page <= 1}>
                <ChevronLeft className="h-4 w-4 mr-1" />
                {tCommon('previous')}
              </Button>
              <span className="text-sm text-gray-600 px-2">
                {t('pageNumber', { page })}
              </span>
              <Button variant="outline" size="sm" onClick={() => setPage(page + 1)} disabled={page >= totalPages}>
                {tCommon('next')}
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Modales */}
      {showDetailsModal && selectedDevice && (
        <DeviceDetailsModal
          device={selectedDevice}
          onClose={() => { setShowDetailsModal(false); setSelectedDevice(null) }}
        />
      )}
      {showCreateModal && (
        <CreateDeviceModal
          onClose={() => setShowCreateModal(false)}
          onSuccess={() => { setShowCreateModal(false); loadDevices() }}
        />
      )}
      {showEditModal && selectedDevice && (
        <EditDeviceModal
          device={selectedDevice}
          onClose={() => { setShowEditModal(false); setSelectedDevice(null) }}
          onSuccess={() => { setShowEditModal(false); setSelectedDevice(null); loadDevices() }}
        />
      )}
      {showDeleteModal && selectedDevice && (
        <DeleteDeviceModal
          device={selectedDevice}
          onClose={() => { setShowDeleteModal(false); setSelectedDevice(null) }}
          onSuccess={() => { setShowDeleteModal(false); setSelectedDevice(null); loadDevices() }}
        />
      )}
    </div>
  )
}


// === MODAL: CREAR DISPOSITIVO ===

function isValidIP(ip: string): boolean {
  const trimmed = ip.trim()
  if (!trimmed) return false
  // IPv4
  const ipv4Regex = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/
  const ipv4Match = trimmed.match(ipv4Regex)
  if (ipv4Match) {
    return ipv4Match.slice(1).every(octet => {
      const num = parseInt(octet, 10)
      return num >= 0 && num <= 255
    })
  }
  // IPv6 (simplificada: acepta formato válido con grupos hex separados por :)
  const ipv6Regex = /^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$/
  return ipv6Regex.test(trimmed)
}

function CreateDeviceModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const { user, isAdmin } = useAuth()
  const t = useTranslations('devices')
  const tCommon = useTranslations('common')
  const { toast } = useToast()
  const [loading, setLoading] = useState(false)
  const [accounts, setAccounts] = useState<Array<{ id: string; name: string }>>([])
  const [vlans, setVlans] = useState<VLAN[]>([])
  const [ipError, setIpError] = useState('')
  const [formData, setFormData] = useState<DeviceCreate>({
    organization_id: user?.organization_id || '',
    vlan_id: null,
    name: '',
    ip_address: '',
    description: '',
    model: '',
    location: '',
    port: 9100,
    is_active: true,
  })

  useEffect(() => {
    if (!isAdmin()) return
    const load = async () => {
      try {
        const response = await apiClient.get('/organizations/')
        setAccounts(response.data.items || [])
      } catch (error) { console.error(error) }
    }
    load()
  }, [isAdmin])

  useEffect(() => {
    const orgId = formData.organization_id
    if (!orgId) { setVlans([]); return }
    const load = async () => {
      try {
        const response = await apiClient.get(`/vlans/?organization_id=${orgId}`)
        setVlans(response.data.vlans || [])
      } catch (error) { console.error(error) }
    }
    load()
  }, [formData.organization_id])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!formData.name.trim() || !formData.ip_address.trim()) return

    if (!isValidIP(formData.ip_address)) {
      setIpError(t('ipInvalid'))
      return
    }
    setIpError('')

    try {
      setLoading(true)
      const payload = {
        ...formData,
        vlan_id: formData.vlan_id || undefined,
      }
      await apiClient.post('/devices/', payload)
      onSuccess()
    } catch (error: unknown) {
      const err = error as { status?: number; detail?: string | { code?: string; ip?: string; vlan_name?: string | null } }
      if (err.status === 409 && typeof err.detail === 'object' && err.detail?.code === 'IP_DUPLICATE') {
        const vlanName = err.detail.vlan_name
        toast({
          variant: 'warning',
          title: t('ipDuplicateTitle'),
          description: vlanName
            ? t('ipDuplicateWithVlan', { ip: formData.ip_address, vlan: vlanName })
            : t('ipDuplicateNoVlan', { ip: formData.ip_address }),
        })
      } else {
        toast({
          variant: 'destructive',
          title: tCommon('error'),
          description: (typeof err.detail === 'string' ? err.detail : null) || t('createError'),
        })
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4 !mt-0">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto overflow-x-hidden">
        <div className="p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-2xl font-bold text-gray-900">{t('createTitle')}</h2>
            <Button type="button" variant="ghost" size="sm" onClick={onClose} className="h-8 w-8 p-0">
              <X className="h-5 w-5" />
            </Button>
          </div>
          <form onSubmit={handleSubmit} className="space-y-4">
            {isAdmin() && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('organization')}</label>
                <select
                  value={formData.organization_id || ''}
                  onChange={(e) => setFormData({ ...formData, organization_id: e.target.value, vlan_id: null })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  required
                >
                  <option value="">{t('selectOrg')}</option>
                  {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              </div>
            )}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('vlanLabel')} *</label>
              <select
                value={formData.vlan_id || ''}
                onChange={(e) => setFormData({ ...formData, vlan_id: e.target.value || null })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                required
              >
                <option value="">{t('selectVlan')}</option>
                {vlans.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
              </select>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('nameLabel')}</label>
                <input
                  type="text"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder={t('namePlaceholder')}
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('ipLabel')}</label>
                <input
                  type="text"
                  value={formData.ip_address}
                  onChange={(e) => {
                    setFormData({ ...formData, ip_address: e.target.value })
                    if (ipError) setIpError('')
                  }}
                  onBlur={() => {
                    if (formData.ip_address.trim() && !isValidIP(formData.ip_address)) {
                      setIpError(t('ipInvalid'))
                    }
                  }}
                  placeholder={t('ipPlaceholder')}
                  required
                  className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 ${ipError ? 'border-red-500' : 'border-gray-300'}`}
                />
                {ipError && <p className="mt-1 text-xs text-red-600">{ipError}</p>}
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('descriptionLabel')}</label>
              <textarea
                value={formData.description || ''}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                placeholder={t('descPlaceholder')}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                rows={2}
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('modelLabel')}</label>
                <input
                  type="text"
                  value={formData.model || ''}
                  onChange={(e) => setFormData({ ...formData, model: e.target.value })}
                  placeholder={t('modelPlaceholder')}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('locationLabel')}</label>
                <input
                  type="text"
                  value={formData.location || ''}
                  onChange={(e) => setFormData({ ...formData, location: e.target.value })}
                  placeholder={t('locationPlaceholder')}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('portLabel')}</label>
                <input
                  type="number"
                  value={formData.port || 9100}
                  onChange={(e) => setFormData({ ...formData, port: parseInt(e.target.value) || 9100 })}
                  min={1}
                  max={65535}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="mt-1 text-xs text-gray-500">{t('portHelper')}</p>
              </div>
            </div>
            <div className="flex items-center">
              <input
                type="checkbox"
                id="is_active"
                checked={formData.is_active}
                onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                className="rounded mr-2"
              />
              <label htmlFor="is_active" className="text-sm text-gray-700">{t('activeLabel')}</label>
            </div>
            <div className="flex justify-end gap-3 pt-4">
              <Button type="button" variant="outline" onClick={onClose} disabled={loading}>{tCommon('cancel')}</Button>
              <Button
                type="submit"
                disabled={loading || !formData.name.trim() || !formData.ip_address.trim() || !formData.vlan_id || (isAdmin() && !formData.organization_id)}
              >
                {loading ? tCommon('creating') : t('createTitle')}
              </Button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

// === MODAL: EDITAR DISPOSITIVO ===

function EditDeviceModal({ device, onClose, onSuccess }: { device: Device; onClose: () => void; onSuccess: () => void }) {
  const t = useTranslations('devices')
  const tCommon = useTranslations('common')
  const [loading, setLoading] = useState(false)
  const [vlans, setVlans] = useState<VLAN[]>([])
  const [ipError, setIpError] = useState('')
  const [formData, setFormData] = useState<DeviceUpdate>({
    vlan_id: device.vlan_id,
    name: device.name,
    ip_address: device.ip_address,
    description: device.description,
    model: device.model,
    location: device.location,
    port: device.port,
    is_active: device.is_active,
  })

  useEffect(() => {
    const load = async () => {
      try {
        const response = await apiClient.get(`/vlans/?organization_id=${device.organization_id}`)
        setVlans(response.data.vlans || [])
      } catch (error) { console.error(error) }
    }
    load()
  }, [device.organization_id])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!formData.name?.trim() || !formData.ip_address?.trim()) return

    if (!isValidIP(formData.ip_address)) {
      setIpError(t('ipInvalid'))
      return
    }
    setIpError('')

    try {
      setLoading(true)
      await apiClient.put(`/devices/${device.id}`, formData)
      onSuccess()
    } catch (error: unknown) {
      console.error('Error:', error)
      const err = error as { response?: { data?: { detail?: string } } }
      alert(err.response?.data?.detail || 'Error al actualizar dispositivo')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4 !mt-0">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto overflow-x-hidden">
        <div className="p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-2xl font-bold text-gray-900">{t('editTitle')}</h2>
            <Button type="button" variant="ghost" size="sm" onClick={onClose} className="h-8 w-8 p-0">
              <X className="h-5 w-5" />
            </Button>
          </div>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('vlanLabel')}</label>
              <select
                value={formData.vlan_id || ''}
                onChange={(e) => setFormData({ ...formData, vlan_id: e.target.value || null })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">{t('selectVlan')}</option>
                {vlans.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
              </select>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('nameLabel')}</label>
                <input
                  type="text"
                  value={formData.name || ''}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder={t('namePlaceholder')}
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('ipLabel')}</label>
                <input
                  type="text"
                  value={formData.ip_address || ''}
                  onChange={(e) => {
                    setFormData({ ...formData, ip_address: e.target.value })
                    if (ipError) setIpError('')
                  }}
                  onBlur={() => {
                    if (formData.ip_address?.trim() && !isValidIP(formData.ip_address)) {
                      setIpError(t('ipInvalid'))
                    }
                  }}
                  placeholder={t('ipPlaceholder')}
                  required
                  className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 ${ipError ? 'border-red-500' : 'border-gray-300'}`}
                />
                {ipError && <p className="mt-1 text-xs text-red-600">{ipError}</p>}
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('descriptionLabel')}</label>
              <textarea
                value={formData.description || ''}
                onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                placeholder={t('descPlaceholder')}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                rows={2}
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('modelLabel')}</label>
                <input
                  type="text"
                  value={formData.model || ''}
                  onChange={(e) => setFormData({ ...formData, model: e.target.value })}
                  placeholder={t('modelPlaceholder')}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('locationLabel')}</label>
                <input
                  type="text"
                  value={formData.location || ''}
                  onChange={(e) => setFormData({ ...formData, location: e.target.value })}
                  placeholder={t('locationPlaceholder')}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('portLabel')}</label>
                <input
                  type="number"
                  value={formData.port || 9100}
                  onChange={(e) => setFormData({ ...formData, port: parseInt(e.target.value) || 9100 })}
                  min={1}
                  max={65535}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
            <div className="flex items-center">
              <input
                type="checkbox"
                id="edit_is_active"
                checked={formData.is_active ?? true}
                onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                className="rounded mr-2"
              />
              <label htmlFor="edit_is_active" className="text-sm text-gray-700">{t('activeLabel')}</label>
            </div>
            <div className="flex justify-end gap-3 pt-4">
              <Button type="button" variant="outline" onClick={onClose} disabled={loading}>{tCommon('cancel')}</Button>
              <Button type="submit" disabled={loading}>{loading ? tCommon('updating') : tCommon('update')}</Button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

// === MODAL: ELIMINAR DISPOSITIVO ===

function DeleteDeviceModal({ device, onClose, onSuccess }: { device: Device; onClose: () => void; onSuccess: () => void }) {
  const t = useTranslations('devices')
  const tCommon = useTranslations('common')
  const [loading, setLoading] = useState(false)

  const handleDelete = async () => {
    try {
      setLoading(true)
      await apiClient.delete(`/devices/${device.id}`)
      onSuccess()
    } catch (error: unknown) {
      console.error('Error:', error)
      const err = error as { response?: { data?: { detail?: string } } }
      alert(err.response?.data?.detail || 'Error al eliminar dispositivo')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4 !mt-0">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
        <div className="p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-bold text-gray-900">{t('deleteTitle')}</h2>
            <Button type="button" variant="ghost" size="sm" onClick={onClose} className="h-8 w-8 p-0">
              <X className="h-5 w-5" />
            </Button>
          </div>
          <p className="text-gray-600 mb-6">{t('deleteConfirm', { name: device.name })}</p>
          <div className="flex justify-end gap-3">
            <Button variant="outline" onClick={onClose} disabled={loading}>{tCommon('cancel')}</Button>
            <Button onClick={handleDelete} disabled={loading} className="bg-red-600 hover:bg-red-700">
              {loading ? tCommon('deleting') : tCommon('delete')}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}


// === MODAL: VER DETALLES DEL DISPOSITIVO ===

function DeviceDetailsModal({ device, onClose }: { device: Device; onClose: () => void }) {
  const t = useTranslations('devices')
  const tCommon = useTranslations('common')
  const timezone = useUserTimezone()

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4 !mt-0">
      <div className="bg-white rounded-lg shadow-xl max-w-lg w-full max-h-[90vh] overflow-y-auto overflow-x-hidden">
        <div className="p-6">
          {/* Encabezado */}
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-blue-100 rounded-lg">
                <Printer className="h-6 w-6 text-blue-600" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-gray-900">{device.name}</h2>
                <Badge variant={device.is_active ? 'default' : 'secondary'}>
                  {device.is_active ? t('statusActive') : t('statusInactive')}
                </Badge>
              </div>
            </div>
            <Button variant="ghost" size="sm" onClick={onClose} className="h-8 w-8 p-0">
              <X className="h-4 w-4" />
            </Button>
          </div>

          {/* Información del dispositivo */}
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase">{t('colIp')}</p>
                <p className="text-sm font-mono text-gray-900">{device.ip_address}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase">{t('portLabel')}</p>
                <p className="text-sm font-mono text-gray-900">{device.port}</p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase">{t('colModel')}</p>
                <p className="text-sm text-gray-900">{device.model || '-'}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase">{t('colLocation')}</p>
                <p className="text-sm text-gray-900">{device.location || '-'}</p>
              </div>
            </div>

            <div>
              <p className="text-xs font-medium text-gray-500 uppercase">{t('colVlan')}</p>
              <div className="text-sm text-gray-900">
                {device.vlan_name ? (
                  <Badge variant="secondary">{device.vlan_name}</Badge>
                ) : (
                  <span className="text-gray-400">{t('noVlan')}</span>
                )}
              </div>
            </div>

            <div>
              <p className="text-xs font-medium text-gray-500 uppercase">{t('descriptionLabel')}</p>
              <p className="text-sm text-gray-900">{device.description || '-'}</p>
            </div>

            <div className="border-t pt-4 grid grid-cols-2 gap-4">
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase">{t('createdAt')}</p>
                <p className="text-sm text-gray-700">{formatDateWithTimezone(device.created_at, timezone)}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500 uppercase">{t('updatedAt')}</p>
                <p className="text-sm text-gray-700">{formatDateWithTimezone(device.updated_at, timezone)}</p>
              </div>
            </div>
          </div>

          {/* Botón cerrar */}
          <div className="flex justify-end pt-6">
            <Button variant="outline" onClick={onClose}>{tCommon('close')}</Button>
          </div>
        </div>
      </div>
    </div>
  )
}
