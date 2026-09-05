'use client'

/**
 * Página de la sección Usage and Billing (configuración y tarifas).
 *
 * Requirements cubiertos por esta task (30):
 * - 10.1: añade la sección Usage and Billing al dashboard.
 * - 10.2: muestra por organización la modalidad, la zona horaria (bloqueada tras el primer
 *         cierre) y el plan tarifario vigente.
 * - 10.4 / 10.8 / 11.1: la edición de tarifas/planes se restringe a superadministradores
 *         (RatePlanEditor solo se renderiza para superadmin).
 *
 * Notas:
 * - El "superadministrador" del sistema es el rol `admin` (isAdmin()); el operador ve la sección
 *   de su propia organización en solo lectura.
 * - El bloqueo de timezone se determina consultando los cierres de la org: si hay ≥1 cierre,
 *   la zona horaria se muestra en solo lectura con un indicador de candado (el cambio real se
 *   hace desde la edición de la organización, que ya rechaza el cambio con 409 si está bloqueada).
 * - Task 31 añade la sección de cierres (ClosuresTable + ClosureDetailDrawer) y el botón de
 *   cierre retroactivo (RetroactiveCloseButton, solo superadmin) — Req 10.3 y 10.5.
 * - Task 32 añade la liquidación anual (AnnualSettlementCard, solo en modalidad anual;
 *   la confirmación manual se gatea a superadmin — Req 9.5). Los ajustes del listado de
 *   workstations (filtro "ocultar archived" y diálogo de borrado) viven en la página de
 *   workstations, no aquí.
 */

import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { Building2, Clock, Lock } from 'lucide-react'

import { useAuth } from '@/hooks/useAuth'
import { organizationsApi } from '@/lib/api'
import { getClosures } from '@/lib/api/billing'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { BillingModeCard } from '@/components/admin/billing/BillingModeCard'
import { RatePlanEditor } from '@/components/admin/billing/RatePlanEditor'
import { ClosuresTable } from '@/components/admin/billing/ClosuresTable'
import { RetroactiveCloseButton } from '@/components/admin/billing/RetroactiveCloseButton'
import { AnnualSettlementCard } from '@/components/admin/billing/AnnualSettlementCard'

import type { Organization } from '@/types/organization'
import type { BillingMode } from '@/types/billing'

/**
 * La modalidad de facturación no está tipada aún en `Organization` (el backend la expone como
 * `billing_mode`). La leemos de forma segura sin usar `any`.
 */
function readBillingMode(org: Organization | undefined): BillingMode {
  if (org && 'billing_mode' in org) {
    const value = (org as Organization & { billing_mode?: unknown }).billing_mode
    if (value === 'annual' || value === 'monthly') return value
  }
  // Valor por defecto seguro y documentado (Req 4.6).
  return 'monthly'
}

