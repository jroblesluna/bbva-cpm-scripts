/**
 * Tests de integración del componente MetricsCard.
 *
 * Verifica: renderizado con datos completos (5 métricas con colores),
 * métricas null ("no disponible" sin indicador de color),
 * estado de error (mensaje localizado), estado de carga (spinner).
 *
 * Validates: Requirements 8.1, 8.2, 8.4, 8.5, 8.6
 */

import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import type { ScalabilityMetrics } from '@/types/scalability-metrics'

// === MOCKS ===

// Mock de next-intl: retorna la key como texto traducido.
// La función t debe ser estable (misma referencia) para evitar loops en useCallback.
const stableT = (key: string, params?: Record<string, unknown>) => {
  if (params) {
    let result = key
    for (const [k, v] of Object.entries(params)) {
      result += ` ${k}:${v}`
    }
    return result
  }
  return key
}

vi.mock('next-intl', () => ({
  useTranslations: () => stableT,
}))

// Mock del apiClient para controlar respuestas del endpoint
const mockGet = vi.fn()
vi.mock('@/lib/api', () => ({
  apiClient: {
    get: (...args: unknown[]) => mockGet(...args),
  },
}))

// Importar el componente después de los mocks
import MetricsCard from '../MetricsCard'

// === DATOS DE PRUEBA ===

/**
 * Crea un objeto de métricas completo para tests.
 * Valores dentro del rango verde por defecto.
 */
function createCompleteMetrics(
  overrides: Partial<ScalabilityMetrics> = {}
): ScalabilityMetrics {
  return {
    websocket: {
      workstation_count: 1500,
      operator_count: 50,
      total: 1550,
      data_available: true,
    },
    python_memory: {
      rss_mb: 512.45,
      container_total_mb: 2048.0,
      avg_per_workstation_mb: 1.5,
    },
    file_descriptors: {
      open_count: 300,
      limit: 1024,
      usage_percent: 29.3,
    },
    network: {
      rx_bytes: 1048576,
      tx_bytes: 2097152,
      rx_rate_bps: 10485760,
      tx_rate_bps: 20971520,
    },
    db_pool: {
      checked_out: 3,
      idle: 7,
      pool_size: 10,
      overflow: 0,
      max_overflow: 5,
      pg_active_connections: 3,
      usage_percent: 30.0,
    },
    collected_at: '2024-06-15T12:00:00Z',
    ...overrides,
  }
}

// === TESTS ===

