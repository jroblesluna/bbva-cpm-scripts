'use client';
/**
 * Tab de visualización de Workers Uvicorn.
 *
 * Consulta /api/v1/health/detailed múltiples veces (round-robin de Nginx)
 * para descubrir todos los workers activos y mostrar sus métricas individuales.
 */
import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '@/components/providers/AuthProvider';
import { useTranslations } from 'next-intl';
import {
  Server,
  RefreshCw,
  Wifi,
  WifiOff,
  Loader2,
  Users,
  MemoryStick,
  Clock,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

// === TIPOS ===

interface WorkerInfo {
  worker_id: string;
  status: string;
  redis: {
    connected: boolean;
    latency_ms: number;
    subscriptions: number;
  };
  connections: {
    workstations: number;
    operators: number;
  };
  cache: {
    hits_last_minute: number;
    misses_last_minute: number;
    hit_ratio_pct: number;
  };
  registration: {
    p95_latency_ms: number;
    total_last_minute: number;
  };
  memory_mb: number;
  uptime_seconds: number;
}

// === UTILIDADES ===

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) {
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  }
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
}

// === COMPONENTE ===

export default function WorkersTab() {
  const { getAuthHeaders } = useAuth();
  const t = useTranslations('systemStatus');
  const [workers, setWorkers] = useState<WorkerInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchWorkers = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || '';
      const headers = getAuthHeaders();

      // Un solo request que retorna todos los workers desde Redis
      const response = await fetch(`${baseUrl}/api/v1/health/workers`, { headers });
      if (!response.ok) throw new Error('Failed to fetch workers');

      const data: WorkerInfo[] = await response.json();
      setWorkers(data.sort((a, b) => a.worker_id.localeCompare(b.worker_id)));
      setLastRefresh(new Date());
    } catch {
      setError(t('workersError'));
    } finally {
      setLoading(false);
    }
  }, [getAuthHeaders, t]);

  // Auto-refresh al montar y cada 30s
  useEffect(() => {
    fetchWorkers();
    const interval = setInterval(fetchWorkers, 30000);
    return () => clearInterval(interval);
  }, [fetchWorkers]);

  const totalWorkstations = workers.reduce(
    (acc, w) => acc + w.connections.workstations,
    0
  );
  const totalOperators = workers.reduce(
    (acc, w) => acc + w.connections.operators,
    0
  );
  const totalMemory = workers.reduce((acc, w) => acc + w.memory_mb, 0);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Server className="h-5 w-5" />
          <h3 className="text-lg font-medium">{t('workersTitle')}</h3>
          <Badge variant={workers.length >= 2 ? 'default' : 'secondary'}>
            {workers.length} worker{workers.length !== 1 ? 's' : ''}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          {lastRefresh && (
            <span className="text-xs text-muted-foreground">
              {lastRefresh.toLocaleTimeString()}
            </span>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={fetchWorkers}
            disabled={loading}
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>

      {/* Tarjetas de resumen */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-2">
              <Users className="h-4 w-4 text-blue-500" />
              <div>
                <p className="text-2xl font-bold">{totalWorkstations}</p>
                <p className="text-xs text-muted-foreground">
                  {t('workersConnected')}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-2">
              <Users className="h-4 w-4 text-green-500" />
              <div>
                <p className="text-2xl font-bold">{totalOperators}</p>
                <p className="text-xs text-muted-foreground">
                  {t('workersOperators')}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-2">
              <MemoryStick className="h-4 w-4 text-purple-500" />
              <div>
                <p className="text-2xl font-bold">{totalMemory.toFixed(0)} MB</p>
                <p className="text-xs text-muted-foreground">
                  {t('workersRamTotal')}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-2">
              <Server className="h-4 w-4 text-orange-500" />
              <div>
                <p className="text-2xl font-bold">{workers.length}</p>
                <p className="text-xs text-muted-foreground">
                  {t('workersActive')}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Tabla de workers */}
      {workers.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">
              {t('workersDetailTitle')}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('workersColWorker')}</TableHead>
                    <TableHead>{t('workersColRedis')}</TableHead>
                    <TableHead className="text-right">
                      {t('workersColWs')}
                    </TableHead>
                    <TableHead className="text-right">
                      {t('workersColOps')}
                    </TableHead>
                    <TableHead className="text-right">
                      {t('workersColRam')}
                    </TableHead>
                    <TableHead className="text-right">
                      {t('workersColRegP95')}
                    </TableHead>
                    <TableHead className="text-right">
                      {t('workersColUptime')}
                    </TableHead>
                    <TableHead>{t('workersColStatus')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {workers.map((w) => (
                    <TableRow key={w.worker_id}>
                      <TableCell className="font-mono text-xs">
                        {w.worker_id}
                      </TableCell>
                      <TableCell>
                        {w.redis.connected ? (
                          <span className="flex items-center gap-1 text-green-600">
                            <Wifi className="h-3 w-3" />
                            <span className="text-xs">
                              {w.redis.latency_ms}ms
                            </span>
                          </span>
                        ) : (
                          <span className="flex items-center gap-1 text-red-500">
                            <WifiOff className="h-3 w-3" />
                            <span className="text-xs">
                              {t('workersRedisOffline')}
                            </span>
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {w.connections.workstations}
                      </TableCell>
                      <TableCell className="text-right font-mono">
                        {w.connections.operators}
                      </TableCell>
                      <TableCell className="text-right text-xs">
                        {w.memory_mb.toFixed(0)} MB
                      </TableCell>
                      <TableCell className="text-right text-xs">
                        {w.registration.p95_latency_ms > 0
                          ? `${w.registration.p95_latency_ms}ms`
                          : '-'}
                      </TableCell>
                      <TableCell className="text-right text-xs">
                        <span className="flex items-center justify-end gap-1">
                          <Clock className="h-3 w-3" />
                          {formatUptime(w.uptime_seconds)}
                        </span>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            w.status === 'healthy' ? 'default' : 'destructive'
                          }
                          className="text-xs"
                        >
                          {w.status}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Estado vacío */}
      {!loading && workers.length === 0 && !error && (
        <div className="text-center py-8 text-muted-foreground">
          <Server className="mx-auto h-12 w-12 mb-2" />
          <p>{t('workersEmpty')}</p>
          <p className="text-xs mt-1">{t('workersEmptyDesc')}</p>
        </div>
      )}
    </div>
  );
}
