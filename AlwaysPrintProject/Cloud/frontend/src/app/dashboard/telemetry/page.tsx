/**
 * Página de dashboard de telemetría.
 *
 * Muestra estadísticas agregadas de la cuenta, tabla de workstations con
 * su última telemetría, y panel de historial al seleccionar una workstation.
 */

'use client';

import { useState, useEffect, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/api';
import { useAuth } from '@/hooks/useAuth';
import { useTranslations } from 'next-intl';
import { formatDateWithTimezone } from '@/lib/dateUtils';
import { useUserTimezone } from '@/hooks/useUserTimezone';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from '@/components/ui/table';
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Clock,
  Monitor,
  RefreshCw,
  Wifi,
} from 'lucide-react';
import type { TelemetryEntry, TelemetryStats } from '@/types/telemetry';
import type { Workstation } from '@/types/workstation';

// ============================================================================
// CONSTANTES
// ============================================================================

const PAGE_SIZE = 50;

// ============================================================================
// INTERFACES INTERNAS
// ============================================================================

/**
 * Respuesta paginada de workstations.
 */
interface WorkstationsPaginatedResponse {
  items: Workstation[];
  total: number;
}

// ============================================================================
// FUNCIONES DE FETCH
// ============================================================================

/**
 * Obtiene estadísticas de telemetría de la cuenta.
 */
async function fetchTelemetryStats(accountId: string): Promise<TelemetryStats> {
  if (!accountId) throw new Error('Sin cuenta asignada');
  const response = await apiClient.get<TelemetryStats>(
    `/organizations/${accountId}/telemetry/stats`
  );
  return response.data;
}

/**
 * Obtiene la última telemetría de las workstations visibles (batch).
 * Envía los IDs de las workstations actualmente en la página para evitar
 * N llamadas individuales. Máximo 100 IDs por llamada.
 */
async function fetchLatestTelemetryBatch(workstationIds: string[]): Promise<Record<string, TelemetryEntry | null>> {
  if (workstationIds.length === 0) return {};
  const response = await apiClient.post<{ items: Record<string, TelemetryEntry | null> }>(
    '/workstations/telemetry/latest-batch',
    { workstation_ids: workstationIds }
  );
  return response.data.items;
}

/**
 * Obtiene el historial de telemetría de una workstation (últimas 24h, max 100).
 */
async function fetchWorkstationTelemetry(workstationId: string): Promise<TelemetryEntry[]> {
  const response = await apiClient.get<TelemetryEntry[]>(
    `/workstations/${workstationId}/telemetry`,
    { params: { limit: 100 } }
  );
  return response.data;
}

/**
 * Obtiene la lista paginada de workstations.
 */
async function fetchWorkstationsPaginated(page: number, pageSize: number): Promise<WorkstationsPaginatedResponse> {
  const response = await apiClient.get<{ items: Workstation[]; total: number }>('/workstations/', {
    params: { page, page_size: pageSize },
  });
  return { items: response.data.items, total: response.data.total };
}

// ============================================================================
// COMPONENTE PRINCIPAL
// ============================================================================

