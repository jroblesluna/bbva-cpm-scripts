/**
 * Página de gestión de mensajes a workstations.
 */

'use client'

import { useState, useEffect } from 'react'
import { apiClient } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useTranslations } from 'next-intl'
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
} from 'lucide-react'
import type { Message, MessageCreate, MessageStats, TargetType } from '@/types/message'
import type { Workstation } from '@/types/workstation'
import type { VLAN } from '@/types/vlan'
import { formatDateWithTimezone } from '@/lib/dateUtils'
import { useUserTimezone } from '@/hooks/useUserTimezone'

export default function MessagesPage() {
  const { getAuthHeaders } = useAuth()
  const timezone = useUserTimezone()
  const t = useTranslations('messages')
  const tCommon = useTranslations('common')
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

  useEffect(() => {
    loadMessages()
    loadStats()
  }, [page, filterDelivered, filterTargetType])

  const loadMessages = async () => {
    try {
      setLoading(true)
      const params = new URLSearchParams({ page: page.toString(), page_size: pageSize.toString() })
      if (filterDelivered !== null) params.append('is_delivered', filterDelivered.toString())
      if (filterTargetType) params.append('target_type', filterTargetType)
      const response = await apiClient.get(`/messages/?${params.toString()}`)
      const data = response.data
      setMessages(data.messages || [])
      setTotal(data.total || 0)
    } catch (error) {
      console.error('Error:', error)
    } finally {
      setLoading(false)
    }
  }

  const loadStats = async () => {
    try {
      const response = await apiClient.get('/messages/stats')
      const data = response.data
      setStats(data)
    } catch (error) {
      console.error('Error:', error)
    }
  }

  const filteredMessages = messages.filter((message) =>
    message.content.toLowerCase().includes(searchTerm.toLowerCase())
  )

  const getTargetTypeLabel = (type: TargetType): string => {
    switch (type) {
      case 'workstation': return t('station')
      case 'vlan': return t('vlan')
      case 'account': return t('organization')
      default: return type
    }
  }

  const getTargetTypeBadgeColor = (type: TargetType): string => {
    switch (type) {
      case 'workstation': return 'bg-blue-100 text-blue-800'
      case 'vlan': return 'bg-purple-100 text-purple-800'
      case 'account': return 'bg-green-100 text-green-800'
      default: return 'bg-gray-100 text-gray-800'
    }
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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">{t('title')}</h1>
          <p className="mt-2 text-gray-600">{t('subtitle')}</p>
        </div>
        <Button onClick={() => setShowSendModal(true)}>
          <Plus className="mr-2 h-4 w-4" />
          {t('send')}
        </Button>
      </div>

      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="p-3 bg-blue-100 rounded-lg"><Send className="h-6 w-6 text-blue-600" /></div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">{t('totalSent')}</p>
                <p className="text-2xl font-bold text-gray-900">{stats.total_sent}</p>
              </div>
            </div>
          </div>
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="p-3 bg-green-100 rounded-lg"><CheckCircle className="h-6 w-6 text-green-600" /></div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">{t('delivered')}</p>
                <p className="text-2xl font-bold text-gray-900">{stats.total_delivered}</p>
              </div>
            </div>
          </div>
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="p-3 bg-yellow-100 rounded-lg"><Clock className="h-6 w-6 text-yellow-600" /></div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">{t('pending')}</p>
                <p className="text-2xl font-bold text-gray-900">{stats.total_pending}</p>
              </div>
            </div>
          </div>
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center">
              <div className="p-3 bg-purple-100 rounded-lg"><MessageSquare className="h-6 w-6 text-purple-600" /></div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-600">{t('deliveryRate')}</p>
                <p className="text-2xl font-bold text-gray-900">{stats.delivery_rate.toFixed(1)}%</p>
              </div>
            </div>
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
          <select value={filterDelivered === null ? 'all' : filterDelivered.toString()}
            onChange={(e) => { setFilterDelivered(e.target.value === 'all' ? null : e.target.value === 'true'); setPage(1) }}
            className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="all">{t('allStatuses')}</option>
            <option value="true">{t('delivered')}</option>
            <option value="false">{t('pending')}</option>
          </select>
          <select value={filterTargetType || 'all'}
            onChange={(e) => { setFilterTargetType(e.target.value === 'all' ? null : (e.target.value as TargetType)); setPage(1) }}
            className="px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="all">{t('allTypes')}</option>
            <option value="workstation">{t('station')}</option>
            <option value="vlan">{t('vlan')}</option>
            <option value="account">{t('organization')}</option>
          </select>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow overflow-hidden">
        {filteredMessages.length === 0 ? (
          <div className="text-center py-12">
            <MessageSquare className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-2 text-sm font-medium text-gray-900">{t('emptyTitle')}</h3>
            <p className="mt-1 text-sm text-gray-500">{t('emptyMessage')}</p>
            <div className="mt-6">
              <Button onClick={() => setShowSendModal(true)}>
                <Plus className="mr-2 h-4 w-4" />{t('send')}
              </Button>
            </div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colType')}</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colContent')}</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colStatus')}</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colSent')}</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colDelivered')}</th>
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
                          <CheckCircle className="mr-1 h-3 w-3" />{t('delivered')}
                        </Badge>
                      ) : (
                        <Badge className="bg-yellow-100 text-yellow-800">
                          <Clock className="mr-1 h-3 w-3" />{t('pending')}
                        </Badge>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {formatDateWithTimezone(message.sent_at, timezone)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {message.delivered_at ? formatDateWithTimezone(message.delivered_at, timezone) : '-'}
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
              <div>
                <p className="text-sm text-gray-700">
                  {t('pagination', { start: (page - 1) * pageSize + 1, end: Math.min(page * pageSize, total), total })}
                </p>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setPage(page - 1)} disabled={page === 1}>{tCommon('previous')}</Button>
                <Button variant="outline" onClick={() => setPage(page + 1)} disabled={page * pageSize >= total}>{tCommon('next')}</Button>
              </div>
            </div>
          </div>
        )}
      </div>

      {showSendModal && (
        <SendMessageModal
          onClose={() => setShowSendModal(false)}
          onSuccess={() => { setShowSendModal(false); loadMessages(); loadStats() }}
        />
      )}
    </div>
  )
}

