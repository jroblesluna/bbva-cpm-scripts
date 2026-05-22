/**
 * Página de gestión de VLANs.
 * Vista de tarjetas (responsive) y vista de tabla con toggle.
 */

'use client'

import { useState, useEffect } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { useTranslations } from 'next-intl'
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
  Printer,
  LayoutGrid,
  List,
  Calendar,
  ShieldAlert,
  ChevronLeft,
  ChevronRight,
  Star,
} from 'lucide-react'
import { apiClient } from '@/lib/api'
import type { VLAN, VLANCreate, VLANUpdate, VLANDetail } from '@/types/vlan'
import type { Device } from '@/types/device'
import { formatDateWithTimezone } from '@/lib/dateUtils'
import { useUserTimezone } from '@/hooks/useUserTimezone'
import { CidrHealthBadge } from '@/components/vlans/CidrHealthBadge'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'

type ViewMode = 'cards' | 'table'

export default function VLANsPage() {
  const { user, getAuthHeaders } = useAuth()
  const timezone = useUserTimezone()
  const t = useTranslations('vlans')
  const tCommon = useTranslations('common')
  const [vlans, setVlans] = useState<VLAN[]>([])
  const [accounts, setAccounts] = useState<Array<{ id: string; name: string }>>([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [filterOrgId, setFilterOrgId] = useState<string | undefined>(undefined)
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showEditModal, setShowEditModal] = useState(false)
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [selectedVlan, setSelectedVlan] = useState<VLAN | null>(null)
  const [vlanDetail, setVlanDetail] = useState<VLANDetail | null>(null)
  const [showDevicesModal, setShowDevicesModal] = useState(false)
  const [vlanDevices, setVlanDevices] = useState<Device[]>([])
  const [devicesVlan, setDevicesVlan] = useState<VLAN | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>('cards')
  const [contingencyTarget, setContingencyTarget] = useState<VLAN | null>(null)
  const [contingencyDevices, setContingencyDevices] = useState<Device[]>([])
  const [contingencyDevicesLoading, setContingencyDevicesLoading] = useState(false)
  const [activeDeviceCounts, setActiveDeviceCounts] = useState<Record<string, number>>({})
  const [page, setPage] = useState(1)
  const pageSize = viewMode === 'cards' ? 10 : 20

  useEffect(() => {
    if (!user) return
    loadAccounts()
    loadVlans()
  }, [user, filterOrgId])

  // Cargar dispositivos activos cuando se abre el modal de contingencia (solo al activar)
  useEffect(() => {
    if (!contingencyTarget || contingencyTarget.forced_contingency) {
      setContingencyDevices([])
      return
    }
    const loadDevices = async () => {
      setContingencyDevicesLoading(true)
      try {
        const response = await apiClient.get(`/devices/?vlan_id=${contingencyTarget.id}`)
        const devices: Device[] = response.data.devices || []
        setContingencyDevices(devices.filter((d) => d.is_active))
      } catch {
        setContingencyDevices([])
      } finally {
        setContingencyDevicesLoading(false)
      }
    }
    loadDevices()
  }, [contingencyTarget])

  const loadAccounts = async () => {
    try {
      const response = await apiClient.get('/organizations/?skip=0&limit=1000')
      setAccounts(response.data.items || [])
    } catch (error) {
      console.error('Error loading accounts:', error)
    }
  }

  const loadVlans = async () => {
    try {
      setLoading(true)
      const params = filterOrgId ? `?organization_id=${filterOrgId}` : ''
      const response = await apiClient.get(`/vlans/${params}`)
      const loadedVlans: VLAN[] = response.data.vlans || []
      setVlans(loadedVlans)
      // Cargar conteo de dispositivos activos por VLAN
      loadActiveDeviceCounts(loadedVlans)
    } catch (error) {
      console.error('Error loading vlans:', error)
    } finally {
      setLoading(false)
    }
  }

  const loadActiveDeviceCounts = async (vlanList: VLAN[]) => {
    const counts: Record<string, number> = {}
    await Promise.all(
      vlanList.map(async (vlan) => {
        try {
          const response = await apiClient.get(`/devices/?vlan_id=${vlan.id}`)
          const devices: Device[] = response.data.devices || []
          counts[vlan.id] = devices.filter((d) => d.is_active).length
        } catch {
          counts[vlan.id] = 0
        }
      })
    )
    setActiveDeviceCounts(counts)
  }

  const filteredVlans = vlans.filter((vlan) => {
    const s = searchTerm.toLowerCase()
    return (
      vlan.name.toLowerCase().includes(s) ||
      vlan.description?.toLowerCase().includes(s) ||
      vlan.cidr_ranges.some((cidr) => cidr.includes(s))
    )
  })

  const totalFiltered = filteredVlans.length
  const totalPages = Math.ceil(totalFiltered / pageSize)
  const paginatedVlans = filteredVlans.slice((page - 1) * pageSize, page * pageSize)
  const paginationStart = (page - 1) * pageSize + 1
  const paginationEnd = Math.min(page * pageSize, totalFiltered)

  const handleEdit = async (vlan: VLAN) => {
    try {
      const response = await apiClient.get(`/vlans/${vlan.id}`)
      const detail = response.data
      setVlanDetail(detail)
      setSelectedVlan(vlan)
      setShowEditModal(true)
    } catch (error) {
      console.error('Error:', error)
    }
  }

  const handleDelete = (vlan: VLAN) => {
    setSelectedVlan(vlan)
    setShowDeleteModal(true)
  }

  const handleViewDevices = async (vlan: VLAN) => {
    try {
      const response = await apiClient.get(`/devices/?vlan_id=${vlan.id}`)
      setVlanDevices(response.data.devices || [])
      setDevicesVlan(vlan)
      setShowDevicesModal(true)
    } catch (error) {
      console.error('Error cargando dispositivos:', error)
    }
  }

  const handleToggleForcedContingency = async (vlan: VLAN, enabled: boolean) => {
    try {
      await apiClient.patch(`/vlans/${vlan.id}/forced-contingency`, null, { params: { enabled } })
      setVlans((prev) =>
        prev.map((v) => (v.id === vlan.id ? { ...v, forced_contingency: enabled } : v))
      )
      setContingencyTarget(null)
    } catch (error) {
      console.error('Error al cambiar contingencia forzada:', error)
    }
  }

  const handleSetDefaultDevice = async (vlan: VLAN, deviceId: string | null) => {
    try {
      const params = deviceId ? { device_id: deviceId } : {}
      await apiClient.patch(`/vlans/${vlan.id}/default-device`, null, { params })
      setVlans((prev) =>
        prev.map((v) => (v.id === vlan.id ? { ...v, default_device_id: deviceId } : v))
      )
      // Actualizar la VLAN en el modal si está abierto
      if (devicesVlan && devicesVlan.id === vlan.id) {
        setDevicesVlan({ ...vlan, default_device_id: deviceId })
      }
    } catch (error) {
      console.error('Error al cambiar impresora predeterminada:', error)
    }
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
    <div className="space-y-6">
      {/* Encabezado */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">{t('title')}</h1>
          <p className="mt-2 text-gray-600">{t('subtitle')}</p>
        </div>
        <Button onClick={() => setShowCreateModal(true)}>
          <Plus className="mr-2 h-4 w-4" />
          {t('create')}
        </Button>
      </div>

      {/* Tarjetas de estadísticas */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 md:gap-6">
        <div className="bg-white rounded-lg shadow p-4 md:p-6">
          <div className="flex items-center">
            <div className="p-3 bg-blue-100 rounded-lg">
              <Network className="h-5 w-5 md:h-6 md:w-6 text-blue-600" />
            </div>
            <div className="ml-3 md:ml-4">
              <p className="text-xs md:text-sm font-medium text-gray-600">{t('totalVlans')}</p>
              <p className="text-xl md:text-2xl font-bold text-gray-900">{vlans.length}</p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-lg shadow p-4 md:p-6">
          <div className="flex items-center">
            <div className="p-3 bg-green-100 rounded-lg">
              <Monitor className="h-5 w-5 md:h-6 md:w-6 text-green-600" />
            </div>
            <div className="ml-3 md:ml-4">
              <p className="text-xs md:text-sm font-medium text-gray-600">{t('stations')}</p>
              <p className="text-xl md:text-2xl font-bold text-gray-900">
                {vlans.reduce((acc, v) => {
                  const detail = v as VLAN & { workstation_count?: number }
                  return acc + (detail.workstation_count ?? 0)
                }, 0)}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-lg shadow p-4 md:p-6 col-span-2 md:col-span-1">
          <div className="flex items-center">
            <div className="p-3 bg-purple-100 rounded-lg">
              <Network className="h-5 w-5 md:h-6 md:w-6 text-purple-600" />
            </div>
            <div className="ml-3 md:ml-4">
              <p className="text-xs md:text-sm font-medium text-gray-600">{t('cidrRanges')}</p>
              <p className="text-xl md:text-2xl font-bold text-gray-900">
                {vlans.reduce((acc, v) => acc + v.cidr_ranges.length, 0)}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Filtros y toggle de vista */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="flex flex-col md:flex-row gap-4">
          <div className="relative flex-1">
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
              onChange={(e) => { setFilterOrgId(e.target.value === 'all' ? undefined : e.target.value); setPage(1) }}
              className="w-full md:w-auto px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">{t('allOrganizations')}</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>{account.name}</option>
              ))}
            </select>
          )}
        </div>
        <div className="flex items-center justify-between mt-4">
          <div className="flex items-center">
            {(searchTerm || filterOrgId) && (
              <Button variant="outline" size="sm" onClick={() => { setSearchTerm(''); setFilterOrgId(undefined); setPage(1) }}>
                <X className="mr-2 h-4 w-4" />
                {tCommon('clearFilters')}
              </Button>
            )}
          </div>
          {/* Toggle de vista: tarjetas / tabla */}
          <div className="flex items-center gap-1 border rounded-md p-0.5">
            <Button
              variant={viewMode === 'cards' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => { setViewMode('cards'); setPage(1) }}
              title="Vista de tarjetas"
              className="h-8 w-8 p-0"
            >
              <LayoutGrid className="w-4 h-4" />
            </Button>
            <Button
              variant={viewMode === 'table' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => { setViewMode('table'); setPage(1) }}
              title="Vista de tabla"
              className="h-8 w-8 p-0"
            >
              <List className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </div>

      {/* Contenido principal: vista de tarjetas o tabla */}
      {filteredVlans.length === 0 ? (
        <div className="bg-white rounded-lg shadow">
          <div className="text-center py-12">
            <Network className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-2 text-sm font-medium text-gray-900">{t('emptyTitle')}</h3>
            <p className="mt-1 text-sm text-gray-500">
              {searchTerm ? t('emptyMessage') : t('emptyCreate')}
            </p>
            {!searchTerm && (
              <div className="mt-6">
                <Button onClick={() => setShowCreateModal(true)}>
                  <Plus className="mr-2 h-4 w-4" />
                  {t('create')}
                </Button>
              </div>
            )}
          </div>
        </div>
      ) : viewMode === 'cards' ? (
        /* Vista de tarjetas (responsive) */
        <div className="space-y-4">
          {paginatedVlans.map((vlan) => (
            <div key={vlan.id} className="bg-white rounded-lg shadow p-4 md:p-6">
              {/* Fila 1: Nombre + CidrHealthBadge */}
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2 min-w-0">
                  <Network className="h-5 w-5 text-gray-400 flex-shrink-0" />
                  <span className="text-sm md:text-base font-medium text-gray-900 truncate">
                    {vlan.name}
                  </span>
                </div>
                <CidrHealthBadge cidrCount={vlan.cidr_ranges.length} />
              </div>
              {/* Fila 2: Organización, CIDRs, descripción */}
              <div className="space-y-2 mb-3">
                <div className="flex flex-wrap items-center gap-2 text-sm text-gray-600">
                  <span className="font-medium">
                    {accounts.find((a) => a.id === vlan.organization_id)?.name || '-'}
                  </span>
                  <span className="text-gray-300">|</span>
                  <div className="flex flex-wrap gap-1">
                    {vlan.cidr_ranges.map((cidr, idx) => (
                      <Badge key={idx} variant="secondary" className="text-xs">
                        {cidr}
                      </Badge>
                    ))}
                  </div>
                </div>
                {vlan.description && (
                  <p className="text-sm text-gray-500 line-clamp-2">
                    {vlan.description}
                  </p>
                )}
                <div className="flex items-center gap-1 text-xs text-gray-400">
                  <Calendar className="h-3 w-3" />
                  <span>{formatDateWithTimezone(vlan.created_at, timezone)}</span>
                </div>
              </div>

              {/* Fila 3: Acciones */}
              <div className="flex flex-wrap gap-1 pt-2 border-t border-gray-100 items-center">
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="inline-flex">
                        <Button
                          variant={vlan.forced_contingency ? 'destructive' : 'ghost'}
                          size="sm"
                          onClick={() => setContingencyTarget(vlan)}
                          disabled={(activeDeviceCounts[vlan.id] ?? 0) === 0 && !vlan.forced_contingency}
                          title={vlan.forced_contingency ? t('forcedContingencyDeactivate') : t('forcedContingencyActivate')}
                          className={`h-8 w-8 p-0 ${vlan.forced_contingency ? 'bg-orange-600 hover:bg-orange-700' : ''} ${(activeDeviceCounts[vlan.id] ?? 0) === 0 && !vlan.forced_contingency ? 'text-gray-400 cursor-not-allowed opacity-50' : ''}`}
                        >
                          <ShieldAlert className="h-4 w-4" />
                        </Button>
                      </span>
                    </TooltipTrigger>
                    {(activeDeviceCounts[vlan.id] ?? 0) === 0 && !vlan.forced_contingency && (
                      <TooltipContent>
                        <p>{t('contingencyNoDevices')}</p>
                      </TooltipContent>
                    )}
                  </Tooltip>
                </TooltipProvider>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleViewDevices(vlan)}
                  title={t('viewDevices')}
                  className="h-8 w-8 p-0"
                >
                  <Printer className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleEdit(vlan)}
                  title={tCommon('edit')}
                  className="h-8 w-8 p-0"
                >
                  <Edit className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleDelete(vlan)}
                  title={tCommon('delete')}
                  className="h-8 w-8 p-0 text-red-600 hover:text-red-700"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* Vista de tabla (con overflow-x-auto para desktop) */
        <div className="bg-white rounded-lg shadow overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 md:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colName')}</th>
                  <th className="px-4 md:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colOrganization')}</th>
                  <th className="px-4 md:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colDescription')}</th>
                  <th className="px-4 md:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colCidr')}</th>
                  <th className="px-4 md:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colHealth')}</th>
                  <th className="px-4 md:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colCreated')}</th>
                  <th className="px-4 md:px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colActions')}</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {paginatedVlans.map((vlan) => (
                  <tr key={vlan.id} className="hover:bg-gray-50">
                    <td className="px-4 md:px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <Network className="h-5 w-5 text-gray-400" />
                        <span className="text-sm font-medium text-gray-900">{vlan.name}</span>
                      </div>
                    </td>
                    <td className="px-4 md:px-6 py-4 whitespace-nowrap">
                      <span className="text-sm text-gray-600">
                        {accounts.find((a) => a.id === vlan.organization_id)?.name || '-'}
                      </span>
                    </td>
                    <td className="px-4 md:px-6 py-4">
                      <span className="text-sm text-gray-500 line-clamp-1">{vlan.description || '-'}</span>
                    </td>
                    <td className="px-4 md:px-6 py-4">
                      <div className="flex flex-wrap gap-1">
                        {vlan.cidr_ranges.map((cidr, idx) => (
                          <Badge key={idx} variant="secondary">{cidr}</Badge>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 md:px-6 py-4 whitespace-nowrap">
                      <CidrHealthBadge cidrCount={vlan.cidr_ranges.length} />
                    </td>
                    <td className="px-4 md:px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {formatDateWithTimezone(vlan.created_at, timezone)}
                    </td>
                    <td className="px-4 md:px-6 py-4 whitespace-nowrap text-right">
                      <div className="flex flex-wrap gap-1 justify-end items-center">
                        <TooltipProvider>
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span className="inline-flex">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => setContingencyTarget(vlan)}
                                  disabled={(activeDeviceCounts[vlan.id] ?? 0) === 0 && !vlan.forced_contingency}
                                  title={vlan.forced_contingency ? t('forcedContingencyDeactivate') : t('forcedContingencyActivate')}
                                  className={`h-8 w-8 p-0 ${vlan.forced_contingency ? 'text-orange-600 bg-orange-50 hover:bg-orange-100' : ''} ${(activeDeviceCounts[vlan.id] ?? 0) === 0 && !vlan.forced_contingency ? 'text-gray-400 cursor-not-allowed opacity-50' : ''}`}
                                >
                                  <ShieldAlert className="h-4 w-4" />
                                </Button>
                              </span>
                            </TooltipTrigger>
                            {(activeDeviceCounts[vlan.id] ?? 0) === 0 && !vlan.forced_contingency && (
                              <TooltipContent>
                                <p>{t('contingencyNoDevices')}</p>
                              </TooltipContent>
                            )}
                          </Tooltip>
                        </TooltipProvider>
                        <Button variant="ghost" size="sm" onClick={() => handleViewDevices(vlan)} title={t('viewDevices')} className="h-8 w-8 p-0">
                          <Printer className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => handleEdit(vlan)} title={tCommon('edit')} className="h-8 w-8 p-0">
                          <Edit className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => handleDelete(vlan)} title={tCommon('delete')} className="h-8 w-8 p-0 text-red-600 hover:text-red-700">
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

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
      {contingencyTarget && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6">
            <div className="flex items-center gap-2 mb-4">
              <ShieldAlert className={`w-5 h-5 ${contingencyTarget.forced_contingency ? 'text-green-600' : 'text-orange-600'}`} />
              <h2 className="text-lg font-bold text-gray-900">
                {contingencyTarget.forced_contingency ? t('forcedContingencyDeactivate') : t('forcedContingencyActivate')}
              </h2>
            </div>
            <p className="text-sm text-gray-600 mb-4">
              {contingencyTarget.forced_contingency
                ? t('forcedContingencyConfirmDeactivate', { name: contingencyTarget.name })
                : t('forcedContingencyConfirmActivate', { name: contingencyTarget.name })
              }
            </p>
            {!contingencyTarget.forced_contingency && (
              <p className="text-xs text-orange-700 bg-orange-50 border border-orange-200 rounded p-2 mb-4">
                {t('forcedContingencyNotification')}
              </p>
            )}
            {/* Información de impresora al activar contingencia */}
            {!contingencyTarget.forced_contingency && (
              <div className="mb-4">
                {contingencyDevicesLoading ? (
                  <p className="text-xs text-gray-500 italic">{tCommon('loading')}</p>
                ) : contingencyDevices.length > 0 ? (
                  <div className="p-3 bg-green-50 border border-green-200 rounded">
                    <div className="flex items-center gap-2 mb-1">
                      <Printer className="h-4 w-4 text-green-600" />
                      <span className="text-sm font-medium text-green-800">{t('contingencyPrinterUsed')}</span>
                    </div>
                    <p className="text-sm text-green-700 font-mono ml-6">
                      {contingencyDevices[0].name} — {contingencyDevices[0].ip_address}:{contingencyDevices[0].port}
                    </p>
                    {contingencyDevices.length > 1 && (
                      <p className="text-xs text-green-600 ml-6 mt-1">
                        {t('contingencyMoreDevices', { count: contingencyDevices.length - 1 })}
                      </p>
                    )}
                  </div>
                ) : (
                  <div className="p-3 bg-red-50 border border-red-200 rounded">
                    <div className="flex items-center gap-2">
                      <Printer className="h-4 w-4 text-red-500" />
                      <span className="text-sm font-medium text-red-700">{t('contingencyNoPrinters')}</span>
                    </div>
                  </div>
                )}
              </div>
            )}
            <div className="flex justify-end gap-3">
              <Button variant="outline" onClick={() => setContingencyTarget(null)}>{tCommon('cancel')}</Button>
              <Button
                variant={contingencyTarget.forced_contingency ? 'default' : 'destructive'}
                onClick={() => handleToggleForcedContingency(contingencyTarget, !contingencyTarget.forced_contingency)}
                className={!contingencyTarget.forced_contingency ? 'bg-orange-600 hover:bg-orange-700' : ''}
              >
                {contingencyTarget.forced_contingency ? t('forcedContingencyDeactivate') : t('forcedContingencyActivate')}
              </Button>
            </div>
          </div>
        </div>
      )}
      {showCreateModal && (
        <CreateVLANModal onClose={() => setShowCreateModal(false)} onSuccess={() => { setShowCreateModal(false); loadVlans() }} />
      )}
      {showEditModal && selectedVlan && vlanDetail && (
        <EditVLANModal
          vlan={selectedVlan}
          detail={vlanDetail}
          onClose={() => { setShowEditModal(false); setSelectedVlan(null); setVlanDetail(null) }}
          onSuccess={() => { setShowEditModal(false); setSelectedVlan(null); setVlanDetail(null); loadVlans() }}
        />
      )}
      {showDeleteModal && selectedVlan && (
        <DeleteVLANModal
          vlan={selectedVlan}
          onClose={() => { setShowDeleteModal(false); setSelectedVlan(null) }}
          onSuccess={() => { setShowDeleteModal(false); setSelectedVlan(null); loadVlans() }}
        />
      )}
      {showDevicesModal && devicesVlan && (
        <VLANDevicesModal
          vlan={devicesVlan}
          devices={vlanDevices}
          onClose={() => { setShowDevicesModal(false); setVlanDevices([]); setDevicesVlan(null) }}
          onSetDefault={(deviceId) => handleSetDefaultDevice(devicesVlan, deviceId)}
        />
      )}
    </div>
  )
}

