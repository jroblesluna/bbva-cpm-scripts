/**
 * Tests unitarios para useAutoAdjustQuality.
 *
 * Verifica el algoritmo de auto-ajuste de calidad basado en RTT:
 * - Nivel inicial por defecto (Level 3: 720p/70%)
 * - No ajusta con datos parciales (< 5 frames)
 * - Baja nivel cuando avg RTT > 2000ms
 * - Sube nivel cuando avg RTT < 500ms
 * - Mantiene nivel cuando avg RTT está entre 500-2000ms
 * - Respeta límites (no baja de Level 1, no sube de Level 4)
 * - No opera cuando enabled=false
 *
 * Requirements: 4.9
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useAutoAdjustQuality } from '../useAutoAdjustQuality'

// ============================================================================
// HELPERS
// ============================================================================

/**
 * Simula performance.now() con valores controlados.
 * Cada llamada avanza el reloj por el incremento dado.
 */
function mockPerformanceNow(values: number[]) {
  let callIndex = 0
  vi.spyOn(performance, 'now').mockImplementation(() => {
    const value = values[callIndex] ?? values[values.length - 1]
    callIndex++
    return value
  })
}

/**
 * Simula un ciclo completo de 5 frames con RTT constante.
 * Alterna entre recordRequestSent (timestamp de envío) y
 * recordFrameReceived (timestamp de recepción).
 */
function simulateFrameCycle(
  result: { current: ReturnType<typeof useAutoAdjustQuality> },
  rttMs: number,
  frames = 5
) {
  // Construir array de timestamps: envío en T, recepción en T + rtt
  const timestamps: number[] = []
  let currentTime = 1000

  for (let i = 0; i < frames; i++) {
    timestamps.push(currentTime) // recordRequestSent
    timestamps.push(currentTime + rttMs) // recordFrameReceived
    currentTime += rttMs + 100 // Pequeño gap entre frames
  }

  mockPerformanceNow(timestamps)

  for (let i = 0; i < frames; i++) {
    act(() => {
      result.current.recordRequestSent()
    })
    act(() => {
      result.current.recordFrameReceived()
    })
  }
}

// ============================================================================
// TESTS
// ============================================================================

