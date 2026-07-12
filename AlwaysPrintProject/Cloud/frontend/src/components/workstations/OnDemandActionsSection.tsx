/**
 * Sección de acciones OnDemand disponibles para una workstation.
 * Muestra la lista de triggers OnDemand y permite ejecutarlos remotamente.
 */

'use client';

import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import { Play, Loader2, Zap, WifiOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
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
import { workstationsApi } from '@/lib/api';

interface OnDemandAction {
  label: string;
  description: string;
}

interface OnDemandActionsSectionProps {
  workstationId: string;
  isOnline: boolean;
}

export function OnDemandActionsSection({ workstationId, isOnline }: OnDemandActionsSectionProps) {
  const t = useTranslations('workstations');
  const tCommon = useTranslations('common');
  const { toast } = useToast();
  const [confirmAction, setConfirmAction] = useState<OnDemandAction | null>(null);

  // Obtener acciones OnDemand disponibles
  const { data: actions, isLoading } = useQuery<OnDemandAction[]>({
    queryKey: ['ondemand-actions', workstationId],
    queryFn: async () => {
      const response = await workstationsApi.getOnDemandActions(workstationId);
      return response;
    },
  });

  // Mutación para ejecutar una acción
  const executeMutation = useMutation({
    mutationFn: async (label: string) => {
      const startTime = Date.now();
      const result = await workstationsApi.sendCommand(
        workstationId,
        'execute_on_demand',
        { label }
      );
      const duration = Date.now() - startTime;
      return { ...result, duration };
    },
    onSuccess: (data) => {
      toast({
        title: t('actionExecuted'),
        description: t('actionExecutedDesc', { duration: String(data.duration) }),
      });
      setConfirmAction(null);
    },
    onError: (error: { detail?: string; status?: number }) => {
      let description: string;
      if (error.status === 409) {
        description = t('wsOfflineTooltip');
      } else if (error.status === 408 || error.status === 504) {
        description = t('actionTimeout');
      } else {
        description = error.detail ?? t('actionFailed');
      }
      toast({
        variant: 'destructive',
        title: t('actionFailed'),
        description,
      });
      setConfirmAction(null);
    },
  });

  // No mostrar sección si la workstation está offline
  if (!isOnline) {
    return null;
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="space-y-2">
        <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
          {t('onDemandSection')}
        </h3>
        <div className="animate-pulse space-y-2">
          {[1, 2].map((i) => (
            <div key={i} className="h-12 bg-gray-100 rounded-lg" />
          ))}
        </div>
      </div>
    );
  }

  // Sin acciones disponibles
  if (!actions || actions.length === 0) {
    return (
      <div className="space-y-2">
        <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
          {t('onDemandSection')}
        </h3>
        <p className="text-sm text-gray-400 italic">{t('noActionsAvailable')}</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
        <div className="flex items-center gap-1.5">
          <Zap className="w-3.5 h-3.5" />
          {t('onDemandSection')}
        </div>
      </h3>

      <div className="space-y-2">
        {actions.map((action) => (
          <div
            key={action.label}
            className="flex items-center justify-between p-3 bg-gray-50 border border-gray-100 rounded-lg"
          >
            <div className="flex-1 min-w-0 mr-3">
              <p className="text-sm font-medium text-gray-900 truncate">{action.label}</p>
              {action.description && (
                <p className="text-xs text-gray-500 truncate">{action.description}</p>
              )}
            </div>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={!isOnline || executeMutation.isPending}
                      onClick={() => setConfirmAction(action)}
                      className="shrink-0"
                    >
                      <Play className="w-3.5 h-3.5 mr-1.5" />
                      {t('executeAction')}
                    </Button>
                  </span>
                </TooltipTrigger>
                {!isOnline && (
                  <TooltipContent>
                    <div className="flex items-center gap-1.5">
                      <WifiOff className="w-3.5 h-3.5" />
                      {t('wsOfflineTooltip')}
                    </div>
                  </TooltipContent>
                )}
              </Tooltip>
            </TooltipProvider>
          </div>
        ))}
      </div>

      {/* Diálogo de confirmación */}
      <Dialog open={!!confirmAction} onOpenChange={(open) => !open && setConfirmAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('actionConfirm')}</DialogTitle>
            <DialogDescription>
              {confirmAction && t('actionConfirmDesc', {
                label: confirmAction.label,
                description: confirmAction.description,
              })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmAction(null)}
              disabled={executeMutation.isPending}
            >
              {tCommon('cancel')}
            </Button>
            <Button
              onClick={() => confirmAction && executeMutation.mutate(confirmAction.label)}
              disabled={executeMutation.isPending}
            >
              {executeMutation.isPending ? (
                <span className="flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {t('executing')}
                </span>
              ) : (
                <>
                  <Play className="w-4 h-4 mr-1.5" />
                  {t('executeAction')}
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
