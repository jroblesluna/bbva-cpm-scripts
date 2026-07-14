/**
 * Visor de capturas de pantalla (modo Screenshot).
 * Muestra frames JPEG recibidos en base64 con object-fit: contain.
 *
 * Funcionalidades:
 * - Muestra imagen JPEG escalada al panel (object-fit: contain)
 * - Botón "Refresh" para solicitar un frame manualmente
 * - Toggle "Auto-refresh" que solicita frames cada 2 segundos
 * - Muestra dimensiones del frame
 * - Estado de carga cuando no hay frame disponible
 * - Auto-solicita el primer frame al montar
 *
 * Requirements: 4.6, 4.7, 4.8
 */

'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { useTranslations } from 'next-intl'
import { RefreshCw, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'

// ============================================================================
// TIPOS
// ============================================================================

interface ScreenshotViewerProps {
  sessionId: string
  frameData: string | null // datos JPEG en base64
  frameWidth: number
  frameHeight: number
  onRequestFrame: () => void // callback para enviar rv_request_frame
  defaultAutoRefresh?: boolean // iniciar con auto-refresh activado (para stream/interactive)
}

// ============================================================================
// CONSTANTES
// ============================================================================

/** Intervalo de auto-refresh en milisegundos */
const AUTO_REFRESH_INTERVAL_MS = 2000

// ============================================================================
// COMPONENTE PRINCIPAL
// ============================================================================

export function ScreenshotViewer({
  sessionId,
  frameData,
  frameWidth,
  frameHeight,
  onRequestFrame,
  defaultAutoRefresh = false,
}: ScreenshotViewerProps) {
  const t = useTranslations('remoteView')
  const [autoRefresh, setAutoRefresh] = useState(defaultAutoRefresh)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Solicitar primer frame al montar
  useEffect(() => {
    onRequestFrame()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Gestión del intervalo de auto-refresh (Req 4.8)
  useEffect(() => {
    if (autoRefresh) {
      intervalRef.current = setInterval(() => {
        onRequestFrame()
      }, AUTO_REFRESH_INTERVAL_MS)
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [autoRefresh, onRequestFrame])

  // Toggle auto-refresh
  const handleToggleAutoRefresh = useCallback(() => {
    setAutoRefresh((prev) => !prev)
  }, [])

  return (
    <div className="flex flex-col flex-1 bg-gray-900 overflow-hidden">
      {/* Área de imagen (Req 4.6) */}
      <div className="flex-1 flex items-center justify-center overflow-hidden p-2">
        {frameData ? (
          <img
            src={`data:image/jpeg;base64,${frameData}`}
            alt={t('screenshotAlt')}
            className="max-w-full max-h-full object-contain"
            style={{ objectFit: 'contain' }}
          />
        ) : (
          // Estado de carga cuando no hay frame
          <div className="flex flex-col items-center gap-3 text-gray-400">
            <Loader2 className="w-8 h-8 animate-spin" />
            <span className="text-sm">{t('loadingFrame')}</span>
          </div>
        )}
      </div>

      {/* Barra de controles inferior */}
      <div className="flex items-center gap-3 px-4 h-10 bg-gray-800 border-t border-gray-700 flex-shrink-0">
        {/* Botón Refresh (Req 4.7) */}
        <Button
          variant="ghost"
          size="sm"
          onClick={onRequestFrame}
          className="h-7 px-2 text-gray-300 hover:text-white hover:bg-gray-700 gap-1.5"
          title={t('refresh')}
          aria-label={t('refresh')}
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span className="text-xs">{t('refresh')}</span>
        </Button>

        {/* Separador visual */}
        <div className="w-px h-5 bg-gray-600" />

        {/* Toggle Auto-refresh (Req 4.8) */}
        <button
          type="button"
          onClick={handleToggleAutoRefresh}
          className="flex items-center gap-2 text-xs text-gray-300 hover:text-white transition-colors"
          aria-pressed={autoRefresh}
          aria-label={t('autoRefresh')}
        >
          {/* Switch visual */}
          <div
            className={`relative w-8 h-4 rounded-full transition-colors ${
              autoRefresh ? 'bg-blue-600' : 'bg-gray-600'
            }`}
          >
            <div
              className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-transform ${
                autoRefresh ? 'translate-x-4' : 'translate-x-0.5'
              }`}
            />
          </div>
          <span>{t('autoRefresh')}</span>
          <span className={`${autoRefresh ? 'text-blue-400' : 'text-gray-500'}`}>
            {autoRefresh ? t('autoRefreshOn') : t('autoRefreshOff')}
          </span>
        </button>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Dimensiones del frame */}
        {frameWidth > 0 && frameHeight > 0 && (
          <span className="text-xs text-gray-500 tabular-nums">
            {t('frameDimensions', { width: frameWidth, height: frameHeight })}
          </span>
        )}
      </div>
    </div>
  )
}
