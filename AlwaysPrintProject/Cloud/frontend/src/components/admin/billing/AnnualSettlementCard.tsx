'use client'

/**
 * Tarjeta de liquidación anual (informativa + confirmación manual).
 *
 * Requirements:
 * - 9.5: presentar la liquidación anual de forma INFORMATIVA (declarado, real, diferencia,
 *   crédito/cargo sugerido) y exigir confirmación manual del superadministrador para aplicarla
 *   (no se aplica automáticamente).
 * - 9.6 (informativo): indicador de "crecimiento libre"/reclasificación del tramo contratado
 *   (within_free_growth / requires_reclassification / free_growth_to).
 *
 * Comportamiento:
 * - GET informativo de la liquidación (getAnnualSettlement). Si el backend responde 404
 *   (no hay suscripción anual activa) se muestra un mensaje neutro, sin error destructivo.
 * - El botón "Confirmar liquidación" (SOLO superadministrador) aplica la liquidación
 *   (confirmAnnualSettlement) tras un paso de confirmación explícito; al éxito muestra un toast
 *   e invalida las queries relacionadas.
 *
 * Este componente solo debe renderizarse cuando la organización está en modalidad anual; el
 * gating de modalidad y de superadmin se hace en la página contenedora.
 */

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { CalendarClock, Loader2, CheckCircle2, AlertTriangle, Info } from 'lucide-react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { useToast } from '@/hooks/use-toast'

import { getAnnualSettlement, confirmAnnualSettlement } from '@/lib/api/billing'
import type { AnnualSettlement, AnnualSubscription } from '@/types/billing'

interface AnnualSettlementCardProps {
  /** Organización objetivo (en modalidad anual). */
  organizationId: string
  /** Si el usuario es superadministrador (puede confirmar la liquidación). */
  canConfirm: boolean
  /** `t` del namespace `usageAndBilling`. */
  t: ReturnType<typeof useTranslations>
  /** `t` del namespace `common`. */
  tCommon: ReturnType<typeof useTranslations>
}

/** Extrae un mensaje de error legible del error de la API (detail | message). */
function extractError(error: unknown, fallback: string): string {
  if (error && typeof error === 'object') {
    const e = error as { detail?: unknown; message?: unknown }
    if (typeof e.detail === 'string') return e.detail
    if (typeof e.message === 'string') return e.message
  }
  return fallback
}

/** Devuelve el `status` HTTP del error normalizado por el apiClient, si existe. */
function errorStatus(error: unknown): number | undefined {
  if (error && typeof error === 'object') {
    const e = error as { status?: unknown }
    if (typeof e.status === 'number') return e.status
  }
  return undefined
}

/** Formatea un valor monetario (`number | string`) a 2 decimales usando `Number()`. */
function formatMoney(value: number | string): string {
  const n = Number(value)
  if (Number.isNaN(n)) return '—'
  return n.toFixed(2)
}

