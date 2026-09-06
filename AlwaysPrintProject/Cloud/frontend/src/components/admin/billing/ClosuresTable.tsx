'use client'

/**
 * Tabla de cierres mensuales de una organización (cabeceras `ClosureHeader`).
 *
 * Requirements:
 * - 10.3: lista los cierres con su cabecera (totales por estado y monto) y permite ver el
 *   detalle por IP de cada cierre (abre el ClosureDetailDrawer).
 *
 * Sigue el estándar de vistas de listado del repo (tabla en Card, headers `bg-gray-50 border-b`,
 * paginación "Mostrando X-Y de Z" cuando hay >20 cierres). Visible para admin + operador (los
 * datos ya vienen filtrados por organización desde el backend / tenant isolation).
 */

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { CalendarClock, Eye, ChevronLeft, ChevronRight } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription } from '@/components/ui/alert'

import { useAuth } from '@/hooks/useAuth'
import { getClosures } from '@/lib/api/billing'
import type { ClosureHeader } from '@/types/billing'

import { ClosureDetailDrawer } from './ClosureDetailDrawer'
import { ClosureReportActions } from './ClosureReportActions'

/** Cierres por página en la tabla (estándar de listados: 20 para tabla). */
const PAGE_SIZE = 20

interface ClosuresTableProps {
  /** Organización cuyos cierres se listan. */
  organizationId: string
  /** `t` del namespace `usageAndBilling`. */
  t: ReturnType<typeof useTranslations>
  /** `t` del namespace `common`. */
  tCommon: ReturnType<typeof useTranslations>
}

/** Formatea el periodo (año/mes) como `YYYY-MM` con el mes a 2 dígitos. */
function formatPeriod(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, '0')}`
}

/**
 * Formatea una fecha ISO a la fecha local corta (solo día). Si la entrada es inválida,
 * devuelve un guion para no romper el render.
 */
function formatDate(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString()
}

/**
 * Formatea un monto (number|string por el Decimal del backend) como moneda de 2 decimales.
 * Se normaliza con Number() antes de formatear; si no es numérico, se muestra un guion.
 */
function formatAmount(amount: number | string): string {
  const value = Number(amount)
  if (Number.isNaN(value)) return '—'
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

export function ClosuresTable({ organizationId, t, tCommon }: ClosuresTableProps) {
  // `t` del namespace `billingReport` para las acciones del reporte PDF (Task 10.3).
  const tReport = useTranslations('billingReport')
  // El rol `admin` es el superadministrador del sistema (habilita "Regenerar análisis").
  const { isAdmin } = useAuth()
  const canRegenerate = isAdmin()

  // Cierre seleccionado para el detalle por IP (null = drawer cerrado).
  const [selectedClosure, setSelectedClosure] = useState<ClosureHeader | null>(null)
  // Página actual (1-based) de la tabla de cierres.
  const [page, setPage] = useState(1)

  const {
    data: closures,
    isLoading,
    isError,
  } = useQuery<ClosureHeader[]>({
    queryKey: ['billing-closures', organizationId],
    queryFn: () => getClosures(organizationId),
    enabled: !!organizationId,
  })

  const total = closures?.length ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)

  // Cierres visibles en la página actual.
  const pageItems = useMemo(() => {
    if (!closures) return []
    const start = (currentPage - 1) * PAGE_SIZE
    return closures.slice(start, start + PAGE_SIZE)
  }, [closures, currentPage])

  const rangeStart = total === 0 ? 0 : (currentPage - 1) * PAGE_SIZE + 1
  const rangeEnd = Math.min(currentPage * PAGE_SIZE, total)

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div className="flex items-center gap-2">
          <CalendarClock className="h-5 w-5 text-muted-foreground" />
          <CardTitle>{t('closuresTitle')}</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <p className="text-center text-muted-foreground py-6">{tCommon('loading')}</p>
        ) : isError ? (
          <Alert variant="destructive">
            <AlertDescription>{t('closuresLoadError')}</AlertDescription>
          </Alert>
        ) : total === 0 ? (
          <Alert>
            <AlertDescription>{t('closuresEmpty')}</AlertDescription>
          </Alert>
        ) : (
          <>
            <div className="overflow-x-auto border rounded-md">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b">
                  <tr>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      {t('colPeriod')}
                    </th>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      {t('colCutoff')}
                    </th>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      {t('colMode')}
                    </th>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      {t('colBillable')}
                    </th>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      {t('colRecycled')}
                    </th>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      {t('colArchived')}
                    </th>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      {t('colAmount')}
                    </th>
                    <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                      {tCommon('actions')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {pageItems.map((closure) => (
                    <tr
                      key={closure.id}
                      className="border-b last:border-b-0 hover:bg-gray-50 cursor-pointer"
                      onClick={() => setSelectedClosure(closure)}
                    >
                      <td className="px-3 py-3 whitespace-nowrap font-medium">
                        <span className="flex items-center gap-2">
                          {formatPeriod(closure.period_year, closure.period_month)}
                          {closure.is_retroactive && (
                            <Badge variant="outline" className="text-amber-600 border-amber-300">
                              {t('retroactiveBadge')}
                            </Badge>
                          )}
                        </span>
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap text-muted-foreground">
                        {formatDate(closure.cutoff_at)}
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap">
                        <Badge variant="secondary">{t(`mode.${closure.mode}`)}</Badge>
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap">{closure.total_billable}</td>
                      <td className="px-3 py-3 whitespace-nowrap">{closure.total_recycled}</td>
                      <td className="px-3 py-3 whitespace-nowrap">{closure.total_archived}</td>
                      <td className="px-3 py-3 whitespace-nowrap font-medium">
                        {formatAmount(closure.amount)}
                      </td>
                      <td className="px-3 py-3 text-right">
                        <div className="flex flex-wrap items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 gap-1"
                            onClick={(e) => {
                              // Evita que el click en el botón dispare el onClick de la fila.
                              e.stopPropagation()
                              setSelectedClosure(closure)
                            }}
                            title={t('viewDetail')}
                          >
                            <Eye className="h-4 w-4" />
                            <span className="hidden lg:inline">{t('viewDetail')}</span>
                          </Button>
                          {/* Acciones del reporte PDF: descargar, regenerar (admin) y vista previa. */}
                          <ClosureReportActions
                            closure={closure}
                            isAdmin={canRegenerate}
                            t={tReport}
                          />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Paginación: solo si hay más de una página (>20 cierres). */}
            {total > PAGE_SIZE && (
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <span className="text-sm text-muted-foreground">
                  {t('pagination', { start: rangeStart, end: rangeEnd, total })}
                </span>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={currentPage <= 1}
                  >
                    <ChevronLeft className="h-4 w-4 mr-1" />
                    {tCommon('previous')}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={currentPage >= totalPages}
                  >
                    {tCommon('next')}
                    <ChevronRight className="h-4 w-4 ml-1" />
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
      </CardContent>

      {/* Drawer de detalle por IP del cierre seleccionado. */}
      <ClosureDetailDrawer
        closure={selectedClosure}
        open={selectedClosure !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedClosure(null)
        }}
        t={t}
        tCommon={tCommon}
      />
    </Card>
  )
}
