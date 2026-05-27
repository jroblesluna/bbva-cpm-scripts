'use client'

import { useState, useEffect, useCallback } from 'react'
import { auditApi } from '@/lib/api'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  FileText,
  Search,
  User,
  Activity,
  TrendingUp,
  ChevronRight,
  RotateCcw,
} from 'lucide-react'
import type { AuditLog, AuditLogStats, ActionType } from '@/types/audit'
import { formatDateWithTimezone } from '@/lib/dateUtils'
import { useUserTimezone } from '@/hooks/useUserTimezone'

const PAGE_SIZE = 15

export default function AuditPage() {
  const timezone = useUserTimezone()
  const t = useTranslations('audit')
  const tCommon = useTranslations('common')

  const [logs, setLogs] = useState<AuditLog[]>([])
  const [stats, setStats] = useState<AuditLogStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)

  const [cursorHistory, setCursorHistory] = useState<string[]>([])
  const [currentCursor, setCurrentCursor] = useState<string | undefined>(undefined)

  const [searchTerm, setSearchTerm] = useState('')
  const [filterActionType, setFilterActionType] = useState<ActionType | null>(null)
  const [filterEntityType, setFilterEntityType] = useState<string>('')

  const isInitialLoad = logs.length === 0 && loading

  const loadLogs = useCallback(async (cursor?: string) => {
    try {
      if (logs.length === 0) setLoading(true)

      const data = await auditApi.search({
        limit: PAGE_SIZE,
        cursor,
        ...(filterActionType ? { action_type: filterActionType } : {}),
        ...(filterEntityType ? { entity_type: filterEntityType } : {}),
      })

      setLogs(data.logs || [])
      setTotal(data.total || 0)
      setNextCursor(data.next_cursor || null)
      setHasMore(data.has_more || false)
    } catch (error) {
      console.error('Error al cargar logs de auditoría:', error)
    } finally {
      setLoading(false)
    }
  }, [filterActionType, filterEntityType])

  const loadStats = async () => {
    try {
      const data = await auditApi.stats()
      setStats(data)
    } catch (error) {
      console.error('Error al cargar estadísticas:', error)
    }
  }

  useEffect(() => {
    loadLogs(currentCursor)
  }, [currentCursor, filterActionType, filterEntityType, loadLogs])

  useEffect(() => {
    loadStats()
  }, [])

  const goToNextPage = () => {
    if (!nextCursor) return
    setCursorHistory(prev => [...prev, currentCursor || ''])
    setCurrentCursor(nextCursor)
  }

  const goToPreviousPage = () => {
    if (cursorHistory.length === 0) return
    const history = [...cursorHistory]
    const previousCursor = history.pop()!
    setCursorHistory(history)
    setCurrentCursor(previousCursor || undefined)
  }

  const goToFirstPage = () => {
    setCursorHistory([])
    setCurrentCursor(undefined)
  }

  const resetFilters = () => {
    setFilterActionType(null)
    setFilterEntityType('')
    setSearchTerm('')
    setCursorHistory([])
    setCurrentCursor(undefined)
  }

  const filteredLogs = logs.filter((log) => {
    const s = searchTerm.toLowerCase()
    if (!s) return true
    return (
      log.entity_type.toLowerCase().includes(s) ||
      log.action_type.toLowerCase().includes(s) ||
      log.entity_id.toLowerCase().includes(s) ||
      (log.entity_name || '').toLowerCase().includes(s)
    )
  })

  const getActionTypeLabel = (type: ActionType): string => {
    const labels: Record<string, string> = {
      create: t('create'),
      update: t('update'),
      delete: t('delete'),
      config_change: t('configChange'),
      contingency_toggle: t('contingency'),
      message_sent: t('messageSent'),
      command_sent: t('commandSent'),
    }
    return labels[type] || type
  }

  const getActionTypeBadgeColor = (type: ActionType): string => {
    const colors: Record<string, string> = {
      create: 'bg-green-100 text-green-800',
      update: 'bg-blue-100 text-blue-800',
      delete: 'bg-red-100 text-red-800',
      config_change: 'bg-yellow-100 text-yellow-800',
      contingency_toggle: 'bg-orange-100 text-orange-800',
      message_sent: 'bg-indigo-100 text-indigo-800',
      command_sent: 'bg-purple-100 text-purple-800',
    }
    return colors[type] || 'bg-gray-100 text-gray-800'
  }

  const currentPageNumber = cursorHistory.length + 1

  if (isInitialLoad) {
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
      <div>
        <h1 className="text-3xl font-bold text-gray-900">{t('title')}</h1>
        <p className="mt-2 text-gray-600">{t('subtitle')}</p>
      </div>

      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="p-3 bg-blue-100 rounded-lg"><FileText className="h-6 w-6 text-blue-600" /></div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">{t('totalActions')}</p>
                <p className="text-2xl font-bold text-gray-900">{stats.total_actions}</p>
              </div>
            </div>
          </div>
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="p-3 bg-green-100 rounded-lg"><Activity className="h-6 w-6 text-green-600" /></div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">{t('last24h')}</p>
                <p className="text-2xl font-bold text-gray-900">{stats.recent_activity_count}</p>
              </div>
            </div>
          </div>
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="p-3 bg-purple-100 rounded-lg"><User className="h-6 w-6 text-purple-600" /></div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">{t('activeUsers')}</p>
                <p className="text-2xl font-bold text-gray-900">{stats.most_active_users.length}</p>
              </div>
            </div>
          </div>
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="p-3 bg-yellow-100 rounded-lg"><TrendingUp className="h-6 w-6 text-yellow-600" /></div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">{t('actionTypes')}</p>
                <p className="text-2xl font-bold text-gray-900">{Object.keys(stats.actions_by_type).length}</p>
              </div>
            </div>
          </div>
        </div>
      )}

      {stats && Object.keys(stats.actions_by_type).length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-medium text-gray-900 mb-4">{t('distribution')}</h3>
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

      <div className="bg-white rounded-lg shadow p-4">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-gray-400" />
            <Input
              type="text"
              placeholder={t('searchPlaceholder')}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-10"
            />
          </div>
          <select
            value={filterActionType || 'all'}
            onChange={(e) => {
              setFilterActionType(e.target.value === 'all' ? null : (e.target.value as ActionType))
              setCursorHistory([])
              setCurrentCursor(undefined)
            }}
            className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">{t('allTypes')}</option>
            <option value="create">{t('create')}</option>
            <option value="update">{t('update')}</option>
            <option value="delete">{t('delete')}</option>
            <option value="config_change">{t('configChange')}</option>
            <option value="contingency_toggle">{t('contingency')}</option>
            <option value="message_sent">{t('messageSent')}</option>
            <option value="command_sent">{t('commandSent')}</option>
          </select>
          <Input
            type="text"
            placeholder={t('filterEntity')}
            value={filterEntityType}
            onChange={(e) => {
              setFilterEntityType(e.target.value)
              setCursorHistory([])
              setCurrentCursor(undefined)
            }}
          />
          <Button variant="outline" onClick={resetFilters} className="flex items-center gap-2">
            <RotateCcw className="h-4 w-4" />
            {tCommon('reset')}
          </Button>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow overflow-hidden">
        {filteredLogs.length === 0 ? (
          <div className="text-center py-12">
            <FileText className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-2 text-sm font-medium text-gray-900">{t('emptyTitle')}</h3>
            <p className="mt-1 text-sm text-gray-500">
              {searchTerm || filterActionType || filterEntityType ? t('emptyFilterMessage') : t('emptyMessage')}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colDate')}</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colAction')}</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colEntity')}</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colEntityId')}</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colIp')}</th>
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
                      <span className="inline-flex items-center gap-1.5">
                        <span className="text-xs font-medium text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">{log.entity_type}</span>
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {log.entity_name ? (
                        <div>
                          <span className="text-sm font-medium text-gray-900">{log.entity_name}</span>
                          <span className="block text-xs text-gray-400 font-mono">{log.entity_id.substring(0, 8)}</span>
                        </div>
                      ) : (
                        <span className="text-sm text-gray-500 font-mono">{log.entity_id.substring(0, 8)}...</span>
                      )}
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

        {(hasMore || cursorHistory.length > 0) && (
          <div className="bg-white px-4 py-3 flex items-center justify-between border-t border-gray-200 sm:px-6">
            <div className="flex-1 flex items-center justify-between">
              <p className="text-sm text-gray-700">
                {t('pagination', {
                  start: (currentPageNumber - 1) * PAGE_SIZE + 1,
                  end: Math.min(currentPageNumber * PAGE_SIZE, total),
                  total,
                })}
              </p>
              <div className="flex items-center gap-2">
                {cursorHistory.length > 0 && (
                  <Button variant="outline" size="sm" onClick={goToFirstPage}>
                    {tCommon('first')}
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={goToPreviousPage}
                  disabled={cursorHistory.length === 0}
                >
                  {tCommon('previous')}
                </Button>
                <span className="text-sm text-gray-600 px-2">
                  {t('pageNumber', { page: currentPageNumber })}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={goToNextPage}
                  disabled={!hasMore}
                >
                  {tCommon('next')}
                  <ChevronRight className="h-4 w-4 ml-1" />
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
