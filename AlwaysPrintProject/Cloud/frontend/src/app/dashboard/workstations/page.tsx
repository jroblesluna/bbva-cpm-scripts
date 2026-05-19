/**
 * Página de gestión de workstations.
 * Vista de tarjetas (responsive) y vista de tabla con columnas ordenables.
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
  RotateCcw,
  Download,
  Terminal,
  FileText,
  LayoutGrid,
  List,
  ArrowUpDown,
} from 'lucide-react';
import { formatDateWithTimezone } from '@/lib/dateUtils';
import { useUserTimezone } from '@/hooks/useUserTimezone';
import { useToast } from '@/hooks/use-toast';
import type { Workstation, WorkstationUpdate, Organization, VLAN } from '@/types';

type ViewMode = 'cards' | 'table';
type SortField = 'ip_private' | 'hostname' | 'current_user' | 'organization' | 'tray_version' | 'last_connection' | 'is_online';
type SortDirection = 'asc' | 'desc';

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
  const [viewMode, setViewMode] = useState<ViewMode>('cards');
  const [sortField, setSortField] = useState<SortField>('ip_private');
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');

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

  const { toast } = useToast();

  const commandMutation = useMutation({
    mutationFn: ({ id, commandType }: { id: string; commandType: 'restart_service' | 'restart_tray' | 'check_update' }) =>
      workstationsApi.sendCommand(id, commandType),
    onSuccess: (_data, variables) => {
      const labels: Record<string, string> = {
        restart_service: 'Reiniciar Servicio',
        restart_tray: 'Reiniciar Tray',
        check_update: 'Verificar Actualización',
      };
      toast({
        title: 'Comando enviado',
        description: `"${labels[variables.commandType]}" enviado exitosamente.`,
      });
    },
    onError: (error: { detail?: string; status?: number }) => {
      const message = error.status === 409
        ? 'La workstation está offline.'
        : (error.detail ?? 'Error al enviar comando.');
      toast({
        variant: 'destructive',
        title: 'Error',
        description: message,
      });
    },
  });

  const logDownloadMutation = useMutation({
    mutationFn: (id: string) => workstationsApi.downloadLatestLog(id),
    onSuccess: ({ blob, filename }) => {
      // Crear enlace temporal para descargar el archivo
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      toast({
        title: 'Log descargado',
        description: `Archivo "${filename}" descargado exitosamente.`,
      });
    },
    onError: (error: { detail?: string; status?: number }) => {
      let message: string;
      if (error.status === 409) {
        message = 'La workstation está offline.';
      } else if (error.status === 408) {
        message = 'Timeout esperando respuesta de la workstation.';
      } else {
        message = error.detail ?? 'Error al descargar el log.';
      }
      toast({
        variant: 'destructive',
        title: 'Error al descargar log',
        description: message,
      });
    },
  });

  const handleDelete = (workstation: Workstation) => {
    if (confirm(`¿Eliminar workstation ${workstation.hostname || workstation.ip_private}? Esta acción no se puede deshacer.`)) {
      deleteMutation.mutate(workstation.id);
    }
  };

  const workstations = workstationsData?.items || [];

  // Ordenar workstations para la vista de tabla
  const sortedWorkstations = [...workstations].sort((a, b) => {
    const dir = sortDirection === 'asc' ? 1 : -1;
    switch (sortField) {
      case 'ip_private':
        return dir * a.ip_private.localeCompare(b.ip_private);
      case 'hostname':
        return dir * (a.hostname ?? '').localeCompare(b.hostname ?? '');
      case 'current_user':
        return dir * (a.current_user ?? '').localeCompare(b.current_user ?? '');
      case 'organization':
        return dir * (a.organization?.name ?? '').localeCompare(b.organization?.name ?? '');
      case 'tray_version':
        return dir * (a.tray_version ?? '').localeCompare(b.tray_version ?? '');
      case 'last_connection':
        return dir * (a.last_connection ?? '').localeCompare(b.last_connection ?? '');
      case 'is_online':
        return dir * (Number(a.is_online) - Number(b.is_online));
      default:
        return 0;
    }
  });

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('asc');
    }
  };

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
      <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-8 gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">{t('title')}</h1>
          <p className="text-gray-600 mt-2">{t('subtitle')}</p>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-500 hidden sm:inline">
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
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 md:gap-6 mb-6">
          <Card>
            <CardContent className="p-4 md:p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">{t('total')}</p>
                  <p className="text-2xl md:text-3xl font-bold text-gray-900">{stats.total}</p>
                </div>
                <Monitor className="w-8 h-8 md:w-12 md:h-12 text-blue-600" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4 md:p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">{t('online')}</p>
                  <p className="text-2xl md:text-3xl font-bold text-green-600">{stats.online}</p>
                </div>
                <CheckCircle className="w-8 h-8 md:w-12 md:h-12 text-green-600" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4 md:p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">{t('offline')}</p>
                  <p className="text-2xl md:text-3xl font-bold text-gray-600">{stats.offline}</p>
                </div>
                <XCircle className="w-8 h-8 md:w-12 md:h-12 text-gray-400" />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-4 md:p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">{t('contingency')}</p>
                  <p className="text-2xl md:text-3xl font-bold text-amber-600">
                    {stats.contingency_active}
                  </p>
                </div>
                <Activity className="w-8 h-8 md:w-12 md:h-12 text-amber-600" />
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
          <div className="flex items-center justify-between mt-4">
            <div className="flex items-center space-x-4">
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
            {/* Toggle de vista: tarjetas / tabla */}
            <div className="flex items-center gap-1 border rounded-md p-0.5">
              <Button
                variant={viewMode === 'cards' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('cards')}
                title="Vista de tarjetas"
                className="h-8 w-8 p-0"
              >
                <LayoutGrid className="w-4 h-4" />
              </Button>
              <Button
                variant={viewMode === 'table' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('table')}
                title="Vista de tabla"
                className="h-8 w-8 p-0"
              >
                <List className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {editingWorkstation && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4" style={{ zIndex: 999 }}>
          <Card className="max-w-2xl w-full max-h-[90vh] overflow-y-auto">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>{t('editTitle', { ip: editingWorkstation.ip_private })}</CardTitle>
              <Button variant="ghost" size="sm" onClick={() => setEditingWorkstation(null)}>
                <XCircle className="w-5 h-5" />
              </Button>
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
        </div>
      )}

      {/* Contenido principal: vista de tarjetas o tabla */}
      {viewMode === 'cards' ? (
        <div className="space-y-4">
          {workstations.length > 0 ? (
            workstations.map((workstation) => (
              <WorkstationCard
                key={workstation.id}
                workstation={workstation}
                userTimezone={userTimezone}
                t={t}
                onViewDetails={() => setSelectedWorkstation(workstation)}
                onEdit={() => setEditingWorkstation(workstation)}
                onDelete={() => handleDelete(workstation)}
                onCommand={(commandType) => commandMutation.mutate({ id: workstation.id, commandType })}
                onDownloadLog={() => logDownloadMutation.mutate(workstation.id)}
                isCommandPending={commandMutation.isPending}
                isDeletePending={deleteMutation.isPending}
                isLogPending={logDownloadMutation.isPending}
              />
            ))
          ) : (
            <EmptyState searchTerm={searchTerm} filterOnline={filterOnline} filterContingency={filterContingency} filterOrgId={filterOrgId} filterVlanId={filterVlanId} t={t} />
          )}
        </div>
      ) : (
        <WorkstationTable
          workstations={sortedWorkstations}
          userTimezone={userTimezone}
          t={t}
          sortField={sortField}
          sortDirection={sortDirection}
          onSort={handleSort}
          onViewDetails={(ws) => setSelectedWorkstation(ws)}
          onEdit={(ws) => setEditingWorkstation(ws)}
          onDelete={handleDelete}
          onCommand={(id, commandType) => commandMutation.mutate({ id, commandType })}
          onDownloadLog={(id) => logDownloadMutation.mutate(id)}
          isCommandPending={commandMutation.isPending}
          isDeletePending={deleteMutation.isPending}
          isLogPending={logDownloadMutation.isPending}
        />
      )}

      {selectedWorkstation && (
        <WorkstationDetailModal
          workstation={selectedWorkstation}
          onClose={() => setSelectedWorkstation(null)}
        />
      )}
    </div>
  );
}

