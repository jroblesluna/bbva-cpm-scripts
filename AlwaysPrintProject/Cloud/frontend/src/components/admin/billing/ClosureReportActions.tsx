'use client'

/**
 * Acciones del Reporte de Cierre Mensual (PDF) para un cierre concreto.
 *
 * Requirements:
 * - 9.1: botón "Descargar reporte" → obtiene la presigned URL (`getClosureReport`) y abre el PDF
 *   en una nueva pestaña (`window.open(report_url, '_blank')`).
 * - 9.2: botón "Regenerar análisis" visible SOLO para admin/superadmin → `regenerateClosureReport`
 *   con confirmación previa; oculto para no-admin (operador).
 * - 9.3: vista previa opcional (recharts) que consume `getClosureReportData` y renderiza la
 *   composición de tramos (barras) y la evolución histórica (barras + línea de monto).
 * - 9.4: consume el cliente API tipado (sin `any`) y respeta el tenant isolation del backend.
 * - 9.5: todos los textos visibles vienen de `next-intl` (namespace `billingReport`).
 *
 * Notas de arquitectura:
 * - El "superadministrador" del sistema es el rol `admin` (`isAdmin()`); el gating de "Regenerar
 *   análisis" se hace aquí con `isAdmin()` (coherente con RetroactiveCloseButton / RatePlanEditor).
 * - El fallo del análisis IA no es error (fail-safe): el backend genera el PDF igual con
 *   `ai_analysis_available=false`. La UI lo refleja con un aviso, sin bloquear la descarga.
 * - No existe componente AlertDialog en `@/components/ui`; la confirmación reutiliza `Dialog`
 *   (mismo patrón que ClosureDetailDrawer) con un `DialogFooter`.
 */

import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { BarChart3, Download, Loader2, RefreshCw } from 'lucide-react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { useToast } from '@/hooks/use-toast'

import {
  getClosureReport,
  getClosureReportData,
  regenerateClosureReport,
} from '@/lib/api/billing'
import type {
  ClosureHeader,
  ClosureReportData,
  ClosureReportUrlResponse,
  HistoryPoint,
} from '@/types/billing'

interface ClosureReportActionsProps {
  /** Cierre sobre el que operan las acciones del reporte. */
  closure: ClosureHeader
  /** Si el usuario actual es admin/superadmin (habilita "Regenerar análisis"). */
  isAdmin: boolean
  /** `t` del namespace `billingReport`. */
  t: ReturnType<typeof useTranslations>
}

/**
 * Forma mínima de un tramo de `tiers_applied` (tipado como `unknown[]` en el schema porque el
 * backend lo serializa como JSON libre). Se normaliza de forma defensiva para el gráfico y la
 * tabla de desglose, sin usar `any`.
 */
interface TierEntry {
  from: number
  to: number | null
  rate: number | string
  ips_in_tier: number
  subtotal: number | string
  tier_index?: number
}

/** Normaliza un valor numérico que puede venir como number|string (Decimal del backend). */
function toNumber(value: number | string | null | undefined): number {
  const parsed = Number(value)
  return Number.isNaN(parsed) ? 0 : parsed
}

