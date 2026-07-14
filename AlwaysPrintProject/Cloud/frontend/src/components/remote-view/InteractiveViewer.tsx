/**
 * Visor interactivo que extiende StreamViewer con captura de mouse y teclado.
 * Captura eventos del usuario, normaliza coordenadas y envía mensajes rv_input
 * al backend para inyección en la workstation remota.
 *
 * Funcionalidades:
 * - Mouse: move, down, up, wheel con coordenadas normalizadas (0.0–1.0)
 * - Teclado: keydown/keyup con code, key y modifiers cuando el contenedor tiene focus
 * - Botón Ctrl+Alt+Del (SAS) en toolbar
 * - Throttle de mousemove a 60 eventos/s para no saturar el WebSocket
 * - Cursor personalizado (crosshair) indicando modo interactivo activo
 * - Prevención de defaults del browser para no interferir con input remoto
 *
 * Requirements: 6.1, 6.2, 6.3, 6.4, 6.6
 */

'use client'

import { useCallback, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { MousePointer2, ShieldAlert } from 'lucide-react'
import { StreamViewer } from './StreamViewer'
import type {
  RvInputMessage,
  KeyModifier,
  MouseButton,
} from '@/types/remote-view'

// ============================================================================
// TIPOS
// ============================================================================

interface InteractiveViewerProps {
  /** ID de la sesión activa */
  sessionId: string
  /** Último frame binario recibido del WebSocket */
  latestFrame: ArrayBuffer | null
  /** Indica si el tab está activo (false = pausado) */
  isActive: boolean
  /** Callback para enviar mensajes rv_input al WebSocket */
  onSendInput: (message: RvInputMessage) => void
}

// ============================================================================
// CONSTANTES
// ============================================================================

/** Intervalo mínimo entre eventos mousemove en ms (~60 eventos/s) */
const MOUSEMOVE_THROTTLE_MS = 16

// ============================================================================
// HELPERS
// ============================================================================

/**
 * Extrae los modificadores activos de un evento de mouse o teclado.
 */
function getModifiers(e: React.MouseEvent | React.KeyboardEvent): KeyModifier[] {
  const mods: KeyModifier[] = []
  if (e.ctrlKey) mods.push('ctrl')
  if (e.altKey) mods.push('alt')
  if (e.shiftKey) mods.push('shift')
  if (e.metaKey) mods.push('meta')
  return mods
}

/**
 * Mapea el botón del evento de mouse al formato del protocolo rv_input.
 */
function mapMouseButton(button: number): MouseButton {
  switch (button) {
    case 0: return 'left'
    case 1: return 'middle'
    case 2: return 'right'
    default: return 'left'
  }
}

/**
 * Normaliza coordenadas del mouse relativas al elemento contenedor (0.0–1.0).
 * Usa offsetX/offsetY del evento respecto a las dimensiones del target.
 */
function normalizeCoordinates(
  e: React.MouseEvent<HTMLDivElement>
): { x: number; y: number } {
  const rect = e.currentTarget.getBoundingClientRect()
  const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
  const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height))
  return { x, y }
}

// ============================================================================
// COMPONENTE PRINCIPAL
// ============================================================================