function SendMessageModal({ onClose, onSuccess }: { onClose: () => void; onSuccess: () => void }) {
  const { user, getAuthHeaders } = useAuth()
  const t = useTranslations('messages')
  const tCommon = useTranslations('common')
  const [loading, setLoading] = useState(false)
  const [targetType, setTargetType] = useState<TargetType>('account')
  const [targetId, setTargetId] = useState<string>('')
  const [content, setContent] = useState('')
  const [workstations, setWorkstations] = useState<Workstation[]>([])
  const [vlans, setVlans] = useState<VLAN[]>([])

  // Selector de cuenta para admin
  const [accounts, setAccounts] = useState<{ id: string; name: string }[]>([])
  const [selectedAccountId, setSelectedAccountId] = useState<string>('')

  useEffect(() => {
    const loadWS = async () => {
      try {
        const r = await apiClient.get('/workstations/')
        setWorkstations(r.data.items || [])
      } catch (e) { console.error(e) }
    }
    const loadVLANs = async () => {
      try {
        const r = await apiClient.get('/vlans/')
        setVlans(r.data.vlans || [])
      } catch (e) { console.error(e) }
    }
    const loadAccounts = async () => {
      try {
        const r = await apiClient.get('/accounts/?skip=0&limit=1000')
        const items = r.data.items || []
        setAccounts(items)
        if (items.length > 0) setSelectedAccountId(items[0].id)
      } catch (e) { console.error(e) }
    }
    loadWS()
    loadVLANs()
    // Admin necesita seleccionar cuenta destino
    if (user?.role === 'admin') {
      loadAccounts()
    }
  }, [user])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!content.trim()) return
    if (targetType !== 'account' && !targetId) return
    // Admin debe seleccionar cuenta
    if (user?.role === 'admin' && !selectedAccountId) {
      alert('Debes seleccionar una organización destino')
      return
    }
    try {
      setLoading(true)
      const messageData: MessageCreate = {
        target_type: targetType,
        target_id: targetType === 'account' ? null : targetId,
        content: content.trim(),
      }
      // Construir URL con account_id para admin
      let url = '/messages/'
      if (user?.role === 'admin' && selectedAccountId) {
        url += `?account_id=${selectedAccountId}`
      }
      await apiClient.post(url, messageData)
      onSuccess()
    } catch (error: any) {
      console.error('Error:', error)
      alert(error.detail || error.message || 'Error al enviar mensaje')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="p-6">
          <h2 className="text-2xl font-bold text-gray-900 mb-4">{t('sendTitle')}</h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Selector de cuenta para admin */}
            {user?.role === 'admin' && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Organización destino</label>
                <select value={selectedAccountId} onChange={(e) => setSelectedAccountId(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500" required>
                  <option value="">Seleccionar organización...</option>
                  {accounts.map((acc) => <option key={acc.id} value={acc.id}>{acc.name}</option>)}
                </select>
              </div>
            )}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('sendTo')}</label>
              <select value={targetType} onChange={(e) => { setTargetType(e.target.value as TargetType); setTargetId('') }}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="account">{t('wholeOrg')}</option>
                <option value="vlan">{t('specificVlan')}</option>
                <option value="workstation">{t('specificStation')}</option>
              </select>
            </div>
            {targetType === 'vlan' && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('selectVlan')}</label>
                <select value={targetId} onChange={(e) => setTargetId(e.target.value)} required
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                  <option value="">{t('selectVlanOpt')}</option>
                  {vlans.map((vlan) => <option key={vlan.id} value={vlan.id}>{vlan.name}</option>)}
                </select>
              </div>
            )}
            {targetType === 'workstation' && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">{t('selectStation')}</label>
                <select value={targetId} onChange={(e) => setTargetId(e.target.value)} required
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                  <option value="">{t('selectStationOpt')}</option>
                  {workstations.map((ws) => (
                    <option key={ws.id} value={ws.id}>{ws.hostname || ws.ip_private} - {ws.current_user || 'Sin usuario'}</option>
                  ))}
                </select>
              </div>
            )}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{t('messageLabel')}</label>
              <textarea value={content} onChange={(e) => setContent(e.target.value)}
                placeholder={t('messagePlaceholder')}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                rows={6} maxLength={5000} required />
              <p className="mt-1 text-xs text-gray-500">{t('charCount', { length: content.length })}</p>
            </div>
            <div className="flex justify-end gap-3 pt-4">
              <Button type="button" variant="outline" onClick={onClose} disabled={loading}>{tCommon('cancel')}</Button>
              <Button type="submit" disabled={loading}>
                <Send className="mr-2 h-4 w-4" />
                {loading ? tCommon('saving') : t('send')}
              </Button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
