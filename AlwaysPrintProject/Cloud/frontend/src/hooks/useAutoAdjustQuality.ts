/**
 * Hook para ajuste automático de calidad basado en RTT.
 *
 * Mide el RTT de cada frame (tiempo entre envío de rv_request_frame
 * y recepción de rv_frame) y cada 5 frames evalúa si debe subir
 * o bajar el nivel de calidad.
 *
 * Niveles (de mayor a menor calidad):
 *   Level 4: 1920×1080, quality=80%
 *   Level 3: 1280×720,  quality=70% ← DEFAULT
 *   Level 2: 854×480,   quality=60%
 *   Level 1: 640×360,   quality=50%
 *
 * Algoritmo (ejecutado cada 5 frames):
 *   avg_rtt = promedio RTT de los últimos 5 frames
 *   Si avg_rtt > 2000ms → bajar 1 nivel (min: Level 1)
 *   Si avg_rtt < 500ms  → subir 1 nivel (max: Level 4)
 *   Si avg_rtt entre 500-2000ms → mantener nivel actual
 *
 * Requirements: 4.9
 */

'use client'

import { useCallback, useRef, useState } from 'react'

// ============================================================================
// TIPOS
// ============================================================================

/** Representa un nivel de calidad de captura */
export interface QualityLevel {
  /** Número de nivel (1-4) */
  level: number
  /** Etiqueta de resolución */
  resolution: string
  /** Porcentaje de calidad JPEG */
  quality: number
  /** Ancho en píxeles */
  width: number
  /** Alto en píxeles */
  height: number
}

/** Opciones para configurar el hook */
export interface UseAutoAdjustQualityOptions {
  /** Solo activo cuando quality_mode=auto */
  enabled: boolean
  /** Callback para enviar remote_view_config con nueva resolución y calidad */
  onConfigChange: (resolution: string, quality: number) => void
}

/** Valores de retorno del hook */
export interface UseAutoAdjustQualityReturn {
  /** Nivel de calidad actual */
  currentLevel: QualityLevel
  /** Llamar cuando se envía rv_request_frame */
  recordRequestSent: () => void
  /** Llamar cuando se recibe rv_frame */
  recordFrameReceived: () => void
  /** Último avg RTT calculado en ms (para debug/display) */
  avgRtt: number
}

// ============================================================================
// CONSTANTES
// ============================================================================

/** Definición de los 4 niveles de calidad ordenados de menor a mayor */
const QUALITY_LEVELS: QualityLevel[] = [
  { level: 1, resolution: '360p', quality: 50, width: 640, height: 360 },
  { level: 2, resolution: '480p', quality: 60, width: 854, height: 480 },
  { level: 3, resolution: '720p', quality: 70, width: 1280, height: 720 },
  { level: 4, resolution: '1080p', quality: 80, width: 1920, height: 1080 },
]

/** Índice del nivel inicial (Level 3 = 720p/70%) */
const DEFAULT_LEVEL_INDEX = 2

/** Cantidad de frames para evaluar el RTT promedio */
const FRAMES_PER_EVALUATION = 5

/** Umbral superior: si avg RTT > este valor → bajar nivel */
const RTT_THRESHOLD_HIGH_MS = 2000

/** Umbral inferior: si avg RTT < este valor → subir nivel */
const RTT_THRESHOLD_LOW_MS = 500

// ============================================================================
// HOOK
// ============================================================================

/**
 * Hook que implementa el auto-ajuste de calidad basado en RTT.
 *
 * Uso:
 * ```tsx
 * const { currentLevel, recordRequestSent, recordFrameReceived, avgRtt } =
 *   useAutoAdjustQuality({
 *     enabled: qualityMode === 'auto',
 *     onConfigChange: (resolution, quality) => {
 *       // Enviar remote_view_config al backend
 *     },
 *   })
 *
 * // Al enviar rv_request_frame:
 * recordRequestSent()
 *
 * // Al recibir rv_frame:
 * recordFrameReceived()
 * ```
 */
export function useAutoAdjustQuality(
  options: UseAutoAdjustQualityOptions
): UseAutoAdjustQualityReturn {
  const { enabled, onConfigChange } = options

  // Estado del nivel actual (índice en QUALITY_LEVELS)
  const [levelIndex, setLevelIndex] = useState(DEFAULT_LEVEL_INDEX)
  const [avgRtt, setAvgRtt] = useState(0)

  // Refs para tracking interno (no necesitan re-render)
  const requestTimestampRef = useRef<number>(0)
  const rttBufferRef = useRef<number[]>([])

  // Ref estable para onConfigChange (evitar dependencia en useCallback)
  const onConfigChangeRef = useRef(onConfigChange)
  onConfigChangeRef.current = onConfigChange

  // Ref estable para enabled
  const enabledRef = useRef(enabled)
  enabledRef.current = enabled

  /**
   * Registra el timestamp de envío de un rv_request_frame.
   * Llamar inmediatamente antes o después de enviar el request.
   */
  const recordRequestSent = useCallback(() => {
    if (!enabledRef.current) return
    requestTimestampRef.current = performance.now()
  }, [])

  /**
   * Registra la recepción de un rv_frame y calcula RTT.
   * Si se han acumulado 5 mediciones, evalúa y ajusta el nivel.
   */
  const recordFrameReceived = useCallback(() => {
    if (!enabledRef.current) return

    const sentAt = requestTimestampRef.current
    if (sentAt === 0) return // No hay request pendiente registrado

    const rtt = performance.now() - sentAt
    requestTimestampRef.current = 0 // Reset para evitar doble conteo

    // Agregar RTT al buffer
    const buffer = rttBufferRef.current
    buffer.push(rtt)

    // Evaluar solo cuando tenemos exactamente FRAMES_PER_EVALUATION mediciones
    if (buffer.length >= FRAMES_PER_EVALUATION) {
      const sum = buffer.reduce((acc, val) => acc + val, 0)
      const avg = sum / buffer.length
      setAvgRtt(Math.round(avg))

      // Limpiar buffer para nuevo ciclo de medición
      rttBufferRef.current = []

      // Determinar nuevo nivel
      setLevelIndex((currentIndex) => {
        let newIndex = currentIndex

        if (avg > RTT_THRESHOLD_HIGH_MS && currentIndex > 0) {
          // RTT alto → bajar nivel (menor calidad)
          newIndex = currentIndex - 1
        } else if (avg < RTT_THRESHOLD_LOW_MS && currentIndex < QUALITY_LEVELS.length - 1) {
          // RTT bajo → subir nivel (mayor calidad)
          newIndex = currentIndex + 1
        }

        // Notificar cambio solo si efectivamente cambió
        if (newIndex !== currentIndex) {
          const newLevel = QUALITY_LEVELS[newIndex]
          onConfigChangeRef.current(
            `${newLevel.width}x${newLevel.height}`,
            newLevel.quality
          )
        }

        return newIndex
      })
    }
  }, [])

  return {
    currentLevel: QUALITY_LEVELS[levelIndex],
    recordRequestSent,
    recordFrameReceived,
    avgRtt,
  }
}
