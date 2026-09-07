/**
 * Tests de "Días inactiva" y "Última conexión" para StaleWorkstationsSection.
 *
 * Verifica (a través del componente RENDERIZADO, sin exportar internals):
 * - "Días inactiva" se calcula desde `ws.last_seen` (NO `updated_at`): una estación con
 *   `last_seen` de hace ~200 días muestra `200d`, tanto en la vista tabla como en cards
 *   (Req 3.1, 3.2).
 * - "Última conexión" muestra el valor de `ws.last_seen` (NO `updated_at`) en cards y tabla
 *   (Req 4.1, 4.2).
 *
 * Validates: Requirements 3.1, 3.2, 4.1, 4.2
 *
 * Notas sobre jsdom / mocks:
 * - next-intl: se mockea `useTranslations` devolviendo la key (con interpolación simple de
 *   params como `key days:90`) — mismo patrón que los tests existentes del repo.
 * - useAuth: `isAdmin` es una función (el componente la invoca como `isAdmin()`); se mockea
 *   para devolver false (operador) y así evitar la carga de organizaciones.
 * - @/lib/api: se mockean `workstationsApi.listStale` (fuente de datos) y `organizationsApi.list`.
 * - Se usa un `last_seen` de hace 200 días + 12h de margen para que `Math.floor` sea 200 de
 *   forma estable (evita flakiness en el borde exacto del día).
 * - El componente distingue "Última conexión" de "Registrada" usando `last_seen` vs
 *   `created_at`; se eligen fechas con día/hora distintos para poder afirmar que la columna
 *   "Última conexión" refleja `last_seen` y no `updated_at`/`created_at`.
 */

import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { Workstation } from '@/types/workstation'
import type { WorkstationListResponse } from '@/types/workstation'

// ============================================================================
// MOCKS
// ============================================================================

// next-intl: la key se devuelve tal cual; los params se anexan como `key days:90`.
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

// useAuth: operador (isAdmin() === false) → no carga organizaciones.
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ isAdmin: () => false }),
}))

// Cliente API tipado (@/lib/api).
const mockListStale = vi.fn()
const mockOrganizationsList = vi.fn()
vi.mock('@/lib/api', () => ({
  workstationsApi: {
    listStale: (...args: unknown[]) => mockListStale(...args),
  },
  organizationsApi: {
    list: (...args: unknown[]) => mockOrganizationsList(...args),
  },
}))

// Importar el componente después de los mocks.
import { StaleWorkstationsSection } from '../StaleWorkstationsSection'

// ============================================================================
// HELPERS
// ============================================================================

const TIMEZONE = 'America/Lima' // UTC-5 (zona de BBVA)
const DAY_MS = 86_400_000

/** Timestamp ISO (UTC con sufijo Z) para hace `days` días + `extraHours` horas. */
function isoDaysAgo(days: number, extraHours = 0): string {
  const ms = Date.now() - days * DAY_MS - extraHours * 3_600_000
  return new Date(ms).toISOString()
}

/**
 * Replica el formateo del componente (`formatDateTimeInOrgTz`) para calcular la cadena
 * esperada de "Última conexión"/"Registrada" en la zona de la organización.
 */