export default function UsageAndBillingPage() {
  const { user, isAdmin } = useAuth()
  const t = useTranslations('usageAndBilling')
  const tCommon = useTranslations('common')

  // El rol `admin` es el superadministrador del sistema.
  const isSuperadmin = isAdmin()

  // Organización seleccionada: superadmin puede cambiarla, operador usa la suya fija.
  const [selectedOrgId, setSelectedOrgId] = useState<string | null>(
    user?.organization_id ?? null
  )

  // Para superadmin: lista de organizaciones para el selector.
  const { data: organizations } = useQuery<Organization[]>({
    queryKey: ['organizations-list'],
    queryFn: () => organizationsApi.list(),
    enabled: isSuperadmin,
  })

  // Preseleccionar la primera organización cuando carguen (solo superadmin sin selección).
  useEffect(() => {
    if (isSuperadmin && !selectedOrgId && organizations && organizations.length > 0) {
      setSelectedOrgId(organizations[0].id)
    }
  }, [organizations, isSuperadmin, selectedOrgId])

  // Organización efectiva para todas las operaciones.
  const organizationId = isSuperadmin ? selectedOrgId : (user?.organization_id ?? null)

  // Detalle de la organización (modalidad + timezone).
  const { data: orgDetail } = useQuery<Organization>({
    queryKey: ['organization-detail', organizationId],
    queryFn: () => organizationsApi.get(organizationId!),
    enabled: !!organizationId,
  })

  // Cierres de la org: si hay ≥1, la timezone queda bloqueada (solo lectura).
  const { data: closures } = useQuery({
    queryKey: ['billing-closures', organizationId],
    queryFn: () => getClosures(organizationId!),
    enabled: !!organizationId,
  })

  const timezoneLocked = !!closures && closures.length > 0
  const billingMode = readBillingMode(orgDetail)
  const timezone = orgDetail?.timezone ?? '—'

  const selectedOrgName = isSuperadmin
    ? organizations?.find((o) => o.id === selectedOrgId)?.name
    : user?.organization?.name ?? orgDetail?.name ?? ''

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Encabezado */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">{t('title')}</h1>
          <p className="text-muted-foreground mt-1">{t('subtitle')}</p>
        </div>
      </div>

      {/* Selector / indicador de organización */}
      <Card>
        <CardContent className="py-4">
          <div className="flex items-center gap-3">
            <Building2 className="h-5 w-5 text-muted-foreground shrink-0" />
            <div className="flex-1">
              {isSuperadmin ? (
                <div className="flex items-center gap-3">
                  <Label htmlFor="org-select" className="shrink-0 font-medium">
                    {tCommon('organization')}:
                  </Label>
                  <select
                    id="org-select"
                    value={selectedOrgId ?? ''}
                    onChange={(e) => setSelectedOrgId(e.target.value || null)}
                    className="flex-1 max-w-xs px-3 py-1.5 border rounded-md text-sm bg-background"
                  >
                    {!organizations || organizations.length === 0 ? (
                      <option value="">{t('loadingOrgs')}</option>
                    ) : (
                      organizations.map((org) => (
                        <option key={org.id} value={org.id}>
                          {org.name}
                        </option>
                      ))
                    )}
                  </select>
                </div>
              ) : (
                <div className="flex items-center gap-3">
                  <span className="font-medium text-sm">{tCommon('organization')}:</span>
                  <span className="text-sm text-muted-foreground">{selectedOrgName}</span>
                  <Badge variant="secondary">{t('yourOrganization')}</Badge>
                </div>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {!organizationId ? (
        <Alert>
          <AlertDescription>{t('selectOrgWarning')}</AlertDescription>
        </Alert>
      ) : (
        <>
          {/* Modalidad de facturación */}
          <BillingModeCard
            organizationId={organizationId}
            currentMode={billingMode}
            canEdit={isSuperadmin}
            t={t}
            tCommon={tCommon}
          />

          {/* Zona horaria (bloqueada tras el primer cierre) */}
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <Clock className="h-5 w-5 text-muted-foreground" />
                <CardTitle>{t('timezoneTitle')}</CardTitle>
              </div>
              <CardDescription>{t('timezoneDesc')}</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap items-center gap-3">
                <Badge variant="outline" className="font-mono text-sm">
                  {timezone}
                </Badge>
                {timezoneLocked ? (
                  <span className="flex items-center gap-1 text-xs text-amber-600">
                    <Lock className="h-3 w-3" />
                    {t('timezoneLocked')}
                  </span>
                ) : (
                  <span className="text-xs text-muted-foreground">
                    {t('timezoneEditableHint')}
                  </span>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Editor de tarifas: SOLO superadministrador (Req 10.4, 10.8, 11.1) */}
          {isSuperadmin && (
            <RatePlanEditor organizationId={organizationId} t={t} tCommon={tCommon} />
          )}

          {/* Liquidación anual: SOLO cuando la organización está en modalidad anual (Req 9.5).
              La confirmación manual se restringe a superadministradores (canConfirm). */}
          {billingMode === 'annual' && (
            <AnnualSettlementCard
              organizationId={organizationId}
              canConfirm={isSuperadmin}
              t={t}
              tCommon={tCommon}
            />
          )}

          {/* Cierres mensuales (Req 10.3) + cierre retroactivo solo superadmin (Req 10.5) */}
          <div className="space-y-3">
            {isSuperadmin && (
              <div className="flex items-center justify-end">
                <RetroactiveCloseButton
                  organizationId={organizationId}
                  t={t}
                  tCommon={tCommon}
                />
              </div>
            )}
            <ClosuresTable organizationId={organizationId} t={t} tCommon={tCommon} />
          </div>
        </>
      )}
    </div>
  )
}