// ============================================================================
// Modal: Crear VLAN
// ============================================================================

function CreateVLANModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const { getAuthHeaders, user, isAdmin } = useAuth()
  const t = useTranslations('vlans')
  const tCommon = useTranslations('common')
  const [loading, setLoading] = useState(false)
  const [accounts, setAccounts] = useState<Array<{ id: string; name: string }>>([])
  const [formData, setFormData] = useState<VLANCreate>({
    organization_id: user?.organization_id || '',
    name: '',
    description: '',
    cidr_ranges: [''],
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
  }, [isAdmin, getAuthHeaders])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const validCidrs = formData.cidr_ranges.filter((c) => c.trim())
    if (!formData.name.trim() || !formData.organization_id || validCidrs.length === 0) return

    try {
      setLoading(true)
      await apiClient.post('/vlans/', { ...formData, cidr_ranges: validCidrs })
      onSuccess()
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : 'Error desconocido'
      console.error('Error:', error)
      alert(msg)
    } finally {
      setLoading(false)
    }
  }

  const addCidrField = () => setFormData({ ...formData, cidr_ranges: [...formData.cidr_ranges, ''] })
  const removeCidrField = (i: number) => setFormData({ ...formData, cidr_ranges: formData.cidr_ranges.filter((_, idx) => idx !== i) })
  const updateCidrField = (i: number, v: string) => {
    const n = [...formData.cidr_ranges]; n[i] = v; setFormData({ ...formData, cidr_ranges: n })
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="p-6">
          <h2 className="text-2xl font-bold text-gray-900 mb-4">{t('createTitle')}</h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            {isAdmin() && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('organization')}</label>
                <select value={formData.organization_id || ''} onChange={(e) => setFormData({ ...formData, organization_id: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" required>
                  <option value="">{t('selectOrg')}</option>
                  {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              </div>
            )}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{tCommon('name')} *</label>
              <input type="text" value={formData.name} onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                placeholder={t('namePlaceholder')} required
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{tCommon('description')}</label>
              <textarea value={formData.description || ''} onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                placeholder={t('descPlaceholder')}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" rows={3} />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('cidrLabel')}</label>
              <div className="space-y-2">
                {formData.cidr_ranges.map((cidr, index) => (
                  <div key={index} className="flex gap-2">
                    <input type="text" value={cidr} onChange={(e) => updateCidrField(index, e.target.value)}
                      placeholder="Ej: 192.168.1.0/24" className="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    {formData.cidr_ranges.length > 1 && (
                      <Button type="button" variant="outline" size="sm" onClick={() => removeCidrField(index)}>
                        <X className="h-4 w-4" />
                      </Button>
                    )}
                  </div>
                ))}
              </div>
              <Button type="button" variant="outline" size="sm" onClick={addCidrField} className="mt-2">
                <Plus className="mr-2 h-4 w-4" />{t('addRange')}
              </Button>
              <p className="mt-1 text-xs text-gray-500">{t('cidrHelper')}</p>
            </div>
            <div className="flex justify-end gap-3 pt-4">
              <Button type="button" variant="outline" onClick={onClose} disabled={loading}>{tCommon('cancel')}</Button>
              <Button type="submit" disabled={loading}>{loading ? tCommon('creating') : t('createTitle')}</Button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

// ============================================================================
// Modal: Editar VLAN
// ============================================================================

function EditVLANModal({ vlan, detail, onClose, onSuccess }: { vlan: VLAN; detail: VLANDetail; onClose: () => void; onSuccess: () => void }) {
  const { getAuthHeaders } = useAuth()
  const t = useTranslations('vlans')
  const tCommon = useTranslations('common')
  const [loading, setLoading] = useState(false)
  const [formData, setFormData] = useState<VLANUpdate>({
    name: vlan.name,
    description: vlan.description,
    cidr_ranges: [...vlan.cidr_ranges],
  })

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const validCidrs = formData.cidr_ranges?.filter((c) => c.trim()) || []
    if (!formData.name?.trim() || validCidrs.length === 0) return
    try {
      setLoading(true)
      await apiClient.put(`/vlans/${vlan.id}`, { ...formData, cidr_ranges: validCidrs })
      onSuccess()
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : 'Error desconocido'
      console.error('Error:', error)
      alert(msg)
    } finally {
      setLoading(false)
    }
  }

  const addCidrField = () => setFormData({ ...formData, cidr_ranges: [...(formData.cidr_ranges || []), ''] })
  const removeCidrField = (i: number) => setFormData({ ...formData, cidr_ranges: formData.cidr_ranges?.filter((_, idx) => idx !== i) || [] })
  const updateCidrField = (i: number, v: string) => {
    const n = [...(formData.cidr_ranges || [])]; n[i] = v; setFormData({ ...formData, cidr_ranges: n })
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="p-6">
          <h2 className="text-2xl font-bold text-gray-900 mb-4">{t('editTitle')}</h2>
          {detail.workstation_count > 0 && (
            <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-md">
              <p className="text-sm text-blue-800">
                <Monitor className="inline h-4 w-4 mr-1" />
                {t('stationsAssigned', { count: detail.workstation_count })}
              </p>
            </div>
          )}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{tCommon('name')} *</label>
              <input type="text" value={formData.name || ''} onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                placeholder={t('namePlaceholder')} required
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{tCommon('description')}</label>
              <textarea value={formData.description || ''} onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                placeholder={t('descPlaceholder')}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" rows={3} />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('cidrLabel')}</label>
              <div className="space-y-2">
                {(formData.cidr_ranges || []).map((cidr, index) => (
                  <div key={index} className="flex gap-2">
                    <input type="text" value={cidr} onChange={(e) => updateCidrField(index, e.target.value)}
                      placeholder="Ej: 192.168.1.0/24" className="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    {(formData.cidr_ranges?.length || 0) > 1 && (
                      <Button type="button" variant="outline" size="sm" onClick={() => removeCidrField(index)}>
                        <X className="h-4 w-4" />
                      </Button>
                    )}
                  </div>
                ))}
              </div>
              <Button type="button" variant="outline" size="sm" onClick={addCidrField} className="mt-2">
                <Plus className="mr-2 h-4 w-4" />{t('addRange')}
              </Button>
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

