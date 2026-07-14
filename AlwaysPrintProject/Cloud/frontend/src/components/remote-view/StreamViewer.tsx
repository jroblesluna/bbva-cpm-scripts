/**
 * Visor de stream H.264 usando Media Source Extensions (MSE).
 * Decodifica frames binarios recibidos por WebSocket y los muestra en un `<video>`.
 *
 * Funcionalidades:
 * - MediaSource + SourceBuffer con codec H.264 Baseline (avc1.42E01E)
 * - Parseo de header binario de 9 bytes (session_hash + flags + width + height)
 * - Append de NAL units al SourceBuffer (wrapped en fMP4 — TODO: mux.js cuando H.264 real)
 * - Manejo de buffer overflow: elimina segmentos antiguos si buffered > 5s
 * - Fallback a visualización de imagen si MSE no puede decodificar (datos JPEG placeholder)
 * - Muestra en <video autoplay muted> sin controles nativos
 *
 * Requirements: 5.4
 */

'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { useTranslations } from 'next-intl'
import { Video, ImageIcon, AlertTriangle } from 'lucide-react'
import {
  parseFrameHeader,
  isJpegPayload,
  isMseSupported,
  MSE_CODEC,
  MAX_BUFFER_SECONDS,
} from './stream-utils'

// ============================================================================
// TIPOS
// ============================================================================

interface StreamViewerProps {
  /** ID de la sesión activa */
  sessionId: string
  /** Último frame binario recibido del WebSocket (ArrayBuffer completo con header) */
  latestFrame: ArrayBuffer | null
  /** Indica si el tab está activo (false = pausado) */
  isActive: boolean
}

/** Modo de renderizado actual */
type RenderMode = 'mse' | 'image' | 'unsupported'

// ============================================================================
// COMPONENTE PRINCIPAL
// ============================================================================