export function AnnualSettlementCard({
  organizationId,
  canConfirm,
  t,
  tCommon,
}: AnnualSettlementCardProps) {
  const { toast } = useToast()
  const queryClient = useQueryClient()

  // Paso de confirmación explícito antes de aplicar la liquidación.
  const [confirming, setConfirming] = useState(false)

  const {
    data: settlement,
    isLoading,
    error,
  } = useQuery<AnnualSettlement, unknown>({
    queryKey: ['annual-settlement', organizationId],
    queryFn: () => getAnnualSettlement(organizationId),
    // No reintentar el 404 (no hay suscripción anual activa): es un estado esperado.
    retry: (failureCount, err) => errorStatus(err) !== 404 && failureCount < 2,
  })

  const confirmMutation = useMutation<AnnualSubscription, unknown, void>({
    mutationFn: () => confirmAnnualSettlement(organizationId),
    onSuccess: () => {
      setConfirming(false)
      toast({
        title: t('settlementConfirmedTitle'),
        description: t('settlementConfirmedDesc'),
      })
      // Refrescar la liquidación (pasa a status='settled') y datos relacionados.
      queryClient.invalidateQueries({ queryKey: ['annual-settlement', organizationId] })
      queryClient.invalidateQueries({ queryKey: ['billing-closures', organizationId] })
    },
    onError: (err: unknown) => {
      toast({
        title: tCommon('error'),
        description: extractError(err, t('settlementConfirmError')),
        variant: 'destructive',
      })
    },
  })

  const status = errorStatus(error)

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <CalendarClock className="h-5 w-5 text-muted-foreground" />
          <CardTitle>{t('settlementTitle')}</CardTitle>
        </div>
        <CardDescription>{t('settlementDesc')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            {tCommon('loading')}
          </div>
        ) : status === 404 ? (
          // No hay suscripción anual activa: estado esperado, mensaje neutro.
          <Alert>
            <Info className="h-4 w-4" />
            <AlertDescription>{t('settlementNoSubscription')}</AlertDescription>
          </Alert>
        ) : error || !settlement ? (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{extractError(error, t('settlementLoadError'))}</AlertDescription>
          </Alert>
        ) : (
          <>
            {/* Resumen informativo de conteos */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">{t('settlementDeclared')}</p>
                <p className="text-lg font-semibold">{settlement.declared}</p>
              </div>
              <div className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">{t('settlementReal')}</p>
                <p className="text-lg font-semibold">{settlement.real}</p>
              </div>
              <div className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">{t('settlementBillableCount')}</p>
                <p className="text-lg font-semibold">{settlement.billable_count}</p>
              </div>
              <div className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">{t('settlementTierCap')}</p>
                <p className="text-lg font-semibold">
                  {settlement.tier_cap ?? t('settlementNoCap')}
                </p>
              </div>
            </div>

            {/* Diferencia y crédito/cargo (dinero vía Number()) */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">{t('settlementDiff')}</p>
                <p className="text-lg font-semibold">{settlement.diff}</p>
              </div>
              <div className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">{t('settlementCredit')}</p>
                <p className="text-lg font-semibold text-emerald-600">
                  {formatMoney(settlement.credit)}
                </p>
              </div>
              <div className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">{t('settlementCharge')}</p>
                <p className="text-lg font-semibold text-amber-600">
                  {formatMoney(settlement.charge)}
                </p>
              </div>
            </div>

            {/* Indicador informativo de crecimiento libre / reclasificación (Req 9.6) */}
            <div className="flex flex-wrap items-center gap-2">
              {settlement.free_growth.within_free_growth ? (
                <Badge variant="secondary" className="gap-1">
                  <CheckCircle2 className="h-3 w-3" />
                  {t('settlementWithinFreeGrowth')}
                </Badge>
              ) : null}
              {settlement.free_growth.requires_reclassification ? (
                <Badge variant="destructive" className="gap-1">
                  <AlertTriangle className="h-3 w-3" />
                  {t('settlementRequiresReclassification')}
                </Badge>
              ) : null}
              {settlement.free_growth.free_growth_to != null ? (
                <span className="text-xs text-muted-foreground">
                  {t('settlementFreeGrowthTo', {
                    to: settlement.free_growth.free_growth_to,
                  })}
                </span>
              ) : null}
            </div>

            {/* Aviso: la liquidación es informativa hasta confirmarla manualmente (Req 9.5) */}
            <Alert>
              <Info className="h-4 w-4" />
              <AlertDescription>{t('settlementInformativeHint')}</AlertDescription>
            </Alert>

            {/* Confirmación manual: SOLO superadministrador */}
            {canConfirm && (
              <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                {confirming ? (
                  <>
                    <span className="text-sm text-muted-foreground">
                      {t('settlementConfirmQuestion')}
                    </span>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setConfirming(false)}
                        disabled={confirmMutation.isPending}
                      >
                        {tCommon('cancel')}
                      </Button>
                      <Button
                        size="sm"
                        onClick={() => confirmMutation.mutate()}
                        disabled={confirmMutation.isPending}
                      >
                        {confirmMutation.isPending ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <CheckCircle2 className="mr-2 h-4 w-4" />
                        )}
                        {confirmMutation.isPending
                          ? t('settlementConfirming')
                          : t('settlementConfirmAction')}
                      </Button>
                    </div>
                  </>
                ) : (
                  <Button onClick={() => setConfirming(true)} title={t('settlementConfirmHint')}>
                    <CheckCircle2 className="mr-2 h-4 w-4" />
                    {t('settlementConfirmButton')}
                  </Button>
                )}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
