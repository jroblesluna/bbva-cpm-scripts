/**
 * Dashboard principal con estadísticas y métricas.
 */

'use client'

import { useState, useEffect } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Monitor, CheckCircle, Building2, Network, AlertCircle, Globe } from 'lucide-react'
import Link from 'next/link'
import { apiClient } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useTranslations } from 'next-intl'

interface WorkstationStats {
  total: number
  online: number
  offline: number
  contingency_active: number
  by_account?: Record<string, {
    name: string
    total: number
    online: number
    offline: number
    contingency: number
  }>
  by_vlan?: Record<string, number>
}

interface PendingIP {
  id: string
  ip_address: string
  first_seen: string
}

export default function DashboardPage() {
  const { user, isAdmin } = useAuth()
  const t = useTranslations('dashboard')
  const [stats, setStats] = useState<WorkstationStats | null>(null)
  const [pendingIPs, setPendingIPs] = useState<PendingIP[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!user) return
    const loadStats = async () => {
      try {
        setIsLoading(true)
        const response = await apiClient.get('/workstations/stats')
        setStats(response.data)
      } catch (err: any) {
        setError(err.message || 'Error al cargar estadísticas')
      } finally {
        setIsLoading(false)
      }
    }
    loadStats()
  }, [user])

  useEffect(() => {
    if (!user || !isAdmin()) return
    const loadPendingIPs = async () => {
      try {
        const response = await apiClient.get('/accounts/public-ips/pending')
        setPendingIPs(Array.isArray(response.data) ? response.data : [])
      } catch (err) {
        console.error('Error loading pending IPs:', err)
      }
    }
    loadPendingIPs()
  }, [user])

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto">
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
      <div className="max-w-7xl mx-auto">
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
    <div className="max-w-7xl mx-auto">
      <h1 className="text-3xl font-bold text-gray-900 mb-8">{t('title')}</h1>

      {/* Tarjetas de estadísticas */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">{t('totalStations')}</p>
                <p className="text-3xl font-bold text-gray-900">{stats?.total || 0}</p>
              </div>
              <div className="bg-blue-100 rounded-full p-3">
                <Monitor className="w-6 h-6 text-blue-600" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">{t('onlineStations')}</p>
                <p className="text-3xl font-bold text-green-600">{stats?.online || 0}</p>
                <p className="text-xs text-gray-500 mt-1">
                  {stats?.offline || 0} {t('offline')}
                </p>
              </div>
              <div className="bg-green-100 rounded-full p-3">
                <CheckCircle className="w-6 h-6 text-green-600" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-600">{t('activeContingency')}</p>
                <p className="text-3xl font-bold text-orange-600">
                  {stats?.contingency_active || 0}
                </p>
              </div>
              <div className="bg-orange-100 rounded-full p-3">
                <AlertCircle className="w-6 h-6 text-orange-600" />
              </div>
            </div>
          </CardContent>
        </Card>

        {isAdmin() && pendingIPs && pendingIPs.length > 0 ? (
          <Link href="/dashboard/admin/pending-ips">
            <Card className="hover:shadow-lg transition cursor-pointer border-amber-200 bg-amber-50">
              <CardContent className="p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-amber-700 font-medium">{t('pendingIps')}</p>
                    <p className="text-3xl font-bold text-amber-600">{pendingIPs.length}</p>
                    <p className="text-xs text-amber-600 mt-1">{t('requireAuthorization')}</p>
                  </div>
                  <div className="bg-amber-200 rounded-full p-3">
                    <Globe className="w-6 h-6 text-amber-700" />
                  </div>
                </div>
              </CardContent>
            </Card>
          </Link>
        ) : (
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-600">{t('vlans')}</p>
                  <p className="text-3xl font-bold text-gray-900">
                    {stats?.by_vlan ? Object.keys(stats.by_vlan).length : 0}
                  </p>
                </div>
                <div className="bg-purple-100 rounded-full p-3">
                  <Network className="w-6 h-6 text-purple-600" />
                </div>
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Distribución por VLAN */}
      {stats?.by_vlan && Object.keys(stats.by_vlan).length > 0 && (
        <Card className="mb-8">
          <CardHeader>
            <CardTitle>{t('vlanDistribution')}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {Object.entries(stats.by_vlan).map(([vlanId, count]) => (
                <div
                  key={vlanId}
                  className="flex items-center justify-between p-4 border border-gray-200 rounded-lg"
                >
                  <div>
                    <p className="text-sm font-medium text-gray-900">VLAN {vlanId}</p>
                    <p className="text-xs text-gray-500">{count} {t('stations')}</p>
                  </div>
                  <Badge variant="secondary">{count}</Badge>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Distribución por Cuenta */}
      {stats?.by_account && Object.keys(stats.by_account).length > 0 && (
        <Card className="mb-8">
          <CardHeader>
            <CardTitle>{t('accountsTitle')}</CardTitle>
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

      {/* Enlaces Rápidos */}
      <Card>
        <CardHeader>
          <CardTitle>{t('quickLinks')}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Link
              href="/dashboard/workstations"
              className="flex items-center p-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition"
            >
              <Monitor className="w-5 h-5 text-blue-600 mr-3" />
              <span className="font-medium text-gray-900">{t('manageStations')}</span>
            </Link>

            <Link
              href="/dashboard/vlans"
              className="flex items-center p-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition"
            >
              <Network className="w-5 h-5 text-purple-600 mr-3" />
              <span className="font-medium text-gray-900">{t('manageVlans')}</span>
            </Link>

            {isAdmin() ? (
              <Link
                href="/dashboard/admin/pending-ips"
                className="flex items-center p-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition"
              >
                <Globe className="w-5 h-5 text-amber-600 mr-3" />
                <div className="flex items-center">
                  <span className="font-medium text-gray-900">{t('pendingIps')}</span>
                  {pendingIPs && pendingIPs.length > 0 && (
                    <Badge variant="destructive" className="ml-2">
                      {pendingIPs.length}
                    </Badge>
                  )}
                </div>
              </Link>
            ) : (
              <Link
                href="/dashboard/config"
                className="flex items-center p-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition"
              >
                <Building2 className="w-5 h-5 text-gray-600 mr-3" />
                <span className="font-medium text-gray-900">{t('configuration')}</span>
              </Link>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
