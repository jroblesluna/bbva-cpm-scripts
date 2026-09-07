/**
 * Tests de formateo de fecha+hora en la zona horaria de la organización para
 * StaleWorkstationsSection (Task 7.2).
 *
 * Verifica que las fechas `created_at` (Registrada) y `last_seen` (Última conexión)
 * se convierten a la zona horaria de la ORGANIZACIÓN (ej. America/Lima, UTC-5 para
 * BBVA) tanto en el footer de las cards como en la tabla, y NUNCA a la zona del
 * navegador que corre los tests.
 *
 * Estrategia:
 * - Se testea a través del componente RENDERIZADO (RTL); no se exportan internos.
 * - `listStale` se mockea para devolver un item con timestamps UTC conocidos y
 *   `organization.timezone = 'America/Lima'` (UTC-5, distinta de la zona del runner).
 * - El valor esperado se calcula con `Intl.DateTimeFormat` usando la zona de la
 *   organización, de modo que la aserción no depende del locale del entorno.
 * - Para probar que NO se usa la zona del navegador, se compara contra el resultado
 *   que produciría la zona por defecto del runner (UTC en jsdom/CI): ambos difieren
 *   porque UTC-5 mueve la fecha al día anterior en la noche.
 *
 * Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { Workstation } from '@/types/workstation'
import type { Organization } from '@/types/organization'

// ============================================================================
// MOCKS
// ============================================================================

// next-intl: la key se devuelve tal cual (con interpolación simple de params),
// mismo patrón que los tests existentes del proyecto.
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

// useAuth: operador (no admin) para evitar la carga de organizaciones y el filtro admin.
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    isAdmin: () => false,
  }),
}))

// Cliente API tipado (@/lib/api). Sólo importa `listStale` para este componente;
// `organizationsApi.list` no se invoca porque isAdmin() === false.
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
// CONSTANTES / HELPERS
// ============================================================================

/**
 * Timestamps del backend: UTC naive (sin sufijo 'Z'), tal como llegan realmente.
 * Se eligen horas de la NOCHE UTC para que la conversión a UTC-5 caiga en el día
 * anterior, garantizando que la fecha en zona de la organización difiera de la
 * fecha en UTC (zona del runner). Así se demuestra que NO se usa la zona del navegador.
 */
const CREATED_AT_UTC = '2026-03-15T02:30:00'
const LAST_SEEN_UTC = '2026-09-10T04:45:00'

/** Zona de la organización (BBVA → America/Lima, UTC-5), distinta de la del runner (UTC). */
const ORG_TIMEZONE = 'America/Lima'

/**
 * Reproduce el formateo del componente para una zona dada. El componente añade 'Z'
 * si falta (interpreta el timestamp como UTC) y usa estos mismos campos de formato.
 */
