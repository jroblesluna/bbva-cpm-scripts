'use client';
/**
 * Panel de infraestructura de workers.
 * Muestra PIDs, tipos (master/worker), estado del heartbeat en Redis,
 * y permite reiniciar backend, resetear heartbeat o matar un worker individual.
 */
import { useState, useCallback } from 'react';
import { useAuth } from '@/components/providers/AuthProvider';
import { useTranslations } from 'next-intl';
import {
  Server,
  RefreshCw,
  Heart,
  HeartOff,
  RotateCcw,
  Power,
  Loader2,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Database,
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
  exe: string;
  redis?: {
    heartbeat_ttl: number;
    workstations_registered: number;
    has_metrics: boolean;
    heartbeat_healthy: boolean;
  };
}

interface InfrastructureData {
  master_pid: number | null;
  processes: ProcessInfo[];
  redis_keys: Record<string, {
    heartbeat_ttl: number;
    workstations_registered: number;
    has_metrics: boolean;
    heartbeat_healthy: boolean;
  }>;
  local_worker_id: string;
}

// === COMPONENTE ===

export default function InfrastructurePanel() {
  const { getAuthHeaders } = useAuth();
  const t = useTranslations('systemStatus');
  const { toast } = useToast();
  const [data, setData] = useState<InfrastructureData | null>(null);
  const [loading, setLoading] = useState(false);
  const [actionPending, setActionPending] = useState<string | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<{
    action: 'restart' | 'kill' | 'forceKill' | 'reset';
    workerId?: string;
  } | null>(null);

  const baseUrl = process.env.NEXT_PUBLIC_API_URL || '';

  const fetchInfrastructure = useCallback(async () => {
    setLoading(true);
    try {
      const headers = getAuthHeaders();
      const res = await fetch(`${baseUrl}/api/v1/health/workers/infrastructure`, { headers });
      if (res.ok) {
        const json = await res.json();
        setData(json);
      }
    } catch {
      toast({ variant: 'destructive', title: t('infraError') });
    } finally {
      setLoading(false);
    }
  }, [getAuthHeaders, baseUrl, t, toast]);

  const handleRestart = async () => {
    setConfirmDialog(null);
    setActionPending('restart');
    try {
      const headers = getAuthHeaders();
      const res = await fetch(`${baseUrl}/api/v1/health/workers/restart-backend`, {
        method: 'POST', headers,
      });
      const json = await res.json();
      toast({ title: t('infraRestartTitle'), description: json.message });
    } catch {
      toast({ variant: 'destructive', title: t('infraRestartFailed') });
    } finally {
      setActionPending(null);
    }
  };

  const handleResetHeartbeat = async (workerId: string) => {
    setConfirmDialog(null);
    setActionPending(`reset-${workerId}`);
    try {
      const headers = getAuthHeaders();
      const res = await fetch(`${baseUrl}/api/v1/health/workers/${workerId}/reset-heartbeat`, {
        method: 'POST', headers,
      });
      const json = await res.json();
      toast({
        title: json.status === 'ok' ? t('infraResetOk') : t('infraResetSkipped'),
        description: json.message,
      });
      // Refrescar datos
      await fetchInfrastructure();
    } catch {
      toast({ variant: 'destructive', title: t('infraResetFailed') });
    } finally {
      setActionPending(null);
    }
  };

  const handleKill = async (workerId: string, force: boolean = false) => {
    setConfirmDialog(null);
    setActionPending(`kill-${workerId}`);
    try {
      const headers = getAuthHeaders();
      const url = `${baseUrl}/api/v1/health/workers/${workerId}/kill${force ? '?force=true' : ''}`;
      const res = await fetch(url, { method: 'POST', headers });
      const json = await res.json();
      toast({ title: t('infraKillTitle'), description: json.message });
    } catch {
      toast({ variant: 'destructive', title: t('infraKillFailed') });
    } finally {
      setActionPending(null);
    }
  };

  return (
    <Card className="mb-4">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Database className="w-4 h-4" />
            {t('infraTitle')}
          </CardTitle>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={fetchInfrastructure}
              disabled={loading}
            >
              {loading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              <span className="ml-1.5">{t('infraInspect')}</span>
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setConfirmDialog({ action: 'restart' })}
              disabled={!!actionPending}
            >
              {actionPending === 'restart' ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RotateCcw className="h-3.5 w-3.5" />
              )}
              <span className="ml-1.5">{t('infraRestartBackend')}</span>
            </Button>
          </div>
        </div>
      </CardHeader>

      {data && (
        <CardContent className="pt-0">
          <div className="text-xs text-muted-foreground mb-2">
            Master PID: <span className="font-mono">{data.master_pid ?? '?'}</span>
            {' | '}
            {t('infraLocalWorker')}: <span className="font-mono">{data.local_worker_id}</span>
          </div>

          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs">PID</TableHead>
                  <TableHead className="text-xs">{t('infraType')}</TableHead>
                  <TableHead className="text-xs">Worker ID</TableHead>
                  <TableHead className="text-xs">Heartbeat</TableHead>
                  <TableHead className="text-xs">TTL</TableHead>
                  <TableHead className="text-xs text-right">WS (Redis)</TableHead>
                  <TableHead className="text-xs">{t('infraActions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.processes.map((proc) => (
                  <TableRow key={proc.pid}>
                    <TableCell className="font-mono text-xs">{proc.pid}</TableCell>
                    <TableCell>
                      <Badge variant={proc.type === 'master' ? 'secondary' : 'default'} className="text-[10px]">
                        {proc.type}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {proc.worker_id ?? '—'}
                    </TableCell>
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
                      ) : (
                        <span className="text-gray-400 text-xs">—</span>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {proc.redis ? `${proc.redis.heartbeat_ttl}s` : '—'}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-right">
                      {proc.redis?.workstations_registered ?? '—'}
                    </TableCell>
                    <TableCell>
                      {proc.type === 'worker' && proc.worker_id && (
                        <div className="flex items-center gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 w-6 p-0"
                            title={t('infraResetHeartbeat')}
                            disabled={!!actionPending}
                            onClick={() => setConfirmDialog({ action: 'reset', workerId: proc.worker_id! })}
                          >
                            <Heart className="w-3 h-3" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 w-6 p-0 text-orange-500 hover:text-orange-700"
                            title="SIGTERM (graceful)"
                            disabled={!!actionPending}
                            onClick={() => setConfirmDialog({ action: 'kill', workerId: proc.worker_id! })}
                          >
                            <Power className="w-3 h-3" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-6 w-6 p-0 text-red-500 hover:text-red-700"
                            title="SIGKILL (force)"
                            disabled={!!actionPending}
                            onClick={() => setConfirmDialog({ action: 'forceKill', workerId: proc.worker_id! })}
                          >
                            <XCircle className="w-3 h-3" />
                          </Button>
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
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
            <Button variant="outline" onClick={() => setConfirmDialog(null)}>
              {t('cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (confirmDialog?.action === 'restart') handleRestart();
                else if (confirmDialog?.action === 'kill' && confirmDialog.workerId) handleKill(confirmDialog.workerId, false);
                else if (confirmDialog?.action === 'forceKill' && confirmDialog.workerId) handleKill(confirmDialog.workerId, true);
                else if (confirmDialog?.action === 'reset' && confirmDialog.workerId) handleResetHeartbeat(confirmDialog.workerId);
              }}
            >
              {t('confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
