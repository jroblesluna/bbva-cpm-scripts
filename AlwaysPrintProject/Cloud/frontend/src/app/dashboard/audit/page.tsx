/**
 * Página de auditoría del sistema.
 */

'use client'

import { useState, useEffect } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  FileText,
  Search,
  Calendar,
  User,
  Activity,
  TrendingUp,
} from 'lucide-react'
import type { AuditLog, AuditLogStats, ActionType } from '@/types/audit'
import { formatDateWithTimezone } from '@/lib/dateUtils'
import { useUserTimezone } from '@/hooks/useUserTimezone'

export default function AuditPage() {
  const { getAuthHeaders } = useAuth()
  const timezone = useUserTimezone()
  const t = useTranslations('audit')
  const tCommon = useTranslations('common')
  const [logs, setLogs] = useState<AuditLog[]>([])
  const [stats, setStats] = useState<AuditLogStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [filterActionType, setFilterActionType] = useState<ActionType | null>(null)
  const [filterEntityType, setFilterEntityType] = useState<string>('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const pageSize = 50

  useEffect(() => {
    loadLogs()
    loadStats()
  }, [page, filterActionType, filterEntityType])

  const loadLogs = async () => {
    try {
      setLoading(true)
      const params = new URLSearchParams({ page: page.toString(), page_size: pageSize.toString() })
      if (filterActionType) params.append('action_type', filterActionType)
      if (filterEntityType) params.append('entity_type', filterEntityType)
      const response = await fetch(`/api/v1/audit/?${params.toString()}`, { headers: getAuthHeaders() })
      if (!response.ok) throw new Error('Error')
      const data = await response.json()
      setLogs(data.logs || [])
      setTotal(data.total || 0)
    } catch (error) {
      console.error('Error:', error)
    } finally {
      setLoading(false)
    }
  }

  const loadStats = async () => {
    try {
      const response = await fetch('/api/v1/audit/stats', { headers: getAuthHeaders() })
      if (!response.ok) throw new Error('Error')
      const data = await response.json()
      setStats(data)
    } catch (error) {
      console.error('Error:', error)
    }
  }

  const filteredLogs = logs.filter((log) => {
    const s = searchTerm.toLowerCase()
    return log.entity_type.toLowerCase().includes(s) || log.action_type.toLowerCase().includes(s) || log.entity_id.toLowerCase().includes(s)
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

  if (loading && page === 1) {
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
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-5 w-5 text-gray-400" />
            <Input type="text" placeholder={t('searchPlaceholder')} value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)} className="pl-10" />
          </div>
          <select value={filterActionType || 'all'}
            onChange={(e) => { setFilterActionType(e.target.value === 'all' ? null : (e.target.value as ActionType)); setPage(1) }}
            className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="all">{t('allTypes')}</option>
            <option value="create">{t('create')}</option>
            <option value="update">{t('update')}</option>
            <option value="delete">{t('delete')}</option>
            <option value="config_change">{t('configChange')}</option>
            <option value="contingency_toggle">{t('contingency')}</option>
            <option value="message_sent">{t('messageSent')}</option>
            <option value="command_sent">{t('commandSent')}</option>
          </select>
          <Input type="text" placeholder={t('filterEntity')} value={filterEntityType}
            onChange={(e) => { setFilterEntityType(e.target.value); setPage(1) }} />
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
                      <span className="text-sm text-gray-900">{log.entity_type}</span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="text-sm text-gray-500 font-mono">{log.entity_id.substring(0, 8)}...</span>
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

        {total > pageSize && (
          <div className="bg-white px-4 py-3 flex items-center justify-between border-t border-gray-200 sm:px-6">
            <div className="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between">
              <p className="text-sm text-gray-700">
                {t('pagination', { start: (page - 1) * pageSize + 1, end: Math.min(page * pageSize, total), total })}
              </p>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setPage(page - 1)} disabled={page === 1}>{tCommon('previous')}</Button>
                <Button variant="outline" onClick={() => setPage(page + 1)} disabled={page * pageSize >= total}>{tCommon('next')}</Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
