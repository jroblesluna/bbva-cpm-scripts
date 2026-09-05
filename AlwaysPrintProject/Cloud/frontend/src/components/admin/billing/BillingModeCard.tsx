'use client'

/**
 * Tarjeta que muestra la modalidad de facturación vigente de una organización
 * ('monthly' | 'annual') y permite al superadministrador cambiarla vía setOrgMode.
 *
 * Requirements: 10.2 (mostrar modalidad por organización), 11.1 (edición restringida a
 * superadministradores). Los operadores/no-superadmin ven la modalidad en solo lectura.
 */

import { useState, useEffect } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { CreditCard, CalendarClock, Lock } from 'lucide-react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'

import { setOrgMode } from '@/lib/api/billing'
import type { BillingMode } from '@/types/billing'

interface BillingModeCardProps {
  /** Organización objetivo. */
  organizationId: string
  /** Modalidad actual (desde el detalle de la organización). */
  currentMode: BillingMode
  /** Si el usuario es superadministrador (puede editar la modalidad). */
  canEdit: boolean
  /** `t` del namespace `usageAndBilling`. */
  t: ReturnType<typeof useTranslations>
  /** `t` del namespace `common`. */
  tCommon: ReturnType<typeof useTranslations>
}

/**
 * Extrae un mensaje de error legible del error de la API (detail | message).
 */
function extractError(error: unknown, fallback: string): string {
  if (error && typeof error === 'object') {
    const e = error as { detail?: unknown; message?: unknown }
    if (typeof e.detail === 'string') return e.detail
    if (typeof e.message === 'string') return e.message
  }
  return fallback
}

export function BillingModeCard({
  organizationId,
  currentMode,
  canEdit,
  t,
  tCommon,
}: BillingModeCardProps) {
  const { toast } = useToast()
  const queryClient = useQueryClient()

  // Modalidad seleccionada localmente (para el selector del superadmin).
  const [selectedMode, setSelectedMode] = useState<BillingMode>(currentMode)

  // Re-sincronizar si cambia la organización o la modalidad recibida.
  useEffect(() => {
    setSelectedMode(currentMode)
  }, [currentMode, organizationId])

  const modeMutation = useMutation({
    mutationFn: (mode: BillingMode) => setOrgMode(organizationId, mode),
    onSuccess: (data) => {
      // Invalidar el detalle de la organización y los planes para reflejar el cambio.
      queryClient.invalidateQueries({ queryKey: ['organization-detail', organizationId] })
      queryClient.invalidateQueries({ queryKey: ['organizations-list'] })
      toast({
        title: t('modeUpdated'),
        description: t('modeUpdatedDesc', { mode: t(`mode.${data.billing_mode}`) }),
      })
    },
    onError: (error: unknown) => {
      // Revertir la selección al valor vigente si falla.
      setSelectedMode(currentMode)
      toast({
        title: tCommon('error'),
        description: extractError(error, t('modeUpdateError')),
        variant: 'destructive',
      })
    },
  })

  const handleSave = () => {
    if (selectedMode !== currentMode) {
      modeMutation.mutate(selectedMode)
    }
  }

  const ModeIcon = currentMode === 'annual' ? CalendarClock : CreditCard

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <ModeIcon className="h-5 w-5 text-muted-foreground" />
          <CardTitle>{t('billingModeTitle')}</CardTitle>
        </div>
        <CardDescription>{t('billingModeDesc')}</CardDescription>
      </CardHeader>
      <CardContent>
        {canEdit ? (
          <div className="flex flex-col sm:flex-row sm:items-center gap-3">
            <select
              value={selectedMode}
              onChange={(e) => setSelectedMode(e.target.value as BillingMode)}
              disabled={modeMutation.isPending}
              className="w-full sm:max-w-xs px-3 py-2 border rounded-md text-sm bg-background"
              aria-label={t('billingModeTitle')}
            >
              <option value="monthly">{t('mode.monthly')}</option>
              <option value="annual">{t('mode.annual')}</option>
            </select>
            <Button
              onClick={handleSave}
              disabled={selectedMode === currentMode || modeMutation.isPending}
            >
              {modeMutation.isPending ? tCommon('saving') : tCommon('save')}
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <Badge variant="secondary">{t(`mode.${currentMode}`)}</Badge>
            <span className="flex items-center gap-1 text-xs text-muted-foreground">
              <Lock className="h-3 w-3" />
              {t('readOnlyHint')}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