// ============================================================================
// Componente: Tarjeta de Workstation (responsive)
// ============================================================================

interface WorkstationCardProps {
  workstation: Workstation;
  userTimezone: string;
  t: ReturnType<typeof useTranslations>;
  onViewDetails: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onCommand: (commandType: 'restart_service' | 'restart_tray' | 'check_update') => void;
  onDownloadLog: () => void;
  isCommandPending: boolean;
  isDeletePending: boolean;
  isLogPending: boolean;
}

function WorkstationCard({
  workstation,
  userTimezone,
  t,
  onViewDetails,
  onEdit,
  onDelete,
  onCommand,
  onDownloadLog,
  isCommandPending,
  isDeletePending,
  isLogPending,
}: WorkstationCardProps) {
  return (
    <Card className="hover:shadow-md transition">
      <CardContent className="p-4 md:p-6">
        {/* Fila 1: Icono + IP + Badges + Acciones (desktop) */}
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
          <div className="flex items-center gap-3">
            <div
              className={`rounded-full p-2 md:p-3 shrink-0 ${workstation.is_online ? 'bg-green-100' : 'bg-gray-100'}`}
            >
              <Monitor
                className={`w-5 h-5 md:w-6 md:h-6 ${workstation.is_online ? 'text-green-600' : 'text-gray-400'}`}
              />
            </div>
            <h3 className="text-lg md:text-xl font-semibold text-gray-900">
              {workstation.ip_private}
            </h3>
            <Badge variant={workstation.is_online ? 'default' : 'secondary'}>
              {workstation.is_online ? t('online') : t('offline')}
            </Badge>
            {workstation.contingency_active && (
              <Badge variant="destructive">
                {t('contingency')}
              </Badge>
            )}
          </div>

          {/* Acciones: visibles en desktop en la misma fila */}
          <div className="hidden md:flex items-center flex-wrap gap-1">
            <Button
              variant="outline"
              size="sm"
              onClick={onViewDetails}
            >
              {t('viewDetails')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={onEdit}
            >
              <Edit className="w-4 h-4" />
            </Button>
            {workstation.is_online && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  title="Descargar Log"
                  onClick={onDownloadLog}
                  disabled={isLogPending}
                >
                  <FileText className="w-4 h-4" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  title="Reiniciar Servicio"
                  onClick={() => onCommand('restart_service')}
                  disabled={isCommandPending}
                >
                  <RotateCcw className="w-4 h-4" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  title="Reiniciar Tray"
                  onClick={() => onCommand('restart_tray')}
                  disabled={isCommandPending}
                >
                  <Terminal className="w-4 h-4" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  title="Verificar Actualización"
                  onClick={() => onCommand('check_update')}
                  disabled={isCommandPending}
                >
                  <Download className="w-4 h-4" />
                </Button>
              </>
            )}
            <Button
              variant="destructive"
              size="sm"
              onClick={onDelete}
              disabled={isDeletePending}
            >
              <Trash2 className="w-4 h-4" />
            </Button>
          </div>
        </div>

        {/* Fila 2: Info compacta (hostname, user, org, version, cidr, vlan) */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-gray-600 mt-3">
          {workstation.hostname && (
            <div className="flex items-center">
              <Monitor className="w-3.5 h-3.5 mr-1 shrink-0" />
              <span className="truncate">{workstation.hostname}</span>
            </div>
          )}
          {workstation.current_user && (
            <div className="flex items-center">
              <User className="w-3.5 h-3.5 mr-1 shrink-0" />
              <span className="truncate">{workstation.current_user}</span>
            </div>
          )}
          {workstation.organization && (
            <div className="flex items-center">
              <Building2 className="w-3.5 h-3.5 mr-1 shrink-0" />
              <span className="truncate">{workstation.organization.name}</span>
            </div>
          )}
          {workstation.cidr && (
            <div className="flex items-center">
              <Network className="w-3.5 h-3.5 mr-1 shrink-0" />
              <span className="font-mono text-xs">{workstation.cidr}</span>
            </div>
          )}
          {workstation.vlan_id && (
            <div className="flex items-center">
              <Network className="w-3.5 h-3.5 mr-1 shrink-0" />
              <span className="truncate">{workstation.vlan?.name ?? workstation.vlan_id}</span>
            </div>
          )}
          <div className="flex items-center">
            <Tag className="w-3.5 h-3.5 mr-1 shrink-0" />
            <span className="font-mono text-xs">
              {workstation.tray_version ? `v${workstation.tray_version}` : '—'}
            </span>
          </div>
        </div>

        {/* Fila 3: Timestamps */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500 mt-2">
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

        {/* Fila 4: Acciones en mobile (flex-wrap) */}
        <div className="flex md:hidden flex-wrap gap-1 mt-3 pt-3 border-t border-gray-100">
          <Button
            variant="outline"
            size="sm"
            onClick={onViewDetails}
            className="h-8 w-8 p-0"
            title={t('viewDetails')}
          >
            <Search className="w-4 h-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={onEdit}
            className="h-8 w-8 p-0"
            title="Editar"
          >
            <Edit className="w-4 h-4" />
          </Button>
          {workstation.is_online && (
            <>
              <Button
                variant="outline"
                size="sm"
                title="Descargar Log"
                onClick={onDownloadLog}
                disabled={isLogPending}
                className="h-8 w-8 p-0"
              >
                <FileText className="w-4 h-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                title="Reiniciar Servicio"
                onClick={() => onCommand('restart_service')}
                disabled={isCommandPending}
                className="h-8 w-8 p-0"
              >
                <RotateCcw className="w-4 h-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                title="Reiniciar Tray"
                onClick={() => onCommand('restart_tray')}
                disabled={isCommandPending}
                className="h-8 w-8 p-0"
              >
                <Terminal className="w-4 h-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                title="Verificar Actualización"
                onClick={() => onCommand('check_update')}
                disabled={isCommandPending}
                className="h-8 w-8 p-0"
              >
                <Download className="w-4 h-4" />
              </Button>
            </>
          )}
          <Button
            variant="destructive"
            size="sm"
            onClick={onDelete}
            disabled={isDeletePending}
            className="h-8 w-8 p-0"
            title="Eliminar"
          >
            <Trash2 className="w-4 h-4" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ============================================================================
// Componente: Vista de Tabla
// ============================================================================

interface WorkstationTableProps {
  workstations: Workstation[];
  userTimezone: string;
  t: ReturnType<typeof useTranslations>;
  sortField: SortField;
  sortDirection: SortDirection;
  onSort: (field: SortField) => void;
  onViewDetails: (ws: Workstation) => void;
  onEdit: (ws: Workstation) => void;
  onDelete: (ws: Workstation) => void;
  onCommand: (id: string, commandType: 'restart_service' | 'restart_tray' | 'check_update') => void;
  onDownloadLog: (id: string) => void;
  isCommandPending: boolean;
  isDeletePending: boolean;
  isLogPending: boolean;
}

function WorkstationTable({
  workstations,
  userTimezone,
  t,
  sortField,
  sortDirection,
  onSort,
  onViewDetails,
  onEdit,
  onDelete,
  onCommand,
  onDownloadLog,
  isCommandPending,
  isDeletePending,
  isLogPending,
}: WorkstationTableProps) {
  if (workstations.length === 0) {
    return (
      <EmptyState searchTerm="" filterOnline={undefined} filterContingency={undefined} filterOrgId={undefined} filterVlanId={undefined} t={t} />
    );
  }

  const SortHeader = ({ field, children }: { field: SortField; children: React.ReactNode }) => (
    <th
      className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider cursor-pointer hover:bg-gray-100 select-none whitespace-nowrap"
      onClick={() => onSort(field)}
    >
      <div className="flex items-center gap-1">
        {children}
        <ArrowUpDown className={`w-3 h-3 ${sortField === field ? 'text-gray-900' : 'text-gray-400'}`} />
        {sortField === field && (
          <span className="text-[10px] text-gray-600">
            {sortDirection === 'asc' ? '↑' : '↓'}
          </span>
        )}
      </div>
    </th>
  );

  return (
    <Card>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <SortHeader field="is_online">Estado</SortHeader>
                <SortHeader field="ip_private">IP</SortHeader>
                <SortHeader field="hostname">Hostname</SortHeader>
                <SortHeader field="current_user">Usuario</SortHeader>
                <SortHeader field="organization">Org</SortHeader>
                <SortHeader field="tray_version">Versión</SortHeader>
                <SortHeader field="last_connection">Última Conexión</SortHeader>
                <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Acciones
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {workstations.map((ws) => (
                <tr key={ws.id} className="hover:bg-gray-50 transition-colors">
                  {/* Estado */}
                  <td className="px-3 py-3 whitespace-nowrap">
                    <div className="flex items-center gap-1.5">
                      <span
                        className={`w-2.5 h-2.5 rounded-full shrink-0 ${ws.is_online ? 'bg-green-500' : 'bg-gray-400'}`}
                      />
                      {ws.contingency_active && (
                        <Badge variant="destructive" className="text-[10px] px-1 py-0">
                          C
                        </Badge>
                      )}
                    </div>
                  </td>
                  {/* IP */}
                  <td className="px-3 py-3 whitespace-nowrap font-mono font-medium text-gray-900">
                    {ws.ip_private}
                  </td>
                  {/* Hostname */}
                  <td className="px-3 py-3 whitespace-nowrap text-gray-700">
                    {ws.hostname ?? '—'}
                  </td>
                  {/* Usuario */}
                  <td className="px-3 py-3 whitespace-nowrap text-gray-700">
                    {ws.current_user ?? '—'}
                  </td>
                  {/* Organización */}
                  <td className="px-3 py-3 whitespace-nowrap text-gray-700">
                    {ws.organization?.name ?? '—'}
                  </td>
                  {/* Versión */}
                  <td className="px-3 py-3 whitespace-nowrap font-mono text-xs text-gray-600">
                    {ws.tray_version ? `v${ws.tray_version}` : '—'}
                  </td>
                  {/* Última Conexión */}
                  <td className="px-3 py-3 whitespace-nowrap text-xs text-gray-500">
                    {ws.last_connection
                      ? formatDateWithTimezone(ws.last_connection, userTimezone)
                      : '—'}
                  </td>
                  {/* Acciones */}
                  <td className="px-3 py-3 whitespace-nowrap">
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onViewDetails(ws)}
                        title={t('viewDetails')}
                        className="h-7 w-7 p-0"
                      >
                        <Search className="w-3.5 h-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onEdit(ws)}
                        title="Editar"
                        className="h-7 w-7 p-0"
                      >
                        <Edit className="w-3.5 h-3.5" />
                      </Button>
                      {ws.is_online && (
                        <>
                          <Button
                            variant="ghost"
                            size="sm"
                            title="Descargar Log"
                            onClick={() => onDownloadLog(ws.id)}
                            disabled={isLogPending}
                            className="h-7 w-7 p-0"
                          >
                            <FileText className="w-3.5 h-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            title="Reiniciar Servicio"
                            onClick={() => onCommand(ws.id, 'restart_service')}
                            disabled={isCommandPending}
                            className="h-7 w-7 p-0"
                          >
                            <RotateCcw className="w-3.5 h-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            title="Reiniciar Tray"
                            onClick={() => onCommand(ws.id, 'restart_tray')}
                            disabled={isCommandPending}
                            className="h-7 w-7 p-0"
                          >
                            <Terminal className="w-3.5 h-3.5" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            title="Verificar Actualización"
                            onClick={() => onCommand(ws.id, 'check_update')}
                            disabled={isCommandPending}
                            className="h-7 w-7 p-0"
                          >
                            <Download className="w-3.5 h-3.5" />
                          </Button>
                        </>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onDelete(ws)}
                        disabled={isDeletePending}
                        title="Eliminar"
                        className="h-7 w-7 p-0 text-red-600 hover:text-red-700 hover:bg-red-50"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

// ============================================================================
// Componente: Estado vacío
// ============================================================================

function EmptyState({
  searchTerm,
  filterOnline,
  filterContingency,
  filterOrgId,
  filterVlanId,
  t,
}: {
  searchTerm: string;
  filterOnline: boolean | undefined;
  filterContingency: boolean | undefined;
  filterOrgId: string | undefined;
  filterVlanId: string | undefined;
  t: ReturnType<typeof useTranslations>;
}) {
  return (
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
  );
}

// ============================================================================
// Componente: Formulario de edición de Workstation (sin cambios)
// ============================================================================

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
    default_printer_id: workstation.default_printer_id || undefined,
  });
  const [availablePrinters, setAvailablePrinters] = useState<Array<{ id: string; name: string; ip_address: string }>>([]);

  // Cargar impresoras disponibles en la VLAN de la workstation
  useEffect(() => {
    if (!workstation.vlan_id) {
      setAvailablePrinters([]);
      return;
    }
    const loadPrinters = async () => {
      try {
        const response = await workstationsApi.getVlanDevices(workstation.vlan_id as string);
        setAvailablePrinters(response);
      } catch (err) {
        console.error('Error cargando impresoras:', err);
      }
    };
    loadPrinters();
  }, [workstation.vlan_id]);

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
      {/* Selector de impresora predeterminada (solo si la workstation tiene VLAN) */}
      {workstation.vlan_id && (
        <div className="space-y-2">
          <Label htmlFor="default_printer_id">{t('defaultPrinter')}</Label>
          <select
            id="default_printer_id"
            value={formData.default_printer_id || ''}
            onChange={(e) =>
              setFormData({ ...formData, default_printer_id: e.target.value || undefined })
            }
            disabled={isLoading}
            className="w-full px-3 py-2 border rounded-md"
          >
            <option value="">{t('selectPrinter')}</option>
            {availablePrinters.length > 0 ? (
              availablePrinters.map((printer) => (
                <option key={printer.id} value={printer.id}>
                  {printer.name} ({printer.ip_address})
                </option>
              ))
            ) : (
              <option value="" disabled>{t('noPrintersInVlan')}</option>
            )}
          </select>
        </div>
      )}
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

// ============================================================================
// Componente: Modal de detalle de Workstation (sin cambios)
// ============================================================================

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
