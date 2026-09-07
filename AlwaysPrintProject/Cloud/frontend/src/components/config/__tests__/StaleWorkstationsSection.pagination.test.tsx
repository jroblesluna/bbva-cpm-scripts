/**
 * Tests de la tarea 7.4: la paginación del reporte de estaciones inactivas
 * no queda tapada por el FAB de información y permanece clicable.
 *
 * Requisitos: 7.1, 7.2, 7.3
 *
 * NOTA sobre el alcance de la verificación:
 * jsdom no calcula layout real (no hay geometría ni z-index efectivo), por lo
 * que NO puede detectar un solapamiento visual verdadero entre el FAB y la
 * paginación. Como proxy verificamos las garantías ESTRUCTURALES que el diseño
 * definió para evitar ese overlap:
 *   - El contenedor raíz del reporte reserva espacio inferior (`pb-24`).
 *   - El bloque de paginación se eleva con un stacking context propio
 *     (`relative z-10`).
 *   - Los controles de paginación están presentes, habilitados y son clicables
 *     (el botón "siguiente" dispara un refetch con `page: 2`).
 * La verificación del overlap pixel-perfect corresponde a pruebas e2e.
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { Workstation } from '@/types/workstation'

// ============================================================================
// MOCKS
// ============================================================================

// Mock next-intl: retorna la key (o la key con params) como texto.
vi.mock('next-intl', () => ({
  useTranslations: () => {
    const t = (key: string) => key
    return t
  },
}))

// Mock useAuth: usuario NO admin para simplificar (no carga organizaciones).
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    isAdmin: () => false,
  }),
}))

// Mock del API client: capturamos las llamadas a listStale para inspeccionar
// los params (page) y controlamos la respuesta (total > pageSize).
const mockListStale = vi.fn()
vi.mock('@/lib/api', () => ({
  workstationsApi: {
    listStale: (...args: unknown[]) => mockListStale(...args),
  },
  organizationsApi: {
    list: vi.fn().mockResolvedValue([]),
  },
}))

// Importar el componente después de los mocks.
import { StaleWorkstationsSection } from '../StaleWorkstationsSection'

// ============================================================================
// HELPERS
// ============================================================================

/** Vista tabla → PAGE_SIZE_TABLE = 20 (default del componente). */
const PAGE_SIZE_TABLE = 20

/** Construye una estación mínima suficiente para renderizar la fila de tabla. */
function makeWorkstation(index: number): Workstation {
  return {
    id: `ws-${index}`,
    ip_private: `10.0.0.${index}`,
    hostname: `host-${index}`,
    current_user: `user-${index}`,
    created_at: '2024-01-01T00:00:00',
    last_seen: '2024-06-01T00:00:00',
    organization: { id: 'org-1', name: 'BBVA', timezone: 'America/Lima' },
  } as unknown as Workstation
}

/**
 * Configura la respuesta del mock: `total` estaciones, devolviendo como máximo
 * `page_size` items para la página solicitada.
 */
function primeListStale(total: number) {
  mockListStale.mockImplementation((params?: { page?: number; page_size?: number }) => {
    const page = params?.page ?? 1
    const pageSize = params?.page_size ?? PAGE_SIZE_TABLE
    const start = (page - 1) * pageSize
    const count = Math.max(0, Math.min(pageSize, total - start))
    const items = Array.from({ length: count }, (_, i) => makeWorkstation(start + i + 1))
    return Promise.resolve({ items, total })
  })
}

// ============================================================================
// TESTS
// ============================================================================

describe('StaleWorkstationsSection - paginación no tapada por el FAB (7.4)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renderiza los controles de paginación cuando total > pageSize', async () => {
    // total = 45 y pageSize = 20 → 3 páginas → la paginación debe renderizarse.
    primeListStale(45)

    render(<StaleWorkstationsSection />)

    // Espera a que termine el fetch inicial y se pinte la tabla.
    await screen.findByText('10.0.0.1')

    // El bloque de paginación muestra "página 1 / 3".
    expect(screen.getByText('1 / 3')).toBeInTheDocument()
  })

  it('el contenedor raíz reserva espacio inferior (pb-24) para no quedar bajo el FAB', async () => {
    primeListStale(45)

    const { container } = render(<StaleWorkstationsSection />)
    await screen.findByText('10.0.0.1')

    // El primer hijo del container es el contenedor raíz del reporte.
    const root = container.firstElementChild
    expect(root).not.toBeNull()
    // Proxy estructural del "reservar espacio inferior" del diseño (Req 7.1).
    expect(root).toHaveClass('pb-24')
  })

  it('el bloque de paginación se eleva con relative z-10 (por encima del FAB)', async () => {
    primeListStale(45)

    render(<StaleWorkstationsSection />)
    await screen.findByText('10.0.0.1')

    // El indicador "1 / 3" vive dentro del bloque de paginación.
    // Subimos hasta el contenedor con las clases de elevación.
    const paginationBlock = screen.getByText('1 / 3').closest('div.relative')
    expect(paginationBlock).not.toBeNull()
    // Proxy estructural del "no quedar cubierta por el FAB" del diseño (Req 7.2).
    expect(paginationBlock).toHaveClass('relative')
    expect(paginationBlock).toHaveClass('z-10')
  })

  it('los controles de paginación están habilitados y son clicables (refetch a page 2)', async () => {
    primeListStale(45)

    render(<StaleWorkstationsSection />)
    await screen.findByText('10.0.0.1')

    // En la página 1: "anterior" deshabilitado, "siguiente" habilitado.
    const buttons = screen.getAllByRole('button')
    // Los dos últimos botones del DOM son las flechas de paginación (prev / next).
    const nextButton = buttons[buttons.length - 1]
    const prevButton = buttons[buttons.length - 2]

    expect(prevButton).toBeDisabled()
    expect(nextButton).not.toBeDisabled()

    // Click en "siguiente" → el componente debe refetch con page: 2 (clicable,
    // es decir NO tapado ni bloqueado por el FAB). Req 7.3.
    fireEvent.click(nextButton)

    await waitFor(() => {
      expect(mockListStale).toHaveBeenCalledWith(
        expect.objectContaining({ page: 2 })
      )
    })

    // Tras avanzar, el indicador refleja la página 2.
    await screen.findByText('2 / 3')
  })
})
