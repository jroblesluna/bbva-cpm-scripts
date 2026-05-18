/**
 * Página de gestión de VLANs.
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
} from 'lucide-react'
import { apiClient } from '@/lib/api'
import type { VLAN, VLANCreate, VLANUpdate, VLANDetail } from '@/types/vlan'
import { formatDateWithTimezone } from '@/lib/dateUtils'
import { useUserTimezone } from '@/hooks/useUserTimezone'

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

  useEffect(() => {
    if (!user) return
    if (user.role === 'admin') loadAccounts()
    loadVlans()
  }, [user, filterOrgId])

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
      setVlans(response.data.vlans || [])
    } catch (error) {
      console.error('Error loading vlans:', error)
    } finally {
      setLoading(false)
    }
  }

  const filteredVlans = vlans.filter((vlan) => {
    const s = searchTerm.toLowerCase()
    return (
      vlan.name.toLowerCase().includes(s) ||
      vlan.description?.toLowerCase().includes(s) ||
      vlan.cidr_ranges.some((cidr) => cidr.includes(s))
    )
  })

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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">{t('title')}</h1>
          <p className="mt-2 text-gray-600">{t('subtitle')}</p>
        </div>
        <Button onClick={() => setShowCreateModal(true)}>
          <Plus className="mr-2 h-4 w-4" />
          {t('create')}
        </Button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center">
            <div className="p-3 bg-blue-100 rounded-lg"><Network className="h-6 w-6 text-blue-600" /></div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-600">{t('totalVlans')}</p>
              <p className="text-2xl font-bold text-gray-900">{vlans.length}</p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center">
            <div className="p-3 bg-green-100 rounded-lg"><Monitor className="h-6 w-6 text-green-600" /></div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-600">{t('stations')}</p>
              <p className="text-2xl font-bold text-gray-900">
                {vlans.reduce((acc, v) => acc + ((v as any).workstation_count || 0), 0)}
              </p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center">
            <div className="p-3 bg-purple-100 rounded-lg"><Network className="h-6 w-6 text-purple-600" /></div>
            <div className="ml-4">
              <p className="text-sm font-medium text-gray-600">{t('cidrRanges')}</p>
              <p className="text-2xl font-bold text-gray-900">
                {vlans.reduce((acc, v) => acc + v.cidr_ranges.length, 0)}
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-lg shadow p-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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
          {user?.role === 'admin' && (
            <select
              value={filterOrgId || 'all'}
              onChange={(e) => setFilterOrgId(e.target.value === 'all' ? undefined : e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">{t('allOrganizations')}</option>
              {accounts.map((account) => (
                <option key={account.id} value={account.id}>{account.name}</option>
              ))}
            </select>
          )}
        </div>
        {(searchTerm || filterOrgId) && (
          <div className="mt-4">
            <Button variant="outline" size="sm" onClick={() => { setSearchTerm(''); setFilterOrgId(undefined) }}>
              <X className="mr-2 h-4 w-4" />
              {tCommon('clearFilters')}
            </Button>
          </div>
        )}
      </div>

      <div className="bg-white rounded-lg shadow overflow-hidden">
        {filteredVlans.length === 0 ? (
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
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colName')}</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colDescription')}</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colCidr')}</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colCreated')}</th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">{t('colActions')}</th>
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
                      <span className="text-sm text-gray-500">{vlan.description || '-'}</span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex flex-wrap gap-1">
                        {vlan.cidr_ranges.map((cidr, idx) => (
                          <Badge key={idx} variant="secondary">{cidr}</Badge>
                        ))}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {formatDateWithTimezone(vlan.created_at, timezone)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <Button variant="ghost" size="sm" onClick={() => handleEdit(vlan)}>
                        <Edit className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => handleDelete(vlan)} className="text-red-600 hover:text-red-700">
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
    </div>
  )
}

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
    } catch (error: any) {
      console.error('Error:', error)
      alert(error.message)
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
    } catch (error: any) {
      console.error('Error:', error)
      alert(error.message)
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
    } catch (error: any) {
      console.error('Error:', error)
      alert(error.message)
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
