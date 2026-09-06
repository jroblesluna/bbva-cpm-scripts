/**
 * Tests unitarios para ClosureReportActions.
 *
 * Verifica:
 * - "Regenerar análisis" oculto para no-admin y visible para admin/superadmin (Req 9.2, 9.3).
 * - "Descargar reporte" invoca getClosureReport y abre report_url en nueva pestaña (Req 9.1).
 * - La vista previa consume getClosureReportData y renderiza los gráficos recharts
 *   (composición de tramos y evolución histórica) (Req 9.3).
 * - Consumo del cliente API tipado (Req 9.4).
 *
 * Validates: Requirements 9.1, 9.2, 9.3, 9.4
 *
 * Notas sobre jsdom:
 * - next-intl: se mockea `useTranslations` para devolver la key (con interpolación simple de
 *   params) — mismo patrón que los tests existentes (RemoteTerminalSection / system-status).
 * - recharts: `ResponsiveContainer` depende de `ResizeObserver` y de dimensiones de layout que
 *   jsdom reporta como 0, por lo que los charts no renderizarían SVG. Se mockea `recharts` con
 *   stubs ligeros que renderizan los `children` dentro de un div de tamaño fijo, y las
 *   aserciones se hacen sobre títulos de sección / leyendas (dataKey) en vez de geometría SVG.
 */

import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import type { ClosureHeader, ClosureReportData, ClosureReportUrlResponse } from '@/types/billing'

// ============================================================================
// MOCKS
// ============================================================================

// next-intl: la key se devuelve tal cual; los params se anexan como `key cycle:1`.
vi.mock('next-intl', () => ({
  useTranslations: () => {
    const t = (key: string, params?: Record<string, unknown>) => {
      if (params) {
        let result = key
        for (const [k, v] of Object.entries(params)) {
          result += ` ${k}:${v}`
        }
        return result
      }
      return key
    }
    return t
  },
}))

// useToast
const mockToast = vi.fn()
vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: mockToast }),
}))

// Cliente API tipado (@/lib/api/billing)
const mockGetClosureReport = vi.fn()
const mockRegenerateClosureReport = vi.fn()
const mockGetClosureReportData = vi.fn()
vi.mock('@/lib/api/billing', () => ({
  getClosureReport: (...args: unknown[]) => mockGetClosureReport(...args),
  regenerateClosureReport: (...args: unknown[]) => mockRegenerateClosureReport(...args),
  getClosureReportData: (...args: unknown[]) => mockGetClosureReportData(...args),
}))

// recharts: stubs que renderizan children en un contenedor de tamaño fijo (jsdom no calcula
// dimensiones reales). Cada primitiva expone su `dataKey`/`name` como texto para poder afirmar
// sobre la presencia de las series sin depender de la geometría del SVG.
vi.mock('recharts', () => {
  const Passthrough = ({ children }: { children?: ReactNode }) => (
    <div style={{ width: 800, height: 300 }}>{children}</div>
  )
  const Series = ({ dataKey, name }: { dataKey?: string; name?: string }) => (
    <div data-testid={`series-${String(dataKey)}`}>{name ?? String(dataKey)}</div>
  )
  const Noop = () => null
  return {
    ResponsiveContainer: Passthrough,
    BarChart: Passthrough,
    ComposedChart: Passthrough,
    Bar: Series,
    Line: Series,
    CartesianGrid: Noop,
    XAxis: Noop,
    YAxis: Noop,
    Legend: Noop,
    Tooltip: Noop,
  }
})

// Importar el componente después de los mocks.
import { ClosureReportActions } from '../ClosureReportActions'
// `t` del namespace billingReport se obtiene con el hook mockeado.
import { useTranslations } from 'next-intl'

// ============================================================================
// HELPERS
// ============================================================================

function createClosureHeader(overrides: Partial<ClosureHeader> = {}): ClosureHeader {
  return {
    id: 'closure-1',
    organization_id: 'org-1',
    period_year: 2026,
    period_month: 5,
    cutoff_at: '2026-05-31T23:59:59Z',
    mode: 'monthly',
    timezone: 'America/Lima',
    total_billable: 42,
    total_recycled: 3,
    total_archived: 1,
    amount: '123.45',
    tiers_applied: [],
    is_retroactive: false,
    created_by_id: null,
    created_at: '2026-06-01T00:00:00Z',
    ...overrides,
  }
}

