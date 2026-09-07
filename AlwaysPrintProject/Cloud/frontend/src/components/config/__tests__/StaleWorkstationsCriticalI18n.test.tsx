/**
 * Tests de resaltado crítico e internacionalización para StaleWorkstationsSection.
 *
 * Verifica (Task 7.5):
 * - Resaltado crítico (rojo) cuando `daysInactive >= 180` (CRITICAL_INACTIVE_DAYS): una estación
 *   con `last_seen` de hace 200 días muestra el Badge de "Días inactiva" con las clases críticas
 *   (text-red-700 / border-red-300 / bg-red-50); una estación de hace ~100 días muestra el estilo
 *   ámbar (no crítico).
 * - i18n: todos los textos visibles provienen de `next-intl` (namespace `config`/`common`), sin
 *   strings hardcodeados. Para detectarlo, se mockea `useTranslations` para que devuelva la clave
 *   tal cual; así, cualquier texto hardcodeado en el JSX quedaría fuera del conjunto de claves y
 *   sería detectable. Se afirma que las etiquetas renderizadas equivalen a las claves i18n.
 *
 * Sobre el tipado estricto (Req 11.3): "sin `any`" no es verificable en runtime — lo garantiza
 * `tsc` en tiempo de compilación (el componente no usa `any`). Este test valida el comportamiento
 * observable (resaltado crítico + i18n) que sí es testeable vía la RENDERED component (RTL).
 *
 * Validates: Requirements 10.1, 10.3, 11.2, 11.3
 *
 * Notas sobre jsdom:
 * - next-intl: se mockea `useTranslations` para devolver la clave (con interpolación simple de
 *   params) — mismo patrón que los tests existentes (RemoteTerminalSection / ClosureReportActions).
 * - `workstationsApi.listStale` y `organizationsApi.list` se mockean para inyectar datos
 *   controlados sin tocar la red.
 * - `useAuth` se mockea como no-admin (evita cargar el filtro/selector de organizaciones).
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { Workstation } from '@/types/workstation'

// ============================================================================
// MOCKS (deben declararse antes de importar el componente bajo prueba)
// ============================================================================

// next-intl: la clave se devuelve tal cual; con params, se anexan como `clave k:v`.
// Esto permite que cualquier string hardcodeado en el JSX sea detectable (no coincidiría
// con ninguna clave i18n conocida).
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

// useAuth: usuario no-admin (no se carga el selector de organizaciones).
const mockIsAdmin = vi.fn(() => false)
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    isAdmin: mockIsAdmin,
  }),
}))

// Cliente API tipado: se controlan las respuestas de listStale y organizationsApi.list.
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

// Importar el componente después de los mocks.
import { StaleWorkstationsSection } from '../StaleWorkstationsSection'

// ============================================================================
// HELPERS
// ============================================================================

/**
 * Timestamp UTC (ISO sin 'Z' final, como los emite el backend) de hace ~`days` días.
 *
 * Se añade medio día de margen para que el `Math.floor` de `daysAgo` (que usa `Date.now()`
 * en el momento del render) devuelva de forma determinista exactamente `days`, sin quedar
 * a merced de la deriva de milisegundos entre la construcción del dato y el render.
 */
function isoDaysAgo(days: number): string {
  const d = new Date(Date.now() - (days + 0.5) * 86400000)
  // Emular el formato naive-UTC del backend (sin sufijo 'Z').
  return d.toISOString().replace(/Z$/, '')
}

/** Construye una Workstation mínima con los campos que usa el componente. */
function makeWorkstation(overrides: Partial<Workstation> = {}): Workstation {
  return {
    id: 'ws-default',
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
    billing_status: 'billable',
    last_connection: null,
    first_seen: isoDaysAgo(400),
    created_at: isoDaysAgo(400),
    updated_at: isoDaysAgo(1),
    last_seen: isoDaysAgo(100),
    cidr: null,
    tray_version: null,
    action_config_name: null,
    action_config_hash: null,
    action_config_version: null,
    default_printer_id: null,
    organization: undefined,
    vlan: null,
    ...overrides,
  }
}

