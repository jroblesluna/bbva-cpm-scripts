'use client'

/**
 * Drawer/diálogo con el detalle por IP de un cierre mensual (`ClosureItem` paginado).
 *
 * Requirements:
 * - 10.3: permite ver el detalle por IP de cada cierre (una fila por workstation en el corte).
 *
 * La paginación es del lado del servidor (getClosureItems con page/page_size). Se usa el
 * componente Dialog de shadcn/ui (no hay Sheet en @/components/ui) con un ancho amplio para
 * mostrar la tabla cómodamente. Sigue el estándar de listados (headers `bg-gray-50 border-b`,
 * paginación "Mostrando X-Y de Z").
 */

import { useEffect, useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { ChevronLeft, ChevronRight } from 'lucide-react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription } from '@/components/ui/alert'

import { getClosureItems } from '@/lib/api/billing'
import type { BillingStatus, ClosureHeader, ClosureItemsPage } from '@/types/billing'

/** Ítems por página del detalle por IP (por defecto 20/página). */
const PAGE_SIZE = 20

interface ClosureDetailDrawerProps {
  /** Cierre a mostrar (null cuando el drawer está cerrado / sin selección). */
  closure: ClosureHeader | null
  /** Si el drawer está abierto. */
  open: boolean
  /** Callback de cambio de estado abierto/cerrado. */
  onOpenChange: (open: boolean) => void
  /** `t` del namespace `usageAndBilling`. */
  t: ReturnType<typeof useTranslations>
  /** `t` del namespace `common`. */
  tCommon: ReturnType<typeof useTranslations>
}

/** Variante de Badge según el estado de facturación de la IP. */
function statusVariant(
  status: BillingStatus
): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (status) {
    case 'billable':
      return 'default'
    case 'recycled':
      return 'secondary'
    case 'archived':
      return 'destructive'
    case 'new':
    default:
      return 'outline'
  }
}

/** Formatea una fecha ISO a fecha/hora local corta. Guion si es inválida. */
function formatDateTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString()
}

/** Formatea el periodo (año/mes) como `YYYY-MM`. */
function formatPeriod(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, '0')}`
}

/** Formatea un monto (number|string) como 2 decimales; guion si no es numérico. */
function formatAmount(amount: number | string): string {
  const value = Number(amount)
  if (Number.isNaN(value)) return '—'
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

export function ClosureDetailDrawer({
  closure,
  open,
  onOpenChange,
  t,
  tCommon,
}: ClosureDetailDrawerProps) {
  // Página actual (1-based) del detalle por IP.
  const [page, setPage] = useState(1)

  // Reiniciar a la primera página cuando cambia el cierre seleccionado.
  useEffect(() => {
    setPage(1)
  }, [closure?.id])

  const {
    data,
    isLoading,
    isError,
    isFetching,
  } = useQuery<ClosureItemsPage>({
    queryKey: ['billing-closure-items', closure?.id, page],
    queryFn: () => getClosureItems(closure!.id, page, PAGE_SIZE),
    enabled: open && !!closure,
    // Mantener la página anterior visible mientras carga la nueva (evita parpadeos).
    placeholderData: keepPreviousData,
  })

  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const items = data?.items ?? []

  const rangeStart = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const rangeEnd = Math.min(page * PAGE_SIZE, total)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>
            {closure
              ? t('detailTitle', {
                  period: formatPeriod(closure.period_year, closure.period_month),
                })
              : t('detailTitleGeneric')}
          </DialogTitle>
          <DialogDescription>{t('detailDesc')}</DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <p className="text-center text-muted-foreground py-6">{tCommon('loading')}</p>
        ) : isError ? (
          <Alert variant="destructive">
            <AlertDescription>{t('detailLoadError')}</AlertDescription>
          </Alert>
        ) : total === 0 ? (
          <Alert>
            <AlertDescription>{t('detailEmpty')}</AlertDescription>
          </Alert>
        ) : (
          <div className="space-y-4">
            <div className="overflow-x-auto border rounded-md max-h-[55vh]">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b sticky top-0">
                  <tr>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      {t('colIp')}
                    </th>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      {t('colCreatedWs')}
                    </th>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      {t('colLastSeenCapped')}
                    </th>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      {tCommon('status')}
                    </th>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      {t('colTier')}
                    </th>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      {t('colAmount')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id} className="border-b last:border-b-0">
                      <td className="px-3 py-3 whitespace-nowrap font-mono">
                        {item.ip_private}
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap text-muted-foreground">
                        {formatDateTime(item.created_at_ws)}
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap text-muted-foreground">
                        {formatDateTime(item.last_seen_capped)}
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap">
                        <Badge variant={statusVariant(item.billing_status)}>
                          {t(`status.${item.billing_status}`)}
                        </Badge>
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap">
                        {item.tier_index === null ? '—' : item.tier_index}
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap font-medium">
                        {formatAmount(item.amount)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Paginación server-side del detalle por IP. */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <span className="text-sm text-muted-foreground">
                {t('pagination', { start: rangeStart, end: rangeEnd, total })}
              </span>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1 || isFetching}
                >
                  <ChevronLeft className="h-4 w-4 mr-1" />
                  {tCommon('previous')}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages || isFetching}
                >
                  {tCommon('next')}
                  <ChevronRight className="h-4 w-4 ml-1" />
                </Button>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
