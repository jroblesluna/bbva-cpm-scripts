/**
 * Página de timeline de actividad de un usuario.
 *
 * Muestra el historial completo de acciones con filtrado por rango de fechas,
 * paginación por cursor y exportación CSV.
 */

'use client'

import { useState, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { usersApi } from '@/lib/api'
import { useTranslations } from 'next-intl'
import { useToast } from '@/hooks/use-toast'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  ArrowLeft,
  Download,
  Calendar,
  Activity,
  AlertCircle,
  User,
  Mail,
  Clock,
  Globe,
  Loader2,
} from 'lucide-react'
import { formatDateWithTimezone } from '@/lib/dateUtils'
import { useUserTimezone } from '@/hooks/useUserTimezone'
import type { AuditLog } from '@/types'

/** Clase CSS de color del badge según action_type */
function getActionBadgeClass(actionType: string): string {
  switch (actionType) {
    case 'create':
      return 'bg-green-100 text-green-800 border-green-200'
    case 'update':
      return 'bg-blue-100 text-blue-800 border-blue-200'
    case 'delete':
      return 'bg-red-100 text-red-800 border-red-200'
    case 'login':
      return 'bg-indigo-100 text-indigo-800 border-indigo-200'
    case 'login_failed':
      return 'bg-orange-100 text-orange-800 border-orange-200'
    case 'config_change':
      return 'bg-purple-100 text-purple-800 border-purple-200'
    case 'contingency_toggle':
      return 'bg-yellow-100 text-yellow-800 border-yellow-200'
    default:
      return 'bg-gray-100 text-gray-800 border-gray-200'
  }
}