function formatInTz(dateStr: string, timeZone: string): string {
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

function createOrganization(overrides: Partial<Organization> = {}): Organization {
  return {
    id: 'org-bbva',
    name: 'BBVA',
    description: null,
    is_active: true,
    timezone: ORG_TIMEZONE,
    language: 'es',
    auto_update_enabled: false,
    target_version: null,
    auto_reregister_enabled: false,
    forced_contingency: false,
    action_config_mandatory: false,
    offline_timeout_minutes: 5,
    jitter_window_seconds: 0,
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:00:00',
    ...overrides,
  }
}

function createWorkstation(overrides: Partial<Workstation> = {}): Workstation {
  return {
    id: 'ws-1',
    organization_id: 'org-bbva',
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
    first_seen: '2026-01-01T00:00:00',
    created_at: CREATED_AT_UTC,
    updated_at: '2026-09-20T12:00:00',
    last_seen: LAST_SEEN_UTC,
    cidr: null,
    tray_version: null,
    action_config_name: null,
    action_config_hash: null,
    action_config_version: null,
    default_printer_id: null,
    organization: createOrganization(),
    vlan: null,
    ...overrides,
  }
}

function mockOneStaleItem(ws: Workstation) {
  mockListStale.mockResolvedValue({ items: [ws], total: 1, skip: 0, limit: 20 })
}

// ============================================================================
// TESTS
// ============================================================================

describe('StaleWorkstationsSection — formateo en zona horaria de la organización', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // --------------------------------------------------------------------------
  // Precondición del test: la zona de la organización produce una salida distinta
  // a la zona del runner. Si el runner ya estuviera en UTC-5 el test perdería valor.
  // --------------------------------------------------------------------------
  it('las fechas esperadas en zona de la organización difieren de la zona UTC del runner', () => {
    const expectedOrgCreated = formatInTz(CREATED_AT_UTC, ORG_TIMEZONE)
    const expectedUtcCreated = formatInTz(CREATED_AT_UTC, 'UTC')
    const expectedOrgLastSeen = formatInTz(LAST_SEEN_UTC, ORG_TIMEZONE)
    const expectedUtcLastSeen = formatInTz(LAST_SEEN_UTC, 'UTC')

    // Los timestamps nocturnos UTC caen en el día anterior a UTC-5 → cadenas distintas.
    expect(expectedOrgCreated).not.toBe(expectedUtcCreated)
    expect(expectedOrgLastSeen).not.toBe(expectedUtcLastSeen)
  })

  // --------------------------------------------------------------------------
  // Tabla (vista por defecto): created_at y last_seen en zona de la organización.
  // --------------------------------------------------------------------------
  it('en la tabla muestra created_at y last_seen convertidos a la zona de la organización (UTC-5)', async () => {
    mockOneStaleItem(createWorkstation())

    render(<StaleWorkstationsSection />)

    const expectedOrgCreated = formatInTz(CREATED_AT_UTC, ORG_TIMEZONE)
    const expectedOrgLastSeen = formatInTz(LAST_SEEN_UTC, ORG_TIMEZONE)

    // Espera a que el fetch resuelva y la fila se pinte con las fechas en UTC-5.
    await waitFor(() => {
      expect(screen.getByText(expectedOrgCreated)).toBeInTheDocument()
    })
    expect(screen.getByText(expectedOrgLastSeen)).toBeInTheDocument()

    // Y NO debe usar la zona del navegador (UTC): esas cadenas no aparecen.
    const utcCreated = formatInTz(CREATED_AT_UTC, 'UTC')
    const utcLastSeen = formatInTz(LAST_SEEN_UTC, 'UTC')
    expect(screen.queryByText(utcCreated)).not.toBeInTheDocument()
    expect(screen.queryByText(utcLastSeen)).not.toBeInTheDocument()
  })

  // --------------------------------------------------------------------------
  // Cards (footer): mismas fechas en zona de la organización tras cambiar de vista.
  // --------------------------------------------------------------------------
  it('en el footer de las cards muestra created_at y last_seen en la zona de la organización (UTC-5)', async () => {
    mockOneStaleItem(createWorkstation())

    render(<StaleWorkstationsSection />)

    // Cambiar a la vista de cards (por defecto es tabla). El toggle usa title tCommon('viewCards').
    const cardsToggle = screen.getByTitle('viewCards')
    fireEvent.click(cardsToggle)

    const expectedOrgCreated = formatInTz(CREATED_AT_UTC, ORG_TIMEZONE)
    const expectedOrgLastSeen = formatInTz(LAST_SEEN_UTC, ORG_TIMEZONE)

    // El footer usa prefijos i18n: "staleColLastSeen: <fecha>" / "staleColCreated: <fecha>".
    await waitFor(() => {
      expect(
        screen.getByText(`staleColCreated: ${expectedOrgCreated}`)
      ).toBeInTheDocument()
    })
    expect(
      screen.getByText(`staleColLastSeen: ${expectedOrgLastSeen}`)
    ).toBeInTheDocument()

    // No usa la zona del navegador (UTC).
    const utcCreated = formatInTz(CREATED_AT_UTC, 'UTC')
    const utcLastSeen = formatInTz(LAST_SEEN_UTC, 'UTC')
    expect(
      screen.queryByText(`staleColCreated: ${utcCreated}`)
    ).not.toBeInTheDocument()
    expect(
      screen.queryByText(`staleColLastSeen: ${utcLastSeen}`)
    ).not.toBeInTheDocument()
  })

  // --------------------------------------------------------------------------
  // Fallback: sin timezone en la organización → UTC (nunca la zona del navegador).
  // --------------------------------------------------------------------------
  it('cuando la organización no define timezone, formatea en UTC (fallback), no en la zona del navegador', async () => {
    const ws = createWorkstation({
      organization: createOrganization({ timezone: undefined as unknown as string }),
    })
    mockOneStaleItem(ws)

    render(<StaleWorkstationsSection />)

    const expectedUtcCreated = formatInTz(CREATED_AT_UTC, 'UTC')
    const expectedUtcLastSeen = formatInTz(LAST_SEEN_UTC, 'UTC')

    await waitFor(() => {
      expect(screen.getByText(expectedUtcCreated)).toBeInTheDocument()
    })
    expect(screen.getByText(expectedUtcLastSeen)).toBeInTheDocument()
  })
})
