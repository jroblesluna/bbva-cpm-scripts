/**
 * Tests unitarios para useViewportReporter.
 *
 * Verifica el hook de reporte de viewport adaptativo:
 * - Reporta dimensiones iniciales al montar (sin debounce)
 * - Debounce de 1s al redimensionar (no dispara inmediatamente)
 * - No reporta dimensiones duplicadas consecutivas
 * - No reporta dimensiones 0 (contenedor oculto)
 * - No opera cuando enabled=false
 * - Limpia observer y timers al desmontar
 *
 * Requirements: 5.8
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useViewportReporter } from '../useViewportReporter'
import type { UseViewportReporterOptions } from '../useViewportReporter'

// ============================================================================
// MOCKS
// ============================================================================

/** Mock de ResizeObserver */
let resizeCallback: ResizeObserverCallback
let observedElements: Element[] = []

const mockDisconnect = vi.fn()
const mockObserve = vi.fn((el: Element) => {
  observedElements.push(el)
})

class MockResizeObserver {
  constructor(callback: ResizeObserverCallback) {
    resizeCallback = callback
  }
  observe = mockObserve
  unobserve = vi.fn()
  disconnect = mockDisconnect
}

// Simular un resize en el contenedor observado
function simulateResize(width: number, height: number) {
  const entry: Partial<ResizeObserverEntry> = {
    contentBoxSize: [{ inlineSize: width, blockSize: height } as ResizeObserverSize],
    contentRect: { width, height, x: 0, y: 0, top: 0, left: 0, bottom: height, right: width, toJSON: () => ({}) },
    target: document.createElement('div'),
    borderBoxSize: [],
    devicePixelContentBoxSize: [],
  }
  resizeCallback([entry as ResizeObserverEntry], {} as ResizeObserver)
}

// ============================================================================
// SETUP
// ============================================================================

