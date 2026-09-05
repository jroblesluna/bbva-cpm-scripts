'use client'

/**
 * Botón para generar un cierre retroactivo (SOLO superadministrador).
 *
 * Requirements:
 * - 10.5 / 11.2: permite a superadministradores generar cierres retroactivos uno por uno desde
 *   el mes pendiente más antiguo, respetando la secuencialidad (la sequencialidad la garantiza
 *   el backend: cada llamada cierra el mes pendiente más antiguo).
 *
 * Al éxito muestra un toast (si `closed`, indica qué periodo se cerró desde `response.closure`;
 * si `closed = false`, muestra el `detail` — no había meses pendientes) e invalida la query de
 * cierres para refrescar la tabla.
 *
 * Este componente NO debe renderizarse para usuarios no-superadmin; el gating se hace en la
 * página contenedora (isAdmin()).
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { CalendarPlus, Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'

import { closeRetroactive } from '@/lib/api/billing'
import type { RetroactiveCloseResponse } from '@/types/billing'

interface RetroactiveCloseButtonProps {
  /** Organización sobre la que se ejecuta el cierre retroactivo. */
  organizationId: string
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

/** Formatea el periodo (año/mes) como `YYYY-MM`. */
function formatPeriod(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, '0')}`
}

export function RetroactiveCloseButton({
  organizationId,
  t,
  tCommon,
}: RetroactiveCloseButtonProps) {
  const { toast } = useToast()
  const queryClient = useQueryClient()

  const mutation = useMutation<RetroactiveCloseResponse, unknown, void>({
    mutationFn: () => closeRetroactive(organizationId),
    onSuccess: (data) => {
      if (data.closed && data.closure) {
        toast({
          title: t('retroClosedTitle'),
          description: t('retroClosedDesc', {
            period: formatPeriod(data.closure.period_year, data.closure.period_month),
          }),
        })
      } else {
        // closed = false: no había meses pendientes. Mostramos el detalle del backend.
        toast({
          title: t('retroNothingTitle'),
          description: data.detail || t('retroNothingDesc'),
        })
      }
      // Refrescar la tabla de cierres de la organización.
      queryClient.invalidateQueries({ queryKey: ['billing-closures', organizationId] })
    },
    onError: (error: unknown) => {
      toast({
        title: tCommon('error'),
        description: extractError(error, t('retroError')),
        variant: 'destructive',
      })
    },
  })

  return (
    <Button
      onClick={() => mutation.mutate()}
      disabled={mutation.isPending}
      title={t('retroButtonHint')}
    >
      {mutation.isPending ? (
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
      ) : (
        <CalendarPlus className="mr-2 h-4 w-4" />
      )}
      {mutation.isPending ? t('retroRunning') : t('retroButton')}
    </Button>
  )
}
