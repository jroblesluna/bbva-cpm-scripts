'use client'

/**
 * Editor de planes tarifarios (SOLO superadministrador).
 *
 * Requirements:
 * - 10.4 / 10.8 / 11.1: solo superadministradores editan tarifas por defecto y planes por org.
 *
 * Funcionalidad:
 * - Lista los planes por defecto del sistema (getRatePlans) por modalidad.
 * - Permite editar nombre, moneda, vigencia (effective_from) y los tramos de un plan por
 *   defecto (updateRatePlan).
 * - Permite editar/crear el plan individual de una organización por modalidad (upsertOrgPlan),
 *   partiendo de los tramos del plan por defecto de esa modalidad como base.
 *
 * Este componente NO debe renderizarse para usuarios no-superadmin; el gating se hace en la
 * página contenedora. Aun así, no expone acciones destructivas.
 */

import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslations } from 'next-intl'
import { Plus, Trash2, Save, Building2, Settings2 } from 'lucide-react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { useToast } from '@/hooks/use-toast'

import { getRatePlans, updateRatePlan, upsertOrgPlan } from '@/lib/api/billing'
import type { BillingMode, RatePlan, RateTier } from '@/types/billing'

interface RatePlanEditorProps {
  /** Organización objetivo (para el plan individual). */
  organizationId: string
  /** `t` del namespace `usageAndBilling`. */
  t: ReturnType<typeof useTranslations>
  /** `t` del namespace `common`. */
  tCommon: ReturnType<typeof useTranslations>
}

