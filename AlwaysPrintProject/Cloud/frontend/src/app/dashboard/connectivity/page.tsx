/**
 * Página de dashboard de conectividad en tiempo real.
 *
 * Muestra workstations con sus checks de conectividad configurados,
 * indicadores de estado (verde/rojo), y actualizaciones en tiempo real
 * vía WebSocket.
 */

'use client';

import { useState, useEffect, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/api';
import { useWebSocket } from '@/hooks/useWebSocket';
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
import { AlertCircle, Globe, RefreshCw, Wifi, WifiOff } from 'lucide-react';
import type { ConnectivityResult } from '@/types/telemetry';
import type { ConnectivityResultReceivedMessage, OperatorMessage } from '@/types/websocket';
import type { Workstation } from '@/types/workstation';

// ============================================================================
// INTERFACES INTERNAS
// ============================================================================

/**
 * Mapa de último resultado por workstation_id + check_id.
 */
type LatestResultsMap = Record<string, ConnectivityResultReceivedMessage>;

// ============================================================================
// FUNCIONES DE FETCH
// ============================================================================

/**
 * Obtiene la lista de workstations de la cuenta.
 */
async function fetchWorkstations(): Promise<Workstation[]> {
  const response = await apiClient.get<{ items: Workstation[] }>('/workstations/', {
    params: { page_size: 500 },
  });
  return response.data.items;
}

/**
 * Obtiene el historial de conectividad de una workstation (últimas 24h, max 100).
 */
async function fetchConnectivityHistory(workstationId: string): Promise<ConnectivityResult[]> {
  const now = new Date();
  const from = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  const response = await apiClient.get<ConnectivityResult[]>(
    `/workstations/${workstationId}/connectivity`,
    { params: { limit: 100, from: from.toISOString() } }
  );
  return response.data;
}

// ============================================================================
// COMPONENTE PRINCIPAL
// ============================================================================

export default function ConnectivityDashboardPage() {
  const [selectedWorkstationId, setSelectedWorkstationId] = useState<string | null>(null);
  const [latestResults, setLatestResults] = useState<LatestResultsMap>({});
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const userTimezone = useUserTimezone();
  const tCommon = useTranslations('common');

  // --- WebSocket para actualizaciones en tiempo real ---
  const handleWebSocketMessage = useCallback((message: OperatorMessage) => {
    if (message.type === 'connectivity_result') {
      const result = message as ConnectivityResultReceivedMessage;
      const key = `${result.workstation_id}::${result.check_id}`;
      setLatestResults((prev) => ({
        ...prev,
        [key]: result,
      }));
    }
  }, []);

  useWebSocket({
    autoConnect: true,
    onMessage: handleWebSocketMessage,
  });

  // --- Queries ---

  const workstationsQuery = useQuery({
    queryKey: ['connectivity', 'workstations'],
    queryFn: fetchWorkstations,
    staleTime: 60000,
    refetchOnWindowFocus: true,
  });

  const historyQuery = useQuery({
    queryKey: ['connectivity', 'history', selectedWorkstationId],
    queryFn: () => fetchConnectivityHistory(selectedWorkstationId!),
    enabled: !!selectedWorkstationId,
    staleTime: 60000,
    refetchOnWindowFocus: true,
  });

  // --- Datos derivados ---

  const workstations = workstationsQuery.data ?? [];

  // --- Render ---
  const isRefreshing = workstationsQuery.isFetching || historyQuery.isFetching;

  // --- Actualizar timestamp cuando los datos se cargan exitosamente ---
  useEffect(() => {
    if (workstationsQuery.data && !isRefreshing) {
      setLastUpdated(new Date());
    }
  }, [workstationsQuery.data, isRefreshing]);

  const handleRefresh = useCallback(() => {
    workstationsQuery.refetch();
    if (selectedWorkstationId) {
      historyQuery.refetch();
    }
  }, [workstationsQuery, historyQuery, selectedWorkstationId]);

  return (
    <div className="max-w-screen-2xl mx-auto">
      {/* Encabezado */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Conectividad</h1>
          <p className="text-gray-600 mt-2">
            Monitoreo en tiempo real de checks de conectividad
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs sm:text-sm text-gray-500 whitespace-nowrap">
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

      {/* Lista de workstations con checks */}
      <WorkstationsConnectivityList
        workstations={workstations}
        latestResults={latestResults}
        isLoading={workstationsQuery.isLoading}
        isError={workstationsQuery.isError}
        onRetry={() => workstationsQuery.refetch()}
        selectedId={selectedWorkstationId}
        onSelect={(id) => setSelectedWorkstationId(id === selectedWorkstationId ? null : id)}
      />

      {/* Panel de historial */}
      {selectedWorkstationId && (
        <div className="mt-6">
          <ConnectivityHistoryPanel
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
// COMPONENTE: LISTA DE WORKSTATIONS CON CONECTIVIDAD
// ============================================================================

function WorkstationsConnectivityList({
  workstations,
  latestResults,
  isLoading,
  isError,
  onRetry,
  selectedId,
  onSelect,
}: {
  workstations: Workstation[];
  latestResults: LatestResultsMap;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Workstations — Conectividad</CardTitle>
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
          <CardTitle>Workstations — Conectividad</CardTitle>
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
          <CardTitle>Workstations — Conectividad</CardTitle>
        </CardHeader>
        <CardContent className="p-12 text-center">
          <Globe className="w-16 h-16 text-gray-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">Sin datos de conectividad</h3>
          <p className="text-gray-600">
            No se han registrado resultados de conectividad aún. Las workstations comenzarán a
            reportar cuando ejecuten sus checks configurados.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Workstations — Checks de conectividad</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {workstations.map((ws) => (
            <WorkstationConnectivityCard
              key={ws.id}
              workstation={ws}
              latestResults={latestResults}
              isSelected={ws.id === selectedId}
              onSelect={() => onSelect(ws.id)}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ============================================================================
// COMPONENTE: CARD DE WORKSTATION CON CHECKS
// ============================================================================

function WorkstationConnectivityCard({
  workstation,
  latestResults,
  isSelected,
  onSelect,
}: {
  workstation: Workstation;
  latestResults: LatestResultsMap;
  isSelected: boolean;
  onSelect: () => void;
}) {
  // Obtener los últimos resultados de conectividad de esta workstation
  const { data: connectivityData } = useQuery({
    queryKey: ['connectivity', 'latest', workstation.id],
    queryFn: async () => {
      const response = await apiClient.get<ConnectivityResult[]>(
        `/workstations/${workstation.id}/connectivity`,
        { params: { limit: 50 } }
      );
      return response.data;
    },
    staleTime: 60000,
  });

  // Agrupar por check_id para obtener el último resultado de cada check
  const latestByCheck = getLatestByCheck(
    connectivityData ?? [],
    latestResults,
    workstation.id
  );
  const displayName = workstation.hostname ?? workstation.ip_private;
  const checks = Object.values(latestByCheck);

  return (
    <div
      className={`border rounded-lg p-4 cursor-pointer transition-colors ${
        isSelected ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:border-gray-300'
      }`}
      onClick={onSelect}
    >
      {/* Encabezado de workstation */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          {workstation.is_online ? (
            <Wifi className="w-4 h-4 text-green-600 flex-shrink-0" />
          ) : (
            <WifiOff className="w-4 h-4 text-gray-400 flex-shrink-0" />
          )}
          <span className="font-medium text-gray-900">{displayName}</span>
          <Badge variant={workstation.is_online ? 'success' : 'secondary'} className="whitespace-nowrap">
            {workstation.is_online ? 'En línea' : 'Desconectada'}
          </Badge>
        </div>
        <span className="text-sm text-gray-500 whitespace-nowrap">
          {checks.length} check{checks.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Tabla de checks */}
      {checks.length > 0 ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8">Estado</TableHead>
              <TableHead>Check ID</TableHead>
              <TableHead>Tipo</TableHead>
              <TableHead>Latencia</TableHead>
              <TableHead>Error</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {checks.map((check) => (
              <TableRow key={check.check_id}>
                <TableCell>
                  <SuccessIndicator success={check.success} />
                </TableCell>
                <TableCell className="font-mono text-sm">{check.check_id}</TableCell>
                <TableCell>
                  <CheckTypeBadge type={check.check_type} />
                </TableCell>
                <TableCell>
                  {check.latency_ms != null ? (
                    <span className="text-sm">{check.latency_ms} ms</span>
                  ) : (
                    <span className="text-gray-400">—</span>
                  )}
                </TableCell>
                <TableCell>
                  {check.error ? (
                    <span className="text-sm text-red-600 truncate max-w-[200px] block">
                      {check.error}
                    </span>
                  ) : (
                    <span className="text-gray-400">—</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : (
        <p className="text-sm text-gray-500 italic">Sin resultados de checks registrados</p>
      )}
    </div>
  );
}

// ============================================================================
// COMPONENTE: PANEL DE HISTORIAL DE CONECTIVIDAD
// ============================================================================

function ConnectivityHistoryPanel({
  workstationId,
  workstationName,
  entries,
  isLoading,
  isError,
  onRetry,
}: {
  workstationId: string;
  workstationName: string;
  entries: ConnectivityResult[];
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}) {
  const userTimezone = useUserTimezone();

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Historial de conectividad — {workstationName}</CardTitle>
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
          <CardTitle>Historial de conectividad — {workstationName}</CardTitle>
        </CardHeader>
        <CardContent>
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription className="flex items-center justify-between">
              <span>Error al cargar el historial de conectividad</span>
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
          <CardTitle>Historial de conectividad — {workstationName}</CardTitle>
        </CardHeader>
        <CardContent className="p-8 text-center">
          <Globe className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-600">
            No hay registros de conectividad en las últimas 24 horas para esta workstation.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Historial de conectividad — {workstationName}
          <span className="text-sm font-normal text-gray-500 ml-2">
            (últimas 24h, máx. 100 entradas)
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8">Estado</TableHead>
              <TableHead>Fecha/Hora</TableHead>
              <TableHead>Check ID</TableHead>
              <TableHead>Tipo</TableHead>
              <TableHead>Latencia</TableHead>
              <TableHead>Error</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map((entry) => (
              <TableRow key={entry.id}>
                <TableCell>
                  <SuccessIndicator success={entry.success} />
                </TableCell>
                <TableCell className="text-sm text-gray-700">
                  {formatRecordedAt(entry.recorded_at, userTimezone)}
                </TableCell>
                <TableCell className="font-mono text-sm">{entry.check_id}</TableCell>
                <TableCell>
                  <CheckTypeBadge type={entry.check_type} />
                </TableCell>
                <TableCell>
                  {entry.latency_ms != null ? (
                    <span className="text-sm">{entry.latency_ms} ms</span>
                  ) : (
                    <span className="text-gray-400">—</span>
                  )}
                </TableCell>
                <TableCell>
                  {entry.error ? (
                    <span className="text-sm text-red-600 truncate max-w-[250px] block">
                      {entry.error}
                    </span>
                  ) : (
                    <span className="text-gray-400">—</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

// ============================================================================
// COMPONENTES AUXILIARES
// ============================================================================

/**
 * Indicador visual verde/rojo para el estado de un check.
 */
function SuccessIndicator({ success }: { success: boolean }) {
  return (
    <span
      className={`inline-block w-3 h-3 rounded-full ${
        success ? 'bg-green-500' : 'bg-red-500'
      }`}
      title={success ? 'Exitoso' : 'Fallido'}
      aria-label={success ? 'Check exitoso' : 'Check fallido'}
    />
  );
}

/**
 * Badge para el tipo de check de conectividad.
 */
function CheckTypeBadge({ type }: { type: string }) {
  const variants: Record<string, string> = {
    http: 'bg-blue-100 text-blue-800',
    tcp: 'bg-purple-100 text-purple-800',
    ping: 'bg-green-100 text-green-800',
    dns: 'bg-amber-100 text-amber-800',
  };

  const className = variants[type] ?? 'bg-gray-100 text-gray-800';

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${className}`}
    >
      {type.toUpperCase()}
    </span>
  );
}

// ============================================================================
// UTILIDADES
// ============================================================================

/**
 * Estructura unificada para mostrar el último resultado de un check.
 */
interface CheckLatestResult {
  check_id: string;
  check_type: string;
  success: boolean;
  latency_ms: number | null;
  error: string | null;
}

/**
 * Obtiene el último resultado por check_id, combinando datos REST y WebSocket.
 * Los datos de WebSocket (más recientes) tienen prioridad.
 */
function getLatestByCheck(
  restData: ConnectivityResult[],
  wsResults: LatestResultsMap,
  workstationId: string
): Record<string, CheckLatestResult> {
  const result: Record<string, CheckLatestResult> = {};

  // Primero, poblar con datos REST (ya vienen ordenados por recorded_at DESC)
  for (const entry of restData) {
    if (!result[entry.check_id]) {
      result[entry.check_id] = {
        check_id: entry.check_id,
        check_type: entry.check_type,
        success: entry.success,
        latency_ms: entry.latency_ms,
        error: entry.error,
      };
    }
  }

  // Luego, sobrescribir con datos de WebSocket (más recientes)
  for (const [key, wsResult] of Object.entries(wsResults)) {
    if (key.startsWith(`${workstationId}::`)) {
      result[wsResult.check_id] = {
        check_id: wsResult.check_id,
        check_type: wsResult.check_type,
        success: wsResult.success,
        latency_ms: wsResult.latency_ms,
        error: wsResult.error,
      };
    }
  }

  return result;
}

/**
 * Formatea una fecha ISO 8601 para mostrar en la tabla de historial.
 */
function formatRecordedAt(isoDate: string, timezone: string = 'UTC'): string {
  try {
    return formatDateWithTimezone(isoDate, timezone);
  } catch {
    return isoDate;
  }
}
