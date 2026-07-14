/**
 * Componente de sincronización bidireccional de clipboard entre el admin y la workstation.
 *
 * Funcionalidades:
 * - Al recibir texto desde la WS (direction=to_admin): escribe en el clipboard del browser
 *   usando navigator.clipboard.writeText() (no requiere user gesture para write)
 * - Botón "Pegar desde mi clipboard": lee del clipboard del browser con
 *   navigator.clipboard.readText() (requiere user gesture — el click del botón lo provee)
 *   y envía rv_clipboard con direction=to_ws
 * - Toast/notificación breve cuando el clipboard se sincroniza exitosamente
 * - Manejo de errores (permisos denegados, API no disponible)
 *
 * Requirements: 6.7
 */

'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { ClipboardPaste, Check, AlertCircle } from 'lucide-react'

// ============================================================================
// TIPOS
// ============================================================================

interface ClipboardSyncProps {
  /** ID de la sesión activa */
  sessionId: string
  /** Si la funcionalidad de clipboard está habilitada (clipboard_sharing_enabled de org config) */
  enabled: boolean
  /** Último texto recibido desde la WS (direction=to_admin) */
  incomingText: string | null
  /** Callback para enviar rv_clipboard con direction=to_ws */
  onSendClipboard: (text: string) => void
}

/** Estado del toast de notificación */
type ToastState = 'idle' | 'success' | 'error'

// ============================================================================
// CONSTANTES
// ============================================================================

/** Duración del toast en milisegundos */
const TOAST_DURATION_MS = 2500

// ============================================================================
// COMPONENTE PRINCIPAL
// ============================================================================

export function ClipboardSync({
  sessionId,
  enabled,
  incomingText,
  onSendClipboard,
}: ClipboardSyncProps) {
  const t = useTranslations('remoteView')

  // Estado del toast de notificación
  const [toastState, setToastState] = useState<ToastState>('idle')
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Referencia al último texto procesado (para evitar re-procesar el mismo)
  const lastProcessedTextRef = useRef<string | null>(null)

  // ============================================================================
  // EFECTO: Escribir clipboard al recibir texto de la WS (direction=to_admin)
  // ============================================================================

  useEffect(() => {
    if (!enabled || !incomingText || incomingText === lastProcessedTextRef.current) {
      return
    }

    // Marcar como procesado antes de escribir (evita doble-procesado)
    lastProcessedTextRef.current = incomingText

    // navigator.clipboard.writeText no requiere user gesture
    navigator.clipboard.writeText(incomingText)
      .then(() => {
        showToast('success')
      })
      .catch(() => {
        showToast('error')
      })
  }, [enabled, incomingText]) // eslint-disable-line react-hooks/exhaustive-deps

  // ============================================================================
  // HELPERS
  // ============================================================================

  /**
   * Muestra un toast temporal con el estado indicado.
   */
  const showToast = useCallback((state: ToastState) => {
    // Limpiar timer anterior si existe
    if (toastTimerRef.current) {
      clearTimeout(toastTimerRef.current)
    }

    setToastState(state)
    toastTimerRef.current = setTimeout(() => {
      setToastState('idle')
      toastTimerRef.current = null
    }, TOAST_DURATION_MS)
  }, [])

  // Cleanup del timer al desmontar
  useEffect(() => {
    return () => {
      if (toastTimerRef.current) {
        clearTimeout(toastTimerRef.current)
      }
    }
  }, [])

  // ============================================================================
  // HANDLER: Leer clipboard del browser y enviar a WS
  // ============================================================================

  /**
   * Lee el clipboard del browser (requiere user gesture — el click del botón lo provee)
   * y envía el contenido via rv_clipboard con direction=to_ws.
   */
  const handlePasteFromClipboard = useCallback(async () => {
    if (!enabled) return

    try {
      const text = await navigator.clipboard.readText()
      if (text) {
        onSendClipboard(text)
        showToast('success')
      }
    } catch {
      showToast('error')
    }
  }, [enabled, onSendClipboard, showToast])

  // ============================================================================
  // RENDERIZADO
  // ============================================================================

  // No renderizar nada si el clipboard sharing está deshabilitado
  if (!enabled) return null

  return (
    <div className="relative flex items-center" data-session-id={sessionId}>
      {/* Botón "Pegar desde mi clipboard" */}
      <button
        type="button"
        onClick={handlePasteFromClipboard}
        className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium
          bg-gray-700 text-gray-200 border border-gray-600 rounded
          hover:bg-gray-600 hover:text-white
          transition-colors"
        title={t('pasteFromClipboard')}
        aria-label={t('pasteFromClipboard')}
      >
        <ClipboardPaste className="w-3.5 h-3.5" />
        {t('pasteFromClipboard')}
      </button>

      {/* Toast de notificación (absoluto relativo al contenedor) */}
      {toastState !== 'idle' && (
        <div
          className={`absolute top-full left-0 mt-1 z-10 flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded shadow-lg whitespace-nowrap
            ${toastState === 'success'
              ? 'bg-green-900/90 text-green-200 border border-green-700/50'
              : 'bg-red-900/90 text-red-200 border border-red-700/50'
            }`}
          role="status"
          aria-live="polite"
        >
          {toastState === 'success' ? (
            <>
              <Check className="w-3.5 h-3.5" />
              {t('clipboardSynced')}
            </>
          ) : (
            <>
              <AlertCircle className="w-3.5 h-3.5" />
              {t('clipboardError')}
            </>
          )}
        </div>
      )}
    </div>
  )
}
