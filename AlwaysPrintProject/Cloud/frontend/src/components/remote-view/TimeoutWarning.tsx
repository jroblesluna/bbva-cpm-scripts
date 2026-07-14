/**
 * Overlay de advertencia de timeout por inactividad.
 * Se muestra cuando faltan 60 segundos para que la sesión expire por inactividad.
 *
 * Estados:
 * - Warning (secondsRemaining > 0 && !isExpired): Backdrop semi-transparente,
 *   mensaje de countdown, botón "Mantener activa"
 * - Expired (isExpired): Backdrop sólido, mensaje permanente "Sesión expirada",
 *   sin botón (sesión cerrada definitivamente)
 *
 * El componente padre gestiona el countdown y pasa los valores como props.
 *
 * Requirements: 7.2, 7.3, 7.4
 */

'use client'

import { useTranslations } from 'next-intl'
import { AlertTriangle, Lock } from 'lucide-react'
import { Button } from '@/components/ui/button'

// ============================================================================
// TIPOS
// ============================================================================

interface TimeoutWarningProps {
  /** Segundos restantes del countdown (60 → 0) */
  secondsRemaining: number
  /** true cuando el timeout se alcanzó y la sesión expiró */
  isExpired: boolean
  /** Callback para resetear el timer de inactividad */
  onKeepAlive: () => void
}

// ============================================================================
// COMPONENTE PRINCIPAL
// ============================================================================

export function TimeoutWarning({
  secondsRemaining,
  isExpired,
  onKeepAlive,
}: TimeoutWarningProps) {
  const t = useTranslations('remoteView')

  // Estado: Sesión expirada permanentemente (Req 7.4)
  if (isExpired) {
    return (
      <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/90">
        <div className="flex flex-col items-center gap-4 text-center px-6">
          <div className="flex items-center justify-center w-14 h-14 rounded-full bg-red-900/50">
            <Lock className="w-8 h-8 text-red-400" />
          </div>
          <p className="text-lg font-medium text-red-400">
            {t('sessionExpiredPermanent')}
          </p>
        </div>
      </div>
    )
  }

  // Estado: Advertencia de timeout con countdown (Req 7.3)
  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/70">
      <div className="flex flex-col items-center gap-4 text-center px-6">
        <div className="flex items-center justify-center w-14 h-14 rounded-full bg-amber-900/50">
          <AlertTriangle className="w-8 h-8 text-amber-400" />
        </div>
        <p className="text-lg font-medium text-amber-300">
          {t('timeoutWarning', { seconds: secondsRemaining })}
        </p>
        <Button
          variant="default"
          size="sm"
          onClick={onKeepAlive}
          className="mt-2 bg-green-600 hover:bg-green-700 text-white gap-2"
        >
          {t('keepAlive')}
        </Button>
      </div>
    </div>
  )
}