export function StreamViewer({
  sessionId,
  latestFrame,
  isActive,
}: StreamViewerProps) {
  const t = useTranslations('remoteView')

  // Referencias
  const videoRef = useRef<HTMLVideoElement>(null)
  const mediaSourceRef = useRef<MediaSource | null>(null)
  const sourceBufferRef = useRef<SourceBuffer | null>(null)
  const pendingBuffersRef = useRef<Uint8Array[]>([])
  const objectUrlRef = useRef<string | null>(null)

  // Tracking de resolución previa para detectar cambios en vivo (Req 5.8, 5.9, 5.10)
  const previousWidthRef = useRef<number>(0)
  const previousHeightRef = useRef<number>(0)

  // Estado
  const [renderMode, setRenderMode] = useState<RenderMode>('mse')
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [frameWidth, setFrameWidth] = useState(0)
  const [frameHeight, setFrameHeight] = useState(0)
  const [isBuffering, setIsBuffering] = useState(true)

  // Verificar soporte MSE al montar
  useEffect(() => {
    if (!isMseSupported()) {
      setRenderMode('unsupported')
    }
  }, [])

  // Inicializar MediaSource cuando estamos en modo MSE y el componente está activo
  useEffect(() => {
    if (renderMode !== 'mse' || !isActive) return

    const video = videoRef.current
    if (!video) return

    const mediaSource = new MediaSource()
    mediaSourceRef.current = mediaSource

    const url = URL.createObjectURL(mediaSource)
    objectUrlRef.current = url
    video.src = url

    const handleSourceOpen = () => {
      try {
        const sourceBuffer = mediaSource.addSourceBuffer(MSE_CODEC)
        sourceBufferRef.current = sourceBuffer

        // Procesar buffers pendientes cuando el SourceBuffer termine de actualizar
        sourceBuffer.addEventListener('updateend', () => {
          flushPendingBuffers()
        })

        // Manejar errores del SourceBuffer
        sourceBuffer.addEventListener('error', () => {
          // Si MSE falla (codec incompatible con datos reales), cambiar a fallback imagen
          setRenderMode('image')
        })

        setIsBuffering(false)
      } catch {
        // Si el codec no es soportado, cambiar a modo imagen
        setRenderMode('image')
      }
    }

    mediaSource.addEventListener('sourceopen', handleSourceOpen)

    return () => {
      // Limpieza al desmontar
      mediaSource.removeEventListener('sourceopen', handleSourceOpen)
      sourceBufferRef.current = null
      mediaSourceRef.current = null

      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current)
        objectUrlRef.current = null
      }
    }
  }, [renderMode, isActive])

  /**
   * Procesa los buffers pendientes en orden FIFO.
   * Solo appende si el SourceBuffer no está actualizando.
   */
  const flushPendingBuffers = useCallback(() => {
    const sourceBuffer = sourceBufferRef.current
    if (!sourceBuffer || sourceBuffer.updating) return

    const pending = pendingBuffersRef.current
    if (pending.length === 0) return

    const nextBuffer = pending.shift()
    if (nextBuffer) {
      try {
        sourceBuffer.appendBuffer(nextBuffer.buffer as ArrayBuffer)
      } catch {
        // QuotaExceededError o InvalidStateError — limpiar buffer viejo
        manageBufferOverflow()
      }
    }
  }, [])

  /**
   * Elimina segmentos antiguos del SourceBuffer cuando el buffer excede MAX_BUFFER_SECONDS.
   * Mantiene solo los últimos 2 segundos para permitir playback continuo.
   */
  const manageBufferOverflow = useCallback(() => {
    const sourceBuffer = sourceBufferRef.current
    if (!sourceBuffer || sourceBuffer.updating) return

    const buffered = sourceBuffer.buffered
    if (buffered.length === 0) return

    const bufferEnd = buffered.end(buffered.length - 1)
    const bufferStart = buffered.start(0)
    const bufferDuration = bufferEnd - bufferStart

    // Si el buffer excede el máximo, eliminar desde el inicio hasta (end - 2s)
    if (bufferDuration > MAX_BUFFER_SECONDS) {
      const removeEnd = bufferEnd - 2
      if (removeEnd > bufferStart) {
        try {
          sourceBuffer.remove(bufferStart, removeEnd)
        } catch {
          // Ignorar errores de remove — no es crítico
        }
      }
    }
  }, [])

  /**
   * Resetea el SourceBuffer al detectar un cambio de resolución en el header del frame.
   * Esto es necesario porque los datos H.264 con resolución diferente no son compatibles
   * con el SourceBuffer existente — el decoder necesita un keyframe con la nueva resolución.
   *
   * En modo imagen, simplemente actualiza las dimensiones (seamless, sin reset necesario).
   *
   * Requirements: 5.8, 5.9, 5.10, 8.3
   */
  const resetSourceBufferOnResolutionChange = useCallback((newWidth: number, newHeight: number) => {
    const sourceBuffer = sourceBufferRef.current
    if (!sourceBuffer) return

    // Descartar buffers pendientes (no son compatibles con la nueva resolución)
    pendingBuffersRef.current = []

    // Esperar a que SourceBuffer no esté actualizando antes de limpiar
    if (sourceBuffer.updating) {
      // Si está actualizando, escuchar el updateend para limpiar después
      const onUpdateEnd = () => {
        sourceBuffer.removeEventListener('updateend', onUpdateEnd)
        performSourceBufferReset(sourceBuffer)
      }
      sourceBuffer.addEventListener('updateend', onUpdateEnd)
    } else {
      performSourceBufferReset(sourceBuffer)
    }

    // eslint-disable-next-line no-console
    console.debug(
      `[StreamViewer] Resolución cambiada: ${previousWidthRef.current}x${previousHeightRef.current} → ${newWidth}x${newHeight}. SourceBuffer reseteado.`
    )
  }, [])

  /**
   * Ejecuta la limpieza del SourceBuffer (remove de todo el contenido buffereado).
   * Tras el reset, el siguiente frame recibido debería ser un keyframe del Tray.
   */
  const performSourceBufferReset = useCallback((sourceBuffer: SourceBuffer) => {
    try {
      const buffered = sourceBuffer.buffered
      if (buffered.length > 0) {
        const start = buffered.start(0)
        const end = buffered.end(buffered.length - 1)
        sourceBuffer.remove(start, end)
      }
    } catch {
      // Si falla el remove, el siguiente keyframe sincronizará de todas formas
    }
  }, [])

  // Procesar cada frame nuevo recibido
  useEffect(() => {
    if (!latestFrame || !isActive) return

    // Parsear header de 9 bytes
    const header = parseFrameHeader(latestFrame)
    if (!header) return

    // Detectar cambio de resolución en el header (Req 5.8, 5.9, 5.10, 8.3)
    const prevW = previousWidthRef.current
    const prevH = previousHeightRef.current
    const resolutionChanged =
      header.width > 0 &&
      header.height > 0 &&
      prevW > 0 &&
      prevH > 0 &&
      (header.width !== prevW || header.height !== prevH)

    // Actualizar dimensiones
    if (header.width > 0 && header.height > 0) {
      setFrameWidth(header.width)
      setFrameHeight(header.height)

      // Si la resolución cambió y estamos en MSE, resetear SourceBuffer
      if (resolutionChanged && renderMode === 'mse') {
        resetSourceBufferOnResolutionChange(header.width, header.height)
      }

      // Actualizar tracking de resolución previa
      previousWidthRef.current = header.width
      previousHeightRef.current = header.height
    }

    // Verificar si el payload es JPEG (datos placeholder del backend)
    if (isJpegPayload(header.payload)) {
      // Cambiar a modo imagen si estamos en MSE
      if (renderMode === 'mse') {
        setRenderMode('image')
      }

      // Crear blob URL para mostrar el JPEG
      const blob = new Blob([header.payload.buffer as ArrayBuffer], { type: 'image/jpeg' })
      const url = URL.createObjectURL(blob)

      // Revocar URL anterior
      if (imageUrl) {
        URL.revokeObjectURL(imageUrl)
      }
      setImageUrl(url)
      return
    }

    // Modo MSE: encolar NAL units para append al SourceBuffer
    if (renderMode === 'mse') {
      // Si hubo cambio de resolución, solo aceptar keyframes (esperar sincronización)
      if (resolutionChanged && !header.isKeyframe) {
        // Descartar frames no-keyframe hasta recibir el primer IDR con la nueva resolución
        return
      }

      // TODO: Cuando se implemente H.264 real, aquí se wrappearán las NAL units
      // en fragmentos fMP4 (usando mux.js o manualmente). Por ahora, se intenta
      // append directo — si falla, el handler de error cambiará a modo imagen.
      pendingBuffersRef.current.push(header.payload)
      flushPendingBuffers()

      // Gestionar buffer overflow
      manageBufferOverflow()
    }
  }, [latestFrame, isActive, renderMode, flushPendingBuffers, manageBufferOverflow, resetSourceBufferOnResolutionChange, imageUrl])

  // Limpiar image URL al desmontar
  useEffect(() => {
    return () => {
      if (imageUrl) {
        URL.revokeObjectURL(imageUrl)
      }
    }
  }, [imageUrl])

  // ============================================================================
  // RENDERIZADO
  // ============================================================================

  // Modo: Navegador no soporta MSE con H.264
  if (renderMode === 'unsupported') {
    return (
      <div className="flex flex-col flex-1 items-center justify-center bg-gray-900 gap-3">
        <AlertTriangle className="w-10 h-10 text-amber-400" />
        <p className="text-sm text-gray-300 text-center px-4">
          {t('streamUnsupported')}
        </p>
      </div>
    )
  }

  // Modo: Fallback a imagen (datos JPEG placeholder)
  if (renderMode === 'image') {
    return (
      <div className="flex flex-col flex-1 bg-gray-900 overflow-hidden">
        {/* Área de imagen */}
        <div className="flex-1 flex items-center justify-center overflow-hidden p-2">
          {imageUrl ? (
            <img
              src={imageUrl}
              alt={t('streamFrameAlt')}
              className="max-w-full max-h-full object-contain"
            />
          ) : (
            <div className="flex flex-col items-center gap-3 text-gray-400">
              <ImageIcon className="w-8 h-8 animate-pulse" />
              <span className="text-sm">{t('streamWaitingData')}</span>
            </div>
          )}
        </div>

        {/* Barra de estado inferior */}
        <div className="flex items-center gap-3 px-4 h-10 bg-gray-800 border-t border-gray-700 flex-shrink-0">
          <div className="flex items-center gap-2">
            <ImageIcon className="w-3.5 h-3.5 text-amber-400" />
            <span className="text-xs text-amber-400">
              {t('streamFallbackMode')}
            </span>
          </div>

          <div className="flex-1" />

          {/* Indicador de estado */}
          <div className="flex items-center gap-1.5">
            <div
              className={`w-2 h-2 rounded-full ${
                isActive ? 'bg-green-500' : 'bg-gray-500'
              }`}
            />
            <span className="text-xs text-gray-400">
              {isActive ? t('streamActive') : t('streamPaused')}
            </span>
          </div>

          {/* Dimensiones */}
          {frameWidth > 0 && frameHeight > 0 && (
            <>
              <div className="w-px h-5 bg-gray-600" />
              <span className="text-xs text-gray-500 tabular-nums">
                {t('frameDimensions', { width: frameWidth, height: frameHeight })}
              </span>
            </>
          )}
        </div>
      </div>
    )
  }

  // Modo: MSE (H.264 real)
  return (
    <div className="flex flex-col flex-1 bg-gray-900 overflow-hidden">
      {/* Área de video */}
      <div className="flex-1 flex items-center justify-center overflow-hidden p-2">
        {isBuffering ? (
          <div className="flex flex-col items-center gap-3 text-gray-400">
            <Video className="w-8 h-8 animate-pulse" />
            <span className="text-sm">{t('streamWaitingData')}</span>
          </div>
        ) : (
          <video
            ref={videoRef}
            autoPlay
            muted
            playsInline
            className="max-w-full max-h-full object-contain bg-black"
            aria-label={t('streamVideoLabel')}
          />
        )}
      </div>

      {/* Barra de estado inferior */}
      <div className="flex items-center gap-3 px-4 h-10 bg-gray-800 border-t border-gray-700 flex-shrink-0">
        <div className="flex items-center gap-2">
          <Video className="w-3.5 h-3.5 text-blue-400" />
          <span className="text-xs text-blue-400">H.264</span>
        </div>

        <div className="flex-1" />

        {/* Indicador de estado */}
        <div className="flex items-center gap-1.5">
          <div
            className={`w-2 h-2 rounded-full ${
              isActive ? 'bg-green-500' : 'bg-gray-500'
            }`}
          />
          <span className="text-xs text-gray-400">
            {isActive ? t('streamActive') : t('streamPaused')}
          </span>
        </div>

        {/* Dimensiones */}
        {frameWidth > 0 && frameHeight > 0 && (
          <>
            <div className="w-px h-5 bg-gray-600" />
            <span className="text-xs text-gray-500 tabular-nums">
              {t('frameDimensions', { width: frameWidth, height: frameHeight })}
            </span>
          </>
        )}
      </div>
    </div>
  )
}
