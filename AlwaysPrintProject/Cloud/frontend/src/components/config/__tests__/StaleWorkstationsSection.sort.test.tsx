/**
 * Tests de ordenamiento server-side e indicador de columna activa para
 * StaleWorkstationsSection (Task 7.3).
 *
 * Verifica sobre el componente RENDERIZADO (RTL):
 * - Al clicar un encabezado de columna se invoca `workstationsApi.listStale`
 *   con el `sort_by` correspondiente, `sort_dir='asc'` y `page=1`.
 * - Al volver a clicar el mismo encabezado, `sort_dir` togglea a `desc`
 *   (misma columna) manteniendo `page=1`.
 * - El indicador de dirección de la columna activa refleja `sortBy`/`sortDir`
 *   (icono ArrowUp para asc / ArrowDown para desc) y `aria-sort` acorde.
 *
 * Requisitos: 8.5, 8.13, 8.14
 *
 * Notas sobre mocks:
 * - next-intl: `useTranslations` devuelve la key tal cual (mismo patrón que
 *   RemoteTerminalSection / system-status).
 * - useAuth: usuario admin por defecto (no altera el flujo de sort).
 * - workstationsApi.listStale / organizationsApi.list: mockeadas como spies.
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { Workstation } from '@/types/workstation'

// ============================================================================
// MOCKS
// ============================================================================

// next-intl: retorna la key como texto (con interpolación mínima ignorada).
vi.mock('next-intl', () => ({
  useTranslations: () => {
    const t = (key: string) => key
    return t
  },
}))

// useAuth: admin por defecto. El ordenamiento no depende del rol, pero el
// componente llama a isAdmin() para decidir la carga de organizaciones.
const mockIsAdmin = vi.fn(() => true)
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    isAdmin: mockIsAdmin,
  }),
}))

// api: listStale y organizationsApi.list como spies controlables.
const mockListStale = vi.fn()
const mockOrgList = vi.fn()
vi.mock('@/lib/api', () => ({
  workstationsApi: {
    listStale: (...args: unknown[]) => mockListStale(...args),
  },
  organizationsApi: {
    list: (...args: unknown[]) => mockOrgList(...args),
  },
}))

// Importar el componente DESPUÉS de declarar los mocks.
import { StaleWorkstationsSection } from '../StaleWorkstationsSection'

// ============================================================================
// HELPERS
// ============================================================================

/** Construye una estación inactiva mínima pero completa para la respuesta. */
function makeStation(overrides: Partial<Workstation> = {}): Workstation {
  return {
    id: 'ws-1',
    organization_id: 'org-1',
    vlan_id: null,
    ip_private: '10.0.0.1',
    hostname: 'w1035401p19',
    os_serial: null,
    current_user: 'P008967',
    is_online: false,
    contingency_active: false,
    forced_contingency: false,
    worker_id: null,
    billing_status: 'active' as Workstation['billing_status'],
    last_connection: null,
    first_seen: '2024-01-01T00:00:00',
    created_at: '2024-01-01T00:00:00',
    updated_at: '2024-06-01T00:00:00',
    last_seen: '2024-01-10T00:00:00',
    cidr: null,
    tray_version: null,
    action_config_name: null,
    action_config_hash: null,
    action_config_version: null,
    default_printer_id: null,
    organization: { id: 'org-1', name: 'BBVA', timezone: 'America/Lima' } as Workstation['organization'],
    vlan: null,
    ...overrides,
  }
}

/** Respuesta con al menos una fila para forzar el render de la tabla. */
function staleResponse(items: Workstation[]) {
  return { items, total: items.length, skip: 0, limit: 20 }
}

/** Devuelve el objeto de params de la última llamada a listStale. */
function lastStaleParams(): Record<string, unknown> {
  const calls = mockListStale.mock.calls
  return calls[calls.length - 1][0] as Record<string, unknown>
}

// ============================================================================
// TESTS
// ============================================================================

describe('StaleWorkstationsSection — ordenamiento e indicador de columna activa', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockIsAdmin.mockReturnValue(true)
    mockOrgList.mockResolvedValue([])
    mockListStale.mockResolvedValue(staleResponse([makeStation()]))
  })

  it('clic en un encabezado dispara refetch con sort_by, sort_dir=asc y page=1', async () => {
    render(<StaleWorkstationsSection />)

    // Espera el fetch inicial (default last_seen/asc).
    await waitFor(() => expect(mockListStale).toHaveBeenCalled())
    mockListStale.mockClear()

    // Clic en el encabezado "IP" (columna que no es la activa por defecto).
    const ipHeader = screen.getByRole('button', { name: 'staleColIp' })
    fireEvent.click(ipHeader)

    await waitFor(() => expect(mockListStale).toHaveBeenCalled())
    const params = lastStaleParams()
    expect(params.sort_by).toBe('ip')
    expect(params.sort_dir).toBe('asc')
    expect(params.page).toBe(1)
  })

  it('segundo clic en la misma columna togglea sort_dir a desc manteniendo page=1', async () => {
    render(<StaleWorkstationsSection />)
    await waitFor(() => expect(mockListStale).toHaveBeenCalled())

    // Primer clic: hostname asc.
    const hostnameHeader = screen.getByRole('button', { name: 'staleColHostname' })
    fireEvent.click(hostnameHeader)
    await waitFor(() => expect(lastStaleParams().sort_by).toBe('hostname'))
    expect(lastStaleParams().sort_dir).toBe('asc')

    mockListStale.mockClear()

    // Segundo clic en la MISMA columna: togglea a desc.
    // El aria-label de la columna activa cambia a staleSortedBy, así que lo
    // localizamos por el texto de encabezado que sigue presente.
    fireEvent.click(screen.getByText('staleColHostname').closest('button')!)

    await waitFor(() => expect(mockListStale).toHaveBeenCalled())
    const params = lastStaleParams()
    expect(params.sort_by).toBe('hostname')
    expect(params.sort_dir).toBe('desc')
    expect(params.page).toBe(1)
  })

  it('el indicador de columna activa refleja sortBy/sortDir (asc → ArrowUp, desc → ArrowDown)', async () => {
    render(<StaleWorkstationsSection />)
    await waitFor(() => expect(mockListStale).toHaveBeenCalled())

    // Activar la columna "usuario" en asc.
    const userHeader = screen.getByRole('button', { name: 'staleColUser' })
    fireEvent.click(userHeader)

    // La celda th activa debe reportar aria-sort=ascending.
    await waitFor(() => {
      const th = screen.getByText('staleColUser').closest('th')!
      expect(th).toHaveAttribute('aria-sort', 'ascending')
    })

    // Toggle a desc.
    fireEvent.click(screen.getByText('staleColUser').closest('button')!)

    await waitFor(() => {
      const th = screen.getByText('staleColUser').closest('th')!
      expect(th).toHaveAttribute('aria-sort', 'descending')
    })

    // Las columnas no activas no deben tener orden.
    const ipTh = screen.getByText('staleColIp').closest('th')!
    expect(ipTh).toHaveAttribute('aria-sort', 'none')
  })
})
