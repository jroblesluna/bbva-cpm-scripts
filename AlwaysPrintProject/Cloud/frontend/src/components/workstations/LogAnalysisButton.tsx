/**
 * Botón para solicitar análisis de log de una workstation.
 *
 * Flujo:
 * 1. Verifica si ya existe un análisis del día (GET today)
 * 2. Si existe, muestra diálogo de confirmación para sobrescribir
 * 3. Si no existe (o el usuario confirma), ejecuta POST analyze-log
 * 4. Muestra loading spinner durante el análisis
 * 5. Maneja errores (offline, timeout, LLM error) con mensajes descriptivos
 */

'use client';

import { useState, useCallback } from 'react';
import { Brain, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { logAnalysisApi } from '@/lib/api';
import { useToast } from '@/hooks/use-toast';
import { useTranslations } from 'next-intl';
import type { LogAnalysisResponse } from '@/types';

interface LogAnalysisButtonProps {
  workstationId: string;
  workstationName: string;
  isOnline: boolean;
  variant?: 'outline' | 'ghost' | 'default';
  size?: 'sm' | 'default' | 'lg' | 'icon';
  iconOnly?: boolean;
  className?: string;
  onAnalysisComplete?: (analysis: LogAnalysisResponse) => void;
}

export function LogAnalysisButton({
  workstationId,
  workstationName,
  isOnline,
  variant = 'outline',
  size = 'sm',
  iconOnly = false,
  className = '',
  onAnalysisComplete,
}: LogAnalysisButtonProps) {
  const { toast } = useToast();
  const t = useTranslations('logAnalysis');

  const [isLoading, setIsLoading] = useState(false);
  const [showOverwriteDialog, setShowOverwriteDialog] = useState(false);

  /**
   * Obtiene el mensaje de error descriptivo según el código de estado HTTP.
   */
  const getErrorMessage = useCallback(
    (error: { detail?: string; status?: number }): string => {
      if (error.status === 409) {
        return t('errorOffline');
      }
      if (error.status === 408) {
        return t('errorTimeout');
      }
      if (error.status === 502) {
        return t('errorLlm');
      }
      if (error.status === 422) {
        return error.detail ?? t('errorProcessing');
      }
      if (!error.status) {
        return t('errorConnection');
      }
      return error.detail ?? t('errorGeneric');
    },
    [t]
  );

  /**
   * Ejecuta el análisis de log (con o sin overwrite).
   */
  const executeAnalysis = useCallback(
    async (overwrite: boolean) => {
      setIsLoading(true);
      try {
        const result = await logAnalysisApi.analyzeLog(workstationId, overwrite);
        toast({
          title: t('successTitle'),
          description: t('successDescription'),
        });
        onAnalysisComplete?.(result);
      } catch (error: unknown) {
        const apiError = error as { detail?: string; status?: number };
        toast({
          variant: 'destructive',
          title: t('errorTitle'),
          description: getErrorMessage(apiError),
        });
      } finally {
        setIsLoading(false);
      }
    },
    [workstationId, toast, t, getErrorMessage, onAnalysisComplete]
  );

  /**
   * Handler principal del botón. Verifica si existe análisis previo.
   */
  const handleClick = useCallback(async () => {
    if (!isOnline) {
      toast({
        variant: 'destructive',
        title: t('errorTitle'),
        description: t('errorOffline'),
      });
      return;
    }

    setIsLoading(true);
    try {
      const todayCheck = await logAnalysisApi.checkToday(workstationId);

      if (todayCheck.exists) {
        // Existe análisis previo: mostrar diálogo de confirmación
        setIsLoading(false);
        setShowOverwriteDialog(true);
      } else {
        // No existe: ejecutar directamente
        await executeAnalysis(false);
      }
    } catch (error: unknown) {
      const apiError = error as { detail?: string; status?: number };
      // Si el endpoint retorna 404, significa que no hay análisis previo
      if (apiError.status === 404) {
        await executeAnalysis(false);
      } else {
        setIsLoading(false);
        toast({
          variant: 'destructive',
          title: t('errorTitle'),
          description: getErrorMessage(apiError),
        });
      }
    }
  }, [isOnline, workstationId, toast, t, executeAnalysis, getErrorMessage]);

  /**
   * Handler de confirmación de sobrescritura.
   */
  const handleConfirmOverwrite = useCallback(async () => {
    setShowOverwriteDialog(false);
    await executeAnalysis(true);
  }, [executeAnalysis]);

  return (
    <>
      <Button
        variant={variant}
        size={size}
        onClick={handleClick}
        disabled={isLoading || !isOnline}
        title={t('buttonTitle')}
        className={className}
      >
        {isLoading ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <Brain className="w-4 h-4" />
        )}
        {!iconOnly && <span className="ml-2">{t('buttonLabel')}</span>}
      </Button>

      <Dialog open={showOverwriteDialog} onOpenChange={setShowOverwriteDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('overwriteTitle')}</DialogTitle>
            <DialogDescription>
              {t('overwriteDescription', { name: workstationName })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowOverwriteDialog(false)}
            >
              {t('overwriteCancel')}
            </Button>
            <Button onClick={handleConfirmOverwrite}>
              {t('overwriteConfirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