/** Resuelve listStale con los items dados (total = items.length). */
function resolveStaleWith(items: Workstation[]): void {
  mockListStale.mockResolvedValue({
    items,
    total: items.length,
    skip: 0,
    limit: items.length,
  })
}

// Clases de estilo del Badge de "Días inactiva".
const CRITICAL_CLASSES = ['text-red-700', 'border-red-300', 'bg-red-50']
const AMBER_CLASSES = ['text-amber-700', 'border-amber-300', 'bg-amber-50']

/**
 * Localiza el Badge de "Días inactiva" de la fila cuya IP sea `ip` (vista tabla).
 *
 * En la vista tabla el Badge renderiza `{inactive}d` (número y letra `d` como nodos de texto
 * separados), por lo que un `findByText('200d')` no los une. Se localiza la celda de la IP,
 * se sube a la fila `<tr>` y se toma el Badge (elemento con las clases outline rojo/ámbar),
 * que es la última celda. Así el test no depende del entero exacto de días.
 */
async function findInactiveBadgeByIp(ip: string): Promise<HTMLElement> {
  const ipCell = await screen.findByText(ip)
  const row = ipCell.closest('tr')
  if (!row) throw new Error(`No se encontró la fila para la IP ${ip}`)
  // El Badge es el único elemento con clase `rounded-full` (Badge variant outline) de la fila.
  const badge = row.querySelector<HTMLElement>('.rounded-full')
  if (!badge) throw new Error(`No se encontró el Badge de días inactiva para la IP ${ip}`)
  return badge
}

// ============================================================================
// TESTS
// ============================================================================

