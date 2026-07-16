/**
 * Visor de streaming con WebSocket dedicado y worker affinity.
 *
 * Abre una conexión WS propia a /ws/rv-stream y reintenta hasta
 * aterrizar en el mismo worker donde está la workstation. Una vez
 * conectado al worker correcto, recibe push tiles directamente
 * sin intermediario Redis (baja latencia, alta frecuencia).
 *
 * Fallback: si no hay targetWorkerId, usa el polling adaptativo
 * a través del WS principal del operador (compatible con versiones
 * anteriores del backend).
 *
 * Requirements: 5.4
 */

'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { useTranslations } from 'next-intl'
import { Video, Wifi, WifiOff } from 'lucide-react'

// ============================================================================
// TIPOS
// ============================================================================

export interface DeltaTile {
  x: number
  y: number
  w: number
  h: number
  data: string
}

interface DeltaStreamViewerProps {
  sessionId: string
  isActive: boolean
  latestKeyframe: { data: string; width: number; height: number } | null
  latestDelta: { tiles: DeltaTile[]; width: number; height: number } | null
  onRequestFrame?: () => void
  targetWorkerId?: string
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
  targetWorkerId,
}: DeltaStreamViewerProps) {
  const t = useTranslations('remoteView')
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [canvasReady, setCanvasReady] = useState(false)
  const [frameCount, setFrameCount] = useState(0)
  const [fps, setFps] = useState(0)
  const [isStale, setIsStale] = useState(false)
  const [streamConnected, setStreamConnected] = useState(false)
  const [affinityAttempts, setAffinityAttempts] = useState(0)
  const lastFpsTimeRef = useRef(performance.now())
  const frameCountSinceLastFps = useRef(0)
  const lastFrameReceivedRef = useRef(performance.now())
  const canvasDimensionsRef = useRef({ width: 0, height: 0 })
  const streamWsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  // Obtener token JWT de localStorage
  const getToken = useCallback(() => {
    if (typeof window === 'undefined') return null
    return localStorage.getItem('access_token')
  }, [])

  // Dibujar keyframe en el canvas
  const drawKeyframe = useCallback((data: string, width: number, height: number) => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const img = new Image()
    img.onload = () => {
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width
        canvas.height = height
        canvasDimensionsRef.current = { width, height }
      }
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      setCanvasReady(true)
      setFrameCount((c) => c + 1)
      frameCountSinceLastFps.current++
      lastFrameReceivedRef.current = performance.now()
    }
    img.src = `data:image/jpeg;base64,${data}`
  }, [])

  // Dibujar delta tiles en el canvas
  const drawDelta = useCallback((tiles: DeltaTile[]) => {
    const canvas = canvasRef.current
    if (!canvas || !canvasReady) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let tilesDrawn = 0
    const totalTiles = tiles.length
    for (const tile of tiles) {
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
  }, [canvasReady])

  // Contador de FPS + detección de stale
  useEffect(() => {
    const interval = setInterval(() => {
      const now = performance.now()
      const elapsed = (now - lastFpsTimeRef.current) / 1000
      if (elapsed > 0) {
        setFps(Math.round(frameCountSinceLastFps.current / elapsed))
        frameCountSinceLastFps.current = 0
        lastFpsTimeRef.current = now

        const timeSinceLastFrame = now - lastFrameReceivedRef.current
        setIsStale(canvasReady && timeSinceLastFrame > 12000)
      }
    }, 1000)
    return () => clearInterval(interval)
  }, [canvasReady])

  // === WebSocket dedicado con worker affinity ===
  useEffect(() => {
    if (!isActive || !targetWorkerId) return

    mountedRef.current = true
    let ws: WebSocket | null = null
    let closed = false

    const connect = () => {
      if (closed || !mountedRef.current) return

      const token = getToken()
      if (!token) return

      // Construir URL del WS dedicado
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const host = window.location.host
      const url = `${protocol}//${host}/ws/rv-stream?session=${sessionId}&token=${token}`

      ws = new WebSocket(url)
      streamWsRef.current = ws

      ws.onopen = () => {
        // Esperamos el mensaje rv_stream_connected con worker_id
      }

      ws.onmessage = (event) => {
        if (closed || !mountedRef.current) return

        try {
          const msg = JSON.parse(event.data)

          if (msg.type === 'rv_stream_connected') {
            // Verificar worker affinity
            if (msg.worker_id === targetWorkerId) {
              // Estamos en el worker correcto
              setStreamConnected(true)
              setAffinityAttempts(0)
            } else {
              // Worker incorrecto — cerrar y reintentar
              setAffinityAttempts((a) => a + 1)
              ws?.close()
              reconnectTimerRef.current = setTimeout(connect, 200)
            }
            return
          }

          if (msg.type === 'rv_frame') {
            // Procesar frame recibido directamente del worker
            if (msg.data) {
              // Keyframe
              drawKeyframe(msg.data, msg.width, msg.height)
            } else if (msg.tiles && Array.isArray(msg.tiles)) {
              // Delta tiles
              drawDelta(msg.tiles)
            }
            return
          }

          if (msg.type === 'pong') {
            // Heartbeat response — ignorar
            return
          }
        } catch {
          // Mensaje no-JSON, ignorar
        }
      }

      ws.onclose = () => {
        streamWsRef.current = null
        setStreamConnected(false)

        // Reconectar solo si no fue cierre voluntario
        if (!closed && mountedRef.current) {
          reconnectTimerRef.current = setTimeout(connect, 1000)
        }
      }

      ws.onerror = () => {
        // onclose se disparará después
      }
    }

    connect()

    return () => {
      closed = true
      mountedRef.current = false
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      if (ws && ws.readyState <= WebSocket.OPEN) {
        ws.close()
      }
      streamWsRef.current = null
      setStreamConnected(false)
    }
  }, [isActive, targetWorkerId, sessionId, getToken, drawKeyframe, drawDelta])

  // Heartbeat (rv_viewer_alive) cada 3s por el stream WS
  useEffect(() => {
    if (!streamConnected) return

    const interval = setInterval(() => {
      const ws = streamWsRef.current
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'rv_viewer_alive', session_id: sessionId }))
      }
    }, 3000)

    return () => clearInterval(interval)
  }, [streamConnected, sessionId])

  // Polling fallback: si no hay stream WS (sin targetWorkerId) o si no llegan frames
  useEffect(() => {
    if (!onRequestFrame || !isActive) return

    const pollInterval = setInterval(() => {
      const timeSinceLastFrame = performance.now() - lastFrameReceivedRef.current
      if (timeSinceLastFrame > 5000) {
        // Si tenemos stream WS conectado, enviar request por ahí
        const ws = streamWsRef.current
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'rv_request_frame', session_id: sessionId }))
        } else {
          // Fallback al WS del operador
          onRequestFrame()
        }
      }
    }, 5000)

    return () => clearInterval(pollInterval)
  }, [onRequestFrame, isActive, sessionId])

  // Dibujar keyframe recibido via props (fallback desde operator WS)
  useEffect(() => {
    if (!latestKeyframe || !isActive || streamConnected) return
    drawKeyframe(latestKeyframe.data, latestKeyframe.width, latestKeyframe.height)
  }, [latestKeyframe, isActive, streamConnected, drawKeyframe])

  // Dibujar delta recibido via props (fallback desde operator WS)
  useEffect(() => {
    if (!latestDelta || !isActive || !canvasReady || streamConnected) return
    drawDelta(latestDelta.tiles)
  }, [latestDelta, isActive, canvasReady, streamConnected, drawDelta])

  // Solicitar primer frame al montar (para obtener keyframe base)
  useEffect(() => {
    if (!isActive) return

    // Solicitar frame inicial después de un breve delay
    const timer = setTimeout(() => {
      const ws = streamWsRef.current
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'rv_request_frame', session_id: sessionId }))
      } else if (onRequestFrame) {
        onRequestFrame()
      }
    }, 500)

    return () => clearTimeout(timer)
  }, [isActive, sessionId, onRequestFrame])

  // ============================================================================
  // RENDER
  // ============================================================================

  if (!canvasReady && !latestKeyframe && !streamConnected) {
    return (
      <div className="flex flex-col flex-1 items-center justify-center bg-gray-900 gap-3">
        <Video className="w-8 h-8 text-gray-500 animate-pulse" />
        <span className="text-sm text-gray-400">
          {targetWorkerId && !streamConnected
            ? `${t('streamConnectingWorker')}${affinityAttempts > 0 ? ` (${affinityAttempts})` : ''}`
            : t('streamWaitingData')}
        </span>
      </div>
    )
  }

  return (
    <div className="flex flex-col flex-1 bg-gray-900 overflow-hidden">
      <div className="flex-1 flex items-center justify-center overflow-hidden p-2 relative">
        <canvas
          ref={canvasRef}
          className="max-w-full max-h-full object-contain"
          style={{ imageRendering: 'auto' }}
          aria-label={t('streamVideoLabel')}
        />

        {isStale && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/40 z-10">
            <div className="flex flex-col items-center gap-2">
              <div className="w-6 h-6 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
              <span className="text-sm text-amber-300 font-medium">{t('streamReconnecting')}</span>
            </div>
          </div>
        )}
      </div>

      {/* Barra de estado */}
      <div className="flex items-center gap-3 px-4 h-10 bg-gray-800 border-t border-gray-700 flex-shrink-0">
        <div className="flex items-center gap-2">
          {streamConnected ? (
            <Wifi className="w-3.5 h-3.5 text-green-400" />
          ) : (
            <WifiOff className={`w-3.5 h-3.5 ${isStale ? 'text-amber-400' : 'text-gray-400'}`} />
          )}
          <span className={`text-xs ${streamConnected ? 'text-green-400' : isStale ? 'text-amber-400' : 'text-gray-400'}`}>
            {streamConnected
              ? t('streamDirect')
              : isStale
                ? t('streamReconnecting')
                : t('streamActive')}
          </span>
        </div>

        <div className="w-px h-5 bg-gray-600" />

        <span className="text-xs text-gray-400 tabular-nums">
          {fps > 0 ? `${fps} FPS` : !isStale ? `1/${5}s` : '—'}
        </span>

        <div className="flex-1" />

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
