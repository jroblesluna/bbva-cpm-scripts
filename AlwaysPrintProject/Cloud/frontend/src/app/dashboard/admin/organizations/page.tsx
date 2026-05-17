/**
 * Página de gestión de organizaciones.
 * 
 * Solo accesible para administradores.
 * Incluye gestión de IPs públicas para auto-asignación de workstations.
 */

'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { organizationsApi } from '@/lib/api'
import { useTranslations } from 'next-intl'
import { COMMON_TIMEZONES, formatDateWithTimezone, getTimezoneName } from '@/lib/dateUtils'
import { useUserTimezone } from '@/hooks/useUserTimezone'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { 
  Building2, 
  Plus, 
  Search, 
  Edit, 
  Trash2, 
  Globe,
  AlertCircle,
  CheckCircle,
  X,
  Network,
  Users,
  Monitor
} from 'lucide-react'
import type { Organization, OrganizationCreate, OrganizationUpdate, PublicIPCreate } from '@/types'

export default function AccountsPage() {
  const queryClient = useQueryClient()
  const userTimezone = useUserTimezone()
  const t = useTranslations('accounts')
  const tCommon = useTranslations('common')
  const [searchTerm, setSearchTerm] = useState('')
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [editingAccount, setEditingAccount] = useState<Organization | null>(null)
  const [managingIPsOrg, setManagingIPsOrg] = useState<Organization | null>(null)

  // Query para listar cuentas
  const { data: accounts, isLoading, error } = useQuery({
    queryKey: ['accounts', 'list'],
    queryFn: () => organizationsApi.list(),
  })

  // Mutation para crear cuenta
  const createMutation = useMutation({
    mutationFn: (data: OrganizationCreate) => organizationsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      setShowCreateForm(false)
    },
  })

  // Mutation para actualizar cuenta
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: OrganizationUpdate }) => 
      organizationsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      setEditingAccount(null)
    },
  })

  // Mutation para eliminar cuenta
  const deleteMutation = useMutation({
    mutationFn: (id: string) => organizationsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
    },
  })

  // Mutation para agregar IP pública
  const addIPMutation = useMutation({
    mutationFn: ({ orgId, data }: { orgId: string; data: PublicIPCreate }) =>
      organizationsApi.addPublicIP(orgId, data),
    onSuccess: async (_, variables) => {
      // Invalidar y refrescar inmediatamente las queries de accounts
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      await queryClient.refetchQueries({ queryKey: ['accounts'] })
      
      // Actualizar el estado local del modal con los datos frescos
      if (managingIPsOrg && managingIPsOrg.id === variables.orgId) {
        const updatedOrgs = queryClient.getQueryData<Organization[]>(['accounts', 'list'])
        const updatedOrg = updatedOrgs?.find(acc => acc.id === variables.orgId)
        if (updatedOrg) {
          setManagingIPsOrg(updatedOrg)
        }
      }
    },
  })

  // Mutation para eliminar IP pública
  const removeIPMutation = useMutation({
    mutationFn: ({ orgId, ipId }: { orgId: string; ipId: string }) =>
      organizationsApi.removePublicIP(orgId, ipId),
    onSuccess: async (_, variables) => {
      // Invalidar y refrescar inmediatamente las queries de accounts
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      await queryClient.refetchQueries({ queryKey: ['accounts'] })
      
      // Actualizar el estado local del modal con los datos frescos
      if (managingIPsOrg && managingIPsOrg.id === variables.orgId) {
        const updatedOrgs = queryClient.getQueryData<Organization[]>(['accounts', 'list'])
        const updatedOrg = updatedOrgs?.find(acc => acc.id === variables.orgId)
        if (updatedOrg) {
          setManagingIPsOrg(updatedOrg)
        }
      }
    },
  })

  // Filtrar cuentas por búsqueda
  const filteredAccounts = Array.isArray(accounts) 
    ? accounts.filter(account =>
        account.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        account.description?.toLowerCase().includes(searchTerm.toLowerCase())
      )
    : []

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6">
        <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 mb-8">{t('title')}</h1>
        <div className="animate-pulse space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-32 bg-gray-200 rounded-lg"></div>
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6">
        <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 mb-8">{t('title')}</h1>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Error al cargar organizaciones. Por favor, intenta de nuevo.
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold text-gray-900">{t('title')}</h1>
          <p className="text-gray-600 mt-2">{t('subtitle')}</p>
        </div>
        <Button onClick={() => setShowCreateForm(true)} className="w-full sm:w-auto">
          <Plus className="w-4 h-4 mr-2" />
          {t('new')}
        </Button>
      </div>

      {/* Barra de búsqueda */}
      <Card className="mb-6">
        <CardContent className="p-4">
          <div className="flex items-center">
            <Search className="w-5 h-5 text-gray-400 mr-3" />
            <Input
              type="text"
              placeholder={t('searchPlaceholder')}
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="flex-1"
            />
          </div>
        </CardContent>
      </Card>

      {/* Formulario de creación */}
      {showCreateForm && (
        <Card className="mb-6 border-blue-200 bg-blue-50">
          <CardHeader>
            <CardTitle>{t('createTitle')}</CardTitle>
          </CardHeader>
          <CardContent>
            <AccountForm
              onSubmit={(data) => createMutation.mutate(data as OrganizationCreate)}
              onCancel={() => setShowCreateForm(false)}
              isLoading={createMutation.isPending}
              error={(createMutation.error as any)?.detail}
            />
          </CardContent>
        </Card>
      )}

      {/* Formulario de edición */}
      {editingAccount && (
        <Card className="mb-6 border-amber-200 bg-amber-50">
          <CardHeader>
            <CardTitle>{t('editTitle', { name: editingAccount.name })}</CardTitle>
          </CardHeader>
          <CardContent>
            <AccountForm
              initialData={editingAccount}
              onSubmit={(data) => updateMutation.mutate({ id: editingAccount.id, data })}
              onCancel={() => setEditingAccount(null)}
              isLoading={updateMutation.isPending}
              error={(updateMutation.error as any)?.detail}
            />
          </CardContent>
        </Card>
      )}

      {/* Modal de gestión de IPs */}
      {managingIPsOrg && (
        <Card className="mb-6 border-green-200 bg-green-50">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>{t('manageIpsTitle', { name: managingIPsOrg.name })}</CardTitle>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setManagingIPsOrg(null)}
            >
              <X className="w-4 h-4" />
            </Button>
          </CardHeader>
          <CardContent>
            <IPManagementForm
              organization={managingIPsOrg}
              onAddIP={(data) => addIPMutation.mutate({ orgId: managingIPsOrg.id, data })}
              onRemoveIP={(ipId) => removeIPMutation.mutate({ orgId: managingIPsOrg.id, ipId })}
              isLoading={addIPMutation.isPending || removeIPMutation.isPending}
              error={(addIPMutation.error as any)?.detail || (removeIPMutation.error as any)?.detail}
            />
          </CardContent>
        </Card>
      )}

      {/* Lista de cuentas */}
      <div className="space-y-4">
        {filteredAccounts && filteredAccounts.length > 0 ? (
          filteredAccounts.map((account) => (
            <Card key={account.id} className="hover:shadow-md transition">
              <CardContent className="p-4 sm:p-6">
                <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
                  <div className="flex items-start flex-1 min-w-0">
                    <div className="bg-blue-100 rounded-full p-3 mr-3 sm:mr-4 shrink-0">
                      <Building2 className="w-5 h-5 sm:w-6 sm:h-6 text-blue-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2 mb-2">
                        <h3 className="text-lg sm:text-xl font-semibold text-gray-900">
                          {account.name}
                        </h3>
                        <Badge variant={account.is_active ? 'default' : 'secondary'}>
                          {account.is_active ? tCommon('active') : tCommon('inactive')}
                        </Badge>
                      </div>
                      
                      {account.description && (
                        <p className="text-gray-600 mb-3">{account.description}</p>
                      )}

                      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-gray-500">
                        <div className="flex items-center">
                          <Globe className="w-4 h-4 mr-1 shrink-0" />
                          <span>{account.public_ips?.length || 0} {t('publicIps')}</span>
                        </div>
                        <div className="flex items-center">
                          <Monitor className="w-4 h-4 mr-1 shrink-0" />
                          <span>Workstations (por implementar)</span>
                        </div>
                        <div className="flex items-center">
                          <Users className="w-4 h-4 mr-1 shrink-0" />
                          <span>Usuarios (por implementar)</span>
                        </div>
                        <div className="flex items-center">
                          <CheckCircle className="w-4 h-4 mr-1 shrink-0" />
                          <span>Creada: {formatDateWithTimezone(account.created_at, userTimezone)}</span>
                        </div>
                      </div>

                      {/* IPs públicas */}
                      {account.public_ips && account.public_ips.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {account.public_ips.map((ip) => (
                            <Badge key={ip.id} variant="outline" className="text-xs">
                              {ip.ip_address}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 sm:ml-4 shrink-0 self-end sm:self-start">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setManagingIPsOrg(account)}
                      title={t('manageIps')}
                    >
                      <Network className="w-4 h-4 mr-1" />
                      <span className="hidden sm:inline">{t('manageIps')}</span>
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setEditingAccount(account)}
                      title="Editar cuenta"
                    >
                      <Edit className="w-4 h-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        if (confirm(t('deleteAccountConfirm', { name: account.name }))) {
                          deleteMutation.mutate(account.id)
                        }
                      }}
                      disabled={deleteMutation.isPending}
                      title="Eliminar cuenta"
                    >
                      <Trash2 className="w-4 h-4 text-red-600" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))
        ) : (
          <Card>
            <CardContent className="p-12 text-center">
              <Building2 className="w-16 h-16 text-gray-300 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-gray-900 mb-2">{t('emptyTitle')}</h3>
              <p className="text-gray-600 mb-4">
                {searchTerm ? t('emptyFilter') : t('emptyCreate')}
              </p>
              {!searchTerm && (
                <Button onClick={() => setShowCreateForm(true)}>
                  <Plus className="w-4 h-4 mr-2" />
                  {t('new')}
                </Button>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}

// Componente de formulario de cuenta (crear/editar)
function AccountForm({
  initialData,
  onSubmit,
  onCancel,
  isLoading,
  error,
}: {
  initialData?: Organization
  onSubmit: (data: OrganizationCreate | OrganizationUpdate) => void
  onCancel: () => void
  isLoading: boolean
  error?: string
}) {
  const t = useTranslations('accounts')
  const tCommon = useTranslations('common')
  const [formData, setFormData] = useState<OrganizationCreate>({
    name: initialData?.name || '',
    description: initialData?.description || '',
    is_active: initialData?.is_active ?? true,
    timezone: initialData?.timezone || 'UTC',
    language: initialData?.language || 'en',
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit(formData)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="name">{t('nameLabel')}</Label>
          <Input
            id="name"
            type="text"
            placeholder={t('namePlaceholder')}
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            required
            disabled={isLoading}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="description">{t('descriptionLabel')}</Label>
          <Input
            id="description"
            type="text"
            placeholder={t('descriptionPlaceholder')}
            value={formData.description || ''}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            disabled={isLoading}
          />
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="timezone">{t('timezoneLabel')}</Label>
        <select
          id="timezone"
          value={formData.timezone}
          onChange={(e) => setFormData({ ...formData, timezone: e.target.value })}
          disabled={isLoading}
          className="w-full px-3 py-2 border rounded-md"
          required
        >
          {COMMON_TIMEZONES.map((tz) => (
            <option key={tz.value} value={tz.value}>{tz.label}</option>
          ))}
        </select>
        <p className="text-xs text-gray-500">{t('timezoneHelper')}</p>
      </div>

      <div className="space-y-2">
        <Label htmlFor="language">{t('languageLabel')}</Label>
        <select
          id="language"
          value={formData.language || 'en'}
          onChange={(e) => setFormData({ ...formData, language: e.target.value })}
          disabled={isLoading}
          className="w-full px-3 py-2 border rounded-md"
        >
          <option value="en">English</option>
          <option value="es">Español</option>
        </select>
        <p className="text-xs text-gray-500">{t('languageHelper')}</p>
      </div>

      <div className="flex items-center space-x-2">
        <input
          type="checkbox"
          id="is_active"
          checked={formData.is_active}
          onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
          disabled={isLoading}
          className="rounded"
        />
        <Label htmlFor="is_active" className="cursor-pointer">{t('activeLabel')}</Label>
      </div>

      <div className="flex justify-end space-x-3">
        <Button type="button" variant="outline" onClick={onCancel} disabled={isLoading}>
          {tCommon('cancel')}
        </Button>
        <Button type="submit" disabled={isLoading}>
          {isLoading ? (initialData ? tCommon('updating') : tCommon('creating')) : (initialData ? tCommon('update') : t('createBtn'))}
        </Button>
      </div>
    </form>
  )
}

// Componente de gestión de IPs públicas
function IPManagementForm({
  organization,
  onAddIP,
  onRemoveIP,
  isLoading,
  error,
}: {
  organization: Organization
  onAddIP: (data: PublicIPCreate) => void
  onRemoveIP: (ipId: string) => void
  isLoading: boolean
  error?: string
}) {
  const t = useTranslations('accounts')
  const tCommon = useTranslations('common')
  const [newIP, setNewIP] = useState('')
  const [newIPDescription, setNewIPDescription] = useState('')

  const handleAddIP = (e: React.FormEvent) => {
    e.preventDefault()

    const ipRegex = /^(\d{1,3}\.){3}\d{1,3}$/
    if (!ipRegex.test(newIP)) {
      alert('Please enter a valid IP address')
      return
    }

    onAddIP({
      ip_address: newIP,
      description: newIPDescription || undefined,
    })

    setNewIP('')
    setNewIPDescription('')
  }

  return (
    <div className="space-y-6">
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Formulario para agregar IP */}
      <div className="border-b pb-4">
        <h3 className="text-sm font-medium text-gray-900 mb-3">{t('addIpTitle')}</h3>
        <form onSubmit={handleAddIP} className="space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="ip_address">{t('ipLabel')}</Label>
              <Input
                id="ip_address"
                type="text"
                placeholder={t('ipPlaceholder')}
                value={newIP}
                onChange={(e) => setNewIP(e.target.value)}
                required
                disabled={isLoading}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="ip_description">{t('ipDescLabel')}</Label>
              <Input
                id="ip_description"
                type="text"
                placeholder={t('ipDescPlaceholder')}
                value={newIPDescription}
                onChange={(e) => setNewIPDescription(e.target.value)}
                disabled={isLoading}
              />
            </div>
          </div>

          <div className="flex justify-end">
            <Button type="submit" disabled={isLoading} size="sm">
              <Plus className="w-4 h-4 mr-2" />
              {t('addIpBtn')}
            </Button>
          </div>
        </form>
      </div>

      {/* Lista de IPs existentes */}
      <div>
        <h3 className="text-sm font-medium text-gray-900 mb-3">
          {t('registeredIps', { count: organization.public_ips?.length || 0 })}
        </h3>
        
        {organization.public_ips && organization.public_ips.length > 0 ? (
          <div className="space-y-2">
            {organization.public_ips.map((ip) => (
              <div
                key={ip.id}
                className="flex items-center justify-between p-3 bg-white border rounded-lg hover:shadow-sm transition"
              >
                <div className="flex items-center flex-1">
                  <Globe className="w-5 h-5 text-blue-600 mr-3" />
                  <div>
                    <p className="font-mono text-sm font-medium text-gray-900">
                      {ip.ip_address}
                    </p>
                    {ip.description && (
                      <p className="text-xs text-gray-500">{ip.description}</p>
                    )}
                  </div>
                </div>

                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    if (confirm(t('deleteIpConfirm', { ip: ip.ip_address }))) {
                      onRemoveIP(ip.id)
                    }
                  }}
                  disabled={isLoading}
                >
                  <Trash2 className="w-4 h-4 text-red-600" />
                </Button>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-8 bg-gray-50 rounded-lg border-2 border-dashed">
            <Globe className="w-12 h-12 text-gray-300 mx-auto mb-3" />
            <p className="text-sm text-gray-600">{t('noIps')}</p>
            <p className="text-xs text-gray-500 mt-1">{t('noIpsSuggestion')}</p>
          </div>
        )}
      </div>

      {/* Información adicional */}
      <Alert>
        <AlertCircle className="h-4 w-4" />
        <AlertDescription className="text-xs">
          {t('autoAssignNote')}
        </AlertDescription>
      </Alert>
    </div>
  )
}
