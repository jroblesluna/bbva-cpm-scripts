'use client';
/**
 * Tab unificada de Workers: infraestructura + métricas en una sola tabla.
 * Muestra PIDs, heartbeat, WS local, WS Redis, RAM, Uptime, Estado y Acciones.
 */
import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '@/components/providers/AuthProvider';
import { useTranslations } from 'next-intl';
import {
  Server,
  RefreshCw,
  Loader2,
  Users,
  MemoryStick,
  Heart,
  HeartOff,
  Power,
  XCircle,
  RotateCcw,
  AlertTriangle,
  CheckCircle,
} from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useToast } from '@/hooks/use-toast';

// === TIPOS ===

interface ProcessInfo {
  pid: number;
  type: 'master' | 'worker';
  worker_id: string | null;
  redis?: {
    heartbeat_ttl: number;
    workstations_registered: number;
    has_metrics: boolean;
    heartbeat_healthy: boolean;
  };
}

interface WorkerMetrics {
  worker_id: string;
  connections: { workstations: number; operators: number };
  redis: { connected: boolean; latency_ms: number };
  memory_mb: number;
  start_time: number;
  status: string;
}

// === UTILIDADES ===

function formatUptime(startTime: number): string {
  if (!startTime) return '—';
  const seconds = Math.floor(Date.now() / 1000 - startTime);
  if (seconds < 0) return '—';
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
  const { toast } = useToast();
  const baseUrl = process.env.NEXT_PUBLIC_API_URL || '';

  const [processes, setProcesses] = useState<ProcessInfo[]>([]);
  const [metrics, setMetrics] = useState<WorkerMetrics[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [actionPending, setActionPending] = useState<string | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<{
    action: 'restart' | 'kill' | 'forceKill' | 'reset';
    workerId?: string;
  } | null>(null);

  // Modal de reinicio
  const [restartModal, setRestartModal] = useState(false);
  const [restartPhase, setRestartPhase] = useState<'sending' | 'stopping' | 'waiting' | 'verifying' | 'done' | 'error'>('sending');
  const [restartMessage, setRestartMessage] = useState('');

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const headers = getAuthHeaders();
      const [infraRes, metricsRes] = await Promise.all([
        fetch(`${baseUrl}/api/v1/health/workers/infrastructure`, { headers }),
        fetch(`${baseUrl}/api/v1/health/workers`, { headers }),
      ]);

      if (infraRes.ok) {
        const infraData = await infraRes.json();
        setProcesses(infraData.processes || []);
      }
      if (metricsRes.ok) {
        const metricsData: WorkerMetrics[] = await metricsRes.json();
        setMetrics(metricsData);
      }
      setLastRefresh(new Date());
    } catch {
      toast({ variant: 'destructive', title: t('workersError') });
    } finally {
      setLoading(false);
    }
  }, [getAuthHeaders, baseUrl, t, toast]);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 30000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  // Métricas agregadas
  const totalWs = metrics.reduce((acc, m) => acc + m.connections.workstations, 0);
  const totalRam = metrics.reduce((acc, m) => acc + m.memory_mb, 0);
  const activeWorkers = metrics.length;

  // Merge processes + metrics
  const metricsMap = new Map(metrics.map(m => [m.worker_id, m]));

  // === ACCIONES ===

  const handleRestart = async () => {
    setConfirmDialog(null);
    setRestartModal(true);
    setRestartPhase('sending');
    setRestartMessage(t('infraRestartPhaseSending'));

    try {
      const headers = getAuthHeaders();
      const res = await fetch(`${baseUrl}/api/v1/health/workers/restart-backend`, {
        method: 'POST', headers,
      });
      if (!res.ok) throw new Error('Request failed');

      setRestartPhase('stopping');
      setRestartMessage(t('infraRestartPhaseStopping'));

      let downDetected = false;
      for (let i = 0; i < 15; i++) {
        await new Promise(r => setTimeout(r, 1000));
        try {
          const probe = await fetch(`${baseUrl}/api/v1/health`, { signal: AbortSignal.timeout(2000) });
          if (!probe.ok) { downDetected = true; break; }
        } catch { downDetected = true; break; }
      }

      if (!downDetected) {
        setRestartPhase('error');
        setRestartMessage(t('infraRestartPhaseNotStopped'));
        setTimeout(() => setRestartModal(false), 5000);
        return;
      }

      setRestartPhase('waiting');
      setRestartMessage(t('infraRestartPhaseWaiting'));

      let attempts = 0;
      while (attempts < 30) {
        await new Promise(r => setTimeout(r, 2000));
        attempts++;
        setRestartMessage(t('infraRestartPhaseWaitingAttempt', { attempt: String(attempts), max: '30' }));
        try {
          const healthRes = await fetch(`${baseUrl}/api/v1/health`, { signal: AbortSignal.timeout(3000) });
          if (healthRes.ok) break;
        } catch { /* continue */ }
      }

      if (attempts >= 30) {
        setRestartPhase('error');
        setRestartMessage(t('infraRestartPhaseTimeout'));
        setTimeout(() => setRestartModal(false), 5000);
        return;
      }

      setRestartPhase('verifying');
      setRestartMessage(t('infraRestartPhaseVerifying'));
      await new Promise(r => setTimeout(r, 2000));

      setRestartPhase('done');
      setRestartMessage(t('infraRestartPhaseDone'));
      setTimeout(() => { setRestartModal(false); fetchAll(); }, 3000);
    } catch {
      setRestartPhase('error');
      setRestartMessage(t('infraRestartFailed'));
      setTimeout(() => setRestartModal(false), 5000);
    }
  };

  const handleResetHeartbeat = async (workerId: string) => {
    setConfirmDialog(null);
    setActionPending(`reset-${workerId}`);
    try {
      const headers = getAuthHeaders();
      const res = await fetch(`${baseUrl}/api/v1/health/workers/${workerId}/reset-heartbeat`, { method: 'POST', headers });
      const json = await res.json();
      toast({ title: json.status === 'ok' ? t('infraResetOk') : t('infraResetSkipped'), description: json.message });
      await fetchAll();
    } catch { toast({ variant: 'destructive', title: t('infraResetFailed') }); }
    finally { setActionPending(null); }
  };

  const handleKill = async (workerId: string, force: boolean) => {
    setConfirmDialog(null);
    setActionPending(`kill-${workerId}`);
    try {
      const headers = getAuthHeaders();
      const res = await fetch(`${baseUrl}/api/v1/health/workers/${workerId}/kill${force ? '?force=true' : ''}`, { method: 'POST', headers });
      const json = await res.json();
      toast({ title: t('infraKillTitle'), description: json.message });
    } catch { toast({ variant: 'destructive', title: t('infraKillFailed') }); }
    finally { setActionPending(null); }
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Server className="h-5 w-5" />
          <h3 className="text-lg font-medium">{t('workersTitle')}</h3>
          <Badge variant={activeWorkers >= 2 ? 'default' : 'secondary'}>
            {activeWorkers} worker{activeWorkers !== 1 ? 's' : ''}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          {lastRefresh && (
            <span className="text-xs text-muted-foreground">{lastRefresh.toLocaleTimeString()}</span>
          )}
          <Button variant="outline" size="sm" onClick={fetchAll} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => setConfirmDialog({ action: 'restart' })}
            disabled={!!actionPending}
          >
            <RotateCcw className="h-3.5 w-3.5 mr-1.5" />
            {t('infraRestartBackend')}
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
                <p className="text-2xl font-bold">{totalWs}</p>
                <p className="text-xs text-muted-foreground">{t('workersConnected')}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-2">
              <MemoryStick className="h-4 w-4 text-purple-500" />
              <div>
                <p className="text-2xl font-bold">{totalRam.toFixed(0)} MB</p>
                <p className="text-xs text-muted-foreground">{t('workersRamTotal')}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-2">
              <Server className="h-4 w-4 text-orange-500" />
              <div>
                <p className="text-2xl font-bold">{activeWorkers}</p>
                <p className="text-xs text-muted-foreground">{t('workersActive')}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-2">
              <Server className="h-4 w-4 text-gray-400" />
              <div>
                <p className="text-2xl font-bold">{processes.length}</p>
                <p className="text-xs text-muted-foreground">PIDs</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Tabla unificada */}
      {processes.length > 0 && (
        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-xs">PID</TableHead>
                    <TableHead className="text-xs">{t('infraType')}</TableHead>
                    <TableHead className="text-xs">Worker</TableHead>
                    <TableHead className="text-xs">Heartbeat</TableHead>
                    <TableHead className="text-xs text-right">WS</TableHead>
                    <TableHead className="text-xs text-right">WS (Redis)</TableHead>
                    <TableHead className="text-xs text-right">RAM</TableHead>
                    <TableHead className="text-xs text-right">Uptime</TableHead>
                    <TableHead className="text-xs">{t('workersColStatus')}</TableHead>
                    <TableHead className="text-xs">{t('infraActions')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {processes.map((proc) => {
                    const m = proc.worker_id ? metricsMap.get(proc.worker_id) : null;
                    return (
                      <TableRow key={proc.pid} className={proc.type === 'master' ? 'bg-gray-50' : ''}>
                        <TableCell className="font-mono text-xs">{proc.pid}</TableCell>
                        <TableCell>
                          <Badge variant={proc.type === 'master' ? 'secondary' : (metricsMap.has(proc.worker_id ?? '') ? 'default' : 'outline')} className={`text-[10px] ${proc.type === 'worker' && !metricsMap.has(proc.worker_id ?? '') ? 'border-orange-300 text-orange-700 bg-orange-50' : ''}`}>
                            {proc.type === 'master' ? 'master' : (metricsMap.has(proc.worker_id ?? '') ? 'worker' : 'orphan')}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-mono text-xs">{proc.worker_id ?? '—'}</TableCell>
                        <TableCell>
                          {proc.type === 'worker' && proc.redis ? (
                            proc.redis.heartbeat_healthy ? (
                              <span className="flex items-center gap-1 text-green-600">
                                <Heart className="w-3 h-3" />
                                <span className="text-[10px]">OK</span>
                              </span>
                            ) : (
                              <span className="flex items-center gap-1 text-red-500">
                                <HeartOff className="w-3 h-3" />
                                <span className="text-[10px]">DEAD</span>
                              </span>
                            )
                          ) : '—'}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          {m ? m.connections.workstations : (proc.type === 'worker' ? '0' : '—')}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          {proc.redis?.workstations_registered ?? '—'}
                        </TableCell>
                        <TableCell className="text-right text-xs">
                          {m ? `${m.memory_mb.toFixed(0)} MB` : '—'}
                        </TableCell>
                        <TableCell className="text-right text-xs">
                          {m ? formatUptime(m.start_time) : '—'}
                        </TableCell>
                        <TableCell>
                          {m ? (
                            <Badge variant={m.status === 'healthy' ? 'default' : 'destructive'} className="text-xs">
                              {m.status}
                            </Badge>
                          ) : proc.type === 'worker' ? (
                            <Badge variant="secondary" className="text-xs text-orange-700 border-orange-300 bg-orange-50">
                              heartbeat lost
                            </Badge>
                          ) : '—'}
                        </TableCell>
                        <TableCell>
                          {proc.type === 'worker' && proc.worker_id && (
                            <div className="flex items-center gap-1">
                              <Button variant="ghost" size="sm" className="h-6 w-6 p-0"
                                title={t('infraResetHeartbeat')} disabled={!!actionPending}
                                onClick={() => setConfirmDialog({ action: 'reset', workerId: proc.worker_id! })}>
                                <Heart className="w-3 h-3" />
                              </Button>
                              <Button variant="ghost" size="sm" className="h-6 w-6 p-0 text-orange-500 hover:text-orange-700"
                                title="SIGTERM" disabled={!!actionPending}
                                onClick={() => setConfirmDialog({ action: 'kill', workerId: proc.worker_id! })}>
                                <Power className="w-3 h-3" />
                              </Button>
                              <Button variant="ghost" size="sm" className="h-6 w-6 p-0 text-red-500 hover:text-red-700"
                                title="SIGKILL" disabled={!!actionPending}
                                onClick={() => setConfirmDialog({ action: 'forceKill', workerId: proc.worker_id! })}>
                                <XCircle className="w-3 h-3" />
                              </Button>
                            </div>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Estado vacío */}
      {!loading && processes.length === 0 && (
        <div className="text-center py-8 text-muted-foreground">
          <Server className="mx-auto h-12 w-12 mb-2" />
          <p>{t('workersEmpty')}</p>
        </div>
      )}

      {/* Diálogo de confirmación */}
      <Dialog open={!!confirmDialog} onOpenChange={(open) => !open && setConfirmDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-orange-500" />
              {confirmDialog?.action === 'restart' && t('infraRestartConfirmTitle')}
              {confirmDialog?.action === 'kill' && t('infraKillConfirmTitle')}
              {confirmDialog?.action === 'forceKill' && t('infraForceKillConfirmTitle')}
              {confirmDialog?.action === 'reset' && t('infraResetConfirmTitle')}
            </DialogTitle>
            <DialogDescription>
              {confirmDialog?.action === 'restart' && t('infraRestartConfirmDesc')}
              {confirmDialog?.action === 'kill' && t('infraKillConfirmDesc', { worker: confirmDialog.workerId })}
              {confirmDialog?.action === 'forceKill' && t('infraForceKillConfirmDesc', { worker: confirmDialog.workerId })}
              {confirmDialog?.action === 'reset' && t('infraResetConfirmDesc', { worker: confirmDialog.workerId })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDialog(null)}>{t('cancel')}</Button>
            <Button variant="destructive" onClick={() => {
              if (confirmDialog?.action === 'restart') handleRestart();
              else if (confirmDialog?.action === 'kill' && confirmDialog.workerId) handleKill(confirmDialog.workerId, false);
              else if (confirmDialog?.action === 'forceKill' && confirmDialog.workerId) handleKill(confirmDialog.workerId, true);
              else if (confirmDialog?.action === 'reset' && confirmDialog.workerId) handleResetHeartbeat(confirmDialog.workerId);
            }}>{t('confirm')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Modal de reinicio */}
      {restartModal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-8 max-w-md w-full mx-4 text-center space-y-4">
            {restartPhase !== 'done' && restartPhase !== 'error' && (
              <Loader2 className="w-12 h-12 animate-spin text-blue-600 mx-auto" />
            )}
            {restartPhase === 'done' && <CheckCircle className="w-12 h-12 text-green-600 mx-auto" />}
            {restartPhase === 'error' && <XCircle className="w-12 h-12 text-red-600 mx-auto" />}
            <h3 className="text-lg font-semibold">
              {restartPhase === 'done' ? t('infraRestartCompleteTitle') : t('infraRestartInProgressTitle')}
            </h3>
            <p className="text-sm text-gray-600">{restartMessage}</p>
            {restartPhase === 'done' && <p className="text-xs text-gray-400">{t('infraRestartAutoClose')}</p>}
          </div>
        </div>
      )}
    </div>
  );
}
