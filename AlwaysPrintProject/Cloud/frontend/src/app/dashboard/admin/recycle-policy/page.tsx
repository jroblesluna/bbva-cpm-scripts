'use client';

/**
 * Página de gestión de la Política de Reciclaje (recycle-policy-config, task 9.3).
 *
 * Visible SOLO para Superadmin (guard `isAdmin()`, Req 8.3): el resto ve un mensaje de acceso
 * denegado. La API además exige `require_admin` server-side. Permite:
 * - Sección Global_Default: ver las políticas globales (regla "+1/-2/-3" + horas) y un formulario
 *   para crear/reemplazar una vía PUT /billing/recycle-policy/global.
 * - Sección Org_Override: selector de organización (organizationsApi.list()) + tabla con los
 *   overrides de esa org (effective_from ya en formato "AAAA-MM") y un formulario para
 *   crear/reemplazar uno vía PUT /billing/recycle-policy/org/{organization_id}.
 *
 * Errores por regla (Req 17.5): ante 422 el backend devuelve `detail.errors = [{rule,message}]`;
 * se muestran TODOS los mensajes en un Alert (sin rechazo silencioso). El 409
 * (ClosedPeriodConflictError) muestra el `detail` string como mensaje de conflicto.
 *
 * i18n (Req 17.4/dynamic-texts): todos los textos vía next-intl (namespace `recyclePolicy` y
 * `common` para botones genéricos).
 */

import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '@/hooks/useAuth';
import { organizationsApi } from '@/lib/api';
import { useTranslations } from 'next-intl';
import {
  Recycle,
  Building2,
  Globe,
  AlertCircle,
  ShieldAlert,
  Save,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useToast } from '@/hooks/use-toast';

import {
  getGlobalRecyclePolicies,
  putGlobalRecyclePolicy,
  getOrgRecyclePolicies,
  putOrgRecyclePolicy,
} from '@/lib/api/recycle-policy';
import type {
  RecyclePolicyIn,
  RecyclePolicyOut,
  RecyclePolicyRuleError,
} from '@/types/recycle-policy';
import type { Organization } from '@/types/organization';

// Valores por defecto del formulario (política legacy Global_Default).
// El Effective_From_Period por defecto es el mes EN CURSO: la política entra en efecto a partir
// del ciclo actual (a su cierre), que es el periodo más temprano configurable (no se permiten
// periodos pasados/cerrados). getMonth() es 0-based, por eso +1.
const DEFAULT_FORM: RecyclePolicyIn = {
  rule: '+1/-2/-3',
  ephemeral_hours: 24,
  effective_from_year: new Date().getFullYear(),
  effective_from_month: new Date().getMonth() + 1,
};

/**
 * Normaliza la Recycle_Rule al formato con signo explícito que exige el backend.
 *
 * El backend valida la regla con el regex `^[+-]\d+/[+-]\d+/[+-]\d+$` (cada offset con signo
 * explícito). Un usuario puede tipear `+1/0/-1` (el `0` sin signo), que es semánticamente
 * válido pero rompe el regex y devuelve 422. Aquí se antepone `+` a cualquier componente sin
 * signo (positivo o cero) para que el payload cumpla el contrato SIN debilitar la validación
 * del servidor. Solo toca componentes numéricos; entradas malformadas se dejan pasar tal cual
 * para que el backend las rechace con su mensaje de formato.
 */
function normalizeRecycleRule(rule: string): string {
  const parts = rule.split('/');
  if (parts.length !== 3) return rule;
  return parts
    .map((p) => {
      const trimmed = p.trim();
      // Ya tiene signo explícito (+/-) o no es un entero: no tocar.
      if (/^[+-]\d+$/.test(trimmed)) return trimmed;
      if (/^\d+$/.test(trimmed)) return `+${trimmed}`;
      return trimmed;
    })
    .join('/');
}

/**
 * Indica si un Effective_From_Period (año/mes) es anterior al mes actual.
 *
 * Regla de negocio: una política solo puede configurarse para el ciclo actual o uno futuro
 * (los periodos pasados o ya cerrados son inmutables y el backend los rechaza con 409). Esta
 * guarda evita siquiera intentar el PUT para un periodo pasado y da un mensaje claro en vez del
 * error genérico del servidor.
 */
