/**
 * Sección de estaciones de trabajo inactivas en la página de configuración.
 * Lista workstations que tuvieron actividad real pero no se han conectado
 * en más de N días (stale detection basada en last_seen, columna real de actividad).
 */

'use client'

import { useState, useEffect } from 'react'
import { useTranslations } from 'next-intl'
import { useAuth } from '@/hooks/useAuth'
import { workstationsApi, organizationsApi } from '@/lib/api'
import type { Workstation } from '@/types/workstation'
import type { Organization } from '@/types'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  LayoutGrid,
  List,
  ChevronLeft,
  ChevronRight,
  Monitor,
  Clock,
  Building2,
  User,
  WifiOff,
  ArrowUp,
  ArrowDown,
  ChevronsUpDown,
  HelpCircle,
} from 'lucide-react'

const PAGE_SIZE_CARDS = 10
const PAGE_SIZE_TABLE = 20

/** Umbral de días de inactividad a partir del cual una estación se resalta como crítica. */
const CRITICAL_INACTIVE_DAYS = 180

/** Columnas admitidas para el ordenamiento server-side del reporte de estaciones inactivas. */
type SortBy =
  | 'ip'
  | 'hostname'
  | 'current_user'
  | 'organizacion'
  | 'created_at'
  | 'last_seen'
  | 'dias_inactiva'

/** Direcciones de ordenamiento admitidas. */
type SortDir = 'asc' | 'desc'

/**
 * Definición de las columnas ordenables de la tabla: clave i18n del encabezado
 * (namespace `config`) y el valor `SortBy` que se envía al backend.
 */
const STALE_TABLE_COLUMNS: ReadonlyArray<{ i18nKey: string; sortBy: SortBy }> = [
  { i18nKey: 'staleColIp', sortBy: 'ip' },
  { i18nKey: 'staleColHostname', sortBy: 'hostname' },
  { i18nKey: 'staleColUser', sortBy: 'current_user' },
  { i18nKey: 'staleColOrg', sortBy: 'organizacion' },
  { i18nKey: 'staleColCreated', sortBy: 'created_at' },
  { i18nKey: 'staleColLastSeen', sortBy: 'last_seen' },
  { i18nKey: 'staleColInactiveDays', sortBy: 'dias_inactiva' },
]

function daysAgo(dateStr: string): number {
  return Math.floor((Date.now() - new Date(dateStr).getTime()) / 86400000)
}

/**
 * Formatea un timestamp del backend (UTC naive) mostrando fecha y hora en la
 * zona horaria de la organización. Nunca usa la zona del navegador.
 *
 * Los timestamps del backend llegan en UTC sin sufijo 'Z'; se añade para que
 * `Date` los interprete como UTC antes de convertirlos a `timeZone`.
 * Si la cadena no es parseable, retorna un guion (retorno seguro).
 */
export function formatDateTimeInOrgTz(dateStr: string, timeZone: string | undefined): string {
  if (!dateStr) return '—'
  const utc = dateStr.endsWith('Z') ? dateStr : `${dateStr}Z`
  const date = new Date(utc)
  if (Number.isNaN(date.getTime())) return '—'
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone: timeZone ?? 'UTC',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).format(date)
  } catch {
    // timeZone inválida u otro error de formateo → fallback a UTC.
    return new Intl.DateTimeFormat(undefined, {
      timeZone: 'UTC',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).format(date)
  }
}