describe('useAutoAdjustQuality', () => {
  let onConfigChange: ReturnType<typeof vi.fn>

  beforeEach(() => {
    onConfigChange = vi.fn()
    vi.restoreAllMocks()
  })

  it('inicia en Level 3 (720p/70%) por defecto', () => {
    const { result } = renderHook(() =>
      useAutoAdjustQuality({ enabled: true, onConfigChange })
    )

    expect(result.current.currentLevel).toEqual({
      level: 3,
      resolution: '720p',
      quality: 70,
      width: 1280,
      height: 720,
    })
    expect(result.current.avgRtt).toBe(0)
  })

  it('no ajusta con datos parciales (< 5 frames)', () => {
    const { result } = renderHook(() =>
      useAutoAdjustQuality({ enabled: true, onConfigChange })
    )

    // Simular solo 4 frames con RTT alto (debería bajar, pero no lo hace aún)
    simulateFrameCycle(result, 3000, 4)

    expect(result.current.currentLevel.level).toBe(3)
    expect(onConfigChange).not.toHaveBeenCalled()
  })

  it('baja nivel cuando avg RTT > 2000ms', () => {
    const { result } = renderHook(() =>
      useAutoAdjustQuality({ enabled: true, onConfigChange })
    )

    // 5 frames con RTT = 2500ms cada uno → avg = 2500ms > 2000ms
    simulateFrameCycle(result, 2500)

    expect(result.current.currentLevel.level).toBe(2)
    expect(result.current.currentLevel.resolution).toBe('480p')
    expect(result.current.currentLevel.quality).toBe(60)
    expect(onConfigChange).toHaveBeenCalledWith('854x480', 60)
  })

  it('sube nivel cuando avg RTT < 500ms', () => {
    const { result } = renderHook(() =>
      useAutoAdjustQuality({ enabled: true, onConfigChange })
    )

    // 5 frames con RTT = 200ms cada uno → avg = 200ms < 500ms
    simulateFrameCycle(result, 200)

    expect(result.current.currentLevel.level).toBe(4)
    expect(result.current.currentLevel.resolution).toBe('1080p')
    expect(result.current.currentLevel.quality).toBe(80)
    expect(onConfigChange).toHaveBeenCalledWith('1920x1080', 80)
  })

  it('mantiene nivel cuando avg RTT está entre 500-2000ms', () => {
    const { result } = renderHook(() =>
      useAutoAdjustQuality({ enabled: true, onConfigChange })
    )

    // 5 frames con RTT = 1000ms → avg = 1000ms (entre 500 y 2000)
    simulateFrameCycle(result, 1000)

    expect(result.current.currentLevel.level).toBe(3)
    expect(onConfigChange).not.toHaveBeenCalled()
  })

  it('no baja por debajo de Level 1', () => {
    const { result } = renderHook(() =>
      useAutoAdjustQuality({ enabled: true, onConfigChange })
    )

    // Bajar 2 veces: Level 3 → 2 → 1
    simulateFrameCycle(result, 3000) // Level 3 → 2
    simulateFrameCycle(result, 3000) // Level 2 → 1
    simulateFrameCycle(result, 3000) // Level 1 → sigue en 1 (no baja más)

    expect(result.current.currentLevel.level).toBe(1)
    expect(result.current.currentLevel.resolution).toBe('360p')
    // onConfigChange llamado solo 2 veces (Level 3→2, Level 2→1, la tercera no cambia)
    expect(onConfigChange).toHaveBeenCalledTimes(2)
  })

  it('no sube por encima de Level 4', () => {
    const { result } = renderHook(() =>
      useAutoAdjustQuality({ enabled: true, onConfigChange })
    )

    // Subir: Level 3 → 4
    simulateFrameCycle(result, 200) // Level 3 → 4
    simulateFrameCycle(result, 200) // Level 4 → sigue en 4 (no sube más)

    expect(result.current.currentLevel.level).toBe(4)
    expect(onConfigChange).toHaveBeenCalledTimes(1)
  })

  it('no opera cuando enabled=false', () => {
    const { result } = renderHook(() =>
      useAutoAdjustQuality({ enabled: false, onConfigChange })
    )

    // Simular frames con RTT bajo (debería subir, pero no porque está deshabilitado)
    const timestamps = [1000, 1200, 1300, 1500, 1600, 1800, 1900, 2100, 2200, 2400]
    mockPerformanceNow(timestamps)

    for (let i = 0; i < 5; i++) {
      act(() => result.current.recordRequestSent())
      act(() => result.current.recordFrameReceived())
    }

    expect(result.current.currentLevel.level).toBe(3)
    expect(onConfigChange).not.toHaveBeenCalled()
  })

  it('calcula avgRtt correctamente tras un ciclo completo', () => {
    const { result } = renderHook(() =>
      useAutoAdjustQuality({ enabled: true, onConfigChange })
    )

    // 5 frames con RTT = 1500ms → avg debería ser ~1500
    simulateFrameCycle(result, 1500)

    expect(result.current.avgRtt).toBe(1500)
  })

  it('resetea el buffer después de evaluar', () => {
    const { result } = renderHook(() =>
      useAutoAdjustQuality({ enabled: true, onConfigChange })
    )

    // Primer ciclo: RTT bajo → sube a Level 4
    simulateFrameCycle(result, 100)
    expect(result.current.currentLevel.level).toBe(4)

    // Segundo ciclo: RTT alto → baja a Level 3
    simulateFrameCycle(result, 3000)
    expect(result.current.currentLevel.level).toBe(3)
  })

  it('ignora recordFrameReceived si no hubo recordRequestSent previo', () => {
    const { result } = renderHook(() =>
      useAutoAdjustQuality({ enabled: true, onConfigChange })
    )

    mockPerformanceNow([1000])

    // Solo recibir frame sin haber enviado request
    act(() => result.current.recordFrameReceived())

    expect(result.current.currentLevel.level).toBe(3)
    expect(result.current.avgRtt).toBe(0)
  })
})
