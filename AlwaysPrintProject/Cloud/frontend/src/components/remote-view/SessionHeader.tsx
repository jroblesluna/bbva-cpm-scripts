/**
 * Barra de controles de sesión de Vista Remota.
 * Se muestra debajo de los tabs y encima del visor de video/screenshot.
 *
 * Contiene:
 * - Indicador de conexión (● verde/rojo)
 * - IP — Hostname
 * - Dropdown de monitor (oculto si solo hay 1)
 * - Selector de resolución/calidad
 * - Selector de modo (filtrado por modes_allowed)
 * - Timer MM:SS (cuenta desde startedAt)
 * - Botón cerrar (✕)
 *
 * Requirements: 9.6, 9.7, 9.8, 8.2, 8.5
 */

'use client'

import { useEffect, useState } from 'react'
import { useTranslations } from 'next-intl'
import { Monitor, X, Clock, Wifi, WifiOff } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { RemoteViewTab, RemoteViewMode } from '@/types/remote-view'

// ============================================================================
// TIPOS
// ============================================================================

interface SessionHeaderProps {
  tab: RemoteViewTab
  isConnected: boolean
  modesAllowed: RemoteViewMode[]
  onMonitorChange: (monitorIndex: number) => void
  onResolutionChange: (resolution: string) => void
  onModeChange: (mode: RemoteViewMode) => void
  onClose: () => void
}

// ============================================================================
// CONSTANTES: Niveles de resolución/calidad
// ============================================================================

/** Opciones de resolución disponibles en modo auto (Req 9.7) */
const RESOLUTION_OPTIONS = [
  { value: 'high', labelKey: 'resHigh' },
  { value: 'medium', labelKey: 'resMedium' },
  { value: 'low', labelKey: 'resLow' },
  { value: 'minimum', labelKey: 'resMinimum' },
  { value: 'auto', labelKey: 'resAuto' },
] as const

// ============================================================================
// HOOK: Timer de sesión
// ============================================================================

/**
 * Hook que calcula el tiempo transcurrido desde startedAt.
 * Devuelve string formateado como MM:SS.
 * Limpia el interval al desmontar.
 */
function useSessionTimer(startedAt: string): string {
  const [elapsed, setElapsed] = useState('00:00')

  useEffect(() => {
    const startTime = new Date(startedAt).getTime()

    const updateTimer = () => {
      const now = Date.now()
      const diffMs = Math.max(0, now - startTime)
      const totalSeconds = Math.floor(diffMs / 1000)
      const minutes = Math.floor(totalSeconds / 60)
      const seconds = totalSeconds % 60
      setElapsed(
        `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
      )
    }

    // Calcular inmediatamente y luego cada segundo
    updateTimer()
    const intervalId = setInterval(updateTimer, 1000)

    return () => clearInterval(intervalId)
  }, [startedAt])

  return elapsed
}

// ============================================================================
// COMPONENTE PRINCIPAL
// ============================================================================

export function SessionHeader({
  tab,
  isConnected,
  modesAllowed,
  onMonitorChange,
  onResolutionChange,
  onModeChange,
  onClose,
}: SessionHeaderProps) {
  const t = useTranslations('remoteView')
  const timer = useSessionTimer(tab.startedAt)

  // Label de la workstation: IP — Hostname
  const wsLabel =
    tab.ip && tab.hostname
      ? `${tab.ip} — ${tab.hostname}`
      : tab.ip || tab.hostname || tab.sessionId.slice(0, 8)

  return (
    <div className="flex items-center gap-3 px-4 h-12 bg-gray-800 border-b border-gray-700 flex-shrink-0">
      {/* Indicador de conexión (Req 9.6) */}
      <div className="flex items-center gap-1.5" title={isConnected ? t('connected') : t('disconnected')}>
        {isConnected ? (
          <Wifi className="w-4 h-4 text-green-400" />
        ) : (
          <WifiOff className="w-4 h-4 text-red-400" />
        )}
        <span
          className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`}
          aria-label={isConnected ? t('connected') : t('disconnected')}
        />
      </div>

      {/* IP — Hostname */}
      <span className="text-sm text-gray-200 font-medium truncate max-w-[180px]">
        {wsLabel}
      </span>

      {/* Separador visual */}
      <div className="w-px h-5 bg-gray-600" />

      {/* Dropdown de monitor (oculto si solo hay 1 — Req 8.5) */}
      {tab.monitors.length > 1 && (
        <div className="flex items-center gap-1.5">
          <Monitor className="w-4 h-4 text-gray-400" />
          <select
            value={tab.selectedMonitor}
            onChange={(e) => onMonitorChange(Number(e.target.value))}
            className="bg-gray-700 text-gray-200 text-xs rounded px-2 py-1 border border-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
            aria-label={t('selectMonitor')}
          >
            {tab.monitors.map((monitor) => (
              <option key={monitor.index} value={monitor.index}>
                {monitor.name || `${t('selectMonitor')} ${monitor.index + 1}`}
                {monitor.primary ? ' ★' : ''}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Selector de resolución/calidad (Req 9.7) */}
      <select
        value={tab.resolution || 'auto'}
        onChange={(e) => onResolutionChange(e.target.value)}
        className="bg-gray-700 text-gray-200 text-xs rounded px-2 py-1 border border-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
        aria-label={t('resolutionLabel')}
      >
        {RESOLUTION_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {t(opt.labelKey)}
          </option>
        ))}
      </select>

      {/* Selector de modo — solo muestra modos en modes_allowed (Req 9.8) */}
      {modesAllowed.length > 1 && (
        <select
          value={tab.mode}
          onChange={(e) => onModeChange(e.target.value as RemoteViewMode)}
          className="bg-gray-700 text-gray-200 text-xs rounded px-2 py-1 border border-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
          aria-label={t('modeLabel')}
        >
          {modesAllowed.map((mode) => (
            <option key={mode} value={mode}>
              {t(`mode_${mode}`)}
            </option>
          ))}
        </select>
      )}

      {/* Spacer para empujar timer y close a la derecha */}
      <div className="flex-1" />

      {/* Timer MM:SS (cuenta desde startedAt) */}
      <div className="flex items-center gap-1.5 text-gray-300 text-sm tabular-nums">
        <Clock className="w-4 h-4 text-gray-400" />
        <span>{timer}</span>
      </div>

      {/* Botón cerrar sesión (✕) */}
      <Button
        variant="ghost"
        size="sm"
        onClick={onClose}
        className="h-8 w-8 p-0 text-gray-400 hover:text-red-400 hover:bg-gray-700"
        title={t('closeSession')}
        aria-label={t('closeSession')}
      >
        <X className="w-4 h-4" />
      </Button>
    </div>
  )
}