/** Estado editable de un tramo (todo como string para el formulario, sin `any`). */
interface EditableTier {
  from: string
  to: string
  rate: string
  free_growth_to: string
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

/** Convierte un RateTier del backend a su forma editable (string). */
function toEditable(tier: RateTier): EditableTier {
  return {
    from: String(tier.from),
    to: tier.to === null || tier.to === undefined ? '' : String(tier.to),
    rate: String(tier.rate),
    free_growth_to:
      tier.free_growth_to === undefined || tier.free_growth_to === null
        ? ''
        : String(tier.free_growth_to),
  }
}

/**
 * Convierte los tramos editables de vuelta al tipo RateTier. Un `to` vacío ⇒ null (tramo final
 * sin tope). `free_growth_to` vacío ⇒ se omite (undefined). Los números se parsean con Number().
 */
function fromEditable(tiers: EditableTier[]): RateTier[] {
  return tiers.map((tier) => {
    const parsed: RateTier = {
      from: Number(tier.from),
      to: tier.to.trim() === '' ? null : Number(tier.to),
      // `rate` puede tener 3 decimales; se envía como number.
      rate: Number(tier.rate),
    }
    if (tier.free_growth_to.trim() !== '') {
      parsed.free_growth_to = Number(tier.free_growth_to)
    }
    return parsed
  })
}

/** Fila editable de tramo tarifario. `annual` habilita la columna de crecimiento libre. */
function TierRow({
  tier,
  index,
  isAnnual,
  onChange,
  onRemove,
  t,
  tCommon,
}: {
  tier: EditableTier
  index: number
  isAnnual: boolean
  onChange: (index: number, field: keyof EditableTier, value: string) => void
  onRemove: (index: number) => void
  t: ReturnType<typeof useTranslations>
  tCommon: ReturnType<typeof useTranslations>
}) {
  return (
    <tr className="border-b last:border-b-0">
      <td className="px-2 py-2">
        <Input
          type="number"
          inputMode="numeric"
          value={tier.from}
          onChange={(e) => onChange(index, 'from', e.target.value)}
          className="h-8 w-24"
          aria-label={t('tierFrom')}
        />
      </td>
      <td className="px-2 py-2">
        <Input
          type="number"
          inputMode="numeric"
          value={tier.to}
          placeholder={t('tierNoCap')}
          onChange={(e) => onChange(index, 'to', e.target.value)}
          className="h-8 w-24"
          aria-label={t('tierTo')}
        />
      </td>
      <td className="px-2 py-2">
        <Input
          type="number"
          inputMode="decimal"
          step="0.001"
          value={tier.rate}
          onChange={(e) => onChange(index, 'rate', e.target.value)}
          className="h-8 w-28"
          aria-label={t('tierRate')}
        />
      </td>
      {isAnnual && (
        <td className="px-2 py-2">
          <Input
            type="number"
            inputMode="numeric"
            value={tier.free_growth_to}
            onChange={(e) => onChange(index, 'free_growth_to', e.target.value)}
            className="h-8 w-28"
            aria-label={t('tierFreeGrowth')}
          />
        </td>
      )}
      <td className="px-2 py-2 text-right">
        <Button
          variant="ghost"
          size="sm"
          className="h-7 w-7 p-0"
          onClick={() => onRemove(index)}
          title={tCommon('delete')}
          aria-label={tCommon('delete')}
        >
          <Trash2 className="h-4 w-4 text-destructive" />
        </Button>
      </td>
    </tr>
  )
}

/** Tabla editable de tramos con encabezados traducidos. */
function TierTable({
  tiers,
  isAnnual,
  onChange,
  onRemove,
  onAdd,
  t,
  tCommon,
}: {
  tiers: EditableTier[]
  isAnnual: boolean
  onChange: (index: number, field: keyof EditableTier, value: string) => void
  onRemove: (index: number) => void
  onAdd: () => void
  t: ReturnType<typeof useTranslations>
  tCommon: ReturnType<typeof useTranslations>
}) {
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto border rounded-md">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr>
              <th className="px-2 py-2 text-left text-xs font-medium text-muted-foreground uppercase">
                {t('tierFrom')}
              </th>
              <th className="px-2 py-2 text-left text-xs font-medium text-muted-foreground uppercase">
                {t('tierTo')}
              </th>
              <th className="px-2 py-2 text-left text-xs font-medium text-muted-foreground uppercase">
                {t('tierRate')}
              </th>
              {isAnnual && (
                <th className="px-2 py-2 text-left text-xs font-medium text-muted-foreground uppercase">
                  {t('tierFreeGrowth')}
                </th>
              )}
              <th className="px-2 py-2" />
            </tr>
          </thead>
          <tbody>
            {tiers.length === 0 ? (
              <tr>
                <td
                  colSpan={isAnnual ? 5 : 4}
                  className="px-2 py-4 text-center text-muted-foreground"
                >
                  {t('noTiers')}
                </td>
              </tr>
            ) : (
              tiers.map((tier, index) => (
                <TierRow
                  key={index}
                  tier={tier}
                  index={index}
                  isAnnual={isAnnual}
                  onChange={onChange}
                  onRemove={onRemove}
                  t={t}
                  tCommon={tCommon}
                />
              ))
            )}
          </tbody>
        </table>
      </div>
      <Button variant="outline" size="sm" onClick={onAdd}>
        <Plus className="mr-2 h-4 w-4" />
        {t('addTier')}
      </Button>
    </div>
  )
}

