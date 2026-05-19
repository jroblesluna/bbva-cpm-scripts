/**
 * Página de gestión de workstations.
 */

'use client';

import { useState, useEffect, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { workstationsApi, organizationsApi, vlansApi } from '@/lib/api';
import { useTranslations } from 'next-intl';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import {
  Monitor,
  Search,
  AlertCircle,
  CheckCircle,
  XCircle,
  Network,
  Building2,
  User,
  Calendar,
  Activity,
  Edit,
  RefreshCw,
  Trash2,
  Tag,
} from 'lucide-react';
import { formatDateWithTimezone } from '@/lib/dateUtils';
import { useUserTimezone } from '@/hooks/useUserTimezone';
import type { Workstation, WorkstationUpdate, Organization, VLAN } from '@/types';

export default function WorkstationsPage() {
  const queryClient = useQueryClient();
  const userTimezone = useUserTimezone();
  const t = useTranslations('workstations');
  const tCommon = useTranslations('common');
  const [searchTerm, setSearchTerm] = useState('');
  const [filterOnline, setFilterOnline] = useState<boolean | undefined>(undefined);
  const [filterContingency, setFilterContingency] = useState<boolean | undefined>(undefined);
  const [filterOrgId, setFilterOrgId] = useState<string | undefined>(undefined);
  const [filterVlanId, setFilterVlanId] = useState<string | undefined>(undefined);
  const [selectedWorkstation, setSelectedWorkstation] = useState<Workstation | null>(null);
  const [editingWorkstation, setEditingWorkstation] = useState<Workstation | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());

  const {
    data: workstationsData,
    isLoading,
    isFetching,
    error,
  } = useQuery({
    queryKey: ['workstations', searchTerm, filterOnline, filterContingency, filterOrgId, filterVlanId],
    queryFn: () =>
      workstationsApi.list({
        search: searchTerm || undefined,
        is_online: filterOnline,
        contingency_active: filterContingency,
        organization_id: filterOrgId,
        vlan_id: filterVlanId,
      }),
    placeholderData: (prev) => prev,
  });

  const { data: stats } = useQuery({
    queryKey: ['workstations', 'stats'],
    queryFn: () => workstationsApi.stats(),
  });

  const { data: accounts } = useQuery({
    queryKey: ['accounts'],
    queryFn: () => organizationsApi.list(),
  });

  // Obtener VLANs de la organización seleccionada para el filtro
  const { data: vlans } = useQuery({
    queryKey: ['vlans', filterOrgId],
    queryFn: () => vlansApi.list({ organization_id: filterOrgId }),
    enabled: !!filterOrgId,
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: WorkstationUpdate }) =>
      workstationsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workstations'] });
      setEditingWorkstation(null);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => workstationsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workstations'] });
      setSelectedWorkstation(null);
    },
  });

  const handleDelete = (workstation: Workstation) => {
    if (confirm(`¿Eliminar workstation ${workstation.hostname || workstation.ip_private}? Esta acción no se puede deshacer.`)) {
      deleteMutation.mutate(workstation.id);
    }
  };

  const workstations = workstationsData?.items || [];

  // Actualizar timestamp cuando los datos se cargan exitosamente
  useEffect(() => {
    if (workstationsData && !isFetching) {
      setLastUpdated(new Date());
    }
  }, [workstationsData, isFetching]);

  const handleRefresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['workstations'], refetchType: 'all' });
  }, [queryClient]);

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-8">{t('title')}</h1>
        <div className="animate-pulse space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-32 bg-gray-200 rounded-lg"></div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-7xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-8">{t('title')}</h1>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{tCommon('loading')}</AlertDescription>
        </Alert>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">{t('title')}</h1>
          <p className="text-gray-600 mt-2">{t('subtitle')}</p>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-500">
            {t('lastUpdated', { time: formatDateWithTimezone(lastUpdated, userTimezone) })}
          </span>
          <Button
            onClick={handleRefresh}
            disabled={isFetching}
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${isFetching ? 'animate-spin' : ''}`} />
            {tCommon('refresh')}
          </Button>
        </div>
      </div>

      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-6">
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">{t('total')}</p>
                  <p className="text-3xl font-bold text-gray-900">{stats.total}</p>
                </div>
                <Monitor className="w-12 h-12 text-blue-600" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">{t('online')}</p>
                  <p className="text-3xl font-bold text-green-600">{stats.online}</p>
                </div>
                <CheckCircle className="w-12 h-12 text-green-600" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">{t('offline')}</p>
                  <p className="text-3xl font-bold text-gray-600">{stats.offline}</p>
                </div>
                <XCircle className="w-12 h-12 text-gray-400" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">{t('contingency')}</p>
                  <p className="text-3xl font-bold text-amber-600">
                    {stats.contingency_active}
                  </p>
                </div>
                <Activity className="w-12 h-12 text-amber-600" />
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      <Card className="mb-6">
        <CardContent className="p-4">
          <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
            <div className="md:col-span-2">
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
            </div>
            <div>
              <select
                value={
                  filterOnline === undefined ? 'all' : filterOnline ? 'online' : 'offline'
                }
                onChange={(e) => {
                  const value = e.target.value;
                  setFilterOnline(value === 'all' ? undefined : value === 'online');
                }}
                className="w-full px-3 py-2 border rounded-md"
              >
                <option value="all">{t('allStatuses')}</option>
                <option value="online">{t('online')}</option>
                <option value="offline">{t('offline')}</option>
              </select>
            </div>
            <div>
              <select
                value={filterOrgId || 'all'}
                onChange={(e) => {
                  const value = e.target.value;
                  setFilterOrgId(value === 'all' ? undefined : value);
                  // Limpiar filtro de VLAN al cambiar organización
                  setFilterVlanId(undefined);
                }}
                className="w-full px-3 py-2 border rounded-md"
              >
                <option value="all">{t('allAccounts')}</option>
                {Array.isArray(accounts) &&
                  accounts.map((account) => (
                    <option key={account.id} value={account.id}>
                      {account.name}
                    </option>
                  ))}
              </select>
            </div>
            {filterOrgId && (
              <div>
                <select
                  value={filterVlanId || 'all'}
                  onChange={(e) => {
                    const value = e.target.value;
                    setFilterVlanId(value === 'all' ? undefined : value);
                  }}
                  className="w-full px-3 py-2 border rounded-md"
                >
                  <option value="all">{t('allVlans')}</option>
                  {Array.isArray(vlans) &&
                    vlans.map((vlan) => (
                      <option key={vlan.id} value={vlan.id}>
                        {vlan.name}
                      </option>
                    ))}
                </select>
              </div>
            )}
          </div>
          <div className="flex items-center space-x-4 mt-4">
            <label className="flex items-center space-x-2 cursor-pointer">
              <input
                type="checkbox"
                checked={filterContingency === true}
                onChange={(e) => setFilterContingency(e.target.checked ? true : undefined)}
                className="rounded"
              />
              <span className="text-sm text-gray-700">{t('onlyContingency')}</span>
            </label>
            {(searchTerm ||
              filterOnline !== undefined ||
              filterContingency !== undefined ||
              filterOrgId ||
              filterVlanId) && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setSearchTerm('');
                  setFilterOnline(undefined);
                  setFilterContingency(undefined);
                  setFilterOrgId(undefined);
                  setFilterVlanId(undefined);
                }}
              >
                {tCommon('clearFilters')}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {editingWorkstation && (
        <Card className="mb-6 border-amber-200 bg-amber-50">
          <CardHeader>
            <CardTitle>{t('editTitle', { ip: editingWorkstation.ip_private })}</CardTitle>
          </CardHeader>
          <CardContent>
            <WorkstationForm
              workstation={editingWorkstation}
              accounts={accounts || []}
              onSubmit={(data) => updateMutation.mutate({ id: editingWorkstation.id, data })}
              onCancel={() => setEditingWorkstation(null)}
              isLoading={updateMutation.isPending}
              error={updateMutation.error?.message}
            />
          </CardContent>
        </Card>
      )}

      <div className="space-y-4">
        {workstations.length > 0 ? (
          workstations.map((workstation) => (
            <Card key={workstation.id} className="hover:shadow-md transition">
              <CardContent className="p-6">
                <div className="flex items-start justify-between">
                  <div className="flex items-start flex-1">
                    <div
                      className={`rounded-full p-3 mr-4 ${workstation.is_online ? 'bg-green-100' : 'bg-gray-100'}`}
                    >
                      <Monitor
                        className={`w-6 h-6 ${workstation.is_online ? 'text-green-600' : 'text-gray-400'}`}
                      />
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center mb-2">
                        <h3 className="text-xl font-semibold text-gray-900 mr-3">
                          {workstation.ip_private}
                        </h3>
                        <Badge variant={workstation.is_online ? 'default' : 'secondary'}>
                          {workstation.is_online ? t('online') : t('offline')}
                        </Badge>
                        {workstation.contingency_active && (
                          <Badge variant="destructive" className="ml-2">
                            {t('contingency')}
                          </Badge>
                        )}
                      </div>
                      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-sm text-gray-600 mb-3">
                        {workstation.hostname && (
                          <div className="flex items-center">
                            <Monitor className="w-4 h-4 mr-1" />
                            {workstation.hostname}
                          </div>
                        )}
                        {workstation.current_user && (
                          <div className="flex items-center">
                            <User className="w-4 h-4 mr-1" />
                            {workstation.current_user}
                          </div>
                        )}
                        {workstation.cidr && (
                          <div className="flex items-center">
                            <Network className="w-4 h-4 mr-1" />
                            CIDR: {workstation.cidr}
                          </div>
                        )}
                        {workstation.vlan_id && (
                          <div className="flex items-center">
                            <Network className="w-4 h-4 mr-1" />
                            VLAN: {workstation.vlan?.name ?? workstation.vlan_id}
                          </div>
                        )}
                        {workstation.organization && (
                          <div className="flex items-center">
                            <Building2 className="w-4 h-4 mr-1" />
                            {workstation.organization.name}
                          </div>
                        )}
                        <div className="flex items-center">
                          <Tag className="w-4 h-4 mr-1" />
                          Versión Tray: {workstation.tray_version ?? '—'}
                        </div>
                      </div>
                      <div className="flex items-center text-xs text-gray-500 space-x-4">
                        <div className="flex items-center">
                          <Calendar className="w-3 h-3 mr-1" />
                          {t('firstConnection')}:{' '}
                          {formatDateWithTimezone(workstation.first_seen, userTimezone)}
                        </div>
                        {workstation.last_connection && (
                          <div className="flex items-center">
                            <Activity className="w-3 h-3 mr-1" />
                            {t('lastConnection')}:{' '}
                            {formatDateWithTimezone(workstation.last_connection, userTimezone)}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center space-x-2 ml-4">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setSelectedWorkstation(workstation)}
                    >
                      {t('viewDetails')}
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setEditingWorkstation(workstation)}
                    >
                      <Edit className="w-4 h-4" />
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => handleDelete(workstation)}
                      disabled={deleteMutation.isPending}
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))
        ) : (
          <Card>
            <CardContent className="p-12 text-center">
              <Monitor className="w-16 h-16 text-gray-300 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-gray-900 mb-2">{t('emptyTitle')}</h3>
              <p className="text-gray-600 mb-4">
                {searchTerm ||
                filterOnline !== undefined ||
                filterContingency !== undefined ||
                filterOrgId ||
                filterVlanId
                  ? t('emptyFilterMessage')
                  : t('emptyMessage')}
              </p>
            </CardContent>
          </Card>
        )}
      </div>

      {selectedWorkstation && (
        <WorkstationDetailModal
          workstation={selectedWorkstation}
          onClose={() => setSelectedWorkstation(null)}
        />
      )}
    </div>
  );
}

function WorkstationForm({
  workstation,
  accounts,
  onSubmit,
  onCancel,
  isLoading,
  error,
}: {
  workstation: Workstation;
  accounts: Organization[];
  onSubmit: (data: WorkstationUpdate) => void;
  onCancel: () => void;
  isLoading: boolean;
  error?: string;
}) {
  const t = useTranslations('workstations');
  const tCommon = useTranslations('common');
  const [formData, setFormData] = useState<WorkstationUpdate>({
    hostname: workstation.hostname || undefined,
    os_serial: workstation.os_serial || undefined,
    current_user: workstation.current_user || undefined,
    organization_id: workstation.organization_id || undefined,
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit(formData);
  };

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
          <Label htmlFor="hostname">{t('hostname')}</Label>
          <Input
            id="hostname"
            type="text"
            placeholder={t('hostnamePlaceholder')}
            value={formData.hostname || ''}
            onChange={(e) =>
              setFormData({ ...formData, hostname: e.target.value || undefined })
            }
            disabled={isLoading}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="os_serial">{t('osSerial')}</Label>
          <Input
            id="os_serial"
            type="text"
            placeholder="XXXXX-XXXXX-XXXXX"
            value={formData.os_serial || ''}
            onChange={(e) =>
              setFormData({ ...formData, os_serial: e.target.value || undefined })
            }
            disabled={isLoading}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="current_user">{t('currentUser')}</Label>
          <Input
            id="current_user"
            type="text"
            placeholder="usuario@dominio.com"
            value={formData.current_user || ''}
            onChange={(e) =>
              setFormData({ ...formData, current_user: e.target.value || undefined })
            }
            disabled={isLoading}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="organization_id">{t('account')}</Label>
          <select
            id="organization_id"
            value={formData.organization_id || ''}
            onChange={(e) =>
              setFormData({ ...formData, organization_id: e.target.value || undefined })
            }
            disabled={isLoading}
            className="w-full px-3 py-2 border rounded-md"
          >
            <option value="">{t('unassigned')}</option>
            {Array.isArray(accounts) &&
              accounts.map((account) => (
                <option key={account.id} value={account.id}>
                  {account.name}
                </option>
              ))}
          </select>
        </div>
      </div>
      <Alert>
        <AlertCircle className="h-4 w-4" />
        <AlertDescription className="text-xs">{t('accountAutoNote')}</AlertDescription>
      </Alert>
      <div className="flex justify-end space-x-3">
        <Button type="button" variant="outline" onClick={onCancel} disabled={isLoading}>
          {tCommon('cancel')}
        </Button>
        <Button type="submit" disabled={isLoading}>
          {isLoading ? tCommon('updating') : tCommon('update')}
        </Button>
      </div>
    </form>
  );
}

function WorkstationDetailModal({
  workstation,
  onClose,
}: {
  workstation: Workstation;
  onClose: () => void;
}) {
  const userTimezone = useUserTimezone();
  const t = useTranslations('workstations');
  const tCommon = useTranslations('common');

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <Card className="max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>{t('detailsTitle')}</CardTitle>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <XCircle className="w-5 h-5" />
          </Button>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Sección prominente: Versión Tray, CIDR y VLAN */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <div className="flex items-center mb-1">
                <Tag className="w-4 h-4 text-blue-600 mr-2" />
                <span className="text-xs font-medium text-blue-700 uppercase">Versión Tray</span>
              </div>
              <p className="text-lg font-semibold text-blue-900">
                {workstation.tray_version ?? '—'}
              </p>
            </div>
            <div className="bg-purple-50 border border-purple-200 rounded-lg p-4">
              <div className="flex items-center mb-1">
                <Network className="w-4 h-4 text-purple-600 mr-2" />
                <span className="text-xs font-medium text-purple-700 uppercase">CIDR</span>
              </div>
              <p className="text-lg font-semibold font-mono text-purple-900">
                {workstation.cidr ?? '—'}
              </p>
            </div>
            <div className="bg-green-50 border border-green-200 rounded-lg p-4">
              <div className="flex items-center mb-1">
                <Network className="w-4 h-4 text-green-600 mr-2" />
                <span className="text-xs font-medium text-green-700 uppercase">VLAN asignada</span>
              </div>
              <p className="text-lg font-semibold text-green-900">
                {workstation.vlan?.name ?? (workstation.vlan_id ? workstation.vlan_id : '—')}
              </p>
            </div>
          </div>

          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-2">{tCommon('status')}</h3>
            <div className="flex items-center space-x-2">
              <Badge variant={workstation.is_online ? 'default' : 'secondary'}>
                {workstation.is_online ? t('online') : t('offline')}
              </Badge>
              {workstation.contingency_active && (
                <Badge variant="destructive">{t('contingency')}</Badge>
              )}
            </div>
          </div>
          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-2">{t('networkInfo')}</h3>
            <dl className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <dt className="text-gray-600">{t('privateIp')}</dt>
                <dd className="font-mono font-medium">{workstation.ip_private}</dd>
              </div>
              <div>
                <dt className="text-gray-600">CIDR</dt>
                <dd className="font-mono font-medium">{workstation.cidr ?? '—'}</dd>
              </div>
              <div>
                <dt className="text-gray-600">VLAN</dt>
                <dd className="font-medium">
                  {workstation.vlan?.name ?? (workstation.vlan_id ? workstation.vlan_id : '—')}
                </dd>
              </div>
            </dl>
          </div>
          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-2">{t('systemInfo')}</h3>
            <dl className="grid grid-cols-2 gap-4 text-sm">
              {workstation.hostname && (
                <div>
                  <dt className="text-gray-600">{t('hostname')}</dt>
                  <dd className="font-medium">{workstation.hostname}</dd>
                </div>
              )}
              {workstation.os_serial && (
                <div>
                  <dt className="text-gray-600">{t('osSerial')}</dt>
                  <dd className="font-mono text-xs">{workstation.os_serial}</dd>
                </div>
              )}
              {workstation.current_user && (
                <div>
                  <dt className="text-gray-600">{t('currentUser')}</dt>
                  <dd className="font-medium">{workstation.current_user}</dd>
                </div>
              )}
              <div>
                <dt className="text-gray-600">Versión Tray</dt>
                <dd className="font-medium">{workstation.tray_version ?? '—'}</dd>
              </div>
            </dl>
          </div>
          {workstation.organization && (
            <div>
              <h3 className="text-sm font-medium text-gray-700 mb-2">{t('account')}</h3>
              <div className="flex items-center">
                <Building2 className="w-5 h-5 text-blue-600 mr-2" />
                <span className="font-medium">{workstation.organization.name}</span>
              </div>
            </div>
          )}
          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-2">{t('dates')}</h3>
            <dl className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <dt className="text-gray-600">{t('firstConnection')}</dt>
                <dd className="font-medium">
                  {formatDateWithTimezone(workstation.first_seen, userTimezone)}
                </dd>
              </div>
              {workstation.last_connection && (
                <div>
                  <dt className="text-gray-600">{t('lastConnection')}</dt>
                  <dd className="font-medium">
                    {formatDateWithTimezone(workstation.last_connection, userTimezone)}
                  </dd>
                </div>
              )}
            </dl>
          </div>
          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-2">ID</h3>
            <code className="text-xs bg-gray-100 px-2 py-1 rounded">{workstation.id}</code>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