export function InteractiveViewer({
  sessionId,
  latestFrame,
  isActive,
  onSendInput,
}: InteractiveViewerProps) {
  const t = useTranslations('remoteView')

  // Estado: si el contenedor tiene focus (input activo)
  const [hasFocus, setHasFocus] = useState(false)

  // Referencia para throttle de mousemove
  const lastMoveTimeRef = useRef<number>(0)

  // ============================================================================
  // HANDLERS DE MOUSE
  // ============================================================================

  /**
   * Mousemove: throttled a 60/s, normaliza coordenadas y envía rv_input.
   */
  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!isActive) return

      const now = performance.now()
      if (now - lastMoveTimeRef.current < MOUSEMOVE_THROTTLE_MS) return
      lastMoveTimeRef.current = now

      const { x, y } = normalizeCoordinates(e)
      onSendInput({
        type: 'rv_input',
        session_id: sessionId,
        event: 'mousemove',
        x,
        y,
      })
    },
    [isActive, sessionId, onSendInput]
  )

  /**
   * Mousedown: normaliza coordenadas + botón y envía rv_input.
   */
  const handleMouseDown = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!isActive) return

      const { x, y } = normalizeCoordinates(e)
      onSendInput({
        type: 'rv_input',
        session_id: sessionId,
        event: 'mousedown',
        x,
        y,
        button: mapMouseButton(e.button),
      })
    },
    [isActive, sessionId, onSendInput]
  )

  /**
   * Mouseup: normaliza coordenadas + botón y envía rv_input.
   */
  const handleMouseUp = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!isActive) return

      const { x, y } = normalizeCoordinates(e)
      onSendInput({
        type: 'rv_input',
        session_id: sessionId,
        event: 'mouseup',
        x,
        y,
        button: mapMouseButton(e.button),
      })
    },
    [isActive, sessionId, onSendInput]
  )

  /**
   * Wheel: envía delta del scroll con coordenadas normalizadas.
   */
  const handleWheel = useCallback(
    (e: React.WheelEvent<HTMLDivElement>) => {
      if (!isActive) return
      e.preventDefault()

      const { x, y } = normalizeCoordinates(e as unknown as React.MouseEvent<HTMLDivElement>)
      onSendInput({
        type: 'rv_input',
        session_id: sessionId,
        event: 'wheel',
        x,
        y,
        delta: e.deltaY,
      })
    },
    [isActive, sessionId, onSendInput]
  )

  /**
   * ContextMenu: previene el menú contextual del browser para capturar right-click.
   */
  const handleContextMenu = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      e.preventDefault()
    },
    []
  )

  // ============================================================================
  // HANDLERS DE TECLADO
  // ============================================================================

  /**
   * KeyDown: extrae code, key, modifiers y envía rv_input.
   * Previene default para evitar shortcuts del browser.
   */
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (!isActive) return
      e.preventDefault()

      onSendInput({
        type: 'rv_input',
        session_id: sessionId,
        event: 'keydown',
        code: e.code,
        key: e.key,
        modifiers: getModifiers(e),
      })
    },
    [isActive, sessionId, onSendInput]
  )

  /**
   * KeyUp: extrae code, key, modifiers y envía rv_input.
   */
  const handleKeyUp = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (!isActive) return
      e.preventDefault()

      onSendInput({
        type: 'rv_input',
        session_id: sessionId,
        event: 'keyup',
        code: e.code,
        key: e.key,
        modifiers: getModifiers(e),
      })
    },
    [isActive, sessionId, onSendInput]
  )

  // ============================================================================
  // HANDLER SAS (Ctrl+Alt+Del)
  // ============================================================================

  /**
   * Envía el evento Secure Attention Sequence (Ctrl+Alt+Del) a la workstation.
   */
  const handleSendSas = useCallback(() => {
    if (!isActive) return
    onSendInput({
      type: 'rv_input',
      session_id: sessionId,
      event: 'sas',
    })
  }, [isActive, sessionId, onSendInput])

  // ============================================================================
  // HANDLERS DE FOCUS
  // ============================================================================

  const handleFocus = useCallback(() => setHasFocus(true), [])
  const handleBlur = useCallback(() => setHasFocus(false), [])

  // ============================================================================
  // RENDERIZADO
  // ============================================================================

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      {/* Toolbar interactiva */}
      <div className="flex items-center gap-3 px-4 h-10 bg-gray-800 border-b border-gray-700 flex-shrink-0">
        {/* Indicador de modo interactivo */}
        <div className="flex items-center gap-2">
          <MousePointer2 className="w-3.5 h-3.5 text-purple-400" />
          <span className="text-xs text-purple-400">
            {t('interactiveMode')}
          </span>
        </div>

        <div className="flex-1" />

        {/* Indicador de focus */}
        {!hasFocus && (
          <span className="text-xs text-gray-500 italic">
            {t('clickToFocus')}
          </span>
        )}

        {/* Botón Ctrl+Alt+Del */}
        <button
          type="button"
          onClick={handleSendSas}
          disabled={!isActive}
          className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium
            bg-red-900/40 text-red-300 border border-red-700/50 rounded
            hover:bg-red-900/60 hover:text-red-200
            disabled:opacity-50 disabled:cursor-not-allowed
            transition-colors"
          title={t('ctrlAltDelTooltip')}
        >
          <ShieldAlert className="w-3.5 h-3.5" />
          {t('ctrlAltDel')}
        </button>
      </div>

      {/* Contenedor de captura de input — envuelve el StreamViewer */}
      <div
        className={`flex-1 relative outline-none ${
          hasFocus ? 'cursor-crosshair' : 'cursor-pointer'
        } ${hasFocus ? 'ring-2 ring-purple-500/50 ring-inset' : ''}`}
        tabIndex={0}
        role="application"
        aria-label={t('interactiveVideoLabel')}
        onMouseMove={handleMouseMove}
        onMouseDown={handleMouseDown}
        onMouseUp={handleMouseUp}
        onWheel={handleWheel}
        onContextMenu={handleContextMenu}
        onKeyDown={handleKeyDown}
        onKeyUp={handleKeyUp}
        onFocus={handleFocus}
        onBlur={handleBlur}
      >
        {/* StreamViewer subyacente (muestra el video/imagen) */}
        <StreamViewer
          sessionId={sessionId}
          latestFrame={latestFrame}
          isActive={isActive}
        />
      </div>
    </div>
  )
}
