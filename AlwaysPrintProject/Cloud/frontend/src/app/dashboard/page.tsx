/**
 * Dashboard principal con estadísticas y métricas.
 * Polling automático cada 10 segundos.
 */

'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Monitor, CheckCircle, Building2, Network, AlertCircle, Globe, RefreshCw, Printer, Settings, AlertTriangle, X, Eye, ShieldAlert, Lock } from 'lucide-react'
import { PieChart, Pie, Cell } from 'recharts'
import Link from 'next/link'
import { apiClient } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useTranslations } from 'next-intl'
import { formatDateWithTimezone } from '@/lib/dateUtils'
import { useUserTimezone } from '@/hooks/useUserTimezone'

// Intervalo de polling en milisegundos (10 segundos)
const POLLING_INTERVAL = 10_000

interface WorkstationStats {
  total: number
  online: number
  offline: number
  contingency_active: number
  total_vlans: number
  by_account?: Record<string, {
    name: string
    total: number
    online: number
    offline: number
    contingency: number
  }>
  by_vlan?: Record<string, number>
  vlan_summary?: VLANSummaryItem[]
  organization_info?: OrganizationInfoData
  workstations_with_config?: WorkstationConfigItemData[]
}

interface VLANSummaryItem {
  id: string
  name: string
  has_devices: boolean
  device_count: number
  workstation_count: number
  has_vlan_config: boolean
  workstations_with_config: number
  forced_contingency: boolean
}

interface OrganizationInfoData {
  id: string
  name: string
  forced_contingency: boolean
  has_org_config: boolean
  action_config_mandatory: boolean
}

interface WorkstationConfigItemData {
  id: string
  ip_private: string
  hostname: string | null
  vlan_name: string | null
  config_name: string
}

interface OrgStats {
  total: number
  with_config: number
  applying_mandatory: number
  in_contingency: number
}

interface PendingIP {
  id: string
  ip_address: string
  first_seen: string
}