/** Formatea un monto a 2 decimales; guion si no es numérico. */
function formatAmount(amount: number | string): string {
  const value = Number(amount)
  if (Number.isNaN(value)) return '—'
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

/** Formatea el periodo (año/mes) como `YYYY-MM`. */
function formatPeriod(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, '0')}`
}

/**
 * Narrowing defensivo de un elemento `unknown` de `tiers_applied` a `TierEntry`.
 * Devuelve `null` si la forma no es reconocible (no rompe el render).
 */
function asTierEntry(raw: unknown): TierEntry | null {
  if (typeof raw !== 'object' || raw === null) return null
  const obj = raw as Record<string, unknown>
  const from = obj.from
  const ips = obj.ips_in_tier
  if (typeof from !== 'number' || typeof ips !== 'number') return null
  const to = obj.to
  const rate = obj.rate
  const subtotal = obj.subtotal
  const tierIndex = obj.tier_index
  return {
    from,
    to: typeof to === 'number' ? to : null,
    rate: typeof rate === 'number' || typeof rate === 'string' ? rate : 0,
    ips_in_tier: ips,
    subtotal: typeof subtotal === 'number' || typeof subtotal === 'string' ? subtotal : 0,
    tier_index: typeof tierIndex === 'number' ? tierIndex : undefined,
  }
}

/** Etiqueta legible de un tramo (`from`–`to` o `from+` si es el tramo sin tope superior). */
function tierLabel(tier: TierEntry): string {
  return tier.to === null ? `${tier.from}+` : `${tier.from}–${tier.to}`
}

export function ClosureReportActions({ closure, isAdmin, t }: ClosureReportActionsProps) {
  const { toast } = useToast()
  const queryClient = useQueryClient()

  // Diálogos: confirmación de regeneración y vista previa.
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)

  /** Abre el PDF en una nueva pestaña y avisa si el análisis IA no está disponible (fail-safe). */
  const openReport = (report: ClosureReportUrlResponse) => {
    window.open(report.report_url, '_blank', 'noopener,noreferrer')
    if (!report.ai_analysis_available) {
      toast({
        title: t('aiAnalysisTitle'),
        description: t('aiAnalysisUnavailable'),
      })
    } else {
      toast({ description: t('openInNewTab') })
    }
  }

  // Descargar reporte (cache-hit si ya existe en S3).
  const downloadMutation = useMutation({
    mutationFn: () => getClosureReport(closure.id),
    onSuccess: openReport,
    onError: () => {
      toast({ variant: 'destructive', description: t('downloadError') })
    },
  })

  // Regenerar análisis IA + PDF (solo admin/superadmin). Sobre-escribe el artefacto cacheado.
  const regenerateMutation = useMutation({
    mutationFn: () => regenerateClosureReport(closure.id),
    onSuccess: (report) => {
      setConfirmOpen(false)
      toast({ description: t('regenerateSuccess') })
      // Invalidar la vista previa para reflejar el nuevo análisis/serie.
      queryClient.invalidateQueries({ queryKey: ['billing-closure-report-data', closure.id] })
      openReport(report)
    },
    onError: () => {
      toast({ variant: 'destructive', description: t('regenerateError') })
    },
  })

  // Datos de la vista previa: solo se cargan cuando el diálogo está abierto.
  const {
    data: reportData,
    isLoading: previewLoading,
    isError: previewError,
  } = useQuery<ClosureReportData>({
    queryKey: ['billing-closure-report-data', closure.id],
    queryFn: () => getClosureReportData(closure.id),
    enabled: previewOpen,
  })

  // Datos derivados para los gráficos de la vista previa.
  const tiers = useMemo<TierEntry[]>(() => {
    if (!reportData) return []
    return reportData.tiers_applied
      .map(asTierEntry)
      .filter((tier): tier is TierEntry => tier !== null && tier.ips_in_tier > 0)
  }, [reportData])

  const tiersChartData = useMemo(
    () => tiers.map((tier) => ({ label: tierLabel(tier), ips: tier.ips_in_tier })),
    [tiers]
  )

  const historyChartData = useMemo(() => {
    if (!reportData) return []
    return reportData.history.map((point: HistoryPoint) => ({
      cycle: t('cycleLabel', { cycle: point.cycle }),
      billable: point.total_billable,
      amount: toNumber(point.amount),
    }))
  }, [reportData, t])

  const period = formatPeriod(closure.period_year, closure.period_month)

  return (
    <div className="flex flex-wrap items-center justify-end gap-1">
      {/* Vista previa opcional (recharts). */}
      <Button
        variant="ghost"
        size="sm"
        className="h-7 gap-1"
        onClick={(e) => {
          e.stopPropagation()
          setPreviewOpen(true)
        }}
        title={t('showPreview')}
      >
        <BarChart3 className="h-4 w-4" />
        <span className="hidden lg:inline">{t('showPreview')}</span>
      </Button>

      {/* Descargar reporte (todos los roles con acceso a la org). */}
      <Button
        variant="ghost"
        size="sm"
        className="h-7 gap-1"
        onClick={(e) => {
          e.stopPropagation()
          downloadMutation.mutate()
        }}
        disabled={downloadMutation.isPending}
        title={t('downloadReport')}
      >
        {downloadMutation.isPending ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Download className="h-4 w-4" />
        )}
        <span className="hidden lg:inline">
          {downloadMutation.isPending ? t('downloading') : t('downloadReport')}
        </span>
      </Button>

      {/* Regenerar análisis: SOLO admin/superadmin. */}
      {isAdmin && (
        <Button
          variant="ghost"
          size="sm"
          className="h-7 gap-1"
          onClick={(e) => {
            e.stopPropagation()
            setConfirmOpen(true)
          }}
          disabled={regenerateMutation.isPending}
          title={t('regenerateAnalysis')}
        >
          {regenerateMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
          <span className="hidden lg:inline">
            {regenerateMutation.isPending ? t('regenerating') : t('regenerateAnalysis')}
          </span>
        </Button>
      )}

      {/* Diálogo de confirmación de regeneración. */}
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent
          className="max-w-md"
          onClick={(e) => e.stopPropagation()}
        >
          <DialogHeader>
            <DialogTitle>{t('regenerateConfirmTitle')}</DialogTitle>
            <DialogDescription>{t('regenerateConfirmQuestion')}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setConfirmOpen(false)}
              disabled={regenerateMutation.isPending}
            >
              {t('cancel')}
            </Button>
            <Button
              onClick={() => regenerateMutation.mutate()}
              disabled={regenerateMutation.isPending}
            >
              {regenerateMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  {t('regenerating')}
                </>
              ) : (
                t('regenerateConfirmAction')
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Diálogo de vista previa (recharts). */}
      <Dialog open={previewOpen} onOpenChange={setPreviewOpen}>
        <DialogContent
          className="max-w-3xl max-h-[85vh] overflow-y-auto"
          onClick={(e) => e.stopPropagation()}
        >
          <DialogHeader>
            <DialogTitle>{t('previewTitle')}</DialogTitle>
            <DialogDescription>
              {t('periodLabel')}: {period}
            </DialogDescription>
          </DialogHeader>

          {previewLoading ? (
            <div className="flex items-center justify-center py-10 text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin mr-2" />
              {t('downloading')}
            </div>
          ) : previewError || !reportData ? (
            <Alert variant="destructive">
              <AlertDescription>{t('previewLoadError')}</AlertDescription>
            </Alert>
          ) : (
            <div className="space-y-6">
              {/* Aviso fail-safe: análisis IA no disponible. */}
              {reportData.ai_analysis === null && (
                <Alert>
                  <AlertDescription>{t('aiAnalysisUnavailable')}</AlertDescription>
                </Alert>
              )}

              {/* Composición de tramos (IPs por tramo). */}
              <section className="space-y-2">
                <h3 className="text-sm font-medium">{t('tiersCompositionTitle')}</h3>
                {tiersChartData.length === 0 ? (
                  <Alert>
                    <AlertDescription>{t('tiersCompositionEmpty')}</AlertDescription>
                  </Alert>
                ) : (
                  <div className="h-64 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={tiersChartData}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="label" fontSize={12} />
                        <YAxis allowDecimals={false} fontSize={12} />
                        <RechartsTooltip />
                        <Bar
                          dataKey="ips"
                          name={t('tierIps')}
                          fill="#2563eb"
                          radius={[4, 4, 0, 0]}
                        />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </section>

              {/* Evolución histórica: facturables (barras) + monto (línea). */}
              <section className="space-y-2">
                <h3 className="text-sm font-medium">{t('historyEvolutionTitle')}</h3>
                {reportData.history.length <= 1 && (
                  <p className="text-xs text-muted-foreground">{t('historyFirstCycle')}</p>
                )}
                <div className="h-64 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={historyChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="cycle" fontSize={12} />
                      <YAxis yAxisId="left" allowDecimals={false} fontSize={12} />
                      <YAxis yAxisId="right" orientation="right" fontSize={12} />
                      <RechartsTooltip />
                      <Legend />
                      <Bar
                        yAxisId="left"
                        dataKey="billable"
                        name={t('billableLabel')}
                        fill="#2563eb"
                        radius={[4, 4, 0, 0]}
                      />
                      <Line
                        yAxisId="right"
                        type="monotone"
                        dataKey="amount"
                        name={t('amountLabel')}
                        stroke="#f97316"
                        strokeWidth={2}
                        dot={{ r: 3 }}
                      />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
              </section>

              {/* Tabla resumen del desglose por tramo. */}
              {tiers.length > 0 && (
                <section className="space-y-2">
                  <h3 className="text-sm font-medium">{t('tiersCompositionTitle')}</h3>
                  <div className="overflow-x-auto border rounded-md">
                    <table className="w-full text-sm">
                      <thead className="bg-gray-50 border-b">
                        <tr>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                            {t('tierFrom')}
                          </th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                            {t('tierTo')}
                          </th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                            {t('tierRate')}
                          </th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                            {t('tierIps')}
                          </th>
                          <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">
                            {t('tierSubtotal')}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {tiers.map((tier, index) => (
                          <tr key={tier.tier_index ?? index} className="border-b last:border-b-0">
                            <td className="px-3 py-2 whitespace-nowrap">{tier.from}</td>
                            <td className="px-3 py-2 whitespace-nowrap">
                              {tier.to === null ? '—' : tier.to}
                            </td>
                            <td className="px-3 py-2 whitespace-nowrap">
                              {formatAmount(tier.rate)}
                            </td>
                            <td className="px-3 py-2 whitespace-nowrap">{tier.ips_in_tier}</td>
                            <td className="px-3 py-2 whitespace-nowrap font-medium">
                              {formatAmount(tier.subtotal)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              {/* Texto del análisis IA (si existe). */}
              {reportData.ai_analysis !== null && (
                <section className="space-y-2">
                  <h3 className="text-sm font-medium">{t('aiAnalysisTitle')}</h3>
                  <p className="text-sm text-muted-foreground whitespace-pre-line">
                    {reportData.ai_analysis}
                  </p>
                </section>
              )}

              {/* Nota de moneda (USD sin impuestos). */}
              <div className="flex items-center gap-2 pt-2 border-t">
                <Badge variant="outline">{reportData.currency}</Badge>
                <span className="text-xs text-muted-foreground">{t('currencyNote')}</span>
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setPreviewOpen(false)}>
              {t('hidePreview')}
            </Button>
            <Button
              onClick={() => downloadMutation.mutate()}
              disabled={downloadMutation.isPending}
            >
              {downloadMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  {t('downloading')}
                </>
              ) : (
                <>
                  <Download className="h-4 w-4 mr-2" />
                  {t('downloadReport')}
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