export function StaleWorkstationsSection() {
  const t = useTranslations('config')
  const tCommon = useTranslations('common')
  const { isAdmin } = useAuth()

  // === FILTROS ===
  const [days, setDays] = useState(90)
  const [minHours, setMinHours] = useState(24)
  const [selectedOrgId, setSelectedOrgId] = useState<string>('')
  const [organizations, setOrganizations] = useState<Organization[]>([])

  // === ESTADO ===
  const [viewMode, setViewMode] = useState<'cards' | 'table'>('table')
  const [page, setPage] = useState(1)
  const [sortBy, setSortBy] = useState<SortBy>('last_seen')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [items, setItems] = useState<Workstation[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)

  const pageSize = viewMode === 'cards' ? PAGE_SIZE_CARDS : PAGE_SIZE_TABLE
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  // === ORDENAMIENTO SERVER-SIDE ===
  // Al clicar una columna: si es la misma, togglea la dirección; si es otra,
  // fija esa columna en 'asc'. En ambos casos vuelve a la página 1.
  function handleSort(col: SortBy) {
    if (col === sortBy) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortBy(col)
      setSortDir('asc')
    }
    setPage(1)
  }

  // === CARGAR ORGANIZACIONES (solo admin) ===
  useEffect(() => {
    if (!isAdmin()) return
    organizationsApi.list().then(setOrganizations).catch(console.error)
  }, [isAdmin])

  // === CARGAR DATOS ===
  useEffect(() => {
    setPage(1)
  }, [days, minHours, selectedOrgId, viewMode])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    workstationsApi
      .listStale({
        days,
        min_hours: minHours,
        organization_id: selectedOrgId || undefined,
        page,
        page_size: pageSize,
        sort_by: sortBy,
        sort_dir: sortDir,
      })
      .then((res) => {
        if (!cancelled) {
          setItems(res.items)
          setTotal(res.total)
        }
      })
      .catch(console.error)
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [days, minHours, selectedOrgId, page, pageSize, sortBy, sortDir])

  const totalLabel = total === 1
    ? t('staleTotal', { count: total })
    : t('staleTotalPlural', { count: total })

  return (
    <div className="space-y-6 pb-24">
      {/* Encabezado */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-gray-900">{t('staleTitle')}</h2>
          <p className="mt-1 text-sm text-gray-600">{t('staleSubtitle', { days })}</p>
        </div>
        <Badge variant="secondary" className="text-sm self-start sm:self-auto">
          {totalLabel}
        </Badge>
      </div>

      {/* Barra de filtros */}
      <Card>
        <CardContent className="p-4">
          <div className="flex flex-col md:flex-row gap-4 items-start md:items-end">
            {/* Días de inactividad */}
            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-600">{t('staleDaysLabel')}</label>
              <select
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
                className="border rounded-md px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {[30, 60, 90, 180, 365].map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            </div>

            {/* Horas mínimas de actividad */}
            <div className="flex flex-col gap-1">
              <label className="flex items-center gap-1 text-xs font-medium text-gray-600">
                {t('staleMinHoursLabel')}
                <span
                  className="inline-flex text-gray-400 cursor-help"
                  title={t('staleMinHoursHelp')}
                  aria-label={t('staleMinHoursHelp')}
                >
                  <HelpCircle className="w-3.5 h-3.5" />
                </span>
              </label>
              <select
                value={minHours}
                onChange={(e) => setMinHours(Number(e.target.value))}
                className="border rounded-md px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {[1, 24, 48, 72, 168].map((h) => (
                  <option key={h} value={h}>{h}</option>
                ))}
              </select>
            </div>

            {/* Filtro por organización (solo admin) */}
            {isAdmin() && organizations.length > 0 && (
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-gray-600">{t('staleFilterOrg')}</label>
                <select
                  value={selectedOrgId}
                  onChange={(e) => setSelectedOrgId(e.target.value)}
                  className="border rounded-md px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 max-w-xs"
                >
                  <option value="">{t('staleFilterOrgAll')}</option>
                  {organizations.map((org) => (
                    <option key={org.id} value={org.id}>{org.name}</option>
                  ))}
                </select>
              </div>
            )}

            {/* Toggle de vista */}
            <div className="flex items-center gap-1 border rounded-md p-0.5 ml-auto">
              <Button
                variant={viewMode === 'cards' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('cards')}
                className="h-8 w-8 p-0"
                title={tCommon('viewCards')}
              >
                <LayoutGrid className="w-4 h-4" />
              </Button>
              <Button
                variant={viewMode === 'table' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('table')}
                className="h-8 w-8 p-0"
                title={tCommon('viewTable')}
              >
                <List className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Contenido */}
      {loading ? (
        <div className="animate-pulse space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-16 bg-gray-100 rounded-lg" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center">
            <WifiOff className="w-10 h-10 text-gray-300 mx-auto mb-3" />
            <p className="text-sm text-gray-500">{t('staleEmpty')}</p>
          </CardContent>
        </Card>
      ) : viewMode === 'cards' ? (
        <div className="space-y-4">
          {items.map((ws) => {
            const inactive = daysAgo(ws.last_seen)
            const isCritical = inactive >= CRITICAL_INACTIVE_DAYS
            return (
              <Card key={ws.id}>
                <CardContent className="p-4 md:p-6">
                  <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
                    {/* Info principal */}
                    <div className="flex items-center gap-3">
                      <Monitor className="w-8 h-8 text-gray-400 shrink-0" />
                      <div>
                        <p className="font-medium text-gray-900">
                          {ws.ip_private}
                          {ws.hostname && (
                            <span className="ml-2 text-gray-500 font-normal text-sm">({ws.hostname})</span>
                          )}
                        </p>
                        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-gray-600 mt-1">
                          {ws.current_user && (
                            <span className="flex items-center gap-1">
                              <User className="w-3.5 h-3.5" />
                              {ws.current_user}
                            </span>
                          )}
                          {ws.organization && (
                            <span className="flex items-center gap-1">
                              <Building2 className="w-3.5 h-3.5" />
                              {ws.organization.name}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Días inactiva */}
                    <div className="flex items-center gap-1.5 shrink-0">
                      <Clock className={`w-4 h-4 ${isCritical ? 'text-red-500' : 'text-amber-500'}`} />
                      <Badge
                        variant="outline"
                        className={
                          isCritical
                            ? 'text-red-700 border-red-300 bg-red-50'
                            : 'text-amber-700 border-amber-300 bg-amber-50'
                        }
                      >
                        {inactive}d {t('staleColInactiveDays').toLowerCase()}
                      </Badge>
                    </div>
                  </div>

                  {/* Fecha última conexión — mobile */}
                  <div className="mt-3 pt-3 border-t border-gray-100 flex gap-4 text-xs text-gray-500">
                    <span>{t('staleColLastSeen')}: {formatDateTimeInOrgTz(ws.last_seen, ws.organization?.timezone)}</span>
                    <span>{t('staleColCreated')}: {formatDateTimeInOrgTz(ws.created_at, ws.organization?.timezone)}</span>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      ) : (
        /* Vista tabla */
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  {STALE_TABLE_COLUMNS.map(({ i18nKey, sortBy: col }) => {
                    const isActive = sortBy === col
                    const dirLabel = sortDir === 'asc' ? t('staleSortAsc') : t('staleSortDesc')
                    return (
                      <th
                        key={i18nKey}
                        aria-sort={isActive ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
                        className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase whitespace-nowrap"
                      >
                        <button
                          type="button"
                          onClick={() => handleSort(col)}
                          aria-label={
                            isActive
                              ? t('staleSortedBy', {
                                  column: t(i18nKey as Parameters<typeof t>[0]),
                                  dir: dirLabel,
                                })
                              : t(i18nKey as Parameters<typeof t>[0])
                          }
                          className={`group inline-flex items-center gap-1 uppercase tracking-wide hover:text-gray-700 focus:outline-none focus:text-gray-700 ${
                            isActive ? 'text-gray-700' : 'text-gray-500'
                          }`}
                        >
                          <span>{t(i18nKey as Parameters<typeof t>[0])}</span>
                          {isActive ? (
                            sortDir === 'asc' ? (
                              <ArrowUp className="w-3.5 h-3.5" aria-hidden="true" />
                            ) : (
                              <ArrowDown className="w-3.5 h-3.5" aria-hidden="true" />
                            )
                          ) : (
                            <ChevronsUpDown
                              className="w-3.5 h-3.5 text-gray-300 group-hover:text-gray-400"
                              aria-hidden="true"
                            />
                          )}
                        </button>
                      </th>
                    )
                  })}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {items.map((ws) => {
                  const inactive = daysAgo(ws.last_seen)
                  const isCritical = inactive >= CRITICAL_INACTIVE_DAYS
                  return (
                    <tr key={ws.id} className="hover:bg-gray-50">
                      <td className="px-3 py-3 whitespace-nowrap font-mono text-xs">{ws.ip_private}</td>
                      <td className="px-3 py-3 whitespace-nowrap">{ws.hostname ?? '—'}</td>
                      <td className="px-3 py-3 whitespace-nowrap">{ws.current_user ?? '—'}</td>
                      <td className="px-3 py-3 whitespace-nowrap">{ws.organization?.name ?? '—'}</td>
                      <td className="px-3 py-3 whitespace-nowrap text-gray-500">
                        {formatDateTimeInOrgTz(ws.created_at, ws.organization?.timezone)}
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap text-gray-500">
                        {formatDateTimeInOrgTz(ws.last_seen, ws.organization?.timezone)}
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap">
                        <Badge
                          variant="outline"
                          className={
                            isCritical
                              ? 'text-red-700 border-red-300 bg-red-50'
                              : 'text-amber-700 border-amber-300 bg-amber-50'
                          }
                        >
                          {inactive}d
                        </Badge>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Paginación */}
      {total > pageSize && (
        <div className="relative z-10 flex items-center justify-between text-sm text-gray-600">
          <span>
            {tCommon('showing')} {Math.min((page - 1) * pageSize + 1, total)}–{Math.min(page * pageSize, total)} {tCommon('of')} {total}
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="h-8 w-8 p-0"
            >
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <span className="px-2">{page} / {totalPages}</span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="h-8 w-8 p-0"
            >
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
