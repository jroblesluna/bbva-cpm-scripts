/**
 * Visor de streaming basado en Canvas que compone keyframes y delta tiles.
 *
 * La TileStreamEngine del Tray envía dos tipos de rv_frame:
 * 1. Keyframe (frame_type="keyframe"): JPEG completo → dibuja todo el canvas
 * 2. Delta (frame_type="delta"): Array de tiles cambiados → dibuja solo esos tiles
 *
 * El canvas se mantiene persistente y se pinta incrementalmente:
 * - En keyframe: decodifica JPEG → drawImage para llenar todo el canvas
 * - En delta: por cada tile, decodifica su JPEG → drawImage en (x, y) con (w, h)
 *
 * Resultado: streaming real a ~5 FPS con bajo consumo de ancho de banda.
 *
 * Requirements: 5.4
 */

'use client'

import { useEffect, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { Video } from 'lucide-react'

// ============================================================================
// TIPOS
// ============================================================================

/** Tile individual dentro de un delta frame */
export interface DeltaTile {
  x: number
  y: number
  w: number
  h: number
  data: string // base64 JPEG
}

interface DeltaStreamViewerProps {
  /** ID de la sesión activa */
  sessionId: string
  /** Si el tab que contiene este viewer está activo */
  isActive: boolean
  /** Último keyframe recibido (imagen JPEG completa) — null si aún no hay */
  latestKeyframe: { data: string; width: number; height: number } | null
  /** Último delta frame recibido (array de tiles cambiados) — null si no hay */
  latestDelta: { tiles: DeltaTile[]; width: number; height: number } | null
  /** Solicitar un frame al montar para obtener imagen base inmediata */
  onRequestFrame?: () => void
}

// ============================================================================
// COMPONENTE PRINCIPAL
// ============================================================================

export function DeltaStreamViewer({
  sessionId,
  isActive,
  latestKeyframe,
  latestDelta,
  onRequestFrame,
}: DeltaStreamViewerProps) {
  const t = useTranslations('remoteView')
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [canvasReady, setCanvasReady] = useState(false)
  const [frameCount, setFrameCount] = useState(0)
  const [fps, setFps] = useState(0)
  const [isStale, setIsStale] = useState(false)
  const lastFpsTimeRef = useRef(performance.now())
  const frameCountSinceLastFps = useRef(0)
  const lastFrameReceivedRef = useRef(performance.now())
  const canvasDimensionsRef = useRef({ width: 0, height: 0 })

  // Contador de FPS + detección de stale (actualiza cada segundo)
  useEffect(() => {
    const interval = setInterval(() => {
      const now = performance.now()
      const elapsed = (now - lastFpsTimeRef.current) / 1000
      if (elapsed > 0) {
        setFps(Math.round(frameCountSinceLastFps.current / elapsed))
        frameCountSinceLastFps.current = 0
        lastFpsTimeRef.current = now

        // Detectar si no llegan frames por más de 3s
        const timeSinceLastFrame = now - lastFrameReceivedRef.current
        setIsStale(canvasReady && timeSinceLastFrame > 3000)
      }
    }, 1000)
    return () => clearInterval(interval)
  }, [canvasReady])

  // Solicitar un frame al montar para obtener imagen base inmediata
  // (el TileStreamEngine pudo haber enviado su keyframe antes de que este componente montara)
  useEffect(() => {
    if (onRequestFrame && isActive) {
      onRequestFrame()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Polling periódico: solicitar frame cada 1s como fallback confiable.
  // El push (TileStreamEngine via Redis pub/sub) puede fallar por cross-worker routing.
  // El request/response (rv_request_frame → rv_frame) funciona siempre.
  useEffect(() => {
    if (!onRequestFrame || !isActive) return

    const pollInterval = setInterval(() => {
      onRequestFrame()
    }, 1000)

    return () => clearInterval(pollInterval)
  }, [onRequestFrame, isActive])

  // Dibujar keyframe en el canvas
  useEffect(() => {
    if (!latestKeyframe || !isActive) return
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const img = new Image()
    img.onload = () => {
      // Redimensionar canvas si las dimensiones cambiaron
      if (canvas.width !== latestKeyframe.width || canvas.height !== latestKeyframe.height) {
        canvas.width = latestKeyframe.width
        canvas.height = latestKeyframe.height
        canvasDimensionsRef.current = { width: latestKeyframe.width, height: latestKeyframe.height }
      }
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      setCanvasReady(true)
      setFrameCount((c) => c + 1)
      frameCountSinceLastFps.current++
      lastFrameReceivedRef.current = performance.now()
    }
    img.src = `data:image/jpeg;base64,${latestKeyframe.data}`
  }, [latestKeyframe, isActive])

  // Dibujar delta tiles en el canvas
  useEffect(() => {
    if (!latestDelta || !isActive || !canvasReady) return
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // Dibujar cada tile en su posición
    let tilesDrawn = 0
    const totalTiles = latestDelta.tiles.length
    for (const tile of latestDelta.tiles) {
      const tileImg = new Image()
      tileImg.onload = () => {
        ctx.drawImage(tileImg, tile.x, tile.y, tile.w, tile.h)
        tilesDrawn++
        if (tilesDrawn === totalTiles) {
          setFrameCount((c) => c + 1)
          frameCountSinceLastFps.current++
          lastFrameReceivedRef.current = performance.now()
        }
      }
      tileImg.src = `data:image/jpeg;base64,${tile.data}`
    }
  }, [latestDelta, isActive, canvasReady])

  // ============================================================================
  // RENDER
  // ============================================================================

  // Estado de espera: no hay keyframe aún
  if (!canvasReady && !latestKeyframe) {
    return (
      <div className="flex flex-col flex-1 items-center justify-center bg-gray-900 gap-3">
        <Video className="w-8 h-8 text-gray-500 animate-pulse" />
        <span className="text-sm text-gray-400">{t('streamWaitingData')}</span>
      </div>
    )
  }

  return (
    <div className="flex flex-col flex-1 bg-gray-900 overflow-hidden">
      {/* Área del canvas */}
      <div className="flex-1 flex items-center justify-center overflow-hidden p-2 relative">
        <canvas
          ref={canvasRef}
          className="max-w-full max-h-full object-contain"
          style={{ imageRendering: 'auto' }}
          aria-label={t('streamVideoLabel')}
        />

        {/* Overlay de reconexión cuando no llegan frames */}
        {isStale && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/40 z-10">
            <div className="flex flex-col items-center gap-2">
              <div className="w-6 h-6 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
              <span className="text-sm text-amber-300 font-medium">{t('streamReconnecting')}</span>
            </div>
          </div>
        )}
      </div>

      {/* Barra de estado inferior */}
      <div className="flex items-center gap-3 px-4 h-10 bg-gray-800 border-t border-gray-700 flex-shrink-0">
        <div className="flex items-center gap-2">
          <Video className={`w-3.5 h-3.5 ${isStale ? 'text-amber-400' : 'text-green-400'}`} />
          <span className={`text-xs ${isStale ? 'text-amber-400' : 'text-green-400'}`}>
            {isStale ? t('streamReconnecting') : t('streamActive')}
          </span>
        </div>

        <div className="w-px h-5 bg-gray-600" />

        {/* Indicador de FPS */}
        <span className="text-xs text-gray-400 tabular-nums">{fps} FPS</span>

        <div className="flex-1" />

        {/* Dimensiones + contador de frames */}
        {canvasDimensionsRef.current.width > 0 && (
          <span className="text-xs text-gray-500 tabular-nums">
            {t('frameDimensions', {
              width: canvasDimensionsRef.current.width,
              height: canvasDimensionsRef.current.height,
            })}{' '}
            | #{frameCount}
          </span>
        )}
      </div>
    </div>
  )
}
