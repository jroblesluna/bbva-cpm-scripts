/**
 * Componente de estado "Esperando aprobación del usuario".
 * Se muestra mientras la sesión está en estado pending_consent,
 * cuando el usuario rechazó la conexión, o cuando expiró el tiempo de espera.
 *
 * Estados visuales:
 * - pending_consent: Spinner + texto "Esperando aprobación..."
 * - rejected (user_declined): Ícono X rojo + texto + botón Reintentar
 * - timed_out (user_timeout): Ícono reloj + texto + botón Reintentar
 *
 * Requirements: 2.5, 3.6, 3.7
 */

'use client'

import { useTranslations } from 'next-intl'
import { Loader2, X, Clock, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'

// ============================================================================
// TIPOS
// ============================================================================

interface ConsentPendingProps {
  sessionId: string
  workstationIp: string
  workstationHostname: string
  status: 'pending_consent' | 'rejected' | 'timed_out'
  rejectionReason?: 'user_declined' | 'user_timeout'
  onRetry: () => void
}

// ============================================================================
// COMPONENTE PRINCIPAL
// ============================================================================

export function ConsentPending({
  sessionId,
  workstationIp,
  workstationHostname,
  status,
  rejectionReason,
  onRetry,
}: ConsentPendingProps) {
  const t = useTranslations('remoteView')

  return (
    <div className="flex flex-1 items-center justify-center bg-gray-900">
      <div className="flex flex-col items-center gap-4 text-center px-6">
        {/* Estado: Esperando consentimiento (Req 2.5) */}
        {status === 'pending_consent' && (
          <>
            <Loader2 className="w-12 h-12 text-blue-400 animate-spin" />
            <p className="text-lg text-white font-medium">
              {t('waitingConsent')}
            </p>
            <p className="text-sm text-gray-400">
              {t('workstationInfo', {
                ip: workstationIp,
                hostname: workstationHostname,
              })}
            </p>
            <p className="text-xs text-gray-500">
              {t('waitingConsentHint')}
            </p>
          </>
        )}

        {/* Estado: Rechazado por el usuario (Req 3.6) */}
        {status === 'rejected' && (
          <>
            <div className="flex items-center justify-center w-12 h-12 rounded-full bg-red-900/40">
              <X className="w-7 h-7 text-red-400" />
            </div>
            <p className="text-lg text-white font-medium">
              {t('userRejected')}
            </p>
            <p className="text-sm text-gray-400">
              {t('workstationInfo', {
                ip: workstationIp,
                hostname: workstationHostname,
              })}
            </p>
            <Button
              variant="default"
              size="sm"
              onClick={onRetry}
              className="mt-2 gap-2"
            >
              <RefreshCw className="w-4 h-4" />
              {t('retry')}
            </Button>
          </>
        )}

        {/* Estado: Tiempo expirado (timeout — Req 3.7 implícito) */}
        {status === 'timed_out' && (
          <>
            <div className="flex items-center justify-center w-12 h-12 rounded-full bg-yellow-900/40">
              <Clock className="w-7 h-7 text-yellow-400" />
            </div>
            <p className="text-lg text-white font-medium">
              {t('userTimedOut')}
            </p>
            <p className="text-sm text-gray-400">
              {t('workstationInfo', {
                ip: workstationIp,
                hostname: workstationHostname,
              })}
            </p>
            <Button
              variant="default"
              size="sm"
              onClick={onRetry}
              className="mt-2 gap-2"
            >
              <RefreshCw className="w-4 h-4" />
              {t('retry')}
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
