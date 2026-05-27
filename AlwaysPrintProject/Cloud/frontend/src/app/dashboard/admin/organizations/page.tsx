/**
 * Página de gestión de organizaciones.
 * 
 * Solo accesible para administradores.
 * Incluye gestión de IPs públicas para auto-asignación de workstations.
 */

'use client'

import React, { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { organizationsApi, logAnalysisApi } from '@/lib/api'
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
  Monitor,
  ShieldAlert,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  RotateCcw,
  RefreshCcw,
  Download,
  Terminal,
} from 'lucide-react'
import type { Organization, OrganizationCreate, OrganizationUpdate, PublicIPCreate } from '@/types'
import { ActionConfigSection } from '@/components/config/ActionConfigSection'
import { useToast } from '@/hooks/use-toast'

export default function AccountsPage() {
  const queryClient = useQueryClient()
  const router = useRouter()
  const userTimezone = useUserTimezone()
  const { toast } = useToast()
  const t = useTranslations('accounts')
  const tCommon = useTranslations('common')
  const tActions = useTranslations('actionConfigs')
  const [searchTerm, setSearchTerm] = useState('')
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [editingAccount, setEditingAccount] = useState<Organization | null>(null)
  const [managingIPsOrg, setManagingIPsOrg] = useState<Organization | null>(null)
  const [contingencyTarget, setContingencyTarget] = useState<Organization | null>(null)
  const [bulkCommandTarget, setBulkCommandTarget] = useState<{ org: Organization; commandType: 'restart_service' | 'restart_tray' | 'check_update' } | null>(null)
  const [bulkCommandPending, setBulkCommandPending] = useState(false)
  const [page, setPage] = useState(1)
  const pageSize = 10
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date())

  // Query para listar cuentas
  const { data: accounts, isLoading, error, isFetching, refetch } = useQuery({
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

  // Mutation para toggle de contingencia forzada
  const forcedContingencyMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      organizationsApi.toggleForcedContingency(id, enabled),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      setContingencyTarget(null)
      toast({
        title: t('forcedContingency'),
        description: variables.enabled
          ? t('forcedContingencyActivated')
          : t('forcedContingencyDeactivated'),
      })
    },
    onError: (error: unknown) => {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast({
        variant: 'destructive',
        title: t('forcedContingency'),
        description: detail ?? t('forcedContingencyError'),
      })
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

  // Actualizar timestamp cuando se cargan datos
  useEffect(() => {
    if (accounts && !isFetching) {
      setLastUpdated(new Date())
    }
  }, [accounts, isFetching])

  const handleRefresh = () => {
    refetch()
  }

  const handleBulkCommand = async () => {
    if (!bulkCommandTarget) return
    setBulkCommandPending(true)
    try {
      const result = await organizationsApi.sendCommand(bulkCommandTarget.org.id, bulkCommandTarget.commandType)
      const labels: Record<string, string> = {
        restart_service: tCommon('bulkRestartService'),
        restart_tray: tCommon('bulkRestartTray'),
        check_update: tCommon('bulkCheckUpdate'),
      }
      toast({
        title: tCommon('bulkCommandSent'),
        description: t('bulkCommandSentDesc', { action: labels[bulkCommandTarget.commandType], count: result.dispatched, name: bulkCommandTarget.org.name }),
      })
    } catch {
      toast({ variant: 'destructive', title: tCommon('error'), description: tCommon('bulkCommandError') })
    } finally {
      setBulkCommandPending(false)
      setBulkCommandTarget(null)
    }
  }

  // Filtrar cuentas por búsqueda
  const filteredAccounts = Array.isArray(accounts) 
    ? accounts.filter(account =>
        account.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        account.description?.toLowerCase().includes(searchTerm.toLowerCase())
      )
    : []

  const totalFiltered = filteredAccounts.length
  const totalPages = Math.ceil(totalFiltered / pageSize)
  const paginatedAccounts = filteredAccounts.slice((page - 1) * pageSize, page * pageSize)
  const paginationStart = (page - 1) * pageSize + 1
  const paginationEnd = Math.min(page * pageSize, totalFiltered)

  if (isLoading) {
    return (
      <div className="max-w-screen-2xl mx-auto">
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
      <div className="max-w-screen-2xl mx-auto">
        <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 mb-8">{t('title')}</h1>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            {t('loadError')}
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  return (
    <div className="max-w-screen-2xl mx-auto">
      {/* Header */}
      <div className="flex flex-col gap-2 mt-2 mb-8">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <h1 className="text-2xl sm:text-3xl font-bold text-gray-900">{t('title')}</h1>
          <Button onClick={() => setShowCreateForm(true)} className="w-full sm:w-auto">
            <Plus className="w-4 h-4 mr-2" />
            {t('new')}
          </Button>
        </div>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between">
          <p className="text-gray-600">{t('subtitle')}</p>
          <div className="flex items-center gap-1">
            <span className="text-xs text-gray-400">
              {tCommon('lastUpdated', { time: formatDateWithTimezone(lastUpdated, userTimezone) })}
            </span>
            <Button variant="ghost" size="sm" onClick={handleRefresh} disabled={isFetching} className="h-6 w-6 p-0 text-gray-400 hover:text-gray-600">
              <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </div>
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
              onChange={(e) => { setSearchTerm(e.target.value); setPage(1) }}
              className="flex-1"
            />
          </div>
        </CardContent>
      </Card>

      {/* Modal de creación */}
      {showCreateForm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <Card className="max-w-2xl w-full max-h-[90vh] overflow-y-auto">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>{t('createTitle')}</CardTitle>
              <Button variant="ghost" size="sm" onClick={() => setShowCreateForm(false)} className="h-8 w-8 p-0">
                <X className="w-4 h-4" />
              </Button>
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
        </div>
      )}

      {/* Modal de edición */}
      {editingAccount && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <Card className="max-w-4xl w-full max-h-[90vh] overflow-y-auto">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>{t('editTitle', { name: editingAccount.name })}</CardTitle>
              <Button variant="ghost" size="sm" onClick={() => setEditingAccount(null)} className="h-8 w-8 p-0">
                <X className="w-4 h-4" />
              </Button>
            </CardHeader>
            <CardContent>
              <AccountForm
                initialData={editingAccount}
                onSubmit={(data) => updateMutation.mutate({ id: editingAccount.id, data })}
                onCancel={() => setEditingAccount(null)}
                isLoading={updateMutation.isPending}
                error={(updateMutation.error as any)?.detail}
              />
              {/* Sección de Action Config para esta organización (colapsable) */}
              <details className="mt-6 pt-6 border-t border-gray-200 group">
                <summary className="flex items-center justify-between cursor-pointer list-none p-3 rounded-lg hover:bg-gray-50 transition-colors [&::-webkit-details-marker]:hidden">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-indigo-100 flex items-center justify-center">
                      <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 text-indigo-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>
                    </div>
                    <div>
                      <h3 className="text-sm font-semibold text-gray-900">{tActions('sectionTitle')}</h3>
                      <p className="text-xs text-gray-500">{tActions('sectionSubtitleOrg')}</p>
                    </div>
                  </div>
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-gray-400 transition-transform group-open:rotate-180" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>
                </summary>
                <div className="mt-3">
                  <ActionConfigSection organizationId={editingAccount.id} hideHeader />
                </div>
              </details>

              {/* Botones al final del modal */}
              <div className="flex justify-end space-x-3 mt-6 pt-6 border-t border-gray-200">
                <Button type="button" variant="outline" onClick={() => setEditingAccount(null)} disabled={updateMutation.isPending}>
                  {tCommon('cancel')}
                </Button>
                <Button type="submit" form={`edit-org-${editingAccount.id}`} disabled={updateMutation.isPending}>
                  {updateMutation.isPending ? tCommon('updating') : tCommon('update')}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Modal de confirmación de contingencia forzada */}
      {contingencyTarget && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <Card className="max-w-md w-full">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="flex items-center gap-2">
                <ShieldAlert className={`w-5 h-5 ${contingencyTarget.forced_contingency ? 'text-green-600' : 'text-orange-600'}`} />
                {contingencyTarget.forced_contingency ? t('forcedContingencyDeactivate') : t('forcedContingencyActivate')}
              </CardTitle>
              <Button variant="ghost" size="sm" onClick={() => setContingencyTarget(null)} className="h-8 w-8 p-0">
                <X className="h-5 w-5" />
              </Button>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-gray-600">
                {contingencyTarget.forced_contingency
                  ? t('forcedContingencyConfirmDeactivate', { name: contingencyTarget.name })
                  : t('forcedContingencyConfirmActivate', { name: contingencyTarget.name })
                }
              </p>
              {!contingencyTarget.forced_contingency && (
                <Alert>
                  <ShieldAlert className="h-4 w-4" />
                  <AlertDescription className="text-xs">
                    {t('forcedContingencyNotification')}
                  </AlertDescription>
                </Alert>
              )}
              <div className="flex justify-end gap-3">
                <Button variant="outline" onClick={() => setContingencyTarget(null)}>
                  {tCommon('cancel')}
                </Button>
                <Button
                  variant={contingencyTarget.forced_contingency ? 'default' : 'destructive'}
                  onClick={() => forcedContingencyMutation.mutate({
                    id: contingencyTarget.id,
                    enabled: !contingencyTarget.forced_contingency,
                  })}
                  disabled={forcedContingencyMutation.isPending}
                  className={!contingencyTarget.forced_contingency ? 'bg-orange-600 hover:bg-orange-700' : ''}
                >
                  {forcedContingencyMutation.isPending
                    ? tCommon('updating')
                    : contingencyTarget.forced_contingency
                      ? t('forcedContingencyDeactivate')
                      : t('forcedContingencyActivate')
                  }
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Modal de gestión de IPs */}
      {managingIPsOrg && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <Card className="max-w-2xl w-full max-h-[90vh] overflow-y-auto">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>{t('manageIpsTitle', { name: managingIPsOrg.name })}</CardTitle>
              <Button variant="ghost" size="sm" onClick={() => setManagingIPsOrg(null)} className="h-8 w-8 p-0">
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
        </div>
      )}

      {/* Modal de confirmación de comando bulk Organización */}
      {bulkCommandTarget && (() => {
        const { org, commandType } = bulkCommandTarget
        const labels: Record<string, { title: string; icon: React.ReactNode; desc: string; warning: string; color: string }> = {
          restart_service: {
            title: tCommon('bulkRestartService'),
            icon: <RotateCcw className="w-5 h-5 text-gray-600" />,
            desc: t('bulkRestartServiceDesc', { name: org.name }),
            warning: t('bulkRestartServiceWarning'),
            color: 'bg-amber-600 hover:bg-amber-700',
          },
          restart_tray: {
            title: tCommon('bulkRestartTray'),
            icon: <Terminal className="w-5 h-5 text-gray-600" />,
            desc: t('bulkRestartTrayDesc', { name: org.name }),
            warning: t('bulkRestartTrayWarning'),
            color: 'bg-amber-600 hover:bg-amber-700',
          },
          check_update: {
            title: tCommon('bulkCheckUpdate'),
            icon: <Download className="w-5 h-5 text-gray-600" />,
            desc: t('bulkCheckUpdateDesc', { name: org.name }),
            warning: t('bulkCheckUpdateWarning'),
            color: 'bg-blue-600 hover:bg-blue-700',
          },
        }
        const meta = labels[commandType]
        return (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
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

      {/* Lista de cuentas */}
      <div className="space-y-4">
        {filteredAccounts && filteredAccounts.length > 0 ? (
          paginatedAccounts.map((account) => (
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
                          <CheckCircle className="w-4 h-4 mr-1 shrink-0" />
                          <span>{t('createdLabel', { date: formatDateWithTimezone(account.created_at, userTimezone) })}</span>
                        </div>
                      </div>

                      {/* IPs públicas */}
                      {account.public_ips && account.public_ips.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {account.public_ips.slice(0, 5).map((ip) => (
                            <Badge key={ip.id} variant="outline" className="text-xs">
                              {ip.ip_address}
                            </Badge>
                          ))}
                          {account.public_ips.length > 5 && (
                            <Badge variant="outline" className="text-xs text-gray-400">
                              {t('moreIps', { count: account.public_ips.length - 5 })}
                            </Badge>
                          )}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center gap-2 sm:ml-4 shrink-0 self-end sm:self-start flex-wrap justify-end">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setBulkCommandTarget({ org: account, commandType: 'restart_service' })}
                      title={tCommon('bulkRestartServiceTooltip')}
                    >
                      <RotateCcw className="w-4 h-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setBulkCommandTarget({ org: account, commandType: 'restart_tray' })}
                      title={tCommon('bulkRestartTrayTooltip')}
                    >
                      <Terminal className="w-4 h-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setBulkCommandTarget({ org: account, commandType: 'check_update' })}
                      title={tCommon('bulkCheckUpdateTooltip')}
                    >
                      <Download className="w-4 h-4" />
                    </Button>
                    <Button
                      variant={account.forced_contingency ? 'destructive' : 'outline'}
                      size="sm"
                      onClick={() => setContingencyTarget(account)}
                      disabled={forcedContingencyMutation.isPending}
                      title={account.forced_contingency ? t('forcedContingencyDeactivate') : t('forcedContingencyActivate')}
                      className={account.forced_contingency ? 'bg-orange-600 hover:bg-orange-700' : ''}
                    >
                      <ShieldAlert className="w-4 h-4 mr-1" />
                      <span className="hidden sm:inline">{account.forced_contingency ? t('forcedContingencyOn') : t('forcedContingencyOff')}</span>
                    </Button>
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
                      onClick={() => router.push(`/dashboard/admin/organizations/${account.id}/edit`)}
                      title={t('editAccount')}
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
                      title={t('deleteAccount')}
                    >
                      <Trash2 className="w-4 h-4 text-red-400" />
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

      {/* Paginación */}
      {totalFiltered > 0 && totalPages > 1 && (
        <div className="bg-white rounded-lg shadow px-4 py-3 flex items-center justify-between border border-gray-200 mt-4 sm:px-6">
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
    </div>
  )
}

// Componente selector de modelo LLM con dos niveles (Provider → Modelo)
function LlmModelSelector({
  value,
  onChange,
  modelsData,
  modelsLoading,
  disabled,
  t,
}: {
  value: string | null
  onChange: (modelId: string | null) => void
  modelsData: { models: Array<{ model_id: string; model_name: string; provider: string }>; default_model_id: string } | undefined
  modelsLoading: boolean
  disabled: boolean
  t: ReturnType<typeof useTranslations>
}) {
  // Obtener providers únicos
  const providers = Array.from(new Set(modelsData?.models?.map((m) => m.provider) || []))
  providers.sort()

  // Determinar provider actual basado en el valor seleccionado
  const currentModel = modelsData?.models?.find((m) => m.model_id === value)
  const [selectedProvider, setSelectedProvider] = useState<string>(currentModel?.provider || '')

  // Modelos filtrados por provider seleccionado
  const filteredModels = modelsData?.models?.filter((m) => m.provider === selectedProvider) || []

  // Actualizar provider cuando cambia el valor externo
  useEffect(() => {
    if (value && modelsData?.models) {
      const model = modelsData.models.find((m) => m.model_id === value)
      if (model) setSelectedProvider(model.provider)
    }
  }, [value, modelsData])

  return (
    <div className="space-y-2">
      <Label>{t('llmModelLabel')}</Label>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* Selector de Provider */}
        <select
          value={selectedProvider}
          onChange={(e) => {
            setSelectedProvider(e.target.value)
            onChange(null) // Reset modelo al cambiar provider
          }}
          disabled={disabled || modelsLoading}
          className="w-full px-3 py-2 border rounded-md text-sm"
        >
          <option value="">{t('llmProviderSelect')}</option>
          {providers.map((provider) => (
            <option key={provider} value={provider}>{provider}</option>
          ))}
        </select>

        {/* Selector de Modelo */}
        <select
          value={value || ''}
          onChange={(e) => onChange(e.target.value || null)}
          disabled={disabled || modelsLoading || !selectedProvider}
          className="w-full px-3 py-2 border rounded-md text-sm"
        >
          <option value="">
            {selectedProvider ? t('llmModelSelect') : t('llmModelDefault')}
            {!selectedProvider && modelsData?.default_model_id ? ` (${modelsData.default_model_id})` : ''}
          </option>
          {filteredModels.map((model) => (
            <option key={model.model_id} value={model.model_id}>
              {model.model_name}
            </option>
          ))}
        </select>
      </div>
      <p className="text-xs text-gray-500">{t('llmModelHelper')}</p>
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
  const [formData, setFormData] = useState<OrganizationCreate & { llm_model_id?: string | null; openai_api_key?: string | null }>({
    name: initialData?.name || '',
    description: initialData?.description || '',
    is_active: initialData?.is_active ?? true,
    timezone: initialData?.timezone || 'UTC',
    language: initialData?.language || 'en',
    llm_model_id: initialData?.llm_model_id || null,
    openai_api_key: initialData?.openai_api_key || null,
  })

  // Cargar modelos LLM disponibles (solo al editar)
  const { data: modelsData, isLoading: modelsLoading } = useQuery({
    queryKey: ['llm-models'],
    queryFn: () => logAnalysisApi.listModels(),
    enabled: !!initialData, // Solo cargar al editar, no al crear
    staleTime: 5 * 60 * 1000, // Cache 5 minutos
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit(formData)
  }

  return (
    <form id={initialData ? `edit-org-${initialData.id}` : 'create-org'} onSubmit={handleSubmit} className="space-y-4">
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

      {/* Selector de modelo LLM (solo al editar) - dos niveles: Provider → Modelo */}
      {initialData && (
        <LlmModelSelector
          value={formData.llm_model_id || null}
          onChange={(modelId) => setFormData({ ...formData, llm_model_id: modelId })}
          modelsData={modelsData}
          modelsLoading={modelsLoading}
          disabled={isLoading}
          t={t}
        />
      )}

      {/* API Key de OpenAI (solo al editar) */}
      {initialData && (
        <div className="space-y-2">
          <Label htmlFor="openai_api_key">{t('openaiKeyLabel')}</Label>
          <Input
            id="openai_api_key"
            type="password"
            placeholder={t('openaiKeyPlaceholder')}
            value={formData.openai_api_key || ''}
            onChange={(e) => setFormData({ ...formData, openai_api_key: e.target.value || null })}
            disabled={isLoading}
          />
          <p className="text-xs text-gray-500">{t('openaiKeyHelper')}</p>
        </div>
      )}

      {!initialData && (
        <div className="flex justify-end space-x-3">
          <Button type="button" variant="outline" onClick={onCancel} disabled={isLoading}>
            {tCommon('cancel')}
          </Button>
          <Button type="submit" disabled={isLoading}>
            {isLoading ? tCommon('creating') : t('createBtn')}
          </Button>
        </div>
      )}
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