function createReportUrl(
  overrides: Partial<ClosureReportUrlResponse> = {}
): ClosureReportUrlResponse {
  return {
    report_url: 'https://s3.us-west-2.amazonaws.com/bucket/report.pdf?sig=abc',
    expires_in_seconds: 3600,
    cached: true,
    ai_analysis_available: true,
    ...overrides,
  }
}

function createReportData(overrides: Partial<ClosureReportData> = {}): ClosureReportData {
  return {
    header: createClosureHeader(),
    tiers_applied: [
      { from: 1, to: 10, rate: 5, ips_in_tier: 8, subtotal: 40, tier_index: 0 },
      { from: 11, to: null, rate: 3, ips_in_tier: 4, subtotal: 12, tier_index: 1 },
    ],
    history: [
      {
        cycle: 1,
        period_year: 2026,
        period_month: 4,
        total_billable: 30,
        total_recycled: 2,
        total_archived: 0,
        amount: '90.00',
      },
      {
        cycle: 2,
        period_year: 2026,
        period_month: 5,
        total_billable: 42,
        total_recycled: 3,
        total_archived: 1,
        amount: '123.45',
      },
    ],
    ai_analysis: 'Resumen ejecutivo del ciclo.',
    currency: 'USD',
    taxes_included: false,
    ...overrides,
  }
}

/** Wrapper con QueryClientProvider (retries off para que los errores no reintenten). */
function renderWithClient(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}

/** Componente puente para obtener el `t` mockeado (el componente lo recibe como prop). */
function Harness({
  closure,
  isAdmin,
}: {
  closure: ClosureHeader
  isAdmin: boolean
}) {
  const t = useTranslations('billingReport')
  return <ClosureReportActions closure={closure} isAdmin={isAdmin} t={t} />
}

function renderComponent(isAdmin: boolean, closure: ClosureHeader = createClosureHeader()) {
  return renderWithClient(<Harness closure={closure} isAdmin={isAdmin} />)
}

// ============================================================================
// TESTS
// ============================================================================

