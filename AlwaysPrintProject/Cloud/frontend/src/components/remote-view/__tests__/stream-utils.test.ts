/**
 * Tests unitarios para las utilidades de procesamiento de frames de stream.
 * Valida el parseo correcto del header binario de 9 bytes y la detección de JPEG.
 *
 * Requirements: 5.4
 */

import { describe, it, expect } from 'vitest'
import {
  parseFrameHeader,
  isJpegPayload,
  HEADER_SIZE,
} from '../stream-utils'

// ============================================================================
// Helpers
// ============================================================================

/**
 * Construye un ArrayBuffer con el formato de frame binario.
 * session_hash(4B) + flags(1B) + width(2B BE) + height(2B BE) + payload
 */
function buildFrame(options: {
  sessionHash?: number[]
  isKeyframe?: boolean
  monitorIndex?: number
  width?: number
  height?: number
  payload?: number[]
}): ArrayBuffer {
  const {
    sessionHash = [0xab, 0xcd, 0xef, 0x12],
    isKeyframe = false,
    monitorIndex = 0,
    width = 1280,
    height = 720,
    payload = [0x00, 0x01, 0x02],
  } = options

  const buffer = new ArrayBuffer(HEADER_SIZE + payload.length)
  const view = new DataView(buffer)
  const bytes = new Uint8Array(buffer)

  // session_hash (4 bytes)
  bytes[0] = sessionHash[0]
  bytes[1] = sessionHash[1]
  bytes[2] = sessionHash[2]
  bytes[3] = sessionHash[3]

  // flags (1 byte): bit 0 = keyframe, bit 1-2 = monitorIndex
  const flags = (isKeyframe ? 1 : 0) | ((monitorIndex & 0x03) << 1)
  view.setUint8(4, flags)

  // width (2 bytes big-endian)
  view.setUint16(5, width, false)

  // height (2 bytes big-endian)
  view.setUint16(7, height, false)

  // payload
  for (let i = 0; i < payload.length; i++) {
    bytes[HEADER_SIZE + i] = payload[i]
  }

  return buffer
}

// ============================================================================
// Tests: parseFrameHeader
// ============================================================================

describe('parseFrameHeader', () => {
  it('retorna null si el buffer es menor a 9 bytes', () => {
    const buffer = new ArrayBuffer(8)
    expect(parseFrameHeader(buffer)).toBeNull()
  })

  it('retorna null si el buffer está vacío', () => {
    const buffer = new ArrayBuffer(0)
    expect(parseFrameHeader(buffer)).toBeNull()
  })

  it('parsea correctamente un frame con keyframe=true', () => {
    const frame = buildFrame({
      sessionHash: [0x01, 0x02, 0x03, 0x04],
      isKeyframe: true,
      monitorIndex: 0,
      width: 1920,
      height: 1080,
      payload: [0x65, 0x88], // NAL IDR ejemplo
    })

    const result = parseFrameHeader(frame)
    expect(result).not.toBeNull()
    expect(result!.isKeyframe).toBe(true)
    expect(result!.monitorIndex).toBe(0)
    expect(result!.width).toBe(1920)
    expect(result!.height).toBe(1080)
    expect(result!.sessionHash[0]).toBe(0x01)
    expect(result!.sessionHash[3]).toBe(0x04)
    expect(result!.payload.length).toBe(2)
    expect(result!.payload[0]).toBe(0x65)
  })

  it('parsea correctamente un frame con keyframe=false', () => {
    const frame = buildFrame({
      isKeyframe: false,
      monitorIndex: 2,
      width: 854,
      height: 480,
      payload: [0x41, 0x9a],
    })

    const result = parseFrameHeader(frame)
    expect(result).not.toBeNull()
    expect(result!.isKeyframe).toBe(false)
    expect(result!.monitorIndex).toBe(2)
    expect(result!.width).toBe(854)
    expect(result!.height).toBe(480)
  })

  it('extrae correctamente monitor_index de los bits 1-2 del flag', () => {
    // monitorIndex 0 → flags = 0b00000000
    const frame0 = buildFrame({ monitorIndex: 0, isKeyframe: false })
    expect(parseFrameHeader(frame0)!.monitorIndex).toBe(0)

    // monitorIndex 1 → flags = 0b00000010
    const frame1 = buildFrame({ monitorIndex: 1, isKeyframe: false })
    expect(parseFrameHeader(frame1)!.monitorIndex).toBe(1)

    // monitorIndex 3 → flags = 0b00000110
    const frame3 = buildFrame({ monitorIndex: 3, isKeyframe: false })
    expect(parseFrameHeader(frame3)!.monitorIndex).toBe(3)
  })

  it('combina correctamente keyframe y monitorIndex en flags', () => {
    // keyframe=true, monitorIndex=2 → flags = 0b00000101
    const frame = buildFrame({ isKeyframe: true, monitorIndex: 2 })
    const result = parseFrameHeader(frame)
    expect(result!.isKeyframe).toBe(true)
    expect(result!.monitorIndex).toBe(2)
  })

  it('maneja frame sin payload (solo header de 9 bytes)', () => {
    const frame = buildFrame({ payload: [] })
    const result = parseFrameHeader(frame)
    expect(result).not.toBeNull()
    expect(result!.payload.length).toBe(0)
  })

  it('parsea dimensiones grandes correctamente (uint16 BE)', () => {
    const frame = buildFrame({ width: 3840, height: 2160 })
    const result = parseFrameHeader(frame)
    expect(result!.width).toBe(3840)
    expect(result!.height).toBe(2160)
  })
})

// ============================================================================
// Tests: isJpegPayload
// ============================================================================

describe('isJpegPayload', () => {
  it('detecta payload JPEG por la firma FFD8FF', () => {
    const payload = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10])
    expect(isJpegPayload(payload)).toBe(true)
  })

  it('retorna false para payload H.264 (NAL unit)', () => {
    // NAL start code + IDR
    const payload = new Uint8Array([0x00, 0x00, 0x00, 0x01, 0x65])
    expect(isJpegPayload(payload)).toBe(false)
  })

  it('retorna false para payload vacío', () => {
    const payload = new Uint8Array([])
    expect(isJpegPayload(payload)).toBe(false)
  })

  it('retorna false para payload de menos de 3 bytes', () => {
    const payload = new Uint8Array([0xff, 0xd8])
    expect(isJpegPayload(payload)).toBe(false)
  })

  it('retorna false si solo el primer byte coincide', () => {
    const payload = new Uint8Array([0xff, 0x00, 0x00])
    expect(isJpegPayload(payload)).toBe(false)
  })
})