export default function UserActivityPage() {
  const params = useParams()
  const userId = params.userId as string
  const router = useRouter()
  const t = useTranslations('timeline')
  const tCommon = useTranslations('common')
  const { toast } = useToast()
  const userTimezone = useUserTimezone()

  // Estado de filtros
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')

  // Estado de paginación
  const [cursor, setCursor] = useState<string | undefined>(undefined)
  const [allLogs, setAllLogs] = useState<AuditLog[]>([])
  const [hasMore, setHasMore] = useState(false)
  const [totalCount, setTotalCount] = useState(0)

  // Estado de UI
  const [isExporting, setIsExporting] = useState(false)
  const [isLoadingMore, setIsLoadingMore] = useState(false)

  // Obtener info del usuario
  const { data: targetUser, isLoading: userLoading } = useQuery({
    queryKey: ['users', userId],
    queryFn: () => usersApi.get(userId),
  })

  // Obtener actividad (primera página)
  const { isLoading: activityLoading, error: activityError, refetch } = useQuery({
    queryKey: ['user-activity', userId, startDate, endDate],
    queryFn: async () => {
      const queryParams: {
        start_date?: string
        end_date?: string
        cursor?: string
        limit?: number
      } = { limit: 15 }
      if (startDate) queryParams.start_date = new Date(startDate).toISOString()
      if (endDate) queryParams.end_date = new Date(endDate).toISOString()
      const result = await usersApi.activity(userId, queryParams)
      setAllLogs(result.logs)
      setHasMore(result.has_more)
      setTotalCount(result.total)
      setCursor(result.next_cursor || undefined)
      return result
    },
  })

  // Cargar más resultados
  const handleLoadMore = useCallback(async () => {
    if (!cursor) return
    setIsLoadingMore(true)
    try {
      const queryParams: {
        start_date?: string
        end_date?: string
        cursor?: string
        limit?: number
      } = { limit: 15, cursor }
      if (startDate) queryParams.start_date = new Date(startDate).toISOString()
      if (endDate) queryParams.end_date = new Date(endDate).toISOString()
      const result = await usersApi.activity(userId, queryParams)
      setAllLogs(prev => [...prev, ...result.logs])
      setHasMore(result.has_more)
      setCursor(result.next_cursor || undefined)
    } catch {
      toast({
        variant: 'destructive',
        title: t('errors.loadFailed'),
      })
    } finally {
      setIsLoadingMore(false)
    }
  }, [cursor, startDate, endDate, userId, toast, t])

  // Exportar CSV
  const handleExport = useCallback(async () => {
    setIsExporting(true)
    try {
      const queryParams: {
        start_date?: string
        end_date?: string
      } = {}
      if (startDate) queryParams.start_date = new Date(startDate).toISOString()
      if (endDate) queryParams.end_date = new Date(endDate).toISOString()
      await usersApi.exportActivity(userId, queryParams)
    } catch {
      toast({
        variant: 'destructive',
        title: t('errors.exportFailed'),
        description: t('errors.exportFailedDescription'),
      })
    } finally {
      setIsExporting(false)
    }
  }, [startDate, endDate, userId, toast, t])

  // Aplicar filtros de fecha (reset paginación)
  const handleApplyFilters = useCallback(() => {
    setCursor(undefined)
    setAllLogs([])
    setHasMore(false)
    refetch()
  }, [refetch])

  // Loading state
  if (userLoading) {
    return (
      <div className="max-w-screen-2xl mx-auto">
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-gray-200 rounded w-48"></div>
          <div className="h-24 bg-gray-200 rounded-lg"></div>
          <div className="h-64 bg-gray-200 rounded-lg"></div>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-screen-2xl mx-auto">
      {/* Botón volver + Encabezado */}
      <div className="mb-6">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.push('/dashboard/admin/users')}
          className="mb-4"
        >
          <ArrowLeft className="w-4 h-4 mr-2" />
          {t('backToUsers')}
        </Button>

        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-2">
              <Activity className="w-8 h-8 text-blue-600" />
              {t('title')}
            </h1>
            {targetUser && (
              <div className="flex flex-wrap items-center gap-4 mt-2 text-sm text-gray-600">
                <span className="flex items-center gap-1">
                  <User className="w-4 h-4" />
                  {targetUser.full_name}
                </span>
                <span className="flex items-center gap-1">
                  <Mail className="w-4 h-4" />
                  {targetUser.email}
                </span>
              </div>
            )}
          </div>

          {/* Botón exportar */}
          <Button
            onClick={handleExport}
            disabled={isExporting || activityLoading}
          >
            {isExporting ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : (
              <Download className="w-4 h-4 mr-2" />
            )}
            {t('exportCsv')}
          </Button>
        </div>
      </div>

      {/* Filtros de fecha */}
      <Card className="mb-6">
        <CardContent className="p-4">
          <div className="flex flex-col md:flex-row gap-4 items-end">
            <div className="flex-1">
              <Label htmlFor="start_date" className="flex items-center gap-1 mb-1.5">
                <Calendar className="w-3.5 h-3.5" />
                {t('dateRange.start')}
              </Label>
              <Input
                id="start_date"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div className="flex-1">
              <Label htmlFor="end_date" className="flex items-center gap-1 mb-1.5">
                <Calendar className="w-3.5 h-3.5" />
                {t('dateRange.end')}
              </Label>
              <Input
                id="end_date"
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
            <Button variant="outline" onClick={handleApplyFilters}>
              {t('applyFilters')}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Contador de resultados */}
      {!activityLoading && !activityError && (
        <div className="mb-4">
          <Badge variant="outline" className="text-sm">
            {t('totalResults', { count: totalCount })}
          </Badge>
        </div>
      )}

      {/* Error state */}
      {activityError && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{t('errors.loadFailed')}</AlertDescription>
        </Alert>
      )}

      {/* Loading state de actividad */}
      {activityLoading && (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 bg-gray-200 rounded-lg animate-pulse"></div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!activityLoading && !activityError && allLogs.length === 0 && (
        <Card>
          <CardContent className="p-12 text-center">
            <Activity className="w-16 h-16 text-gray-300 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">
              {t('emptyState')}
            </h3>
          </CardContent>
        </Card>
      )}

      {/* Lista de actividad */}
      {!activityLoading && allLogs.length > 0 && (
        <div className="space-y-3">
          {allLogs.map((log) => (
            <Card key={log.id} className="hover:shadow-sm transition">
              <CardContent className="p-4">
                <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
                  {/* Info principal */}
                  <div className="flex-1">
                    <div className="flex flex-wrap items-center gap-2 mb-1">
                      <Badge
                        variant="outline"
                        className={getActionBadgeClass(log.action_type)}
                      >
                        {log.action_type}
                      </Badge>
                      <span className="text-sm font-medium text-gray-700">
                        {log.entity_type}
                      </span>
                      {log.entity_name && (
                        <span className="text-sm text-gray-600">
                          — {log.entity_name}
                        </span>
                      )}
                    </div>

                    {/* Datos secundarios */}
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500 mt-1">
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {formatDateWithTimezone(log.created_at, userTimezone)}
                      </span>
                      {log.ip_address && (
                        <span className="flex items-center gap-1">
                          <Globe className="w-3 h-3" />
                          {log.ip_address}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Botón cargar más */}
      {hasMore && !activityLoading && (
        <div className="mt-6 flex justify-center">
          <Button
            variant="outline"
            onClick={handleLoadMore}
            disabled={isLoadingMore}
          >
            {isLoadingMore ? (
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            ) : null}
            {t('loadMore')}
          </Button>
        </div>
      )}
    </div>
  )
}