beforeEach(() => {
  vi.useFakeTimers()
  observedElements = []
  mockDisconnect.mockClear()
  mockObserve.mockClear()
  vi.stubGlobal('ResizeObserver', MockResizeObserver)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

/**
 * Crea un contenedor mock con dimensiones específicas.
 */
function createMockContainer(width: number, height: number) {
  const el = document.createElement('div')
  Object.defineProperty(el, 'clientWidth', { value: width, configurable: true })
  Object.defineProperty(el, 'clientHeight', { value: height, configurable: true })
  return el
}

/**
 * Renderiza el hook con opciones por defecto.
 */
function renderViewportReporter(overrides: Partial<UseViewportReporterOptions> = {}) {
  const container = createMockContainer(
    overrides.containerRef?.current?.clientWidth ?? 960,
    overrides.containerRef?.current?.clientHeight ?? 540
  )

  const containerRef = overrides.containerRef ?? { current: container }
  const onViewportChange = overrides.onViewportChange ?? vi.fn()

  const options: UseViewportReporterOptions = {
    enabled: true,
    sessionId: 'test-session-id',
    containerRef: containerRef as React.RefObject<HTMLElement | null>,
    onViewportChange,
    debounceMs: 1000,
    ...overrides,
  }

  return { ...renderHook(() => useViewportReporter(options)), onViewportChange, container }
}

// ============================================================================
// TESTS
// ============================================================================

describe('useViewportReporter', () => {
  it('reporta dimensiones iniciales al montar (sin debounce)', () => {
    const onViewportChange = vi.fn()
    const container = createMockContainer(960, 540)
    const containerRef = { current: container }

    renderHook(() =>
      useViewportReporter({
        enabled: true,
        sessionId: 'session-1',
        containerRef: containerRef as React.RefObject<HTMLElement | null>,
        onViewportChange,
      })
    )

    // Se reporta inmediatamente, sin esperar debounce
    expect(onViewportChange).toHaveBeenCalledTimes(1)
    expect(onViewportChange).toHaveBeenCalledWith(960, 540)
  })

  it('no reporta dimensiones iniciales si el contenedor es null', () => {
    const onViewportChange = vi.fn()
    const containerRef = { current: null }

    renderHook(() =>
      useViewportReporter({
        enabled: true,
        sessionId: 'session-1',
        containerRef: containerRef as React.RefObject<HTMLElement | null>,
        onViewportChange,
      })
    )

    expect(onViewportChange).not.toHaveBeenCalled()
  })

  it('aplica debounce de 1s al redimensionar', () => {
    const onViewportChange = vi.fn()
    const container = createMockContainer(960, 540)
    const containerRef = { current: container }

    renderHook(() =>
      useViewportReporter({
        enabled: true,
        sessionId: 'session-1',
        containerRef: containerRef as React.RefObject<HTMLElement | null>,
        onViewportChange,
        debounceMs: 1000,
      })
    )

    // Reporte inicial
    expect(onViewportChange).toHaveBeenCalledTimes(1)

    // Simular resize
    simulateResize(1200, 800)

    // No se reporta inmediatamente
    expect(onViewportChange).toHaveBeenCalledTimes(1)

    // Avanzar 999ms — aún no se reporta
    vi.advanceTimersByTime(999)
    expect(onViewportChange).toHaveBeenCalledTimes(1)

    // Avanzar 1ms más → se reporta
    vi.advanceTimersByTime(1)
    expect(onViewportChange).toHaveBeenCalledTimes(2)
    expect(onViewportChange).toHaveBeenLastCalledWith(1200, 800)
  })

  it('cancela timer previo si hay un segundo resize antes del debounce', () => {
    const onViewportChange = vi.fn()
    const container = createMockContainer(960, 540)
    const containerRef = { current: container }

    renderHook(() =>
      useViewportReporter({
        enabled: true,
        sessionId: 'session-1',
        containerRef: containerRef as React.RefObject<HTMLElement | null>,
        onViewportChange,
        debounceMs: 1000,
      })
    )

    // Primer resize
    simulateResize(1200, 800)
    vi.advanceTimersByTime(500)

    // Segundo resize antes de que expire el debounce
    simulateResize(1400, 900)
    vi.advanceTimersByTime(1000)

    // Solo se reporta el último valor (después del reporte inicial)
    expect(onViewportChange).toHaveBeenCalledTimes(2)
    expect(onViewportChange).toHaveBeenLastCalledWith(1400, 900)
  })

  it('no reporta dimensiones duplicadas consecutivas', () => {
    const onViewportChange = vi.fn()
    const container = createMockContainer(960, 540)
    const containerRef = { current: container }

    renderHook(() =>
      useViewportReporter({
        enabled: true,
        sessionId: 'session-1',
        containerRef: containerRef as React.RefObject<HTMLElement | null>,
        onViewportChange,
        debounceMs: 1000,
      })
    )

    // Reporte inicial: 960x540
    expect(onViewportChange).toHaveBeenCalledTimes(1)

    // Simular resize con las mismas dimensiones
    simulateResize(960, 540)
    vi.advanceTimersByTime(1000)

    // No se reporta porque las dimensiones no cambiaron
    expect(onViewportChange).toHaveBeenCalledTimes(1)
  })

  it('no reporta dimensiones 0 (contenedor oculto)', () => {
    const onViewportChange = vi.fn()
    const container = createMockContainer(0, 0)
    const containerRef = { current: container }

    renderHook(() =>
      useViewportReporter({
        enabled: true,
        sessionId: 'session-1',
        containerRef: containerRef as React.RefObject<HTMLElement | null>,
        onViewportChange,
      })
    )

    // No se reporta porque width/height son 0
    expect(onViewportChange).not.toHaveBeenCalled()
  })

  it('no opera cuando enabled=false', () => {
    const onViewportChange = vi.fn()
    const container = createMockContainer(960, 540)
    const containerRef = { current: container }

    renderHook(() =>
      useViewportReporter({
        enabled: false,
        sessionId: 'session-1',
        containerRef: containerRef as React.RefObject<HTMLElement | null>,
        onViewportChange,
      })
    )

    // No se reporta ni se observa
    expect(onViewportChange).not.toHaveBeenCalled()
    expect(mockObserve).not.toHaveBeenCalled()
  })

  it('desconecta el observer al desmontar', () => {
    const onViewportChange = vi.fn()
    const container = createMockContainer(960, 540)
    const containerRef = { current: container }

    const { unmount } = renderHook(() =>
      useViewportReporter({
        enabled: true,
        sessionId: 'session-1',
        containerRef: containerRef as React.RefObject<HTMLElement | null>,
        onViewportChange,
      })
    )

    unmount()

    expect(mockDisconnect).toHaveBeenCalledTimes(1)
  })

  it('cancela timer pendiente al desmontar', () => {
    const onViewportChange = vi.fn()
    const container = createMockContainer(960, 540)
    const containerRef = { current: container }

    const { unmount } = renderHook(() =>
      useViewportReporter({
        enabled: true,
        sessionId: 'session-1',
        containerRef: containerRef as React.RefObject<HTMLElement | null>,
        onViewportChange,
        debounceMs: 1000,
      })
    )

    // Simular resize para iniciar timer
    simulateResize(1200, 800)

    // Desmontar antes de que expire el debounce
    unmount()

    // Avanzar tiempo — el callback no se ejecuta
    vi.advanceTimersByTime(2000)
    expect(onViewportChange).toHaveBeenCalledTimes(1) // Solo el reporte inicial
  })

  it('redondea dimensiones decimales a enteros', () => {
    const onViewportChange = vi.fn()
    const container = createMockContainer(960, 540)
    const containerRef = { current: container }

    renderHook(() =>
      useViewportReporter({
        enabled: true,
        sessionId: 'session-1',
        containerRef: containerRef as React.RefObject<HTMLElement | null>,
        onViewportChange,
        debounceMs: 1000,
      })
    )

    // Simular resize con dimensiones decimales
    simulateResize(959.7, 540.3)
    vi.advanceTimersByTime(1000)

    // Se reporta redondeado a enteros (960, 540 es igual al inicial, no se reporta)
    // Probar con valores diferentes
    simulateResize(1199.6, 799.4)
    vi.advanceTimersByTime(1000)

    expect(onViewportChange).toHaveBeenLastCalledWith(1200, 799)
  })

  it('usa debounceMs personalizado', () => {
    const onViewportChange = vi.fn()
    const container = createMockContainer(960, 540)
    const containerRef = { current: container }

    renderHook(() =>
      useViewportReporter({
        enabled: true,
        sessionId: 'session-1',
        containerRef: containerRef as React.RefObject<HTMLElement | null>,
        onViewportChange,
        debounceMs: 500,
      })
    )

    simulateResize(1200, 800)

    // A los 499ms no se reporta
    vi.advanceTimersByTime(499)
    expect(onViewportChange).toHaveBeenCalledTimes(1) // Solo inicial

    // A los 500ms se reporta
    vi.advanceTimersByTime(1)
    expect(onViewportChange).toHaveBeenCalledTimes(2)
    expect(onViewportChange).toHaveBeenLastCalledWith(1200, 800)
  })
})
