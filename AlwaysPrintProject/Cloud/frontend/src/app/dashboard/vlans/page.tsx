/**
 * Página de gestión de VLANs.
 * Vista de tarjetas (responsive) y vista de tabla con toggle.
 */

'use client'

import React, { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/hooks/useAuth'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ActionConfigSection } from '@/components/config/ActionConfigSection'
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
  RefreshCw,
  RotateCcw,
  RefreshCcw,
  Download,
  Terminal,
} from 'lucide-react'
import { apiClient, vlansApi } from '@/lib/api'
import type { VLAN, VLANCreate, VLANUpdate, VLANDetail } from '@/types/vlan'
import type { Device, DeviceCreate } from '@/types/device'
import { formatDateWithTimezone } from '@/lib/dateUtils'
import { useUserTimezone } from '@/hooks/useUserTimezone'
import { useToast } from '@/hooks/use-toast'
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
  const router = useRouter()
  const timezone = useUserTimezone()
  const { toast } = useToast()
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
  const [showAddDeviceModal, setShowAddDeviceModal] = useState(false)
  const [addDeviceVlan, setAddDeviceVlan] = useState<VLAN | null>(null)
  const [bulkCommandTarget, setBulkCommandTarget] = useState<{ vlan: VLAN; commandType: 'restart_service' | 'restart_tray' | 'check_update' } | null>(null)
  const [bulkCommandPending, setBulkCommandPending] = useState(false)
  const [page, setPage] = useState(1)
  const pageSize = viewMode === 'cards' ? 10 : 20
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date())
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => {
    if (!user) return
    if (user.role === 'admin') loadAccounts()
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

  const loadVlans = async (silent = false) => {
    try {
      if (!silent) setLoading(true)
      const params = filterOrgId ? `?organization_id=${filterOrgId}` : ''
      const response = await apiClient.get(`/vlans/${params}`)
      const loadedVlans: VLAN[] = response.data.vlans || []
      setVlans(loadedVlans)
      setLastUpdated(new Date())
      // Cargar conteo de dispositivos activos por VLAN
      loadActiveDeviceCounts(loadedVlans)
    } catch (error) {
      console.error('Error loading vlans:', error)
    } finally {
      if (!silent) setLoading(false)
      setRefreshing(false)
    }
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    await loadVlans(true)
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
      toast({
        title: t('forcedContingency'),
        description: enabled
          ? t('forcedContingencyActivated')
          : t('forcedContingencyDeactivated'),
      })
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast({
        variant: 'destructive',
        title: t('forcedContingency'),
        description: detail ?? t('forcedContingencyError'),
      })
    }
  }

  const handleBulkCommand = async () => {
    if (!bulkCommandTarget) return
    setBulkCommandPending(true)
    try {
      const result = await vlansApi.sendCommand(bulkCommandTarget.vlan.id, bulkCommandTarget.commandType)
      const labels: Record<string, string> = {
        restart_service: tCommon('bulkRestartService'),
        restart_tray: tCommon('bulkRestartTray'),
        check_update: tCommon('bulkCheckUpdate'),
      }
      toast({
        title: tCommon('bulkCommandSent'),
        description: t('bulkCommandSentDesc', { action: labels[bulkCommandTarget.commandType], count: result.dispatched, name: bulkCommandTarget.vlan.name }),
      })
    } catch {
      toast({ variant: 'destructive', title: tCommon('error'), description: tCommon('bulkCommandError') })
    } finally {
      setBulkCommandPending(false)
      setBulkCommandTarget(null)
    }
  }

  const handleAddDevice = (vlan: VLAN) => {
    setAddDeviceVlan(vlan)
    setShowAddDeviceModal(true)
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
              title={tCommon('viewCards')}
              className="h-8 w-8 p-0"
            >
              <LayoutGrid className="w-4 h-4" />
            </Button>
            <Button
              variant={viewMode === 'table' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => { setViewMode('table'); setPage(1) }}
              title={tCommon('viewTable')}
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
                  onClick={() => setBulkCommandTarget({ vlan, commandType: 'restart_service' })}
                  title={tCommon('bulkRestartServiceTooltip')}
                  className="h-8 w-8 p-0"
                >
                  <RotateCcw className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setBulkCommandTarget({ vlan, commandType: 'restart_tray' })}
                  title={tCommon('bulkRestartTrayTooltip')}
                  className="h-8 w-8 p-0"
                >
                  <Terminal className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setBulkCommandTarget({ vlan, commandType: 'check_update' })}
                  title={tCommon('bulkCheckUpdateTooltip')}
                  className="h-8 w-8 p-0"
                >
                  <Download className="h-4 w-4" />
                </Button>
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
                  onClick={() => router.push(`/dashboard/workstations?vlan_id=${vlan.id}&org_id=${vlan.organization_id}`)}
                  title={t('viewWorkstations')}
                  className="h-8 w-8 p-0"
                >
                  <Monitor className="h-4 w-4" />
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
                  className="h-8 w-8 p-0 text-red-400 hover:text-red-500"
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
                        <Button variant="ghost" size="sm" onClick={() => setBulkCommandTarget({ vlan, commandType: 'restart_service' })} title={tCommon('bulkRestartServiceTooltip')} className="h-8 w-8 p-0">
                          <RotateCcw className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setBulkCommandTarget({ vlan, commandType: 'restart_tray' })} title={tCommon('bulkRestartTrayTooltip')} className="h-8 w-8 p-0">
                          <Terminal className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setBulkCommandTarget({ vlan, commandType: 'check_update' })} title={tCommon('bulkCheckUpdateTooltip')} className="h-8 w-8 p-0">
                          <Download className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => handleViewDevices(vlan)} title={t('viewDevices')} className="h-8 w-8 p-0">
                          <Printer className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => router.push(`/dashboard/workstations?vlan_id=${vlan.id}&org_id=${vlan.organization_id}`)} title={t('viewWorkstations')} className="h-8 w-8 p-0">
                          <Monitor className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => handleEdit(vlan)} title={tCommon('edit')} className="h-8 w-8 p-0">
                          <Edit className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => handleDelete(vlan)} title={tCommon('delete')} className="h-8 w-8 p-0 text-red-400 hover:text-red-500">
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
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4 !mt-0">
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
          onAddDevice={() => {
            setShowDevicesModal(false)
            setAddDeviceVlan(devicesVlan)
            setShowAddDeviceModal(true)
          }}
        />
      )}
      {showAddDeviceModal && addDeviceVlan && (
        <CreateDeviceFromVLANModal
          vlan={addDeviceVlan}
          orgName={accounts.find((a) => a.id === addDeviceVlan.organization_id)?.name || ''}
          onClose={() => { setShowAddDeviceModal(false); setAddDeviceVlan(null) }}
          onSuccess={async () => {
            setShowAddDeviceModal(false)
            const vlan = addDeviceVlan
            setAddDeviceVlan(null)
            await loadActiveDeviceCounts(vlans)
            await handleViewDevices(vlan)
          }}
        />
      )}

      {/* Modal de confirmación de comando bulk VLAN */}
      {bulkCommandTarget && (() => {
        const { vlan, commandType } = bulkCommandTarget
        const labels: Record<string, { title: string; icon: React.ReactNode; desc: string; warning: string; color: string }> = {
          restart_service: {
            title: tCommon('bulkRestartService'),
            icon: <RotateCcw className="w-5 h-5 text-gray-600" />,
            desc: t('bulkRestartServiceDesc', { name: vlan.name }),
            warning: t('bulkRestartServiceWarning'),
            color: 'bg-amber-600 hover:bg-amber-700',
          },
          restart_tray: {
            title: tCommon('bulkRestartTray'),
            icon: <Terminal className="w-5 h-5 text-gray-600" />,
            desc: t('bulkRestartTrayDesc', { name: vlan.name }),
            warning: t('bulkRestartTrayWarning'),
            color: 'bg-amber-600 hover:bg-amber-700',
          },
          check_update: {
            title: tCommon('bulkCheckUpdate'),
            icon: <Download className="w-5 h-5 text-gray-600" />,
            desc: t('bulkCheckUpdateDesc', { name: vlan.name }),
            warning: t('bulkCheckUpdateWarning'),
            color: 'bg-blue-600 hover:bg-blue-700',
          },
        }
        const meta = labels[commandType]
        return (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4 !mt-0">
            <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6">
              <div className="flex items-center gap-2 mb-4">
                {meta.icon}
                <h2 className="text-lg font-bold text-gray-900">{t('bulkModalTitle', { action: meta.title })}</h2>
              </div>
              <p className="text-sm text-gray-600 mb-3">{meta.desc}</p>
              <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2 mb-4">{meta.warning}</p>
              <div className="flex justify-end gap-3">
                <button
                  className="px-4 py-2 rounded border border-gray-300 text-sm hover:bg-gray-50"
                  onClick={() => setBulkCommandTarget(null)}
                  disabled={bulkCommandPending}
                >
                  {tCommon('cancel')}
                </button>
                <button
                  className={`px-4 py-2 rounded text-white text-sm ${meta.color} disabled:opacity-60`}
                  onClick={handleBulkCommand}
                  disabled={bulkCommandPending}
                >
                  {bulkCommandPending ? tCommon('sending') : tCommon('bulkConfirmBtn', { action: meta.title })}
                </button>
              </div>
            </div>
          </div>
        )
      })()}
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
  const [devices, setDevices] = useState<Device[]>([])
  const [devicesLoading, setDevicesLoading] = useState(true)
  const [selectedDefaultDevice, setSelectedDefaultDevice] = useState<string | null>(vlan.default_device_id)
  const [formData, setFormData] = useState<VLANUpdate>({
    name: vlan.name,
    description: vlan.description,
    cidr_ranges: [...vlan.cidr_ranges],
  })
  const [metadataEntries, setMetadataEntries] = useState<Array<{ key: string; value: string }>>(
    vlan.metadata
      ? Object.entries(vlan.metadata).map(([key, value]) => ({ key, value: String(value) }))
      : []
  )

  // Cargar dispositivos de la VLAN al abrir el modal
  useEffect(() => {
    const loadDevices = async () => {
      try {
        setDevicesLoading(true)
        const response = await apiClient.get(`/devices/?vlan_id=${vlan.id}`)
        setDevices((response.data.devices || []).filter((d: Device) => d.is_active))
      } catch {
        setDevices([])
      } finally {
        setDevicesLoading(false)
      }
    }
    loadDevices()
  }, [vlan.id])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const validCidrs = formData.cidr_ranges?.filter((c) => c.trim()) || []
    if (!formData.name?.trim() || validCidrs.length === 0) return
    try {
      setLoading(true)
      // Construir metadata desde las entradas clave-valor
      const metadata = metadataEntries.length > 0
        ? Object.fromEntries(metadataEntries.filter(e => e.key.trim()).map(e => [e.key.trim(), e.value]))
        : null
      await apiClient.put(`/vlans/${vlan.id}`, { ...formData, cidr_ranges: validCidrs, metadata: metadata })
      // Actualizar impresora predeterminada si cambió
      if (selectedDefaultDevice !== vlan.default_device_id) {
        const params = selectedDefaultDevice ? { device_id: selectedDefaultDevice } : {}
        await apiClient.patch(`/vlans/${vlan.id}/default-device`, null, { params })
      }
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
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4 !mt-0">
      <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full max-h-[90vh] overflow-y-auto overflow-x-hidden">
        <div className="p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-2xl font-bold text-gray-900">{t('editTitle')}</h2>
            <Button type="button" variant="ghost" size="sm" onClick={onClose} className="h-8 w-8 p-0">
              <X className="h-5 w-5" />
            </Button>
          </div>
          {detail.workstation_count > 0 && (
            <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-md">
              <p className="text-sm text-blue-800">
                <Monitor className="inline h-4 w-4 mr-1" />
                {t('stationsAssigned', { count: detail.workstation_count })}
              </p>
            </div>
          )}
          <form id="edit-vlan-form" onSubmit={handleSubmit} className="space-y-4">
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
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('defaultDevice')}</label>
              <p className="text-xs text-gray-500 mb-2">{t('defaultDeviceHelper')}</p>
              {devicesLoading ? (
                <p className="text-sm text-gray-500">{tCommon('loading')}</p>
              ) : devices.length === 0 ? (
                <p className="text-sm text-gray-500">{t('defaultDeviceNoDevices')}</p>
              ) : (
                <select
                  value={selectedDefaultDevice || ''}
                  onChange={(e) => setSelectedDefaultDevice(e.target.value || null)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">{t('selectDefaultDevice')}</option>
                  {devices.map((device) => (
                    <option key={device.id} value={device.id}>
                      {device.name} — {device.ip_address}:{device.port}
                    </option>
                  ))}
                </select>
              )}
            </div>
            {/* Metadata de la VLAN (pares clave-valor) */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('metadataLabel')}</label>
              <p className="text-xs text-gray-500 mb-2">{t('metadataHelper')}</p>
              <div className="space-y-2">
                {metadataEntries.map((entry, index) => (
                  <div key={index} className="flex gap-2">
                    <input
                      type="text"
                      value={entry.key}
                      onChange={(e) => {
                        const updated = [...metadataEntries]
                        updated[index] = { ...updated[index], key: e.target.value }
                        setMetadataEntries(updated)
                      }}
                      placeholder={t('metadataKeyPlaceholder')}
                      className="w-1/3 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                    />
                    <input
                      type="text"
                      value={entry.value}
                      onChange={(e) => {
                        const updated = [...metadataEntries]
                        updated[index] = { ...updated[index], value: e.target.value }
                        setMetadataEntries(updated)
                      }}
                      placeholder={t('metadataValuePlaceholder')}
                      className="flex-1 px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
                    />
                    <Button type="button" variant="outline" size="sm" onClick={() => setMetadataEntries(metadataEntries.filter((_, i) => i !== index))}>
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setMetadataEntries([...metadataEntries, { key: '', value: '' }])}
                className="mt-2"
              >
                <Plus className="mr-2 h-4 w-4" />{t('metadataAdd')}
              </Button>
            </div>
          </form>
          {/* Sección de Action Config para esta VLAN (colapsable) */}
          <details className="mt-6 pt-6 border-t border-gray-200 group">
            <summary className="flex items-center justify-between cursor-pointer list-none p-3 rounded-lg hover:bg-gray-50 transition-colors [&::-webkit-details-marker]:hidden">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-indigo-100 flex items-center justify-center">
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 text-indigo-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-gray-900">{t('actionConfigTitle')}</h3>
                  <p className="text-xs text-gray-500">{t('actionConfigDesc')}</p>
                </div>
              </div>
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-gray-400 transition-transform group-open:rotate-180" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
            </summary>
            <div className="mt-3">
              <ActionConfigSection organizationId={vlan.organization_id} vlanId={vlan.id} />
            </div>
          </details>
          <div className="flex justify-end gap-3 pt-6 mt-6 border-t border-gray-200">
            <Button type="button" variant="outline" onClick={onClose} disabled={loading}>{tCommon('cancel')}</Button>
            <Button type="submit" form="edit-vlan-form" disabled={loading}>{loading ? tCommon('updating') : tCommon('update')}</Button>
          </div>
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
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4 !mt-0">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
        <div className="p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-bold text-gray-900">{t('deleteTitle')}</h2>
            <Button type="button" variant="ghost" size="sm" onClick={onClose} className="h-8 w-8 p-0">
              <X className="h-5 w-5" />
            </Button>
          </div>
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

function VLANDevicesModal({ vlan, devices, onClose, onSetDefault, onAddDevice }: { vlan: VLAN; devices: Device[]; onClose: () => void; onSetDefault: (deviceId: string | null) => void; onAddDevice: () => void }) {
  const t = useTranslations('vlans')
  const tCommon = useTranslations('common')
  const tDevices = useTranslations('devices')

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4 !mt-0">
      <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full max-h-[80vh] overflow-y-auto">
        <div className="p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-bold text-gray-900">
              {t('devicesInVlan')} — {vlan.name}
            </h2>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={onAddDevice}
                title={t('addDevice')}
                className="h-8 gap-1"
              >
                <Plus className="h-4 w-4" />
                {tDevices('createTitle')}
              </Button>
              <Button variant="ghost" size="sm" onClick={onClose} className="h-8 w-8 p-0">
                <X className="h-5 w-5" />
              </Button>
            </div>
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

// ============================================================================
// Helpers
// ============================================================================

function isValidIP(ip: string): boolean {
  const trimmed = ip.trim()
  if (!trimmed) return false
  const ipv4Regex = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/
  const ipv4Match = trimmed.match(ipv4Regex)
  if (ipv4Match) {
    return ipv4Match.slice(1).every((octet) => {
      const num = parseInt(octet, 10)
      return num >= 0 && num <= 255
    })
  }
  const ipv6Regex = /^([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}$/
  return ipv6Regex.test(trimmed)
}

// ============================================================================
// Modal: Crear dispositivo desde una VLAN (sin seleccionar org/vlan)
// ============================================================================

function CreateDeviceFromVLANModal({
  vlan,
  orgName,
  onClose,
  onSuccess,
}: {
  vlan: VLAN
  orgName: string
  onClose: () => void
  onSuccess: () => void
}) {
  const t = useTranslations('devices')
  const tCommon = useTranslations('common')
  const [loading, setLoading] = useState(false)
  const [ipError, setIpError] = useState('')
  const [formData, setFormData] = useState<DeviceCreate>({
    organization_id: vlan.organization_id,
    vlan_id: vlan.id,
    name: '',
    ip_address: '',
    description: '',
    model: '',
    location: '',
    port: 9100,
    is_active: true,
  })

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
      await apiClient.post('/devices/', formData)
      onSuccess()
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } }
      alert(err.response?.data?.detail || 'Error al crear dispositivo')
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
          <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-md">
            <div className="flex items-center gap-2">
              <Network className="h-4 w-4 text-blue-600 flex-shrink-0" />
              <div className="text-sm">
                <span className="text-blue-700 font-medium">{vlan.name}</span>
                {orgName && <span className="text-blue-500 ml-2">· {orgName}</span>}
              </div>
            </div>
          </div>
          <form onSubmit={handleSubmit} className="space-y-4">
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
                  onChange={(e) => { setFormData({ ...formData, ip_address: e.target.value }); if (ipError) setIpError('') }}
                  onBlur={() => { if (formData.ip_address.trim() && !isValidIP(formData.ip_address)) setIpError(t('ipInvalid')) }}
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
                id="add_device_is_active"
                checked={formData.is_active}
                onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
                className="rounded mr-2"
              />
              <label htmlFor="add_device_is_active" className="text-sm text-gray-700">{t('activeLabel')}</label>
            </div>
            <div className="flex justify-end gap-3 pt-4">
              <Button type="button" variant="outline" onClick={onClose} disabled={loading}>{tCommon('cancel')}</Button>
              <Button
                type="submit"
                disabled={loading || !formData.name.trim() || !formData.ip_address.trim()}
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