export function RatePlanEditor({ organizationId, t, tCommon }: RatePlanEditorProps) {
  const { toast } = useToast()
  const queryClient = useQueryClient()

  const {
    data: plans,
    isLoading,
    isError,
  } = useQuery<RatePlan[]>({
    queryKey: ['rate-plans'],
    queryFn: () => getRatePlans(),
  })

  // Modalidad seleccionada en el editor (por defecto mensual).
  const [mode, setMode] = useState<BillingMode>('monthly')

  // Plan por defecto de la modalidad seleccionada.
  const defaultPlan = useMemo(
    () => plans?.find((p) => p.mode === mode && p.is_default) ?? plans?.find((p) => p.mode === mode),
    [plans, mode]
  )

  const isAnnual = mode === 'annual'

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Settings2 className="h-5 w-5 text-muted-foreground" />
          <CardTitle>{t('ratePlanTitle')}</CardTitle>
        </div>
        <CardDescription>{t('ratePlanDesc')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Selector de modalidad a editar */}
        <div className="flex items-center gap-3">
          <Label htmlFor="rate-mode" className="shrink-0 font-medium">
            {t('billingModeTitle')}:
          </Label>
          <select
            id="rate-mode"
            value={mode}
            onChange={(e) => setMode(e.target.value as BillingMode)}
            className="px-3 py-1.5 border rounded-md text-sm bg-background"
          >
            <option value="monthly">{t('mode.monthly')}</option>
            <option value="annual">{t('mode.annual')}</option>
          </select>
        </div>

        {isLoading ? (
          <p className="text-center text-muted-foreground py-6">{tCommon('loading')}</p>
        ) : isError ? (
          <Alert variant="destructive">
            <AlertDescription>{t('ratePlanLoadError')}</AlertDescription>
          </Alert>
        ) : !defaultPlan ? (
          <Alert>
            <AlertDescription>{t('noDefaultPlan')}</AlertDescription>
          </Alert>
        ) : (
          <div className="space-y-8">
            <DefaultPlanForm
              key={`default-${defaultPlan.id}`}
              plan={defaultPlan}
              isAnnual={isAnnual}
              onSaved={() => queryClient.invalidateQueries({ queryKey: ['rate-plans'] })}
              extractError={extractError}
              toast={toast}
              t={t}
              tCommon={tCommon}
            />

            <OrgPlanForm
              key={`org-${organizationId}-${defaultPlan.id}`}
              organizationId={organizationId}
              mode={mode}
              isAnnual={isAnnual}
              basePlan={defaultPlan}
              extractError={extractError}
              toast={toast}
              t={t}
              tCommon={tCommon}
            />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ── Formulario del plan por defecto ──────────────────────────────────────────

type ToastFn = ReturnType<typeof useToast>['toast']

function DefaultPlanForm({
  plan,
  isAnnual,
  onSaved,
  extractError,
  toast,
  t,
  tCommon,
}: {
  plan: RatePlan
  isAnnual: boolean
  onSaved: () => void
  extractError: (error: unknown, fallback: string) => string
  toast: ToastFn
  t: ReturnType<typeof useTranslations>
  tCommon: ReturnType<typeof useTranslations>
}) {
  const [name, setName] = useState(plan.name)
  const [currency, setCurrency] = useState(plan.currency)
  // effective_from se maneja como fecha (YYYY-MM-DD) para el input date.
  const [effectiveFrom, setEffectiveFrom] = useState(
    plan.effective_from ? plan.effective_from.slice(0, 10) : ''
  )
  const [tiers, setTiers] = useState<EditableTier[]>(plan.tiers.map(toEditable))

  const mutation = useMutation({
    mutationFn: () =>
      updateRatePlan(plan.id, {
        name,
        currency,
        effective_from: effectiveFrom.trim() === '' ? null : effectiveFrom,
        tiers: fromEditable(tiers),
      }),
    onSuccess: () => {
      toast({ title: t('ratePlanSaved'), description: t('ratePlanSavedDesc') })
      onSaved()
    },
    onError: (error: unknown) => {
      toast({
        title: tCommon('error'),
        description: extractError(error, t('ratePlanSaveError')),
        variant: 'destructive',
      })
    },
  })

  const handleTierChange = (index: number, field: keyof EditableTier, value: string) => {
    setTiers((prev) => prev.map((tier, i) => (i === index ? { ...tier, [field]: value } : tier)))
  }
  const handleRemove = (index: number) => setTiers((prev) => prev.filter((_, i) => i !== index))
  const handleAdd = () =>
    setTiers((prev) => [...prev, { from: '', to: '', rate: '', free_growth_to: '' }])

  return (
    <section className="space-y-4">
      <div className="flex items-center gap-2">
        <h3 className="text-lg font-semibold">{t('defaultPlanTitle')}</h3>
        <Badge variant="secondary">{t('defaultBadge')}</Badge>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="space-y-1">
          <Label htmlFor="plan-name">{tCommon('name')}</Label>
          <Input id="plan-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="plan-currency">{t('currency')}</Label>
          <Input
            id="plan-currency"
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            maxLength={8}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="plan-effective">{t('effectiveFrom')}</Label>
          <Input
            id="plan-effective"
            type="date"
            value={effectiveFrom}
            onChange={(e) => setEffectiveFrom(e.target.value)}
          />
        </div>
      </div>

      <TierTable
        tiers={tiers}
        isAnnual={isAnnual}
        onChange={handleTierChange}
        onRemove={handleRemove}
        onAdd={handleAdd}
        t={t}
        tCommon={tCommon}
      />

      <div className="flex justify-end">
        <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
          <Save className="mr-2 h-4 w-4" />
          {mutation.isPending ? tCommon('saving') : t('saveDefaultPlan')}
        </Button>
      </div>
    </section>
  )
}

// ── Formulario del plan individual de la organización ────────────────────────

function OrgPlanForm({
  organizationId,
  mode,
  isAnnual,
  basePlan,
  extractError,
  toast,
  t,
  tCommon,
}: {
  organizationId: string
  mode: BillingMode
  isAnnual: boolean
  basePlan: RatePlan
  extractError: (error: unknown, fallback: string) => string
  toast: ToastFn
  t: ReturnType<typeof useTranslations>
  tCommon: ReturnType<typeof useTranslations>
}) {
  // El plan individual parte de los tramos del plan por defecto como base editable.
  const [currency, setCurrency] = useState(basePlan.currency)
  const [effectiveFrom, setEffectiveFrom] = useState('')
  const [tiers, setTiers] = useState<EditableTier[]>(basePlan.tiers.map(toEditable))

  const mutation = useMutation({
    mutationFn: () =>
      upsertOrgPlan(organizationId, {
        mode,
        currency,
        effective_from: effectiveFrom.trim() === '' ? null : effectiveFrom,
        tiers: fromEditable(tiers),
      }),
    onSuccess: () => {
      toast({ title: t('orgPlanSaved'), description: t('orgPlanSavedDesc') })
    },
    onError: (error: unknown) => {
      toast({
        title: tCommon('error'),
        description: extractError(error, t('orgPlanSaveError')),
        variant: 'destructive',
      })
    },
  })

  const handleTierChange = (index: number, field: keyof EditableTier, value: string) => {
    setTiers((prev) => prev.map((tier, i) => (i === index ? { ...tier, [field]: value } : tier)))
  }
  const handleRemove = (index: number) => setTiers((prev) => prev.filter((_, i) => i !== index))
  const handleAdd = () =>
    setTiers((prev) => [...prev, { from: '', to: '', rate: '', free_growth_to: '' }])

  return (
    <section className="space-y-4 border-t pt-6">
      <div className="flex items-center gap-2">
        <Building2 className="h-5 w-5 text-muted-foreground" />
        <h3 className="text-lg font-semibold">{t('orgPlanTitle')}</h3>
      </div>
      <p className="text-sm text-muted-foreground">{t('orgPlanDesc')}</p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="space-y-1">
          <Label htmlFor="org-plan-currency">{t('currency')}</Label>
          <Input
            id="org-plan-currency"
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            maxLength={8}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="org-plan-effective">{t('effectiveFrom')}</Label>
          <Input
            id="org-plan-effective"
            type="date"
            value={effectiveFrom}
            onChange={(e) => setEffectiveFrom(e.target.value)}
          />
        </div>
      </div>

      <TierTable
        tiers={tiers}
        isAnnual={isAnnual}
        onChange={handleTierChange}
        onRemove={handleRemove}
        onAdd={handleAdd}
        t={t}
        tCommon={tCommon}
      />

      <div className="flex justify-end">
        <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
          <Save className="mr-2 h-4 w-4" />
          {mutation.isPending ? tCommon('saving') : t('saveOrgPlan')}
        </Button>
      </div>
    </section>
  )
}
