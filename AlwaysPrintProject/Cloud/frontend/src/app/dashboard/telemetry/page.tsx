/**
 * Página de dashboard de telemetría.
 *
 * Muestra estadísticas agregadas de la cuenta, tabla de workstations con
 * su última telemetría, y panel de historial al seleccionar una workstation.
 */

'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/api';
import { useAuth } from '@/hooks/useAuth';
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
// INTERFACES INTERNAS
// ============================================================================

/**
 * Workstation con su última entrada de telemetría asociada.
 */
interface WorkstationTelemetryRow {
  workstation: Workstation;
  latestEntry: TelemetryEntry | null;
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
    `/accounts/${accountId}/telemetry/stats`
  );
  return response.data;
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
 * Obtiene la lista de workstations de la cuenta.
 */
async function fetchWorkstations(): Promise<Workstation[]> {
  const response = await apiClient.get<{ items: Workstation[] }>('/workstations/', {
    params: { page_size: 500 },
  });
  return response.data.items;
}

// ============================================================================
// COMPONENTE PRINCIPAL
// ============================================================================

export default function TelemetryDashboardPage() {
  const { user, isLoading: authLoading } = useAuth();
  const accountId = user?.account_id ?? '';
  const [selectedWorkstationId, setSelectedWorkstationId] = useState<string | null>(null);

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
    queryKey: ['telemetry', 'workstations'],
    queryFn: fetchWorkstations,
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

  // --- Derivar datos para la tabla ---

  const workstations = workstationsQuery.data ?? [];

  // --- Render ---
  const isRefreshing = statsQuery.isFetching || workstationsQuery.isFetching;

  return (
    <div className="max-w-7xl mx-auto">
      {/* Encabezado */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Telemetría</h1>
          <p className="text-gray-600 mt-2">
            Monitoreo del estado operativo de las workstations
          </p>
        </div>
        <Button
          disabled={isRefreshing}
          onClick={() => {
            statsQuery.refetch();
            workstationsQuery.refetch();
          }}
        >
          <RefreshCw className={`w-4 h-4 mr-2 ${isRefreshing ? 'animate-spin' : ''}`} />
          Actualizar
        </Button>
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
          <span>Error al cargar estadísticas de telemetría</span>
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RefreshCw className="w-3 h-3 mr-1" />
            Reintentar
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
              <p className="text-sm font-medium text-gray-600">Reportando</p>
              <p className="text-3xl font-bold text-gray-900">
                {stats.workstations_reporting}
              </p>
              <p className="text-xs text-gray-500 mt-1">de {stats.total_workstations} total</p>
            </div>
            <Monitor className="w-12 h-12 text-blue-600" />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">Errores</p>
              <p className="text-3xl font-bold text-red-600">{errorCount}</p>
              <p className="text-xs text-gray-500 mt-1">cola error o missing</p>
            </div>
            <AlertCircle className="w-12 h-12 text-red-600" />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">Contingencia activa</p>
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
              <p className="text-sm font-medium text-gray-600">Tiempo promedio liberación</p>
              <p className="text-3xl font-bold text-gray-900">
                {stats.avg_jobs_identified > 0 ? `${stats.avg_jobs_identified}` : '—'}
              </p>
              <p className="text-xs text-gray-500 mt-1">jobs identificados (prom.)</p>
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
  isLoading,
  isError,
  onRetry,
  selectedId,
  onSelect,
}: {
  workstations: Workstation[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  // Obtener última telemetría por workstation
  // Nota: usamos una query separada para obtener la telemetría más reciente de cada ws
  // En este caso, la tabla de workstations muestra datos básicos y al seleccionar se carga el historial

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Workstations</CardTitle>
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
          <CardTitle>Workstations</CardTitle>
        </CardHeader>
        <CardContent>
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription className="flex items-center justify-between">
              <span>Error al cargar la lista de workstations</span>
              <Button variant="outline" size="sm" onClick={onRetry}>
                <RefreshCw className="w-3 h-3 mr-1" />
                Reintentar
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
          <CardTitle>Workstations</CardTitle>
        </CardHeader>
        <CardContent className="p-12 text-center">
          <Wifi className="w-16 h-16 text-gray-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">Sin datos de telemetría</h3>
          <p className="text-gray-600">
            No se ha registrado telemetría aún. Las workstations comenzarán a reportar cuando
            se conecten al sistema.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Workstations — Última telemetría</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nombre</TableHead>
              <TableHead>Estado cola</TableHead>
              <TableHead>Contingencia</TableHead>
              <TableHead>Jobs identificados</TableHead>
              <TableHead>Tiempo liberación</TableHead>
              <TableHead>Desconexiones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {workstations.map((ws) => (
              <WorkstationRow
                key={ws.id}
                workstation={ws}
                isSelected={ws.id === selectedId}
                onSelect={() => onSelect(ws.id)}
              />
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

// ============================================================================
// COMPONENTE: FILA DE WORKSTATION CON TELEMETRÍA
// ============================================================================

function WorkstationRow({
  workstation,
  isSelected,
  onSelect,
}: {
  workstation: Workstation;
  isSelected: boolean;
  onSelect: () => void;
}) {
  // Obtener la última telemetría de esta workstation
  const { data: telemetryData } = useQuery({
    queryKey: ['telemetry', 'latest', workstation.id],
    queryFn: async () => {
      const response = await apiClient.get<TelemetryEntry[]>(
        `/workstations/${workstation.id}/telemetry`,
        { params: { limit: 1 } }
      );
      return response.data;
    },
    staleTime: 60000,
    refetchInterval: 60000,
  });

  const latest = telemetryData?.[0] ?? null;
  const displayName = workstation.hostname ?? workstation.ip_private;

  return (
    <TableRow
      className={`cursor-pointer ${isSelected ? 'bg-blue-50' : ''}`}
      onClick={onSelect}
    >
      <TableCell className="font-medium">{displayName}</TableCell>
      <TableCell>
        {latest ? (
          <QueueStatusBadge status={latest.queue_status} />
        ) : (
          <Badge variant="secondary">Sin datos</Badge>
        )}
      </TableCell>
      <TableCell>
        {latest ? (
          <ContingencyBadge active={latest.contingency_active} />
        ) : (
          <span className="text-gray-400">—</span>
        )}
      </TableCell>
      <TableCell>
        {latest ? latest.jobs_identified : <span className="text-gray-400">—</span>}
      </TableCell>
      <TableCell>
        {latest?.avg_release_time_ms != null ? (
          `${latest.avg_release_time_ms} ms`
        ) : (
          <span className="text-gray-400">—</span>
        )}
      </TableCell>
      <TableCell>
        {latest ? latest.disconnection_count : <span className="text-gray-400">—</span>}
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
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Historial — {workstationName}</CardTitle>
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
          <CardTitle>Historial — {workstationName}</CardTitle>
        </CardHeader>
        <CardContent>
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription className="flex items-center justify-between">
              <span>Error al cargar el historial de telemetría</span>
              <Button variant="outline" size="sm" onClick={onRetry}>
                <RefreshCw className="w-3 h-3 mr-1" />
                Reintentar
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
          <CardTitle>Historial — {workstationName}</CardTitle>
        </CardHeader>
        <CardContent className="p-8 text-center">
          <Activity className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-600">
            No hay registros de telemetría en las últimas 24 horas para esta workstation.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Historial — {workstationName}
          <span className="text-sm font-normal text-gray-500 ml-2">
            (últimas 24h, máx. 100 entradas)
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Fecha/Hora</TableHead>
              <TableHead>Estado cola</TableHead>
              <TableHead>Contingencia</TableHead>
              <TableHead>Jobs</TableHead>
              <TableHead>Tiempo lib.</TableHead>
              <TableHead>Desconexiones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map((entry) => (
              <TableRow key={entry.id}>
                <TableCell className="text-sm text-gray-700">
                  {formatRecordedAt(entry.recorded_at)}
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
  if (active) {
    return <Badge variant="destructive">Activa</Badge>;
  }
  return <Badge variant="secondary">Inactiva</Badge>;
}

// ============================================================================
// UTILIDADES
// ============================================================================

/**
 * Formatea una fecha ISO 8601 para mostrar en la tabla de historial.
 */
function formatRecordedAt(isoDate: string): string {
  try {
    const date = new Date(isoDate);
    return date.toLocaleString('es-ES', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return isoDate;
  }
}
