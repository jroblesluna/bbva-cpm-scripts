/**
 * Utilidades para el procesamiento de frames de stream H.264.
 * Parseo del header binario y detección de tipo de payload.
 *
 * Requirements: 5.4
 */

// ============================================================================
// TIPOS
// ============================================================================

/** Resultado del parseo del header de 9 bytes */
export interface FrameHeader {
  /** Primeros 4 bytes del UUID de sesión (para routing) */
  sessionHash: Uint8Array
  /** true si es keyframe (IDR) */
  isKeyframe: boolean
  /** Índice del monitor (0-3) */
  monitorIndex: number
  /** Ancho del frame en píxeles */
  width: number
  /** Alto del frame en píxeles */
  height: number
  /** Payload (NAL units H.264 o datos JPEG según el modo) */
  payload: Uint8Array
}

// ============================================================================
// CONSTANTES
// ============================================================================

/** Tamaño del header binario en bytes */
export const HEADER_SIZE = 9

/** Codec MIME para MSE (H.264 Baseline Profile, Level 3.0) */
export const MSE_CODEC = 'video/mp4; codecs="avc1.42E01E"'

/** Máximo de segundos buffereados antes de limpiar segmentos antiguos */
export const MAX_BUFFER_SECONDS = 5

/** Signature bytes de JPEG (FFD8FF) para detectar fallback */
const JPEG_SIGNATURE = new Uint8Array([0xff, 0xd8, 0xff])

// ============================================================================
// FUNCIONES
// ============================================================================

/**
 * Parsea el header binario de 9 bytes de un frame de stream.
 * Formato: session_hash(4B) + flags(1B) + width(2B BE) + height(2B BE) + payload
 */
export function parseFrameHeader(data: ArrayBuffer): FrameHeader | null {
  if (data.byteLength < HEADER_SIZE) {
    return null
  }

  const view = new DataView(data)
  const bytes = new Uint8Array(data)

  // Bytes 0-3: session_hash (primeros 4 bytes del UUID)
  const sessionHash = bytes.slice(0, 4)

  // Byte 4: flags
  // bit 0: keyframe (1=IDR)
  // bit 1-2: monitor_index (0-3)
  // bit 3-7: reserved
  const flags = view.getUint8(4)
  const isKeyframe = (flags & 0x01) === 1
  const monitorIndex = (flags >> 1) & 0x03

  // Bytes 5-6: width (uint16 big-endian)
  const width = view.getUint16(5, false)

  // Bytes 7-8: height (uint16 big-endian)
  const height = view.getUint16(7, false)

  // Resto: payload (NAL units o JPEG)
  const payload = bytes.slice(HEADER_SIZE)

  return {
    sessionHash,
    isKeyframe,
    monitorIndex,
    width,
    height,
    payload,
  }
}

/**
 * Detecta si el payload es una imagen JPEG (por la firma FFD8FF).
 * Usado para activar el modo fallback cuando el backend envía JPEG placeholders.
 */
export function isJpegPayload(payload: Uint8Array): boolean {
  if (payload.length < 3) return false
  return (
    payload[0] === JPEG_SIGNATURE[0] &&
    payload[1] === JPEG_SIGNATURE[1] &&
    payload[2] === JPEG_SIGNATURE[2]
  )
}

/**
 * Verifica si el navegador soporta MSE con el codec H.264 especificado.
 */
export function isMseSupported(): boolean {
  if (typeof window === 'undefined') return false
  if (!('MediaSource' in window)) return false
  return MediaSource.isTypeSupported(MSE_CODEC)
}