function expectedFormatted(dateStr: string, timeZone: string): string {
  const utc = dateStr.endsWith('Z') ? dateStr : `${dateStr}Z`
  return new Intl.DateTimeFormat(undefined, {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(utc))
}

function createWorkstation(overrides: Partial<Workstation> = {}): Workstation {
  // last_seen: hace 200 días (+12h de margen) → "Días inactiva" = 200d.
  // updated_at: reciente → si el componente lo usara (BUG), "Días inactiva" sería 0d.
  return {
    id: 'ws-1',
    organization_id: 'org-1',
    vlan_id: null,
    ip_private: '10.0.0.5',
    hostname: 'w1035401p19',
    os_serial: null,
    current_user: 'P008967',
    is_online: false,
    contingency_active: false,
    forced_contingency: false,
    worker_id: null,
    billing_status: 'active' as Workstation['billing_status'],
    last_connection: null,
    first_seen: isoDaysAgo(400),
    created_at: isoDaysAgo(300, 6),
    updated_at: isoDaysAgo(0, 1), // reciente (trampa para el bug)
    last_seen: isoDaysAgo(200, 12),
    cidr: null,
    tray_version: null,
    action_config_name: null,
    action_config_hash: null,
    action_config_version: null,
    default_printer_id: null,
    organization: {
      id: 'org-1',
      name: 'BBVA',
      is_active: true,
      timezone: TIMEZONE,
      language: 'es',
      auto_update_enabled: false,
      target_version: null,
      auto_reregister_enabled: false,
      forced_contingency: false,
      action_config_mandatory: false,
      offline_timeout_minutes: 5,
      jitter_window_seconds: 60,
      created_at: isoDaysAgo(500),
      updated_at: isoDaysAgo(500),
    },
    ...overrides,
  }
}

function listResponse(items: Workstation[]): WorkstationListResponse {
  return { items, total: items.length, skip: 0, limit: 20 }
}

// ============================================================================
// TESTS
// ============================================================================

describe('StaleWorkstationsSection — Días inactiva y Última conexión', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockOrganizationsList.mockResolvedValue([])
  })

  it('calcula "Días inactiva" desde last_seen (200d) en la vista tabla', async () => {
    const ws = createWorkstation()
    mockListStale.mockResolvedValue(listResponse([ws]))

    render(<StaleWorkstationsSection />)

    // La vista por defecto es tabla; el badge de días muestra "200d".
    const badge = await screen.findByText('200d')
    expect(badge).toBeInTheDocument()

    // Sanity: si usara updated_at (reciente) mostraría "0d" → no debe aparecer.
    expect(screen.queryByText('0d')).not.toBeInTheDocument()
  })

  it('muestra "Última conexión" con el valor de last_seen en la tabla (no updated_at)', async () => {
    const ws = createWorkstation()
    mockListStale.mockResolvedValue(listResponse([ws]))

    render(<StaleWorkstationsSection />)

    await screen.findByText('200d')

    const lastSeenText = expectedFormatted(ws.last_seen, TIMEZONE)
    const updatedText = expectedFormatted(ws.updated_at, TIMEZONE)

    // La celda de "Última conexión" refleja last_seen...
    expect(screen.getByText(lastSeenText)).toBeInTheDocument()
    // ...y NO el updated_at reciente (que sería el bug).
    expect(screen.queryByText(updatedText)).not.toBeInTheDocument()
  })

  it('calcula "Días inactiva" desde last_seen (200d) también en la vista cards', async () => {
    const ws = createWorkstation()
    mockListStale.mockResolvedValue(listResponse([ws]))

    render(<StaleWorkstationsSection />)

    // Esperar a la primera carga (tabla) y luego cambiar a vista cards.
    await screen.findByText('200d')

    // Cambiar a cards con el botón de vista (title = viewCards, key i18n).
    const cardsButton = screen.getByRole('button', { name: 'viewCards' })
    fireEvent.click(cardsButton)

    // En cards el badge muestra "200d staleColInactiveDays" (key en minúscula).
    await waitFor(() => {
      expect(screen.getByText(/^200d\b/)).toBeInTheDocument()
    })
  })

  it('muestra "Última conexión" con el valor de last_seen en cards (footer)', async () => {
    const ws = createWorkstation()
    mockListStale.mockResolvedValue(listResponse([ws]))

    render(<StaleWorkstationsSection />)
    await screen.findByText('200d')

    const cardsButton = screen.getByRole('button', { name: 'viewCards' })
    fireEvent.click(cardsButton)

    const lastSeenText = expectedFormatted(ws.last_seen, TIMEZONE)

    // El footer de la card muestra "staleColLastSeen: <last_seen formateado>".
    await waitFor(() => {
      const matches = screen.getAllByText((_, el) =>
        (el?.textContent ?? '').includes(`staleColLastSeen: ${lastSeenText}`)
      )
      expect(matches.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('pasa last_seen/asc por defecto a listStale (sanity del wiring de datos)', async () => {
    const ws = createWorkstation()
    mockListStale.mockResolvedValue(listResponse([ws]))

    render(<StaleWorkstationsSection />)
    await screen.findByText('200d')

    expect(mockListStale).toHaveBeenCalledWith(
      expect.objectContaining({ sort_by: 'last_seen', sort_dir: 'asc' })
    )
  })
})