// ============================================================================
// Modal: Eliminar VLAN
// ============================================================================

function DeleteVLANModal({ vlan, onClose, onSuccess }: { vlan: VLAN; onClose: () => void; onSuccess: () => void }) {
  const { getAuthHeaders } = useAuth()
  const t = useTranslations('vlans')
  const tCommon = useTranslations('common')
  const [loading, setLoading] = useState(false)

  const handleDelete = async () => {
    try {
      setLoading(true)
      await apiClient.delete(`/vlans/${vlan.id}`)
      onSuccess()
    } catch (error: unknown) {
      const msg = error instanceof Error ? error.message : 'Error desconocido'
      console.error('Error:', error)
      alert(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
        <div className="p-6">
          <h2 className="text-xl font-bold text-gray-900 mb-4">{t('deleteTitle')}</h2>
          <p className="text-gray-600 mb-6">{t('deleteConfirm', { name: vlan.name })}</p>
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

// ============================================================================
// Modal: Dispositivos de VLAN
// ============================================================================

function VLANDevicesModal({ vlan, devices, onClose, onSetDefault }: { vlan: VLAN; devices: Device[]; onClose: () => void; onSetDefault: (deviceId: string | null) => void }) {
  const t = useTranslations('vlans')
  const tCommon = useTranslations('common')
  const tDevices = useTranslations('devices')

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full max-h-[80vh] overflow-y-auto">
        <div className="p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-bold text-gray-900">
              {t('devicesInVlan')} — {vlan.name}
            </h2>
            <Button variant="ghost" size="sm" onClick={onClose}>
              <X className="h-5 w-5" />
            </Button>
          </div>
          {devices.length === 0 ? (
            <div className="text-center py-8">
              <Printer className="mx-auto h-12 w-12 text-gray-400" />
              <p className="mt-2 text-sm text-gray-500">{t('noDevices')}</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{tDevices('colName')}</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{tDevices('colIp')}</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{tDevices('colModel')}</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{tDevices('colLocation')}</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{tDevices('colStatus')}</th>
                    <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">{t('defaultDevice')}</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {devices.map((device) => {
                    const isDefault = vlan.default_device_id === device.id
                    return (
                      <tr key={device.id} className={`hover:bg-gray-50 ${isDefault ? 'bg-yellow-50' : ''}`}>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <div className="flex items-center">
                            <Printer className="h-4 w-4 text-gray-400 mr-2" />
                            <span className="text-sm font-medium text-gray-900">{device.name}</span>
                          </div>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <span className="text-sm font-mono text-gray-700">{device.ip_address}:{device.port}</span>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <span className="text-sm text-gray-500">{device.model || '-'}</span>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <span className="text-sm text-gray-500">{device.location || '-'}</span>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <Badge variant={device.is_active ? 'default' : 'secondary'}>
                            {device.is_active ? tDevices('statusActive') : tDevices('statusInactive')}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-center">
                          <Button
                            variant={isDefault ? 'default' : 'ghost'}
                            size="sm"
                            onClick={() => onSetDefault(isDefault ? null : device.id)}
                            disabled={!device.is_active}
                            title={isDefault ? t('removeDefaultDevice') : t('setDefaultDevice')}
                            className={`h-8 w-8 p-0 ${isDefault ? 'bg-yellow-500 hover:bg-yellow-600 text-white' : ''}`}
                          >
                            <Star className={`h-4 w-4 ${isDefault ? 'fill-white' : ''}`} />
                          </Button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div className="flex justify-end mt-4">
            <Button variant="outline" onClick={onClose}>{tCommon('close')}</Button>
          </div>
        </div>
      </div>
    </div>
  )
}