function isPastPeriod(year: number, month: number): boolean {
  const now = new Date();
  const currentKey = now.getFullYear() * 12 + now.getMonth(); // getMonth() es 0-based
  const targetKey = year * 12 + (month - 1);
  return targetKey < currentKey;
}

/** Formatea un año/mes como "AAAA-MM" para los mensajes. */
function formatPeriod(year: number, month: number): string {
  return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}`;
}

/**
 * Extrae la lista de errores por regla de un error de API 422.
 * El interceptor de apiClient normaliza el error a `{ detail, status }`; en 422 `detail` es
 * el objeto `{ errors: [{rule, message}, ...] }`. Devuelve [] si no aplica.
 */
function extractRuleErrors(error: unknown): RecyclePolicyRuleError[] {
  const detail = (error as { detail?: unknown })?.detail;
  if (detail && typeof detail === 'object' && Array.isArray((detail as { errors?: unknown }).errors)) {
    return (detail as { errors: RecyclePolicyRuleError[] }).errors;
  }
  return [];
}

/**
 * Extrae un mensaje de conflicto (409) legible del error de API.
 */
function extractDetailMessage(error: unknown): string | null {
  const detail = (error as { detail?: unknown })?.detail;
  if (typeof detail === 'string') return detail;
  return null;
}

export default function RecyclePolicyPage() {
  const { isAdmin } = useAuth();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const t = useTranslations('recyclePolicy');
  const tCommon = useTranslations('common');

  // Formulario Global_Default
  const [globalForm, setGlobalForm] = useState<RecyclePolicyIn>(DEFAULT_FORM);
  const [globalRuleErrors, setGlobalRuleErrors] = useState<RecyclePolicyRuleError[]>([]);
  const [globalConflict, setGlobalConflict] = useState<string | null>(null);

  // Organización seleccionada para overrides
  const [selectedOrgId, setSelectedOrgId] = useState<string | null>(null);

  // Formulario Org_Override
  const [orgForm, setOrgForm] = useState<RecyclePolicyIn>(DEFAULT_FORM);
  const [orgRuleErrors, setOrgRuleErrors] = useState<RecyclePolicyRuleError[]>([]);
  const [orgConflict, setOrgConflict] = useState<string | null>(null);

  const superadmin = isAdmin();

  // Lista de organizaciones (solo si es superadmin)
  const { data: organizations } = useQuery<Organization[]>({
    queryKey: ['organizations-list'],
    queryFn: () => organizationsApi.list(),
    enabled: superadmin,
  });

  // Preseleccionar la primera organización
  useEffect(() => {
    if (superadmin && !selectedOrgId && organizations && organizations.length > 0) {
      setSelectedOrgId(organizations[0].id);
    }
  }, [organizations, superadmin, selectedOrgId]);

  // Query: políticas Global_Default
  const { data: globalPolicies, isLoading: isLoadingGlobal } = useQuery<RecyclePolicyOut[]>({
    queryKey: ['recycle-policy', 'global'],
    queryFn: () => getGlobalRecyclePolicies(),
    enabled: superadmin,
  });

  // Query: Org_Override de la organización seleccionada
  const { data: orgPolicies, isLoading: isLoadingOrg } = useQuery<RecyclePolicyOut[]>({
    queryKey: ['recycle-policy', 'org', selectedOrgId],
    queryFn: () => getOrgRecyclePolicies(selectedOrgId!),
    enabled: superadmin && !!selectedOrgId,
  });

  // Mutation: guardar Global_Default
  const globalMutation = useMutation({
    mutationFn: (payload: RecyclePolicyIn) => putGlobalRecyclePolicy(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recycle-policy', 'global'] });
      setGlobalRuleErrors([]);
      setGlobalConflict(null);
      toast({ title: t('saveSuccessTitle'), description: t('saveGlobalSuccessDesc') });
    },
    onError: (error: any) => {
      const status = error?.status;
      const ruleErrors = extractRuleErrors(error);
      const conflict = extractDetailMessage(error);
      if (status === 422 && ruleErrors.length > 0) {
        setGlobalRuleErrors(ruleErrors);
        setGlobalConflict(null);
        toast({ title: t('validationErrorsTitle'), description: t('validationErrorsToast'), variant: 'destructive' });
      } else if (status === 409) {
        setGlobalRuleErrors([]);
        setGlobalConflict(conflict ?? t('conflictGeneric'));
        toast({ title: t('conflictTitle'), description: conflict ?? t('conflictGeneric'), variant: 'destructive' });
      } else {
        setGlobalRuleErrors([]);
        setGlobalConflict(null);
        toast({ title: t('errorTitle'), description: conflict ?? t('errorSave'), variant: 'destructive' });
      }
    },
  });

  // Mutation: guardar Org_Override
  const orgMutation = useMutation({
    mutationFn: (payload: RecyclePolicyIn) => putOrgRecyclePolicy(selectedOrgId!, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recycle-policy', 'org', selectedOrgId] });
      setOrgRuleErrors([]);
      setOrgConflict(null);
      toast({ title: t('saveSuccessTitle'), description: t('saveOrgSuccessDesc') });
    },
    onError: (error: any) => {
      const status = error?.status;
      const ruleErrors = extractRuleErrors(error);
      const conflict = extractDetailMessage(error);
      if (status === 422 && ruleErrors.length > 0) {
        setOrgRuleErrors(ruleErrors);
        setOrgConflict(null);
        toast({ title: t('validationErrorsTitle'), description: t('validationErrorsToast'), variant: 'destructive' });
      } else if (status === 409) {
        setOrgRuleErrors([]);
        setOrgConflict(conflict ?? t('conflictGeneric'));
        toast({ title: t('conflictTitle'), description: conflict ?? t('conflictGeneric'), variant: 'destructive' });
      } else {
        setOrgRuleErrors([]);
        setOrgConflict(null);
        toast({ title: t('errorTitle'), description: conflict ?? t('errorSave'), variant: 'destructive' });
      }
    },
  });

  // Guard de rol Superadmin (Req 8.3)
  if (!superadmin) {
    return (
      <div className="container mx-auto py-6">
        <Alert variant="destructive">
          <ShieldAlert className="h-4 w-4" />
          <AlertDescription>
            <p className="font-semibold">{t('accessDeniedTitle')}</p>
            <p>{t('accessDeniedDesc')}</p>
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  const selectedOrgName = organizations?.find((o) => o.id === selectedOrgId)?.name ?? '';

  const handleGlobalSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setGlobalRuleErrors([]);
    setGlobalConflict(null);
    // Guarda de negocio: solo ciclo actual o futuro (no reintentar periodos pasados/cerrados).
    if (isPastPeriod(globalForm.effective_from_year, globalForm.effective_from_month)) {
      const msg = t('pastPeriodError', {
        period: formatPeriod(globalForm.effective_from_year, globalForm.effective_from_month),
        current: formatPeriod(new Date().getFullYear(), new Date().getMonth() + 1),
      });
      setGlobalConflict(msg);
      toast({ title: t('errorTitle'), description: msg, variant: 'destructive' });
      return;
    }
    globalMutation.mutate({ ...globalForm, rule: normalizeRecycleRule(globalForm.rule) });
  };

  const handleOrgSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedOrgId) return;
    setOrgRuleErrors([]);
    setOrgConflict(null);
    // Guarda de negocio: solo ciclo actual o futuro (no reintentar periodos pasados/cerrados).
    if (isPastPeriod(orgForm.effective_from_year, orgForm.effective_from_month)) {
      const msg = t('pastPeriodError', {
        period: formatPeriod(orgForm.effective_from_year, orgForm.effective_from_month),
        current: formatPeriod(new Date().getFullYear(), new Date().getMonth() + 1),
      });
      setOrgConflict(msg);
      toast({ title: t('errorTitle'), description: msg, variant: 'destructive' });
      return;
    }
    orgMutation.mutate({ ...orgForm, rule: normalizeRecycleRule(orgForm.rule) });
  };

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Encabezado */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Recycle className="h-7 w-7" />
            {t('title')}
          </h1>
          <p className="text-muted-foreground mt-1">{t('subtitle')}</p>
        </div>
      </div>

      {/* Explicación de la Recycle_Rule */}
      <Alert>
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{t('ruleHelp')}</AlertDescription>
      </Alert>

      {/* ── Sección Global_Default ─────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Globe className="h-5 w-5 text-muted-foreground" />
            <CardTitle>{t('globalSectionTitle')}</CardTitle>
          </div>
          <CardDescription>{t('globalSectionDesc')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Tabla de políticas globales existentes */}
          <div className="overflow-hidden rounded-lg border">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b">
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('colRule')}</th>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('colEphemeralHours')}</th>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('colEffectiveFrom')}</th>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('colCreatedAt')}</th>
                  </tr>
                </thead>
                <tbody>
                  {isLoadingGlobal ? (
                    <tr>
                      <td colSpan={4} className="px-3 py-6 text-center text-muted-foreground">{tCommon('loading')}</td>
                    </tr>
                  ) : !globalPolicies || globalPolicies.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="px-3 py-6 text-center text-muted-foreground">{t('noGlobalPolicies')}</td>
                    </tr>
                  ) : (
                    globalPolicies.map((p) => (
                      <tr key={p.id} className="border-b last:border-0">
                        <td className="px-3 py-3 whitespace-nowrap font-mono">{p.rule}</td>
                        <td className="px-3 py-3 whitespace-nowrap">{t('hoursValue', { hours: p.ephemeral_hours })}</td>
                        <td className="px-3 py-3 whitespace-nowrap">{p.effective_from}</td>
                        <td className="px-3 py-3 whitespace-nowrap text-muted-foreground">
                          {new Date(p.created_at).toLocaleDateString()}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Errores por regla del guardado global (Req 17.5) */}
          {globalRuleErrors.length > 0 && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                <p className="font-semibold mb-2">{t('validationErrorsTitle')}</p>
                <ul className="list-disc list-inside space-y-1">
                  {globalRuleErrors.map((err, i) => (
                    <li key={`${err.rule}-${i}`}>
                      <span className="font-mono text-xs mr-1">[{err.rule}]</span>
                      {err.message}
                    </li>
                  ))}
                </ul>
              </AlertDescription>
            </Alert>
          )}

          {/* Conflicto con periodos cerrados (409) */}
          {globalConflict && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                <p className="font-semibold mb-1">{t('conflictTitle')}</p>
                <p>{globalConflict}</p>
              </AlertDescription>
            </Alert>
          )}

          {/* Formulario Global_Default */}
          <form onSubmit={handleGlobalSubmit} className="space-y-4">
            <h3 className="font-medium">{t('editGlobalTitle')}</h3>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div>
                <Label htmlFor="global-rule">{t('ruleLabel')}</Label>
                <Input
                  id="global-rule"
                  value={globalForm.rule}
                  onChange={(e) => setGlobalForm({ ...globalForm, rule: e.target.value })}
                  placeholder="+1/-2/-3"
                  className="mt-2 font-mono"
                />
              </div>
              <div>
                <Label htmlFor="global-hours">{t('ephemeralHoursLabel')}</Label>
                <Input
                  id="global-hours"
                  type="number"
                  min={1}
                  max={168}
                  value={globalForm.ephemeral_hours}
                  onChange={(e) => setGlobalForm({ ...globalForm, ephemeral_hours: Number(e.target.value) })}
                  className="mt-2"
                />
              </div>
              <div>
                <Label htmlFor="global-year">{t('effectiveYearLabel')}</Label>
                <Input
                  id="global-year"
                  type="number"
                  min={2000}
                  max={2999}
                  value={globalForm.effective_from_year}
                  onChange={(e) => setGlobalForm({ ...globalForm, effective_from_year: Number(e.target.value) })}
                  className="mt-2"
                />
              </div>
              <div>
                <Label htmlFor="global-month">{t('effectiveMonthLabel')}</Label>
                <Input
                  id="global-month"
                  type="number"
                  min={1}
                  max={12}
                  value={globalForm.effective_from_month}
                  onChange={(e) => setGlobalForm({ ...globalForm, effective_from_month: Number(e.target.value) })}
                  className="mt-2"
                />
              </div>
            </div>
            <div className="flex gap-2">
              <Button type="submit" disabled={globalMutation.isPending}>
                <Save className="mr-2 h-4 w-4" />
                {globalMutation.isPending ? tCommon('loading') : tCommon('save')}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* ── Sección Org_Override ───────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Building2 className="h-5 w-5 text-muted-foreground" />
            <CardTitle>{t('orgSectionTitle')}</CardTitle>
          </div>
          <CardDescription>{t('orgSectionDesc')}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Selector de organización */}
          <div className="flex items-center gap-3">
            <Label htmlFor="org-select" className="shrink-0 font-medium">
              {tCommon('organization')}:
            </Label>
            <select
              id="org-select"
              value={selectedOrgId ?? ''}
              onChange={(e) => {
                setSelectedOrgId(e.target.value || null);
                setOrgRuleErrors([]);
                setOrgConflict(null);
              }}
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

          {/* Tabla de overrides de la org seleccionada */}
          <div className="overflow-hidden rounded-lg border">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b">
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('colRule')}</th>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('colEphemeralHours')}</th>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('colEffectiveFrom')}</th>
                    <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('colCreatedAt')}</th>
                  </tr>
                </thead>
                <tbody>
                  {!selectedOrgId ? (
                    <tr>
                      <td colSpan={4} className="px-3 py-6 text-center text-muted-foreground">{t('selectOrgPrompt')}</td>
                    </tr>
                  ) : isLoadingOrg ? (
                    <tr>
                      <td colSpan={4} className="px-3 py-6 text-center text-muted-foreground">{tCommon('loading')}</td>
                    </tr>
                  ) : !orgPolicies || orgPolicies.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="px-3 py-6 text-center text-muted-foreground">{t('noOrgPolicies')}</td>
                    </tr>
                  ) : (
                    orgPolicies.map((p) => (
                      <tr key={p.id} className="border-b last:border-0">
                        <td className="px-3 py-3 whitespace-nowrap font-mono">{p.rule}</td>
                        <td className="px-3 py-3 whitespace-nowrap">{t('hoursValue', { hours: p.ephemeral_hours })}</td>
                        <td className="px-3 py-3 whitespace-nowrap">{p.effective_from}</td>
                        <td className="px-3 py-3 whitespace-nowrap text-muted-foreground">
                          {new Date(p.created_at).toLocaleDateString()}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Errores por regla del guardado de override (Req 17.5) */}
          {orgRuleErrors.length > 0 && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                <p className="font-semibold mb-2">{t('validationErrorsTitle')}</p>
                <ul className="list-disc list-inside space-y-1">
                  {orgRuleErrors.map((err, i) => (
                    <li key={`${err.rule}-${i}`}>
                      <span className="font-mono text-xs mr-1">[{err.rule}]</span>
                      {err.message}
                    </li>
                  ))}
                </ul>
              </AlertDescription>
            </Alert>
          )}

          {/* Conflicto con periodos cerrados (409) */}
          {orgConflict && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                <p className="font-semibold mb-1">{t('conflictTitle')}</p>
                <p>{orgConflict}</p>
              </AlertDescription>
            </Alert>
          )}

          {/* Formulario Org_Override */}
          <form onSubmit={handleOrgSubmit} className="space-y-4">
            <h3 className="font-medium flex items-center gap-2">
              {t('editOrgTitle')}
              {selectedOrgName && <Badge variant="secondary">{selectedOrgName}</Badge>}
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div>
                <Label htmlFor="org-rule">{t('ruleLabel')}</Label>
                <Input
                  id="org-rule"
                  value={orgForm.rule}
                  onChange={(e) => setOrgForm({ ...orgForm, rule: e.target.value })}
                  placeholder="+1/0/-1"
                  className="mt-2 font-mono"
                />
              </div>
              <div>
                <Label htmlFor="org-hours">{t('ephemeralHoursLabel')}</Label>
                <Input
                  id="org-hours"
                  type="number"
                  min={1}
                  max={168}
                  value={orgForm.ephemeral_hours}
                  onChange={(e) => setOrgForm({ ...orgForm, ephemeral_hours: Number(e.target.value) })}
                  className="mt-2"
                />
              </div>
              <div>
                <Label htmlFor="org-year">{t('effectiveYearLabel')}</Label>
                <Input
                  id="org-year"
                  type="number"
                  min={2000}
                  max={2999}
                  value={orgForm.effective_from_year}
                  onChange={(e) => setOrgForm({ ...orgForm, effective_from_year: Number(e.target.value) })}
                  className="mt-2"
                />
              </div>
              <div>
                <Label htmlFor="org-month">{t('effectiveMonthLabel')}</Label>
                <Input
                  id="org-month"
                  type="number"
                  min={1}
                  max={12}
                  value={orgForm.effective_from_month}
                  onChange={(e) => setOrgForm({ ...orgForm, effective_from_month: Number(e.target.value) })}
                  className="mt-2"
                />
              </div>
            </div>
            <div className="flex gap-2">
              <Button type="submit" disabled={!selectedOrgId || orgMutation.isPending}>
                <Save className="mr-2 h-4 w-4" />
                {orgMutation.isPending ? tCommon('loading') : tCommon('save')}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
