/**
 * Contenedor de una sesión individual de Vista Remota.
 * Renderiza SessionHeader + el viewer correspondiente al modo actual,
 * más overlays de ConsentPending, TimeoutWarning y ClipboardSync.
 *
 * El cambio de modo (dropdown en SessionHeader) envía `remote_view_config`
 * con el nuevo mode al backend vía WebSocket y cambia el viewer sin recargar.
 *
 * Requirements: 9.9, 11.4, 3.11
 */

'use client'

import { useCallback } from 'react'
import { useTranslations } from 'next-intl'
import { SessionHeader } from './SessionHeader'
import { ScreenshotViewer } from './ScreenshotViewer'
import { DeltaStreamViewer } from './DeltaStreamViewer'
import { ConsentPending } from './ConsentPending'
import { TimeoutWarning } from './TimeoutWarning'
import { ClipboardSync } from './ClipboardSync'
import type { RemoteViewTab, RemoteViewMode, RvInputMessage, DeltaTile } from '@/types/remote-view'

// ============================================================================
// TIPOS
// ============================================================================

interface SessionTabProps {
  /** Datos del tab/sesión activa */
  tab: RemoteViewTab
  /** Si este tab es el activo (visible) */
  isActive: boolean
  /** Modos permitidos por la organización */
  modesAllowed: RemoteViewMode[]
  /** Cerrar la sesión */
  onClose: () => void
  /** Cambio de modo: envía remote_view_config con nuevo mode */
  onModeChange: (mode: RemoteViewMode) => void
  /** Cambio de monitor seleccionado */
  onMonitorChange: (monitorIndex: number) => void
  /** Cambio de resolución/calidad */
  onResolutionChange: (resolution: string) => void
  /** Último frame binario recibido del WebSocket (Stream/Interactive) */
  latestFrame: ArrayBuffer | null
  /** Datos base64 del frame (Screenshot mode) */
  frameData: string | null
  /** Ancho del frame actual */
  frameWidth: number
  /** Alto del frame actual */
  frameHeight: number
  /** Último delta frame (tiles que cambiaron, Canvas streaming) */
  latestDelta: { tiles: DeltaTile[]; width: number; height: number } | null
  /** Solicitar un frame (Screenshot mode: rv_request_frame) */
  onRequestFrame: () => void
  /** Enviar evento de input (Interactive mode: rv_input) */
  onSendInput: (msg: RvInputMessage) => void
  /** Enviar texto al clipboard de la workstation (rv_clipboard) */
  onSendClipboard: (text: string) => void
  /** Último texto recibido desde la WS vía clipboard */
  incomingClipboardText: string | null
  /** Si el clipboard bidireccional está habilitado */
  clipboardEnabled: boolean
  /** Si la conexión WebSocket está activa */
  isConnected: boolean
  /** Segundos restantes para timeout (null si no hay warning activo) */
  timeoutSecondsRemaining: number | null
  /** Si la sesión ya expiró por timeout */
  isExpired: boolean
  /** Resetear timer de inactividad */
  onKeepAlive: () => void
  /** Reintentar conexión (cuando consent fue rechazado) */
  onRetry: () => void
}

// ============================================================================
// COMPONENTE PRINCIPAL
// ============================================================================

export function SessionTab({
  tab,
  isActive,
  modesAllowed,
  onClose,
  onModeChange,
  onMonitorChange,
  onResolutionChange,
  latestFrame,
  frameData,
  frameWidth,
  frameHeight,
  latestDelta,
  onRequestFrame,
  onSendInput,
  onSendClipboard,
  incomingClipboardText,
  clipboardEnabled,
  isConnected,
  timeoutSecondsRemaining,
  isExpired,
  onKeepAlive,
  onRetry,
}: SessionTabProps) {
  const t = useTranslations('remoteView')

  /**
   * Handler de cambio de modo desde el dropdown de SessionHeader.
   * Delega al padre que envía remote_view_config con el nuevo mode.
   * La transición es seamless: no recrea la sesión (Req 9.9, 3.11).
   */
  const handleModeChange = useCallback(
    (mode: RemoteViewMode) => {
      onModeChange(mode)
    },
    [onModeChange]
  )

  // ============================================================================
  // RENDERIZADO CONDICIONAL DEL VIEWER
  // ============================================================================

  /**
   * Renderiza el viewer correcto según el modo actual del tab.
   * - screenshot → ScreenshotViewer (request/response, auto-refresh)
   * - stream → DeltaStreamViewer (canvas, keyframe + delta tiles)
   * - interactive → DeltaStreamViewer (canvas, con input capturado por InteractiveViewer en el futuro)
   */
  const renderViewer = () => {
    if (tab.mode === 'screenshot') {
      return (
        <ScreenshotViewer
          sessionId={tab.sessionId}
          frameData={frameData}
          frameWidth={frameWidth}
          frameHeight={frameHeight}
          onRequestFrame={onRequestFrame}
        />
      )
    }

    // Stream e Interactive: usar DeltaStreamViewer (canvas-based, composición incremental)
    return (
      <DeltaStreamViewer
        sessionId={tab.sessionId}
        isActive={isActive}
        latestKeyframe={frameData ? { data: frameData, width: frameWidth, height: frameHeight } : null}
        latestDelta={latestDelta}
      />
    )
  }

  // ============================================================================
  // RENDER
  // ============================================================================

  return (
    <div className="flex flex-col flex-1 h-full overflow-hidden">
      {/* SessionHeader: siempre visible arriba */}
      <SessionHeader
        tab={tab}
        isConnected={isConnected}
        modesAllowed={modesAllowed}
        onMonitorChange={onMonitorChange}
        onResolutionChange={onResolutionChange}
        onModeChange={handleModeChange}
        onClose={onClose}
      />

      {/* Contenido principal: viewer o estado de consent */}
      <div className="flex-1 relative overflow-hidden">
        {/* ConsentPending: mientras esperamos aprobación o sesión fue rechazada/expirada */}
        {(tab.status === 'pending_consent' || tab.status === 'disconnected' || tab.status === 'expired') && (
          <ConsentPending
            sessionId={tab.sessionId}
            workstationIp={tab.ip}
            workstationHostname={tab.hostname}
            status={
              tab.status === 'pending_consent' ? 'pending_consent' :
              tab.status === 'expired' ? 'timed_out' :
              'rejected'
            }
            rejectionReason={tab.status === 'expired' ? 'user_timeout' : 'user_declined'}
            onRetry={onRetry}
          />
        )}

        {/* Viewer activo: solo cuando la sesión está activa o pausada */}
        {(tab.status === 'active' || tab.status === 'paused') && renderViewer()}

        {/* ClipboardSync: en toolbar cuando está habilitado y modo interactivo */}
        {tab.status === 'active' && tab.mode === 'interactive' && clipboardEnabled && (
          <div className="absolute bottom-12 right-4 z-10">
            <ClipboardSync
              sessionId={tab.sessionId}
              enabled={clipboardEnabled}
              incomingText={incomingClipboardText}
              onSendClipboard={onSendClipboard}
            />
          </div>
        )}

        {/* TimeoutWarning overlay: cuando quedan ≤60s para timeout */}
        {timeoutSecondsRemaining !== null && (
          <TimeoutWarning
            secondsRemaining={timeoutSecondsRemaining}
            isExpired={isExpired}
            onKeepAlive={onKeepAlive}
          />
        )}
      </div>
    </div>
  )
}