describe('MetricsCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // --- Test 1: Render con datos completos → 5 métricas visibles con colores correctos ---
  describe('Render con datos completos', () => {
    it('muestra 5 métricas con indicadores de color verde cuando valores están en rango normal', async () => {
      // Valores dentro del rango verde
      mockGet.mockResolvedValue({ data: createCompleteMetrics() })

      render(<MetricsCard />)

      await waitFor(() => {
        // Verificar las 5 métricas están visibles por su label
        expect(screen.getByText('websocket.label')).toBeInTheDocument()
        expect(screen.getByText('memory.perWorkstation')).toBeInTheDocument()
        expect(screen.getByText('fileDescriptors.usage')).toBeInTheDocument()
        expect(screen.getByText('dbPool.usage')).toBeInTheDocument()
        expect(screen.getByText('network.txRate')).toBeInTheDocument()
      })

      // Verificar que los indicadores de color verde están presentes (bg-green-500)
      const indicators = document.querySelectorAll('.bg-green-500')
      expect(indicators.length).toBe(5)
    })

    it('muestra indicador amarillo cuando valor de WebSocket excede greenMax', async () => {
      // Total WS = 3500 → amarillo (greenMax=3000, yellowMax=4500)
      const metrics = createCompleteMetrics({
        websocket: {
          workstation_count: 3400,
          operator_count: 100,
          total: 3500,
          data_available: true,
        },
      })
      mockGet.mockResolvedValue({ data: metrics })

      render(<MetricsCard />)

      await waitFor(() => {
        expect(screen.getByText('websocket.label')).toBeInTheDocument()
      })

      // Debe haber al menos un indicador amarillo
      const yellowIndicators = document.querySelectorAll('.bg-yellow-500')
      expect(yellowIndicators.length).toBeGreaterThanOrEqual(1)
    })

    it('muestra indicador rojo cuando valor excede yellowMax', async () => {
      // FD usage = 85% → rojo (greenMax=60, yellowMax=80)
      const metrics = createCompleteMetrics({
        file_descriptors: {
          open_count: 870,
          limit: 1024,
          usage_percent: 85.0,
        },
      })
      mockGet.mockResolvedValue({ data: metrics })

      render(<MetricsCard />)

      await waitFor(() => {
        expect(screen.getByText('fileDescriptors.usage')).toBeInTheDocument()
      })

      // Debe haber al menos un indicador rojo
      const redIndicators = document.querySelectorAll('.bg-red-500')
      expect(redIndicators.length).toBeGreaterThanOrEqual(1)
    })

    it('muestra valores numéricos correctos con sus unidades', async () => {
      mockGet.mockResolvedValue({ data: createCompleteMetrics() })

      render(<MetricsCard />)

      await waitFor(() => {
        // WebSocket total: 1550 (sin unidad)
        expect(screen.getByText('1550')).toBeInTheDocument()
        // Memoria por WS: 1.5 con unidad
        expect(screen.getByText('1.5')).toBeInTheDocument()
        expect(screen.getByText('memory.unit')).toBeInTheDocument()
        // FD usage: 29.3 con %
        expect(screen.getByText('29.3')).toBeInTheDocument()
        // DB pool: 30 con %
        expect(screen.getByText('30')).toBeInTheDocument()
      })
    })
  })

  // --- Test 2: Render con métrica null → texto "no disponible" sin indicador de color ---
  describe('Render con métrica null', () => {
    it('muestra texto "no disponible" cuando una métrica es null', async () => {
      const metrics = createCompleteMetrics({
        python_memory: null,
      })
      mockGet.mockResolvedValue({ data: metrics })

      render(<MetricsCard />)

      await waitFor(() => {
        // Debe mostrar texto "no disponible" (la key de i18n)
        expect(screen.getByText('states.unavailable')).toBeInTheDocument()
      })
    })

    it('no muestra indicador de color para métricas con valor null', async () => {
      const metrics = createCompleteMetrics({
        python_memory: null,
        file_descriptors: null,
      })
      mockGet.mockResolvedValue({ data: metrics })

      render(<MetricsCard />)

      await waitFor(() => {
        expect(screen.getByText('websocket.label')).toBeInTheDocument()
      })

      // Con 2 métricas null, solo deben haber 3 indicadores de color
      const greenIndicators = document.querySelectorAll('.bg-green-500')
      const yellowIndicators = document.querySelectorAll('.bg-yellow-500')
      const redIndicators = document.querySelectorAll('.bg-red-500')
      const totalColorIndicators =
        greenIndicators.length + yellowIndicators.length + redIndicators.length
      expect(totalColorIndicators).toBe(3)
    })

    it('muestra múltiples textos "no disponible" cuando varias métricas son null', async () => {
      const metrics = createCompleteMetrics({
        python_memory: null,
        file_descriptors: null,
        network: null,
      })
      mockGet.mockResolvedValue({ data: metrics })

      render(<MetricsCard />)

      await waitFor(() => {
        // 3 métricas con valor null → 3 textos "no disponible"
        const unavailableTexts = screen.getAllByText('states.unavailable')
        expect(unavailableTexts.length).toBe(3)
      })
    })
  })

  // --- Test 3: Render en estado error → mensaje localizado de error ---
  describe('Render en estado error', () => {
    it('muestra mensaje de error localizado cuando la API falla', async () => {
      // Simular error de red/API
      mockGet.mockRejectedValue(new Error('Network Error'))

      render(<MetricsCard />)

      await waitFor(() => {
        // El componente muestra t('states.error') como mensaje de error
        expect(screen.getByText('states.error')).toBeInTheDocument()
      })
    })

    it('muestra botón de refresh en estado de error para reintentar', async () => {
      mockGet.mockRejectedValue(new Error('Server Error'))

      render(<MetricsCard />)

      await waitFor(() => {
        expect(screen.getByText('states.error')).toBeInTheDocument()
        // El botón de refresh debe estar visible
        expect(screen.getByText('refresh')).toBeInTheDocument()
      })
    })

    it('no muestra métricas cuando hay error de API', async () => {
      mockGet.mockRejectedValue(new Error('500 Internal Server Error'))

      render(<MetricsCard />)

      await waitFor(() => {
        expect(screen.getByText('states.error')).toBeInTheDocument()
      })

      // No deben aparecer labels de métricas
      expect(screen.queryByText('websocket.label')).not.toBeInTheDocument()
      expect(screen.queryByText('memory.perWorkstation')).not.toBeInTheDocument()
      expect(screen.queryByText('fileDescriptors.usage')).not.toBeInTheDocument()
    })
  })

  // --- Test 4: Render en estado loading → spinner visible ---
  describe('Render en estado loading', () => {
    it('muestra spinner mientras se cargan las métricas', () => {
      // Mock que nunca resuelve para mantener estado de carga
      mockGet.mockReturnValue(new Promise(() => {}))

      render(<MetricsCard />)

      // El texto de loading debe estar visible inmediatamente
      expect(screen.getByText('states.loading')).toBeInTheDocument()
    })

    it('muestra clase animate-spin en el spinner durante carga', () => {
      mockGet.mockReturnValue(new Promise(() => {}))

      render(<MetricsCard />)

      // Verificar que hay un elemento con clase animate-spin (el Loader2 icon)
      const spinner = document.querySelector('.animate-spin')
      expect(spinner).toBeInTheDocument()
    })

    it('no muestra métricas ni error durante la carga', () => {
      mockGet.mockReturnValue(new Promise(() => {}))

      render(<MetricsCard />)

      // No deben aparecer métricas ni mensajes de error
      expect(screen.queryByText('websocket.label')).not.toBeInTheDocument()
      expect(screen.queryByText('states.error')).not.toBeInTheDocument()
      expect(screen.queryByText('states.unavailable')).not.toBeInTheDocument()
    })

    it('muestra el título de la card durante la carga', () => {
      mockGet.mockReturnValue(new Promise(() => {}))

      render(<MetricsCard />)

      // El título siempre debe estar presente
      expect(screen.getByText('title')).toBeInTheDocument()
    })
  })
})