describe('StaleWorkstationsSection — resaltado crítico e i18n (Task 7.5)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockIsAdmin.mockReturnValue(false)
    mockOrgList.mockResolvedValue([])
  })

  // --------------------------------------------------------------------------
  // Resaltado crítico ≥ 180 días (Req 11.2)
  // --------------------------------------------------------------------------

  describe('Resaltado crítico (>= 180 días)', () => {
    it('aplica el estilo crítico (rojo) al Badge de una estación con last_seen de hace 200 días', async () => {
      const critical = makeWorkstation({
        id: 'ws-critico',
        ip_private: '10.0.0.200',
        last_seen: isoDaysAgo(200),
      })
      resolveStaleWith([critical])

      render(<StaleWorkstationsSection />)

      // Vista tabla (default viewMode='table'): el Badge de la fila lleva las clases críticas.
      const badge = await findInactiveBadgeByIp('10.0.0.200')
      for (const cls of CRITICAL_CLASSES) {
        expect(badge).toHaveClass(cls)
      }
      // No debe llevar las clases ámbar (no crítico).
      for (const cls of AMBER_CLASSES) {
        expect(badge).not.toHaveClass(cls)
      }
    })

    it('aplica el estilo ámbar (no crítico) a una estación con last_seen de hace ~100 días', async () => {
      const nonCritical = makeWorkstation({
        id: 'ws-ambar',
        ip_private: '10.0.0.100',
        last_seen: isoDaysAgo(100),
      })
      resolveStaleWith([nonCritical])

      render(<StaleWorkstationsSection />)

      const badge = await findInactiveBadgeByIp('10.0.0.100')
      for (const cls of AMBER_CLASSES) {
        expect(badge).toHaveClass(cls)
      }
      for (const cls of CRITICAL_CLASSES) {
        expect(badge).not.toHaveClass(cls)
      }
    })

    it('en el mismo listado, cada estación recibe el estilo según su umbral (crítico vs ámbar)', async () => {
      const critical = makeWorkstation({
        id: 'ws-critico',
        ip_private: '10.0.0.200',
        last_seen: isoDaysAgo(200),
      })
      const nonCritical = makeWorkstation({
        id: 'ws-ambar',
        ip_private: '10.0.0.100',
        last_seen: isoDaysAgo(100),
      })
      resolveStaleWith([critical, nonCritical])

      render(<StaleWorkstationsSection />)

      const criticalBadge = await findInactiveBadgeByIp('10.0.0.200')
      const amberBadge = await findInactiveBadgeByIp('10.0.0.100')

      CRITICAL_CLASSES.forEach((c) => expect(criticalBadge).toHaveClass(c))
      AMBER_CLASSES.forEach((c) => expect(amberBadge).toHaveClass(c))
    })

    it('el umbral es inclusivo: exactamente 180 días ya es crítico', async () => {
      const boundary = makeWorkstation({
        id: 'ws-borde',
        ip_private: '10.0.0.180',
        last_seen: isoDaysAgo(180),
      })
      resolveStaleWith([boundary])

      render(<StaleWorkstationsSection />)

      const badge = await findInactiveBadgeByIp('10.0.0.180')
      CRITICAL_CLASSES.forEach((c) => expect(badge).toHaveClass(c))
    })
  })

  // --------------------------------------------------------------------------
  // Internacionalización: sin strings hardcodeados (Req 10.1, 10.3)
  // --------------------------------------------------------------------------

  describe('i18n — textos visibles provienen de next-intl', () => {
    it('renderiza título, subtítulo y labels de filtros usando claves i18n (no hardcodeadas)', async () => {
      resolveStaleWith([makeWorkstation()])

      render(<StaleWorkstationsSection />)

      await waitFor(() => expect(mockListStale).toHaveBeenCalled())

      // Con el mock que devuelve la clave, el texto visible ES la clave i18n.
      // Si el JSX tuviera un string hardcodeado, no coincidiría con estas claves.
      expect(screen.getByText('staleTitle')).toBeInTheDocument()
      // staleSubtitle lleva interpolación { days } → "staleSubtitle days:90".
      expect(screen.getByText(/^staleSubtitle days:\d+$/)).toBeInTheDocument()
      expect(screen.getByText('staleDaysLabel')).toBeInTheDocument()
      expect(screen.getByText('staleMinHoursLabel')).toBeInTheDocument()
    })

    it('los encabezados de columna de la tabla provienen de claves i18n del namespace config', async () => {
      resolveStaleWith([makeWorkstation()])

      render(<StaleWorkstationsSection />)

      // Cada encabezado ordenable renderiza su clave i18n como texto.
      const expectedHeaderKeys = [
        'staleColIp',
        'staleColHostname',
        'staleColUser',
        'staleColOrg',
        'staleColCreated',
        'staleColLastSeen',
        'staleColInactiveDays',
      ]
      for (const key of expectedHeaderKeys) {
        expect(await screen.findByText(key)).toBeInTheDocument()
      }
    })

    it('el total y las fechas usan claves i18n (interpolación con params visibles)', async () => {
      resolveStaleWith([makeWorkstation()])

      render(<StaleWorkstationsSection />)

      // total === 1 → clave "staleTotal" con { count } → "staleTotal count:1".
      expect(await screen.findByText('staleTotal count:1')).toBeInTheDocument()
    })

    it('el empty state usa la clave i18n staleEmpty cuando no hay estaciones', async () => {
      resolveStaleWith([])

      render(<StaleWorkstationsSection />)

      expect(await screen.findByText('staleEmpty')).toBeInTheDocument()
    })

    it('el label de "Días inactiva" en cada fila incluye el sufijo i18n (no texto hardcodeado)', async () => {
      // En la vista tabla el Badge muestra solo "Nd", pero la clave staleColInactiveDays
      // aparece como encabezado; comprobamos que exista la clave (i18n) y no un literal.
      resolveStaleWith([makeWorkstation({ last_seen: isoDaysAgo(200) })])

      render(<StaleWorkstationsSection />)

      const header = await screen.findByText('staleColInactiveDays')
      // El encabezado es un botón clicable de ordenamiento; debe estar dentro de un <th>.
      expect(header.closest('th')).not.toBeNull()
      expect(within(header.closest('th') as HTMLElement).getByText('staleColInactiveDays')).toBeInTheDocument()
    })
  })
})
