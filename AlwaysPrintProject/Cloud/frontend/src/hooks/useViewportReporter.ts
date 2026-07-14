/**
 * Hook que reporta las dimensiones del viewport del contenedor del visor remoto.
 * Envía viewport_width/height al iniciar la sesión y al redimensionar (1s debounce).
 * Utiliza ResizeObserver para detectar cambios de tamaño del contenedor.
 *
 * Nunca realiza upscale — solo reporta dimensiones reales del contenedor.
 *
 * Requirements: 5.8
 */

'use client'

import { useCallback, useEffect, useRef } from 'react'

// ============================================================================
// TIPOS
// ============================================================================

export interface UseViewportReporterOptions {
  /** Si el reporte de viewport está habilitado (depende de org config viewport_adaptive_downscale) */
  enabled: boolean
  /** ID de la sesión para incluir en el mensaje de configuración */
  sessionId: string
  /** Referencia al elemento contenedor del visor */
  containerRef: React.RefObject<HTMLElement | null>
  /** Callback invocado con las dimensiones del viewport al cambiar */
  onViewportChange: (width: number, height: number) => void
  /** Delay de debounce en ms (por defecto: 1000) */
  debounceMs?: number
}

// ============================================================================
// CONSTANTES
// ============================================================================

/** Delay por defecto de debounce para el resize (1 segundo) */
const DEFAULT_DEBOUNCE_MS = 1000

// ============================================================================
// HOOK PRINCIPAL
// ============================================================================

export function useViewportReporter({
  enabled,
  sessionId,
  containerRef,
  onViewportChange,
  debounceMs = DEFAULT_DEBOUNCE_MS,
}: UseViewportReporterOptions): void {
  // Referencia al timeout de debounce para poder cancelarlo
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Referencia estable al callback para evitar re-suscripciones innecesarias del observer
  const onViewportChangeRef = useRef(onViewportChange)
  onViewportChangeRef.current = onViewportChange

  // Últimas dimensiones reportadas para evitar envíos duplicados
  const lastReportedRef = useRef<{ width: number; height: number }>({ width: 0, height: 0 })

  // Referencia al sessionId para evitar re-suscripciones innecesarias
  const sessionIdRef = useRef(sessionId)
  sessionIdRef.current = sessionId

  /**
   * Reporta las dimensiones si son distintas a las últimas reportadas.
   * Ignora dimensiones de 0 (elemento no visible o no montado).
   */
  const reportDimensions = useCallback((width: number, height: number) => {
    // No reportar dimensiones 0 (elemento oculto o no montado)
    if (width <= 0 || height <= 0) return

    // Redondear a enteros (las dimensiones CSS pueden ser decimales)
    const roundedWidth = Math.round(width)
    const roundedHeight = Math.round(height)

    // No reportar si las dimensiones no cambiaron
    if (
      lastReportedRef.current.width === roundedWidth &&
      lastReportedRef.current.height === roundedHeight
    ) {
      return
    }

    lastReportedRef.current = { width: roundedWidth, height: roundedHeight }
    onViewportChangeRef.current(roundedWidth, roundedHeight)
  }, [])

  /**
   * Maneja el resize con debounce.
   * Cancela el timer anterior y programa uno nuevo con el delay configurado.
   */
  const handleResize = useCallback(
    (width: number, height: number) => {
      // Cancelar timer previo
      if (debounceTimerRef.current !== null) {
        clearTimeout(debounceTimerRef.current)
      }

      // Programar nuevo reporte con debounce
      debounceTimerRef.current = setTimeout(() => {
        reportDimensions(width, height)
        debounceTimerRef.current = null
      }, debounceMs)
    },
    [debounceMs, reportDimensions]
  )

  useEffect(() => {
    // No hacer nada si está deshabilitado o no hay contenedor
    if (!enabled) return

    const container = containerRef.current
    if (!container) return

    // Reportar dimensiones iniciales inmediatamente (sin debounce)
    const initialWidth = container.clientWidth
    const initialHeight = container.clientHeight
    reportDimensions(initialWidth, initialHeight)

    // Crear ResizeObserver para detectar cambios de tamaño
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        // Usar contentBoxSize si está disponible, sino clientWidth/Height
        let width: number
        let height: number

        if (entry.contentBoxSize && entry.contentBoxSize.length > 0) {
          const boxSize = entry.contentBoxSize[0]
          width = boxSize.inlineSize
          height = boxSize.blockSize
        } else {
          // Fallback para navegadores antiguos
          width = entry.contentRect.width
          height = entry.contentRect.height
        }

        handleResize(width, height)
      }
    })

    observer.observe(container)

    // Limpieza: desconectar observer y cancelar timer pendiente
    return () => {
      observer.disconnect()

      if (debounceTimerRef.current !== null) {
        clearTimeout(debounceTimerRef.current)
        debounceTimerRef.current = null
      }
    }
  }, [enabled, containerRef, handleResize, reportDimensions])
}