export default function TelemetryDashboardPage() {
  const { user, isLoading: authLoading } = useAuth();
  const accountId = user?.organization_id ?? '';
  const userTimezone = useUserTimezone();
  const tCommon = useTranslations('common');
  const t = useTranslations('telemetry');
  const [selectedWorkstationId, setSelectedWorkstationId] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const [page, setPage] = useState(1);

  // --- Queries con auto-refresh cada 60s ---

  const statsQuery = useQuery({
    queryKey: ['telemetry', 'stats', accountId],
    queryFn: () => fetchTelemetryStats(accountId),
    enabled: !authLoading && !!accountId,
    staleTime: 60000,
    refetchInterval: 60000,
    refetchOnWindowFocus: true,
  });

  const workstationsQuery = useQuery({
    queryKey: ['telemetry', 'workstations', page],
    queryFn: () => fetchWorkstationsPaginated(page, PAGE_SIZE),
    staleTime: 60000,
    refetchInterval: 60000,
    refetchOnWindowFocus: true,
    placeholderData: (prev) => prev,
  });

  // Derivar lista de workstations antes de la query batch (que depende de sus IDs)
  const workstations = workstationsQuery.data?.items ?? [];
  const totalWorkstations = workstationsQuery.data?.total ?? 0;
  const totalPages = Math.ceil(totalWorkstations / PAGE_SIZE);

  const latestBatchQuery = useQuery({
    queryKey: ['telemetry', 'latest-batch', workstations.map(w => w.id).sort().join(',')],
    queryFn: () => fetchLatestTelemetryBatch(workstations.map(w => w.id)),
    enabled: workstations.length > 0,
    staleTime: 60000,
    refetchInterval: 60000,
    refetchOnWindowFocus: true,
  });

  const historyQuery = useQuery({
    queryKey: ['telemetry', 'history', selectedWorkstationId],
    queryFn: () => fetchWorkstationTelemetry(selectedWorkstationId!),
    enabled: !!selectedWorkstationId,
    staleTime: 60000,
    refetchOnWindowFocus: true,
  });

  // --- Render ---
  const isRefreshing = statsQuery.isFetching || workstationsQuery.isFetching || latestBatchQuery.isFetching;

  // --- Actualizar timestamp cuando los datos se cargan exitosamente ---
  useEffect(() => {
    if ((statsQuery.data || workstationsQuery.data) && !isRefreshing) {
      setLastUpdated(new Date());
    }
  }, [statsQuery.data, workstationsQuery.data, isRefreshing]);

  const handleRefresh = useCallback(() => {
    statsQuery.refetch();
    workstationsQuery.refetch();
    latestBatchQuery.refetch();
  }, [statsQuery, workstationsQuery, latestBatchQuery]);

  return (
    <div className="max-w-7xl mx-auto">
      {/* Encabezado */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">{t('title')}</h1>
          <p className="text-gray-600 mt-2">
            {t('subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-500">
            {tCommon('lastUpdated', { time: formatDateWithTimezone(lastUpdated, userTimezone) })}
          </span>
          <Button
            disabled={isRefreshing}
            onClick={handleRefresh}
          >
            <RefreshCw className={`w-4 h-4 mr-2 ${isRefreshing ? 'animate-spin' : ''}`} />
            {tCommon('refresh')}
          </Button>
        </div>
      </div>

      {/* Cards de estadísticas */}
      <StatsCards
        stats={statsQuery.data}
        isLoading={statsQuery.isLoading}
        isError={statsQuery.isError}
        onRetry={() => statsQuery.refetch()}
      />

      {/* Tabla de workstations */}
      <div className="mt-6">
        <WorkstationsTable
          workstations={workstations}
          latestBatch={latestBatchQuery.data ?? {}}
          total={totalWorkstations}
          page={page}
          totalPages={totalPages}
          onPageChange={setPage}
          isLoading={workstationsQuery.isLoading}
          isError={workstationsQuery.isError}
          onRetry={() => workstationsQuery.refetch()}
          selectedId={selectedWorkstationId}
          onSelect={(id) => setSelectedWorkstationId(id === selectedWorkstationId ? null : id)}
        />
      </div>

      {/* Panel de historial */}
      {selectedWorkstationId && (
        <div className="mt-6">
          <TelemetryHistoryPanel
            workstationId={selectedWorkstationId}
            workstationName={
              workstations.find((w) => w.id === selectedWorkstationId)?.hostname ??
              workstations.find((w) => w.id === selectedWorkstationId)?.ip_private ??
              selectedWorkstationId
            }
            entries={historyQuery.data ?? []}
            isLoading={historyQuery.isLoading}
            isError={historyQuery.isError}
            onRetry={() => historyQuery.refetch()}
          />
        </div>
      )}
    </div>
  );
}

// ============================================================================
// COMPONENTE: CARDS DE ESTADÍSTICAS
// ============================================================================

function StatsCards({
  stats,
  isLoading,
  isError,
  onRetry,
}: {
  stats: TelemetryStats | undefined;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}) {
  const t = useTranslations('telemetry');

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        {[1, 2, 3, 4].map((i) => (
          <Card key={i}>
            <CardContent className="p-6">
              <div className="animate-pulse space-y-3">
                <div className="h-4 bg-gray-200 rounded w-2/3"></div>
                <div className="h-8 bg-gray-200 rounded w-1/3"></div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription className="flex items-center justify-between">
          <span>{t('statsError')}</span>
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw className="w-3 h-3 mr-1" />
            {t('retry')}
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  if (!stats) return null;

  const errorCount =
    (stats.queue_status_summary?.error ?? 0) + (stats.queue_status_summary?.missing ?? 0);

  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
      <Card>
        <CardContent className="p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">{t('reporting')}</p>
              <p className="text-3xl font-bold text-gray-900">
                {stats.workstations_reporting}
              </p>
              <p className="text-xs text-gray-500 mt-1">{t('ofTotal', { total: stats.total_workstations })}</p>
            </div>
            <Monitor className="w-12 h-12 text-blue-600" />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">{t('errors')}</p>
              <p className="text-3xl font-bold text-red-600">{errorCount}</p>
              <p className="text-xs text-gray-500 mt-1">{t('errorsDetail')}</p>
            </div>
            <AlertCircle className="w-12 h-12 text-red-600" />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">{t('contingencyActive')}</p>
              <p className="text-3xl font-bold text-amber-600">
                {stats.contingency_active_count}
              </p>
            </div>
            <AlertTriangle className="w-12 h-12 text-amber-600" />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">{t('avgRelease')}</p>
              <p className="text-3xl font-bold text-gray-900">
                {stats.avg_jobs_identified > 0 ? `${stats.avg_jobs_identified}` : '—'}
              </p>
              <p className="text-xs text-gray-500 mt-1">{t('avgJobs')}</p>
            </div>
            <Clock className="w-12 h-12 text-indigo-600" />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ============================================================================
// COMPONENTE: TABLA DE WORKSTATIONS
// ============================================================================

function WorkstationsTable({
  workstations,
  latestBatch,
  total,
  page,
  totalPages,
  onPageChange,
  isLoading,
  isError,
  onRetry,
  selectedId,
  onSelect,
}: {
  workstations: Workstation[];
  latestBatch: Record<string, TelemetryEntry | null>;
  total: number;
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const t = useTranslations('telemetry');
  const tCommon = useTranslations('common');

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t('workstations')}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="animate-pulse space-y-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-12 bg-gray-200 rounded"></div>
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  if (isError) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t('workstations')}</CardTitle>
        </CardHeader>
        <CardContent>
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription className="flex items-center justify-between">
              <span>{t('loadError')}</span>
              <Button variant="outline" size="sm" onClick={onRetry}>
                <RefreshCw className="w-3 h-3 mr-1" />
                {t('retry')}
              </Button>
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  if (workstations.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t('workstations')}</CardTitle>
        </CardHeader>
        <CardContent className="p-12 text-center">
          <Wifi className="w-16 h-16 text-gray-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">{t('noTelemetryTitle')}</h3>
          <p className="text-gray-600">
            {t('noTelemetryMsg')}
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('lastTelemetry')}</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('colName')}</TableHead>
              <TableHead>{t('colQueueStatus')}</TableHead>
              <TableHead>{t('colContingency')}</TableHead>
              <TableHead>{t('colJobs')}</TableHead>
              <TableHead>{t('colReleaseTime')}</TableHead>
              <TableHead>{t('colDisconnections')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {workstations.map((ws) => (
              <WorkstationRow
                key={ws.id}
                workstation={ws}
                latestEntry={latestBatch[ws.id] ?? null}
                isSelected={ws.id === selectedId}
                onSelect={() => onSelect(ws.id)}
              />
            ))}
          </TableBody>
        </Table>

        {/* Controles de paginación */}
        {total > PAGE_SIZE && (
          <div className="flex items-center justify-between border-t border-gray-200 pt-4 mt-4">
            <p className="text-sm text-gray-700">
              {t('pagination', {
                start: (page - 1) * PAGE_SIZE + 1,
                end: Math.min(page * PAGE_SIZE, total),
                total,
              })}
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => onPageChange(page - 1)}
                disabled={page === 1}
              >
                {tCommon('previous')}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => onPageChange(page + 1)}
                disabled={page >= totalPages}
              >
                {tCommon('next')}
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ============================================================================
// COMPONENTE: FILA DE WORKSTATION CON TELEMETRÍA
// ============================================================================

function WorkstationRow({
  workstation,
  latestEntry,
  isSelected,
  onSelect,
}: {
  workstation: Workstation;
  latestEntry: TelemetryEntry | null;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const t = useTranslations('telemetry');

  const displayName = workstation.hostname ?? workstation.ip_private;

  return (
    <TableRow
      className={`cursor-pointer ${isSelected ? 'bg-blue-50' : ''}`}
      onClick={onSelect}
    >
      <TableCell className="font-medium">{displayName}</TableCell>
      <TableCell>
        {latestEntry ? (
          <QueueStatusBadge status={latestEntry.queue_status} />
        ) : (
          <Badge variant="secondary">{t('noData')}</Badge>
        )}
      </TableCell>
      <TableCell>
        {latestEntry ? (
          <ContingencyBadge active={latestEntry.contingency_active} />
        ) : (
          <span className="text-gray-400">—</span>
        )}
      </TableCell>
      <TableCell>
        {latestEntry ? latestEntry.jobs_identified : <span className="text-gray-400">—</span>}
      </TableCell>
      <TableCell>
        {latestEntry?.avg_release_time_ms != null ? (
          `${latestEntry.avg_release_time_ms} ms`
        ) : (
          <span className="text-gray-400">—</span>
        )}
      </TableCell>
      <TableCell>
        {latestEntry ? latestEntry.disconnection_count : <span className="text-gray-400">—</span>}
      </TableCell>
    </TableRow>
  );
}

// ============================================================================
// COMPONENTE: PANEL DE HISTORIAL
// ============================================================================

function TelemetryHistoryPanel({
  workstationId,
  workstationName,
  entries,
  isLoading,
  isError,
  onRetry,
}: {
  workstationId: string;
  workstationName: string;
  entries: TelemetryEntry[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}) {
  const t = useTranslations('telemetry');
  const userTimezone = useUserTimezone();

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t('history')} — {workstationName}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="animate-pulse space-y-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-10 bg-gray-200 rounded"></div>
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  if (isError) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t('history')} — {workstationName}</CardTitle>
        </CardHeader>
        <CardContent>
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription className="flex items-center justify-between">
              <span>{t('historyError')}</span>
              <Button variant="outline" size="sm" onClick={onRetry}>
                <RefreshCw className="w-3 h-3 mr-1" />
                {t('retry')}
              </Button>
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  if (entries.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t('history')} — {workstationName}</CardTitle>
        </CardHeader>
        <CardContent className="p-8 text-center">
          <Activity className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-600">
            {t('noHistoryMsg')}
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {t('history')} — {workstationName}
          <span className="text-sm font-normal text-gray-500 ml-2">
            {t('last24h')}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('colDateTime')}</TableHead>
              <TableHead>{t('colQueueStatus')}</TableHead>
              <TableHead>{t('colContingency')}</TableHead>
              <TableHead>{t('colJobs')}</TableHead>
              <TableHead>{t('colReleaseTime')}</TableHead>
              <TableHead>{t('colDisconnections')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map((entry) => (
              <TableRow key={entry.id}>
                <TableCell className="text-sm text-gray-700">
                  {formatRecordedAt(entry.recorded_at, userTimezone)}
                </TableCell>
                <TableCell>
                  <QueueStatusBadge status={entry.queue_status} />
                </TableCell>
                <TableCell>
                  <ContingencyBadge active={entry.contingency_active} />
                </TableCell>
                <TableCell>{entry.jobs_identified}</TableCell>
                <TableCell>
                  {entry.avg_release_time_ms != null ? `${entry.avg_release_time_ms} ms` : '—'}
                </TableCell>
                <TableCell>{entry.disconnection_count}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

// ============================================================================
// COMPONENTES AUXILIARES: BADGES
// ============================================================================

function QueueStatusBadge({ status }: { status: TelemetryEntry['queue_status'] }) {
  switch (status) {
    case 'ok':
      return <Badge variant="success">OK</Badge>;
    case 'missing':
      return <Badge variant="warning">Missing</Badge>;
    case 'error':
      return <Badge variant="destructive">Error</Badge>;
    default:
      return <Badge variant="secondary">{status}</Badge>;
  }
}

function ContingencyBadge({ active }: { active: boolean }) {
  const t = useTranslations('telemetry');
  if (active) {
    return <Badge variant="destructive">{t('contingencyActive2')}</Badge>;
  }
  return <Badge variant="secondary">{t('contingencyInactive')}</Badge>;
}

// ============================================================================
// UTILIDADES
// ============================================================================

/**
 * Formatea una fecha ISO 8601 para mostrar en la tabla de historial.
 * Usa el timezone proporcionado para consistencia.
 */
function formatRecordedAt(isoDate: string, timezone: string): string {
  try {
    return formatDateWithTimezone(isoDate, timezone);
  } catch {
    return isoDate;
  }
}