describe('ClosureReportActions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetClosureReport.mockResolvedValue(createReportUrl())
    mockRegenerateClosureReport.mockResolvedValue(createReportUrl({ cached: false }))
    mockGetClosureReportData.mockResolvedValue(createReportData())
    // window.open mockeado (jsdom lanza "Not implemented" si no se mockea).
    vi.spyOn(window, 'open').mockImplementation(() => null)
  })

  // --------------------------------------------------------------------------
  // Gating de "Regenerar análisis" por rol (Req 9.2, 9.3)
  // --------------------------------------------------------------------------

  describe('Gating de "Regenerar análisis" por rol', () => {
    it('NO muestra "Regenerar análisis" cuando isAdmin=false', () => {
      renderComponent(false)

      expect(
        screen.queryByRole('button', { name: /regenerateAnalysis/ })
      ).not.toBeInTheDocument()
      // El botón de descargar sí debe estar presente para cualquier rol con acceso.
      expect(screen.getByRole('button', { name: /downloadReport/ })).toBeInTheDocument()
    })

    it('muestra "Regenerar análisis" cuando isAdmin=true', () => {
      renderComponent(true)

      expect(screen.getByRole('button', { name: /regenerateAnalysis/ })).toBeInTheDocument()
    })
  })

  // --------------------------------------------------------------------------
  // Descargar reporte (Req 9.1)
  // --------------------------------------------------------------------------

  describe('Descargar reporte', () => {
    it('invoca getClosureReport y abre report_url en nueva pestaña al hacer click', async () => {
      renderComponent(false)

      const downloadButton = screen.getByRole('button', { name: /downloadReport/ })
      fireEvent.click(downloadButton)

      await waitFor(() => {
        expect(mockGetClosureReport).toHaveBeenCalledWith('closure-1')
      })

      await waitFor(() => {
        expect(window.open).toHaveBeenCalledWith(
          'https://s3.us-west-2.amazonaws.com/bucket/report.pdf?sig=abc',
          '_blank',
          'noopener,noreferrer'
        )
      })
    })

    it('avisa (toast fail-safe) cuando el análisis IA no está disponible', async () => {
      mockGetClosureReport.mockResolvedValue(
        createReportUrl({ ai_analysis_available: false })
      )

      renderComponent(false)
      fireEvent.click(screen.getByRole('button', { name: /downloadReport/ }))

      await waitFor(() => {
        expect(window.open).toHaveBeenCalled()
      })
      expect(mockToast).toHaveBeenCalledWith(
        expect.objectContaining({ description: 'aiAnalysisUnavailable' })
      )
    })

    it('muestra toast de error cuando getClosureReport falla y no abre pestaña', async () => {
      mockGetClosureReport.mockRejectedValue(new Error('boom'))

      renderComponent(false)
      fireEvent.click(screen.getByRole('button', { name: /downloadReport/ }))

      await waitFor(() => {
        expect(mockToast).toHaveBeenCalledWith(
          expect.objectContaining({ variant: 'destructive', description: 'downloadError' })
        )
      })
      expect(window.open).not.toHaveBeenCalled()
    })
  })

  // --------------------------------------------------------------------------
  // Regenerar análisis (Req 9.2)
  // --------------------------------------------------------------------------

  describe('Regenerar análisis', () => {
    it('confirma y luego invoca regenerateClosureReport, abriendo el nuevo reporte', async () => {
      renderComponent(true)

      // Abrir el diálogo de confirmación.
      fireEvent.click(screen.getByRole('button', { name: /regenerateAnalysis/ }))

      // Confirmar la acción.
      const confirmButton = await screen.findByRole('button', {
        name: /regenerateConfirmAction/,
      })
      fireEvent.click(confirmButton)

      await waitFor(() => {
        expect(mockRegenerateClosureReport).toHaveBeenCalledWith('closure-1')
      })
      await waitFor(() => {
        expect(window.open).toHaveBeenCalled()
      })
    })
  })

  // --------------------------------------------------------------------------
  // Vista previa con recharts (Req 9.3)
  // --------------------------------------------------------------------------

  describe('Vista previa (recharts)', () => {
    it('consume getClosureReportData y renderiza los gráficos al abrir la vista previa', async () => {
      renderComponent(false)

      fireEvent.click(screen.getByRole('button', { name: /showPreview/ }))

      await waitFor(() => {
        expect(mockGetClosureReportData).toHaveBeenCalledWith('closure-1')
      })

      // Títulos de las secciones de gráficos. `tiersCompositionTitle` se reutiliza para el
      // gráfico de composición y para la tabla de desglose, por eso hay ≥1 ocurrencia.
      await waitFor(() => {
        expect(screen.getAllByText('tiersCompositionTitle').length).toBeGreaterThanOrEqual(1)
      })
      expect(screen.getByText('historyEvolutionTitle')).toBeInTheDocument()

      // Series de recharts (por dataKey) — composición de tramos y evolución histórica.
      expect(screen.getByTestId('series-ips')).toBeInTheDocument()
      expect(screen.getByTestId('series-billable')).toBeInTheDocument()
      expect(screen.getByTestId('series-amount')).toBeInTheDocument()

      // El texto del análisis IA se muestra cuando existe.
      expect(screen.getByText('Resumen ejecutivo del ciclo.')).toBeInTheDocument()
    })

    it('muestra el aviso fail-safe en la vista previa cuando ai_analysis es null', async () => {
      mockGetClosureReportData.mockResolvedValue(createReportData({ ai_analysis: null }))

      renderComponent(false)
      fireEvent.click(screen.getByRole('button', { name: /showPreview/ }))

      const alert = await screen.findByText('aiAnalysisUnavailable')
      expect(alert).toBeInTheDocument()
    })

    it('muestra la tabla de desglose por tramo con los tramos con IPs', async () => {
      renderComponent(false)
      fireEvent.click(screen.getByRole('button', { name: /showPreview/ }))

      // Esperar a que cargue la vista previa.
      await screen.findByText('historyEvolutionTitle')

      // Etiquetas de valores de la tabla de tramos (from de cada tramo con ips > 0).
      const dialog = screen.getByRole('dialog')
      expect(within(dialog).getByText('8')).toBeInTheDocument() // ips_in_tier tramo 1
      expect(within(dialog).getByText('4')).toBeInTheDocument() // ips_in_tier tramo 2
    })
  })
})
