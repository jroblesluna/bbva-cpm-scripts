/**
 * Sección de Debugging en el detalle de workstation.
 * Muestra perfiles disponibles, permite iniciar sesiones,
 * ver estado en tiempo real (countdown), y ejecutar acciones post-captura.
 *
 * Cubre Tasks 44-49:
 * - Task 44: Sección "Debugging disponible" con perfiles activos
 * - Task 45: Diálogo de confirmación con duración, motivo, instrucciones
 * - Task 46: Vista de sesión activa con timer countdown
 * - Task 47: Vista de datos disponibles (status "ready")
 * - Task 48: Vista de análisis completado con descarga PDF/ZIP
 * - Task 49: Feedback de estados (loading, progress, errores, WS real-time)
 */

'use client';

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import {
  Bug,
  Play,
  Square,
  Download,
  Trash2,
  Loader2,
  WifiOff,
  Clock,
  CheckCircle2,
  AlertCircle,
  FileText,
  Timer,
  Archive,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { useToast } from '@/hooks/use-toast';
import { apiClient } from '@/lib/api';

// === Interfaces ===

interface DebuggingProfile {
  id: string;
  name: string;
  description: string;
  confirmation_message: string;
  external_logs: string[];
  eventlog_groups: string[];
  registry_keys: string[];
  monitored_services: string[];
  is_active: boolean;
  created_at: string;
}

interface DebuggingSession {
  id: string;
  profile_id: string | null;
  workstation_id: string;
  status: 'active' | 'ready' | 'uploading' | 'analyzing' | 'analyzed' | 'analysis_failed' | 'deleted' | 'failed';
  duration_seconds: number;
  start_time: string;
  end_time: string | null;
  motivo: string | null;
  additional_instructions: string | null;
  total_data_size_bytes: number | null;
  s3_report_key: string | null;
  initiated_by: string | null;
  created_at: string;
}

interface DebuggingReportURL {
  report_url: string;
  expires_in_seconds: number;
}

interface WorkstationDebuggingSectionProps {
  workstationId: string;
  organizationId?: string;
  isOnline: boolean;
}

// === Helpers ===

/** Formatea bytes a tamaño legible */
function formatBytes(bytes: number | null): string {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

// === Componente Principal ===

export function WorkstationDebuggingSection({
  workstationId,
  organizationId,
  isOnline,
}: WorkstationDebuggingSectionProps) {
  const t = useTranslations('debugging');
  const tCommon = useTranslations('common');
  const { toast } = useToast();
  const queryClient = useQueryClient();

  // Estado del diálogo de confirmación
  const [confirmProfile, setConfirmProfile] = useState<DebuggingProfile | null>(null);
  const [duration, setDuration] = useState(60);
  const [motivo, setMotivo] = useState('');
  const [instructions, setInstructions] = useState('');
  // Estado del diálogo de eliminación
  const [deleteConfirmSessionId, setDeleteConfirmSessionId] = useState<string | null>(null);

  // === Queries ===

  // Perfiles activos de la organización (el backend filtra por org del usuario)
  const { data: profiles, isLoading: profilesLoading } = useQuery<DebuggingProfile[]>({
    queryKey: ['debugging-profiles', workstationId, organizationId],
    queryFn: async () => {
      const res = await apiClient.get('/debugging/profiles', {
        params: { include_inactive: false, organization_id: organizationId },
      });
      return res.data;
    },
  });

  // Sesiones de debugging para esta workstation
  const { data: sessions, isLoading: sessionsLoading } = useQuery<DebuggingSession[]>({
    queryKey: ['debugging-sessions', workstationId],
    queryFn: async () => {
      const res = await apiClient.get('/debugging/sessions', {
        params: { workstation_id: workstationId, organization_id: organizationId },
      });
      return res.data;
    },
    enabled: !!workstationId,
    // Refrescar cada 5s si hay sesión activa o en proceso
    refetchInterval: (query) => {
      const data = query.state.data as DebuggingSession[] | undefined;
      if (!data) return false;
      const hasActiveSession = data.some(s =>
        ['active', 'uploading', 'analyzing'].includes(s.status)
      );
      return hasActiveSession ? 5000 : false;
    },
  });

  // Determinar la sesión relevante (la más reciente no-deleted/no-failed primero)
  const activeSession = sessions?.find(s => s.status === 'active');
  const readySession = sessions?.find(s => s.status === 'ready');
  const analyzingSession = sessions?.find(s => s.status === 'analyzing' || s.status === 'uploading');
  const analyzedSession = sessions?.find(s => s.status === 'analyzed');
  const failedSession = sessions?.find(s => s.status === 'analysis_failed' || s.status === 'failed');

  // Sesión "principal" a mostrar (prioridad: active > ready > analyzing > analyzed > failed)
  const currentSession = activeSession || readySession || analyzingSession || analyzedSession || failedSession;

  // === Mutations ===

  // Iniciar sesión de debugging
  const startMutation = useMutation({
    mutationFn: async (data: {
      profile_id: string;
      workstation_id: string;
      duration_seconds: number;
      motivo?: string;
      additional_instructions?: string;
    }) => {
      const res = await apiClient.post('/debugging/sessions', data, {
        params: { organization_id: organizationId },
      });
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['debugging-sessions', workstationId] });
      toast({ title: t('wsStarted') });
      resetConfirmForm();
    },
    onError: () => {
      toast({ title: t('wsErrorStart'), variant: 'destructive' });
    },
  });

  // Detener sesión
  const stopMutation = useMutation({
    mutationFn: async (sessionId: string) => {
      await apiClient.post(`/debugging/sessions/${sessionId}/stop`, null, {
        params: { organization_id: organizationId },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['debugging-sessions', workstationId] });
      toast({ title: t('wsStopped') });
    },
    onError: () => {
      toast({ title: t('wsErrorStop'), variant: 'destructive' });
    },
  });

  // Analizar sesión
  const analyzeMutation = useMutation({
    mutationFn: async (sessionId: string) => {
      await apiClient.post(`/debugging/sessions/${sessionId}/analyze`, null, {
        params: { organization_id: organizationId },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['debugging-sessions', workstationId] });
      toast({ title: t('wsAnalysisRequested') });
    },
    onError: () => {
      toast({ title: t('wsErrorAnalyze'), variant: 'destructive' });
    },
  });

  // Eliminar datos de sesión
  const deleteMutation = useMutation({
    mutationFn: async (sessionId: string) => {
      await apiClient.post(`/debugging/sessions/${sessionId}/delete`, null, {
        params: { organization_id: organizationId },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['debugging-sessions', workstationId] });
      toast({ title: t('wsDeleted') });
      setDeleteConfirmSessionId(null);
    },
    onError: () => {
      toast({ title: t('wsErrorDelete'), variant: 'destructive' });
      setDeleteConfirmSessionId(null);
    },
  });

  // Descargar reporte PDF
  const downloadReportMutation = useMutation({
    mutationFn: async (sessionId: string) => {
      const res = await apiClient.get<DebuggingReportURL>(`/debugging/sessions/${sessionId}/report`, {
        params: { organization_id: organizationId },
      });
      return res.data;
    },
    onSuccess: (data) => {
      window.open(data.report_url, '_blank');
    },
    onError: () => {
      toast({ title: t('wsFailed'), variant: 'destructive' });
    },
  });

  // === Helpers ===

  const resetConfirmForm = () => {
    setConfirmProfile(null);
    setDuration(60);
    setMotivo('');
    setInstructions('');
  };

  const handleStartDebugging = () => {
    if (!confirmProfile) return;
    startMutation.mutate({
      profile_id: confirmProfile.id,
      workstation_id: workstationId,
      duration_seconds: duration,
      motivo: motivo || undefined,
      additional_instructions: instructions || undefined,
    });
  };

  // === Gate: no mostrar si cargando ===

  if (profilesLoading || sessionsLoading) {
    return (
      <div className="space-y-2">
        <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
          <div className="flex items-center gap-1.5">
            <Bug className="w-3.5 h-3.5" />
            {t('wsTitle')}
          </div>
        </h3>
        <div className="flex items-center gap-2 py-4 justify-center">
          <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
          <span className="text-sm text-gray-500">{tCommon('loading')}</span>
        </div>
      </div>
    );
  }

  // No mostrar sección si no hay perfiles activos y no hay sesión relevante
  if ((!profiles || profiles.filter(p => p.is_active).length === 0) && !currentSession) {
    return null;
  }

  const activeProfiles = profiles?.filter(p => p.is_active) || [];

  return (
    <div className="space-y-3">
      {/* Header de sección */}
      <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wide">
        <div className="flex items-center gap-1.5">
          <Bug className="w-3.5 h-3.5" />
          {t('wsTitle')}
        </div>
      </h3>

      {/* === Vista según estado de sesión === */}

      {/* Estado: ACTIVE — Timer countdown */}
      {activeSession && (
        <ActiveTimerView
          session={activeSession}
          t={t}
          onStop={() => stopMutation.mutate(activeSession.id)}
          isStopPending={stopMutation.isPending}
        />
      )}

      {/* Estado: READY — Datos disponibles */}
      {readySession && !activeSession && (
        <div className="p-4 bg-green-50 border border-green-200 rounded-lg space-y-3">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-green-600" />
            <span className="text-sm font-medium text-green-900">{t('wsDataReady')}</span>
            {readySession.total_data_size_bytes && (
              <Badge variant="outline" className="text-xs">
                {t('wsDataSize', { size: formatBytes(readySession.total_data_size_bytes) })}
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={() => analyzeMutation.mutate(readySession.id)} disabled={analyzeMutation.isPending}>
              {analyzeMutation.isPending ? (
                <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
              ) : (
                <FileText className="w-3.5 h-3.5 mr-1.5" />
              )}
              {t('wsAnalyze')}
            </Button>
            <Button size="sm" variant="destructive" onClick={() => setDeleteConfirmSessionId(readySession.id)}>
              <Trash2 className="w-3.5 h-3.5 mr-1.5" />
              {t('wsDelete')}
            </Button>
          </div>
        </div>
      )}

      {/* Estado: UPLOADING — Subiendo datos */}
      {analyzingSession && analyzingSession.status === 'uploading' && !activeSession && !readySession && (
        <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
          <div className="flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin text-blue-600" />
            <span className="text-sm font-medium text-blue-900">{t('wsCapturing')}</span>
          </div>
        </div>
      )}

      {/* Estado: ANALYZING — Análisis en curso */}
      {analyzingSession && analyzingSession.status === 'analyzing' && !activeSession && !readySession && (
        <div className="p-4 bg-purple-50 border border-purple-200 rounded-lg">
          <div className="flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin text-purple-600" />
            <span className="text-sm font-medium text-purple-900">{t('wsAnalyzing')}</span>
          </div>
        </div>
      )}

      {/* Estado: ANALYZED — Análisis completado */}
      {analyzedSession && !activeSession && !readySession && !analyzingSession && (
        <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-lg space-y-3">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-600" />
            <span className="text-sm font-medium text-emerald-900">{t('wsAnalyzed')}</span>
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={() => downloadReportMutation.mutate(analyzedSession.id)}
              disabled={downloadReportMutation.isPending}
            >
              {downloadReportMutation.isPending ? (
                <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
              ) : (
                <Download className="w-3.5 h-3.5 mr-1.5" />
              )}
              {t('wsDownloadPdf')}
            </Button>
            {analyzedSession.total_data_size_bytes && (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => downloadReportMutation.mutate(analyzedSession.id)}
                    >
                      <Archive className="w-3.5 h-3.5 mr-1.5" />
                      ZIP
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    {t('wsDataSize', { size: formatBytes(analyzedSession.total_data_size_bytes) })}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
          </div>
        </div>
      )}

      {/* Estado: ANALYSIS_FAILED o FAILED — Error */}
      {failedSession && !activeSession && !readySession && !analyzingSession && !analyzedSession && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{t('wsFailed')}</AlertDescription>
        </Alert>
      )}

      {/* === Listado de perfiles disponibles === */}

      {/* Si no hay sesión activa, mostrar perfiles con botón iniciar */}
      {!activeSession && !readySession && !analyzingSession && activeProfiles.length > 0 && (
        <div className="space-y-2">
          {activeProfiles.map((profile) => (
            <div
              key={profile.id}
              className="flex items-center justify-between p-3 bg-gray-50 border border-gray-100 rounded-lg"
            >
              <div className="flex-1 min-w-0 mr-3">
                <p className="text-sm font-medium text-gray-900 truncate">{profile.name}</p>
                <p className="text-xs text-gray-500 line-clamp-1">{profile.description}</p>
              </div>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={!isOnline}
                        onClick={() => setConfirmProfile(profile)}
                        className="shrink-0"
                      >
                        <Play className="w-3.5 h-3.5 mr-1.5" />
                        <span className="hidden sm:inline">{t('wsStartDebugging')}</span>
                      </Button>
                    </span>
                  </TooltipTrigger>
                  {!isOnline && (
                    <TooltipContent>
                      <div className="flex items-center gap-1.5">
                        <WifiOff className="w-3.5 h-3.5" />
                        {t('wsOffline')}
                      </div>
                    </TooltipContent>
                  )}
                </Tooltip>
              </TooltipProvider>
            </div>
          ))}
        </div>
      )}

      {/* Si hay sesión activa, mostrar otros perfiles deshabilitados */}
      {activeSession && activeProfiles.length > 1 && (
        <div className="space-y-2 opacity-50">
          {activeProfiles
            .filter(p => p.id !== activeSession.profile_id)
            .map((profile) => (
              <div
                key={profile.id}
                className="flex items-center justify-between p-3 bg-gray-50 border border-gray-100 rounded-lg"
              >
                <div className="flex-1 min-w-0 mr-3">
                  <p className="text-sm font-medium text-gray-900 truncate">{profile.name}</p>
                  <p className="text-xs text-gray-500 line-clamp-1">{profile.description}</p>
                </div>
                <Button variant="outline" size="sm" disabled className="shrink-0">
                  <Play className="w-3.5 h-3.5 mr-1.5" />
                  <span className="hidden sm:inline">{t('wsStartDebugging')}</span>
                </Button>
              </div>
            ))}
        </div>
      )}

      {/* === Diálogo de confirmación para iniciar debugging === */}
      <Dialog open={!!confirmProfile} onOpenChange={(open) => !open && resetConfirmForm()}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t('wsConfirmTitle')}</DialogTitle>
            <DialogDescription>
              {confirmProfile?.confirmation_message}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            {/* Nombre y descripción del perfil */}
            <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg">
              <p className="text-sm font-medium text-blue-900">{confirmProfile?.name}</p>
              <p className="text-xs text-blue-700 mt-1">{confirmProfile?.description}</p>
            </div>

            {/* Resumen de targets (solo lectura) */}
            {confirmProfile && (
              <div className="space-y-2">
                <Label className="text-xs font-medium text-gray-500 uppercase">{t('wsTargets')}</Label>
                <div className="flex flex-wrap gap-1.5">
                  {confirmProfile.monitored_services.length > 0 && (
                    <Badge variant="outline" className="text-xs">
                      {confirmProfile.monitored_services.length} {t('monitoredServices').toLowerCase()}
                    </Badge>
                  )}
                  {confirmProfile.eventlog_groups.length > 0 && (
                    <Badge variant="outline" className="text-xs">
                      {confirmProfile.eventlog_groups.join(', ')}
                    </Badge>
                  )}
                  {confirmProfile.external_logs.length > 0 && (
                    <Badge variant="outline" className="text-xs">
                      {confirmProfile.external_logs.length} logs
                    </Badge>
                  )}
                  {confirmProfile.registry_keys.length > 0 && (
                    <Badge variant="outline" className="text-xs">
                      {confirmProfile.registry_keys.length} {t('registryKeys').toLowerCase()}
                    </Badge>
                  )}
                </div>
              </div>
            )}

            {/* Selector de duración */}
            <div className="space-y-2">
              <Label htmlFor="debug-duration">{t('wsDuration')}</Label>
              <Input
                id="debug-duration"
                type="number"
                min={15}
                max={300}
                value={duration}
                onChange={(e) => setDuration(Math.min(300, Math.max(15, parseInt(e.target.value) || 60)))}
              />
              <p className="text-xs text-gray-500">{t('wsDurationHelp')}</p>
            </div>

            {/* Motivo (opcional) */}
            <div className="space-y-2">
              <Label htmlFor="debug-motivo">{t('wsMotivo')}</Label>
              <Input
                id="debug-motivo"
                value={motivo}
                onChange={(e) => setMotivo(e.target.value)}
                placeholder={t('wsMotivoPlaceholder')}
              />
            </div>

            {/* Instrucciones adicionales (opcional) */}
            <div className="space-y-2">
              <Label htmlFor="debug-instructions">{t('wsInstructions')}</Label>
              <Textarea
                id="debug-instructions"
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                placeholder={t('wsInstructionsPlaceholder')}
                rows={3}
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={resetConfirmForm}
              disabled={startMutation.isPending}
            >
              {tCommon('cancel')}
            </Button>
            <Button
              onClick={handleStartDebugging}
              disabled={startMutation.isPending}
            >
              {startMutation.isPending ? (
                <span className="flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {tCommon('loading')}
                </span>
              ) : (
                <>
                  <Play className="w-4 h-4 mr-1.5" />
                  {t('wsStartDebugging')}
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* === Diálogo de confirmación para eliminar datos === */}
      <Dialog open={!!deleteConfirmSessionId} onOpenChange={(open) => !open && setDeleteConfirmSessionId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{tCommon('confirmDelete')}</DialogTitle>
            <DialogDescription>{tCommon('cannotUndo')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteConfirmSessionId(null)}
              disabled={deleteMutation.isPending}
            >
              {tCommon('cancel')}
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteConfirmSessionId && deleteMutation.mutate(deleteConfirmSessionId)}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin mr-1.5" />
              ) : (
                <Trash2 className="w-4 h-4 mr-1.5" />
              )}
              {tCommon('delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// === Subcomponente: Timer de Sesión Activa (Task 46) ===

interface ActiveTimerViewProps {
  session: DebuggingSession;
  t: ReturnType<typeof useTranslations>;
  onStop: () => void;
  isStopPending: boolean;
}

function ActiveTimerView({ session, t, onStop, isStopPending }: ActiveTimerViewProps) {
  const [remainingSeconds, setRemainingSeconds] = useState<number>(0);

  // Calcular tiempo restante con actualización cada segundo
  useEffect(() => {
    const calculateRemaining = () => {
      const startTime = new Date(session.start_time).getTime();
      const endTime = startTime + session.duration_seconds * 1000;
      const now = Date.now();
      const remaining = Math.max(0, Math.floor((endTime - now) / 1000));
      setRemainingSeconds(remaining);
    };

    calculateRemaining();
    const interval = setInterval(calculateRemaining, 1000);
    return () => clearInterval(interval);
  }, [session.start_time, session.duration_seconds]);

  // Calcular progreso
  const elapsedSeconds = Math.max(0, session.duration_seconds - remainingSeconds);
  const progressPct = Math.min(100, (elapsedSeconds / session.duration_seconds) * 100);

  return (
    <div className="p-4 bg-amber-50 border border-amber-200 rounded-lg space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Timer className="w-4 h-4 text-amber-600 animate-pulse" />
          <span className="text-sm font-medium text-amber-900">{t('wsCapturing')}</span>
        </div>
        <Badge variant="outline" className="text-xs font-mono">
          <Clock className="w-3 h-3 mr-1" />
          {t('wsTimeRemaining', { seconds: String(remainingSeconds) })}
        </Badge>
      </div>

      {/* Barra de progreso */}
      <div className="w-full h-2 bg-amber-200 rounded-full overflow-hidden">
        <div
          className="h-full bg-amber-500 rounded-full transition-all duration-1000"
          style={{ width: `${progressPct}%` }}
        />
      </div>

      {/* Botón de detener */}
      <Button
        size="sm"
        variant="destructive"
        onClick={onStop}
        disabled={isStopPending}
      >
        {isStopPending ? (
          <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
        ) : (
          <Square className="w-3.5 h-3.5 mr-1.5" />
        )}
        {t('wsStopDebugging')}
      </Button>
    </div>
  );
}