export default function DashboardPage() {
  const { user, isAdmin } = useAuth()
  const t = useTranslations('dashboard')
  const userTimezone = useUserTimezone()
  const [stats, setStats] = useState<WorkstationStats | null>(null)
  const [orgStats, setOrgStats] = useState<OrgStats | null>(null)
  const [pendingIPs, setPendingIPs] = useState<PendingIP[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const pollingRef = useRef<NodeJS.Timeout | null>(null)

  const loadStats = useCallback(async (silent = false) => {
    if (!user) return
    try {
      if (!silent) setIsLoading(true)
      setIsRefreshing(true)
      const response = await apiClient.get('/workstations/stats')
      setStats(response.data)
      setLastUpdated(new Date())
      setError(null)
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Error al cargar estadísticas'
      if (!silent) setError(errorMessage)
    } finally {
      if (!silent) setIsLoading(false)
      setIsRefreshing(false)
    }
  }, [user])

  const loadPendingIPs = useCallback(async () => {
    if (!user || !isAdmin()) return
    try {
      const response = await apiClient.get('/organizations/public-ips/pending')
      setPendingIPs(Array.isArray(response.data) ? response.data : [])
    } catch (err) {
      console.error('Error loading pending IPs:', err)
    }
  }, [user])

  const loadOrgStats = useCallback(async () => {
    if (!user || !isAdmin()) return
    try {
      const response = await apiClient.get('/organizations/stats')
      setOrgStats(response.data)
    } catch (err) {
      console.error('Error loading org stats:', err)
    }
  }, [user])

  // Carga inicial
  useEffect(() => {
    if (!user) return
    loadStats()
    loadPendingIPs()
    loadOrgStats()
  }, [user, loadStats, loadPendingIPs, loadOrgStats])

  // Polling cada 10 segundos
  useEffect(() => {
    if (!user) return

    pollingRef.current = setInterval(() => {
      loadStats(true) // silent = true para no mostrar skeleton
      loadPendingIPs()
      loadOrgStats()
    }, POLLING_INTERVAL)

    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
      }
    }
  }, [user, loadStats, loadPendingIPs, loadOrgStats])

  /**
   * Formatea la fecha/hora de última actualización con timezone del usuario.
   */
  const formatLastUpdated = (date: Date): string => {
    return formatDateWithTimezone(date, userTimezone)
  }

  if (isLoading) {
    return (
      <div className="max-w-screen-2xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-8">{t('title')}</h1>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {[1, 2, 3, 4].map((i) => (
            <Card key={i} className="animate-pulse">
              <CardContent className="p-6">
                <div className="h-20 bg-gray-200 rounded"></div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    console.error('Error en dashboard:', error)

    const isAuthError = error.includes('Not authenticated') || error.includes('autenticado')
    const isNetworkError = error.includes('Network Error') || error.includes('Failed to fetch')

    return (
      <div className="max-w-screen-2xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-8">{t('title')}</h1>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            {isAuthError ? (
              <>
                <strong>{t('sessionExpired')}</strong>
              </>
            ) : isNetworkError ? (
              <>
                <strong>{t('connectionError')}</strong>
                <div className="mt-3">
                  <Button onClick={() => window.location.reload()} size="sm" variant="outline">
                    {t('retry')}
                  </Button>
                </div>
              </>
            ) : (
              <>
                {t('loadError')}
                <div className="mt-2 text-xs font-mono bg-red-50 p-2 rounded">
                  {error}
                </div>
                <div className="mt-3">
                  <Button onClick={() => window.location.reload()} size="sm" variant="outline">
                    {t('retry')}
                  </Button>
                </div>
              </>
            )}
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  return (
    <div className="max-w-screen-2xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-3xl font-bold text-gray-900">{t('title')}</h1>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-gray-500">
              {t('lastUpdated', { time: formatLastUpdated(lastUpdated) })}
            </span>
          )}
          <div className={`transition-opacity ${isRefreshing ? 'opacity-100' : 'opacity-0'}`}>
            <RefreshCw className="w-4 h-4 text-blue-500 animate-spin" />
          </div>
        </div>
      </div>

      {/* IPs Pendientes (solo admin, si hay) */}
      {isAdmin() && pendingIPs && pendingIPs.length > 0 && (
        <Link href="/dashboard/admin/pending-ips">
          <Card className="mb-8 hover:shadow-lg transition cursor-pointer border-amber-200 bg-amber-50">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="bg-amber-200 rounded-full p-2">
                    <Globe className="w-5 h-5 text-amber-700" />
                  </div>
                  <div>
                    <p className="text-sm text-amber-700 font-medium">{t('pendingIps')}</p>
                    <p className="text-xs text-amber-600">{t('requireAuthorization')}</p>
                  </div>
                </div>
                <p className="text-2xl font-bold text-amber-600">{pendingIPs.length}</p>
              </div>
            </CardContent>
          </Card>
        </Link>
      )}

      {/* Sección Organizaciones — solo admin */}
      {isAdmin() && orgStats && (
        <Card className="mb-8">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Building2 className="w-5 h-5 text-blue-600" />
              {t('orgSectionTitle')}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="p-4 border border-gray-200 rounded-lg">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-gray-500">{t('orgTotal')}</p>
                    <p className="text-2xl font-bold text-gray-900">{orgStats.total}</p>
                  </div>
                  <div className="bg-blue-100 rounded-full p-2">
                    <Building2 className="w-5 h-5 text-blue-600" />
                  </div>
                </div>
              </div>

              <div className="p-4 border border-gray-200 rounded-lg">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-gray-500">{t('orgWithConfig')}</p>
                    <p className="text-2xl font-bold text-indigo-600">{orgStats.with_config}</p>
                  </div>
                  <div className="bg-indigo-100 rounded-full p-2">
                    <Settings className="w-5 h-5 text-indigo-600" />
                  </div>
                </div>
              </div>

              <div className="p-4 border border-gray-200 rounded-lg">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-gray-500">{t('orgApplyingMandatory')}</p>
                    <p className="text-2xl font-bold text-green-600">{orgStats.applying_mandatory}</p>
                  </div>
                  <div className="bg-green-100 rounded-full p-2">
                    <CheckCircle className="w-5 h-5 text-green-600" />
                  </div>
                </div>
              </div>

              <div className={`p-4 border rounded-lg ${orgStats.in_contingency > 0 ? 'border-orange-200 bg-orange-50' : 'border-gray-200'}`}>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-gray-500">{t('orgInContingency')}</p>
                    <p className="text-2xl font-bold text-orange-600">{orgStats.in_contingency}</p>
                  </div>
                  <div className={`rounded-full p-2 ${orgStats.in_contingency > 0 ? 'bg-orange-100' : 'bg-orange-50'}`}>
                    <AlertTriangle className={`w-5 h-5 ${orgStats.in_contingency > 0 ? 'text-orange-600' : 'text-orange-400'}`} />
                  </div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* === SECCIÓN 1: ORGANIZACIÓN === */}
      {stats?.organization_info && (
        <OrganizationSection orgInfo={stats.organization_info} t={t} />
      )}

      {/* === SECCIÓN 2: VLANs === */}
      {stats?.vlan_summary && stats.vlan_summary.length > 0 && (
        <VLANStatusSection stats={stats} t={t} />
      )}

      {/* === SECCIÓN 3: ESTACIONES === */}
      <StationsSection stats={stats} t={t} />

      {/* Donuts de contingencia — solo admin */}
      {isAdmin() && stats && orgStats && (
        <ContingencyDonuts stats={stats} orgStats={orgStats} t={t} />
      )}

      {/* Distribución por Cuenta (solo admin) */}
      {stats?.by_account && Object.keys(stats.by_account).length > 0 && (
        <Card className="mb-8">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Building2 className="w-5 h-5 text-blue-600" />
              {t('accountsTitle')}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {Object.entries(stats.by_account).map(([accountId, accountData]) => (
                <div
                  key={accountId}
                  className="p-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition"
                >
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center">
                      <Building2 className="w-5 h-5 text-blue-600 mr-3" />
                      <h3 className="text-lg font-semibold text-gray-900">
                        {accountData.name}
                      </h3>
                    </div>
                    <Badge variant="outline" className="text-sm">
                      {accountData.total} {t('stations')}
                    </Badge>
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="text-center p-3 bg-blue-50 rounded-lg">
                      <p className="text-2xl font-bold text-blue-600">{accountData.total}</p>
                      <p className="text-xs text-gray-600 mt-1">{t('total')}</p>
                    </div>
                    <div className="text-center p-3 bg-green-50 rounded-lg">
                      <p className="text-2xl font-bold text-green-600">{accountData.online}</p>
                      <p className="text-xs text-gray-600 mt-1">{t('online')}</p>
                    </div>
                    <div className="text-center p-3 bg-gray-50 rounded-lg">
                      <p className="text-2xl font-bold text-gray-600">{accountData.offline}</p>
                      <p className="text-xs text-gray-600 mt-1">{t('offline')}</p>
                    </div>
                    <div className="text-center p-3 bg-orange-50 rounded-lg">
                      <p className="text-2xl font-bold text-orange-600">{accountData.contingency}</p>
                      <p className="text-xs text-gray-600 mt-1">{t('contingency')}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

// ============================================================================
// Componente: Sección de Estaciones (cards resumen + modal detalle)
// ============================================================================

function StationsSection({ stats, t }: { stats: WorkstationStats | null; t: ReturnType<typeof useTranslations> }) {
  const [showModal, setShowModal] = useState(false)

  const wsWithConfig = stats?.workstations_with_config?.length || 0

  return (
    <>
      <Card className="mb-8">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Monitor className="w-5 h-5 text-blue-600" />
              {t('sectionStations')}
            </CardTitle>
            {wsWithConfig > 0 && (
              <Button variant="outline" size="sm" onClick={() => setShowModal(true)} className="gap-1.5">
                <Eye className="w-4 h-4" />
                {t('vlanShowMore')}
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="p-4 border border-gray-200 rounded-lg">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-gray-500">{t('totalStations')}</p>
                  <p className="text-2xl font-bold text-gray-900">{stats?.total || 0}</p>
                </div>
                <div className="bg-blue-100 rounded-full p-2">
                  <Monitor className="w-5 h-5 text-blue-600" />
                </div>
              </div>
            </div>

            <div className="p-4 border border-gray-200 rounded-lg">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-gray-500">{t('onlineStations')}</p>
                  <p className="text-2xl font-bold text-gray-900">{stats?.online || 0}</p>
                  <p className="text-xs text-gray-400 mt-0.5">{stats?.offline || 0} {t('offline')}</p>
                </div>
                <div className="bg-green-100 rounded-full p-2">
                  <CheckCircle className="w-5 h-5 text-green-600" />
                </div>
              </div>
            </div>

            <div className={`p-4 border rounded-lg ${(stats?.contingency_active || 0) > 0 ? 'border-orange-200 bg-orange-50' : 'border-gray-200'}`}>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-gray-500">{t('activeContingency')}</p>
                  <p className="text-2xl font-bold text-gray-900">
                    {stats?.contingency_active || 0}
                  </p>
                </div>
                <div className={`rounded-full p-2 ${(stats?.contingency_active || 0) > 0 ? 'bg-orange-100' : 'bg-orange-50'}`}>
                  <ShieldAlert className={`w-5 h-5 ${(stats?.contingency_active || 0) > 0 ? 'text-orange-600' : 'text-orange-400'}`} />
                </div>
              </div>
            </div>

            <div className="p-4 border border-gray-200 rounded-lg">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-gray-500">{t('stationsWithConfig')}</p>
                  <p className="text-2xl font-bold text-gray-900">{wsWithConfig}</p>
                </div>
                <div className="bg-green-100 rounded-full p-2">
                  <Settings className="w-5 h-5 text-green-600" />
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Modal: Workstations con config propia */}
      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4 !mt-0">
          <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full max-h-[80vh] overflow-hidden flex flex-col">
            <div className="flex items-center justify-between p-6 border-b border-gray-200">
              <h2 className="text-xl font-bold text-gray-900">{t('stationsConfigModalTitle')}</h2>
              <Button type="button" variant="ghost" size="sm" onClick={() => setShowModal(false)} className="h-8 w-8 p-0">
                <X className="h-5 w-5" />
              </Button>
            </div>
            <div className="overflow-y-auto p-6">
              <div className="space-y-3">
                {(stats?.workstations_with_config || []).map((ws) => (
                  <div
                    key={ws.id}
                    className="flex flex-col md:flex-row md:items-center md:justify-between p-4 border border-gray-200 rounded-lg gap-3"
                  >
                    <div className="flex items-center gap-3">
                      <Monitor className="w-5 h-5 text-blue-600 flex-shrink-0" />
                      <div>
                        <p className="text-sm font-medium text-gray-900">{ws.hostname || ws.ip_private}</p>
                        <p className="text-xs text-gray-500">
                          {ws.ip_private}{ws.vlan_name ? ` · ${ws.vlan_name}` : ''}
                        </p>
                      </div>
                    </div>
                    <Badge variant="outline" className="text-xs gap-1 border-green-300 text-green-700">
                      <Settings className="w-3 h-3" />
                      {ws.config_name}
                    </Badge>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ============================================================================
// Componente: Sección de Organización
// ============================================================================

function OrganizationSection({ orgInfo, t }: { orgInfo: OrganizationInfoData; t: ReturnType<typeof useTranslations> }) {
  return (
    <Card className="mb-8">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Building2 className="w-5 h-5 text-blue-600" />
          {t('sectionOrganization')}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Contingencia a nivel org */}
          <div className={`p-4 border rounded-lg ${orgInfo.forced_contingency ? 'border-orange-200 bg-orange-50' : 'border-gray-200'}`}>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-gray-500">{t('orgContingency')}</p>
                <p className={`text-sm font-semibold mt-1 ${orgInfo.forced_contingency ? 'text-orange-700' : 'text-gray-900'}`}>
                  {orgInfo.forced_contingency ? t('orgContingencyActive') : t('orgContingencyInactive')}
                </p>
              </div>
              <div className={`rounded-full p-2 ${orgInfo.forced_contingency ? 'bg-orange-100' : 'bg-orange-50'}`}>
                <ShieldAlert className={`w-5 h-5 ${orgInfo.forced_contingency ? 'text-orange-600' : 'text-orange-400'}`} />
              </div>
            </div>
          </div>

          {/* Config a nivel org */}
          <div className={`p-4 border rounded-lg ${!orgInfo.has_org_config ? 'border-red-200 bg-red-50' : 'border-gray-200'}`}>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-gray-500">{t('orgConfig')}</p>
                <p className={`text-sm font-semibold mt-1 ${orgInfo.has_org_config ? 'text-gray-900' : 'text-red-700'}`}>
                  {orgInfo.has_org_config ? t('orgConfigActive') : t('orgConfigMissing')}
                </p>
              </div>
              <div className={`rounded-full p-2 ${orgInfo.has_org_config ? 'bg-green-100' : 'bg-red-100'}`}>
                <Settings className={`w-5 h-5 ${orgInfo.has_org_config ? 'text-green-600' : 'text-red-600'}`} />
              </div>
            </div>
          </div>

          {/* Config mandatory */}
          <div className="p-4 border border-gray-200 rounded-lg">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs text-gray-500">{t('orgMandatory')}</p>
                <p className="text-sm font-semibold mt-1 text-gray-900">
                  {orgInfo.action_config_mandatory ? t('orgMandatoryYes') : t('orgMandatoryNo')}
                </p>
              </div>
              <div className={`rounded-full p-2 ${orgInfo.action_config_mandatory ? 'bg-indigo-100' : 'bg-gray-100'}`}>
                <Lock className={`w-5 h-5 ${orgInfo.action_config_mandatory ? 'text-indigo-600' : 'text-gray-400'}`} />
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// ============================================================================
// Componente: Sección de Estado de VLANs (cards resumen + modal detalle)
// ============================================================================

function VLANStatusSection({ stats, t }: { stats: WorkstationStats; t: ReturnType<typeof useTranslations> }) {
  const [showModal, setShowModal] = useState(false)

  const vlanSummary = stats.vlan_summary || []
  const vlansWithoutDevices = vlanSummary.filter(v => !v.has_devices).length
  const vlansWithConfig = vlanSummary.filter(v => v.has_vlan_config).length
  const vlansWithoutConfig = vlanSummary.filter(v => !v.has_vlan_config).length
  const vlansInContingency = vlanSummary.filter(v => v.forced_contingency).length

  return (
    <>
      <Card className="mb-8">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Network className="w-5 h-5 text-purple-600" />
              {t('sectionVlans')}
            </CardTitle>
            <Button variant="outline" size="sm" onClick={() => setShowModal(true)} className="gap-1.5">
              <Eye className="w-4 h-4" />
              {t('vlanShowMore')}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="p-4 border border-gray-200 rounded-lg">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-gray-500">{t('vlanCardTotal')}</p>
                  <p className="text-2xl font-bold text-gray-900">{vlanSummary.length}</p>
                </div>
                <div className="bg-purple-100 rounded-full p-2">
                  <Network className="w-5 h-5 text-purple-600" />
                </div>
              </div>
            </div>

            <div className={`p-4 border rounded-lg ${vlansWithoutDevices > 0 ? 'border-orange-200 bg-orange-50' : 'border-gray-200'}`}>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-gray-500">{t('vlanCardNoDevices')}</p>
                  <p className="text-2xl font-bold text-gray-900">{vlansWithoutDevices}</p>
                </div>
                <div className={`rounded-full p-2 ${vlansWithoutDevices > 0 ? 'bg-orange-100' : 'bg-gray-100'}`}>
                  <AlertTriangle className={`w-5 h-5 ${vlansWithoutDevices > 0 ? 'text-orange-600' : 'text-gray-400'}`} />
                </div>
              </div>
            </div>

            <div className="p-4 border border-gray-200 rounded-lg">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-gray-500">{t('vlanCardWithConfig')}</p>
                  <p className="text-2xl font-bold text-gray-900">{vlansWithConfig}</p>
                </div>
                <div className="bg-green-100 rounded-full p-2">
                  <Settings className="w-5 h-5 text-green-600" />
                </div>
              </div>
            </div>

            <div className={`p-4 border rounded-lg ${vlansInContingency > 0 ? 'border-orange-200 bg-orange-50' : 'border-gray-200'}`}>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-gray-500">{t('vlanCardContingency')}</p>
                  <p className="text-2xl font-bold text-gray-900">{vlansInContingency}</p>
                </div>
                <div className={`rounded-full p-2 ${vlansInContingency > 0 ? 'bg-orange-100' : 'bg-orange-50'}`}>
                  <ShieldAlert className={`w-5 h-5 ${vlansInContingency > 0 ? 'text-orange-600' : 'text-orange-400'}`} />
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Modal de detalle de VLANs */}
      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4 !mt-0">
          <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full max-h-[80vh] overflow-hidden flex flex-col">
            <div className="flex items-center justify-between p-6 border-b border-gray-200">
              <h2 className="text-xl font-bold text-gray-900">{t('vlanSummaryTitle')}</h2>
              <div className="flex items-center gap-2">
                {vlansWithoutDevices > 0 && (
                  <Badge variant="destructive" className="text-xs">
                    {vlansWithoutDevices} {t('vlanSummaryNoDevices')}
                  </Badge>
                )}
                <Button type="button" variant="ghost" size="sm" onClick={() => setShowModal(false)} className="h-8 w-8 p-0">
                  <X className="h-5 w-5" />
                </Button>
              </div>
            </div>
            <div className="overflow-y-auto p-6">
              <div className="space-y-3">
                {vlanSummary.filter(v => !v.has_devices || v.has_vlan_config).map((vlan) => (
                  <div
                    key={vlan.id}
                    className={`flex flex-col md:flex-row md:items-center md:justify-between p-4 border rounded-lg gap-3 ${
                      !vlan.has_devices ? 'border-red-200 bg-red-50' : 'border-gray-200'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <Network className="w-5 h-5 text-purple-600 flex-shrink-0" />
                      <div>
                        <p className="text-sm font-medium text-gray-900">{vlan.name}</p>
                        <p className="text-xs text-gray-500">
                          {vlan.workstation_count} {t('stations')}
                        </p>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      {vlan.has_devices ? (
                        <Badge variant="outline" className="text-xs gap-1">
                          <Printer className="w-3 h-3" />
                          {vlan.device_count} {t('vlanSummaryDevices')}
                        </Badge>
                      ) : (
                        <Badge variant="destructive" className="text-xs gap-1">
                          <AlertTriangle className="w-3 h-3" />
                          {t('vlanSummaryNoDevicesLabel')}
                        </Badge>
                      )}

                      {vlan.has_vlan_config ? (
                        <Badge variant="outline" className="text-xs gap-1 border-green-300 text-green-700">
                          <Settings className="w-3 h-3" />
                          {t('vlanSummaryHasConfig')}
                        </Badge>
                      ) : (
                        <Badge variant="secondary" className="text-xs gap-1">
                          <Settings className="w-3 h-3" />
                          {t('vlanSummaryNoConfig')}
                        </Badge>
                      )}

                      {vlan.workstations_with_config > 0 && (
                        <Badge variant="outline" className="text-xs gap-1 border-blue-300 text-blue-700">
                          <Monitor className="w-3 h-3" />
                          {t('vlanSummaryWsWithConfig', { count: vlan.workstations_with_config })}
                        </Badge>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ============================================================================
// Componente: Donuts de contingencia
// ============================================================================

const DONUT_COLORS = {
  contingency: '#f97316',
  normal: '#e5e7eb',
}

function DonutChart({ active, total, label }: { active: number; total: number; label: string }) {
  const pct = total > 0 ? Math.round((active / total) * 100) : 0
  const data = [
    { value: active },
    { value: Math.max(total - active, 0) },
  ]

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative">
        <PieChart width={140} height={140}>
          <Pie
            data={data}
            cx={65}
            cy={65}
            innerRadius={46}
            outerRadius={62}
            startAngle={90}
            endAngle={-270}
            dataKey="value"
            strokeWidth={0}
          >
            <Cell fill={DONUT_COLORS.contingency} />
            <Cell fill={DONUT_COLORS.normal} />
          </Pie>
        </PieChart>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <span className="text-2xl font-bold text-orange-500">{pct}%</span>
          <span className="text-xs text-gray-400">{active}/{total}</span>
        </div>
      </div>
      <p className="text-sm font-medium text-gray-700 text-center">{label}</p>
      <div className="flex items-center gap-3 text-xs text-gray-500">
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-full bg-orange-500" />
          Contingencia
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 rounded-full bg-gray-200 border border-gray-300" />
          Normal
        </span>
      </div>
    </div>
  )
}

function ContingencyDonuts({
  stats,
  orgStats,
}: {
  stats: WorkstationStats
  orgStats: OrgStats
  t: ReturnType<typeof useTranslations>
}) {
  const vlansInContingency = stats.vlan_summary?.filter(v => v.forced_contingency).length ?? 0
  const totalVlans = stats.vlan_summary?.length ?? stats.total_vlans

  return (
    <Card className="mb-8">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <AlertTriangle className="w-4 h-4 text-orange-500" />
          Contingencia activa
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-3 gap-6 justify-items-center">
          <DonutChart
            active={stats.contingency_active}
            total={stats.total}
            label="Estaciones"
          />
          <DonutChart
            active={vlansInContingency}
            total={totalVlans}
            label="VLANs"
          />
          <DonutChart
            active={orgStats.in_contingency}
            total={orgStats.total}
            label="Organizaciones"
          />
        </div>
      </CardContent>
    </Card>
  )
}
