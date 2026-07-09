/**
 * Página de acciones masivas (Bulk On-Demand Actions).
 * Permite ejecutar una acción OnDemand en todas las workstations online de la organización.
 * Solo accesible para roles admin y operator.
 */

'use client';

import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import { useAuth } from '@/hooks/useAuth';
import { bulkActionsApi } from '@/lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Zap, AlertCircle, Clock, Loader2, CheckCircle2, XCircle, RotateCcw } from 'lucide-react';
import type { OnDemandAction, BulkPreview, BulkSessionStatus } from '@/types/bulk-actions';
import { formatEstimatedTime } from '@/lib/bulk-actions-utils';

// ============================================================================
// COMPONENTE: Stat — Muestra un contador individual con label y color
// ============================================================================
function Stat({ label, value, color }: { label: string; value: number; color?: string }) {
  const colorClass = color === 'green' ? 'text-green-600' : color === 'red' ? 'text-red-600' : 'text-gray-900';
  return (
    <div className="text-center">
      <p className="text-xs text-gray-500 uppercase font-medium">{label}</p>
      <p className={`text-xl font-bold ${colorClass}`}>{value}</p>
    </div>
  );
}

// ============================================================================
// COMPONENTE: ExecutionProgressSection — Panel de progreso en tiempo real
// Usa polling via GET /bulk-actions/status/{session_id} cada 3s como mecanismo
// principal. WebSocket (bulk_progress) puede integrarse posteriormente.
// ============================================================================
function ExecutionProgressSection({
  sessionId,
  t,
  onReset,
}: {
  sessionId: string;
  t: ReturnType<typeof useTranslations>;
  onReset: () => void;
}) {
  // Polling de estado — se detiene cuando la sesión ya no está running
  const { data: statusData } = useQuery({
    queryKey: ['bulk-session-status', sessionId],
    queryFn: async () => {
      const res = await bulkActionsApi.getStatus(sessionId);
      return res.data as BulkSessionStatus;
    },
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data?.status === 'completed' || data?.status === 'cancelled' || data?.status === 'failed') {
        return false;
      }
      return 3000; // Polling cada 3s mientras está running
    },
  });

  // Mutación para cancelar la ejecución
  const cancelMutation = useMutation({
    mutationFn: async () => {
      const res = await bulkActionsApi.cancel(sessionId);
      return res.data;
    },
  });

  const isRunning = statusData?.status === 'running';
  const isFinished = statusData?.status === 'completed' || statusData?.status === 'cancelled' || statusData?.status === 'failed';
  const progressPercent = statusData ? Math.round((statusData.sent / Math.max(statusData.total, 1)) * 100) : 0;

  // Determinar título según estado
  const getTitle = () => {
    if (!statusData || statusData.status === 'running') return t('executionInProgress');
    if (statusData.status === 'completed') return t('executionCompleted');
    if (statusData.status === 'failed') return t('executionFailed');
    return t('executionCancelled');
  };

  // Icono según estado
  const getIcon = () => {
    if (!statusData || statusData.status === 'running') return <Loader2 className="w-5 h-5 animate-spin text-blue-500" />;
    if (statusData.status === 'completed') return <CheckCircle2 className="w-5 h-5 text-green-500" />;
    if (statusData.status === 'failed') return <XCircle className="w-5 h-5 text-red-500" />;
    return <AlertCircle className="w-5 h-5 text-yellow-500" />;
  };

  // Color de la barra de progreso según estado
  const getBarColor = () => {
    if (statusData?.status === 'completed') return 'bg-green-500';
    if (statusData?.status === 'cancelled') return 'bg-yellow-500';
    if (statusData?.status === 'failed') return 'bg-red-500';
    return 'bg-blue-500';
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {getIcon()}
          {getTitle()}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Barra de progreso */}
        <div className="w-full bg-gray-200 rounded-full h-3">
          <div
            className={`h-3 rounded-full transition-all duration-300 ${getBarColor()}`}
            style={{ width: `${progressPercent}%` }}
          />
        </div>
        <p className="text-sm text-gray-600 text-center">{progressPercent}%</p>

        {/* Grid de contadores */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <Stat label={t('total')} value={statusData?.total ?? 0} />
          <Stat label={t('sent')} value={statusData?.sent ?? 0} />
          <Stat label={t('success')} value={statusData?.success ?? 0} color="green" />
          <Stat label={t('errors')} value={statusData?.errors ?? 0} color="red" />
        </div>

        {/* Tiempo transcurrido */}
        {statusData?.elapsed_ms != null && (
          <p className="text-sm text-gray-500 text-center">
            {t('elapsed')}: {formatEstimatedTime(statusData.elapsed_ms)}
          </p>
        )}

        {/* Botón de cancelación (solo cuando está running) */}
        {isRunning && (
          <div className="flex justify-center pt-2">
            <Button
              variant="destructive"
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
            >
              {cancelMutation.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              <XCircle className="w-4 h-4 mr-2" />
              {t('cancelExecution')}
            </Button>
          </div>
        )}

        {/* Botones al finalizar */}
        {isFinished && (
          <div className="flex justify-center gap-3 pt-2">
            <Button variant="outline" onClick={onReset}>
              <RotateCcw className="w-4 h-4 mr-2" />
              {t('newExecution')}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function BulkActionsPage() {
  const { user } = useAuth();
  const t = useTranslations('bulkActions');
  const tCommon = useTranslations('common');

  // Estado
  const [selectedAction, setSelectedAction] = useState<string>('');
  const [delayMs, setDelayMs] = useState<number>(500);
  const [showPreview, setShowPreview] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);

  // Obtener acciones OnDemand disponibles del alwaysconfig activo
  const { data: actions, isLoading, error } = useQuery({
    queryKey: ['bulk-actions-available'],
    queryFn: async () => {
      const res = await bulkActionsApi.getAvailableActions();
      return res.data as OnDemandAction[];
    },
  });

  // Query de preview — se activa al abrir el diálogo de confirmación
  const { data: previewData, isLoading: isLoadingPreview } = useQuery({
    queryKey: ['bulk-actions-preview', selectedAction, delayMs],
    queryFn: async () => {
      const res = await bulkActionsApi.preview({ label: selectedAction, delay_ms: delayMs });
      return res.data as BulkPreview;
    },
    enabled: showPreview && selectedAction !== '',
  });

  // Mutación para iniciar la ejecución masiva
  const startMutation = useMutation({
    mutationFn: async () => {
      const res = await bulkActionsApi.start({ label: selectedAction, delay_ms: delayMs });
      return res.data as BulkSessionStatus;
    },
    onSuccess: (data) => {
      setShowPreview(false);
      setSessionId(data.session_id);
    },
  });

  // Verificación de rol — solo admin y operator pueden acceder
  // Si el usuario no está autenticado, no mostramos nada (el middleware redirige)
  if (!user) {
    return null;
  }

  // Validar delay dentro de rango permitido
  const handleDelayChange = (value: string) => {
    const num = parseInt(value, 10);
    if (!isNaN(num)) {
      setDelayMs(Math.min(10000, Math.max(50, num)));
    } else if (value === '') {
      setDelayMs(50);
    }
  };

  // Acción seleccionada completa
  const selectedActionObj = actions?.find((a) => a.label === selectedAction);

  // Puede iniciar preview si hay acción seleccionada y delay válido
  const canPreview = selectedAction !== '' && delayMs >= 50 && delayMs <= 10000;

  return (
    <div className="space-y-6 p-4 md:p-6">
      {/* Encabezado */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold">{t('title')}</h1>
          <p className="text-gray-600 mt-1">{t('subtitle')}</p>
        </div>
        <Zap className="w-8 h-8 md:w-12 md:h-12 text-yellow-500 hidden sm:block" />
      </div>

      {/* Panel de progreso — se muestra cuando hay sesión activa */}
      {sessionId && (
        <ExecutionProgressSection
          sessionId={sessionId}
          t={t}
          onReset={() => {
            setSessionId(null);
            setSelectedAction('');
          }}
        />
      )}

      {/* Contenido de configuración — se oculta cuando hay sesión activa */}
      {!sessionId && (
        <>
          {/* Selector de acción */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Zap className="w-5 h-5" />
                {t('actionLabel')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {isLoading && (
                <div className="flex items-center gap-2 text-gray-500">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>{tCommon('loading')}</span>
                </div>
              )}

              {error && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>
                    {(error as { detail?: string })?.detail === 'No hay configuración activa para la organización'
                      ? t('noActiveConfig')
                      : tCommon('error')}
                  </AlertDescription>
                </Alert>
              )}

              {!isLoading && !error && actions && actions.length === 0 && (
                <Alert>
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>{t('noActionsAvailable')}</AlertDescription>
                </Alert>
              )}

              {!isLoading && !error && actions && actions.length > 0 && (
                <div className="space-y-3">
                  <Label>{t('selectAction')}</Label>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {actions.map((action) => (
                      <button
                        key={action.label}
                        type="button"
                        onClick={() => setSelectedAction(action.label)}
                        className={`
                          text-left p-4 rounded-lg border-2 transition-all
                          ${selectedAction === action.label
                            ? 'border-blue-500 bg-blue-50 ring-2 ring-blue-200'
                            : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                          }
                        `}
                      >
                        <div className="font-medium text-sm">{action.label}</div>
                        {action.description && (
                          <div className="text-xs text-gray-500 mt-1">{action.description}</div>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Configuración de Throttle */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Clock className="w-5 h-5" />
                {t('throttleLabel')}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-gray-600">{t('throttleDescription')}</p>

              <div className="flex flex-col sm:flex-row sm:items-end gap-4">
                <div className="flex-1 max-w-xs">
                  <Label htmlFor="delay-input">{t('throttleLabel')}</Label>
                  <div className="relative mt-1">
                    <Input
                      id="delay-input"
                      type="number"
                      min={50}
                      max={10000}
                      step={50}
                      value={delayMs}
                      onChange={(e) => handleDelayChange(e.target.value)}
                      className="pr-10"
                    />
                    <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-gray-400">
                      {t('milliseconds')}
                    </span>
                  </div>
                </div>

                <div className="text-xs text-gray-500 space-y-1">
                  <p>{t('throttleMin')}</p>
                  <p>{t('throttleMax')}</p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Resumen y botón de preview */}
          {selectedActionObj && (
            <Card>
              <CardContent className="pt-6">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  <div className="space-y-1">
                    <p className="text-sm text-gray-600">
                      <span className="font-medium">{t('actionLabel')}:</span> {selectedActionObj.label}
                    </p>
                    {selectedActionObj.description && (
                      <p className="text-sm text-gray-500">
                        <span className="font-medium">{t('actionDescription')}:</span> {selectedActionObj.description}
                      </p>
                    )}
                    <p className="text-sm text-gray-500">
                      <span className="font-medium">{t('throttleLabel')}:</span> {delayMs}{t('milliseconds')}
                    </p>
                  </div>

                  <Button
                    onClick={() => setShowPreview(true)}
                    disabled={!canPreview}
                    className="w-full sm:w-auto"
                  >
                    <Zap className="w-4 h-4 mr-2" />
                    {t('preview')}
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}

      {/* Diálogo de confirmación con preview */}
      <Dialog open={showPreview} onOpenChange={setShowPreview}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('previewTitle')}</DialogTitle>
            <DialogDescription>
              {selectedActionObj?.description ?? selectedActionObj?.label}
            </DialogDescription>
          </DialogHeader>

          {isLoadingPreview && (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="w-6 h-6 animate-spin text-gray-500" />
            </div>
          )}

          {previewData && !isLoadingPreview && (
            <div className="space-y-4 py-2">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* Acción */}
                <div className="space-y-1">
                  <p className="text-xs text-gray-500 font-medium uppercase">{t('actionLabel')}</p>
                  <p className="text-sm font-semibold">{previewData.action_label}</p>
                </div>

                {/* Workstations online */}
                <div className="space-y-1">
                  <p className="text-xs text-gray-500 font-medium uppercase">{t('workstationsOnline')}</p>
                  <p className="text-sm font-semibold">{previewData.workstations_online}</p>
                </div>

                {/* Tiempo estimado */}
                <div className="space-y-1">
                  <p className="text-xs text-gray-500 font-medium uppercase">{t('estimatedTime')}</p>
                  <p className="text-sm font-semibold">
                    {formatEstimatedTime(previewData.estimated_time_ms)}
                  </p>
                </div>

                {/* Delay configurado */}
                <div className="space-y-1">
                  <p className="text-xs text-gray-500 font-medium uppercase">{t('throttleLabel')}</p>
                  <p className="text-sm font-semibold">{delayMs}{t('milliseconds')}</p>
                </div>
              </div>
            </div>
          )}

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowPreview(false)}
              disabled={startMutation.isPending}
            >
              {tCommon('cancel')}
            </Button>
            <Button
              onClick={() => startMutation.mutate()}
              disabled={isLoadingPreview || !previewData || startMutation.isPending}
            >
              {startMutation.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              {t('confirmExecution')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
