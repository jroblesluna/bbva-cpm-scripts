/**
 * Página de configuración del sistema - Rediseño con cards por organización.
 *
 * Admin: Ve cards de todas las organizaciones con resumen de config, puede ir a editar.
 * Operador: Va directamente al editor de su organización, agrupado por tópicos.
 */

'use client';

import { useState, useEffect } from 'react';
import { apiClient, organizationsApi } from '@/lib/api';
import { useAuth } from '@/hooks/useAuth';
import { formatDateWithTimezone } from '@/lib/dateUtils';
import { useUserTimezone } from '@/hooks/useUserTimezone';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  Save,
  RotateCcw,
  Plus,
  X,
  Info,
  AlertCircle,
  Building2,
  RefreshCw,
  Pin,
  Pencil,
  ArrowLeft,
  Printer,
  Network,
  Wifi,
  Download,
  Search,
  Cog,
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { ConnectivityCheckEditor } from '@/components/ConnectivityCheckEditor';
import { LocaleSelector } from '@/components/LocaleSelector';
import { ActionConfigSection } from '@/components/config/ActionConfigSection';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import type {
  GlobalConfig,
  GlobalConfigUpdate,
  SearchTargets,
  ConnectivityCheck,
} from '@/types/config';
import { listActionConfigs } from '@/lib/api/action-config';

interface Account {
  id: string;
  name: string;
  timezone: string;
  is_active: boolean;
  auto_update_enabled: boolean;
  target_version: string | null;
  auto_reregister_enabled: boolean;
}

interface OrgConfigSummary {
  organization_id: string;
  corporate_queue_name: string;
  pending_task_polling_minutes: number;
  bootstrap_domains: string;
  search_targets: SearchTargets | null;
  connectivity_checks: ConnectivityCheck[];
  locale: string;
  updated_at: string;
  exists: boolean;
  activeActionConfig: string | null; // nombre de la config activa, o null
}

export default function ConfigPage() {
  const { user } = useAuth();
  const t = useTranslations('config');
  const tCommon = useTranslations('common');
  const userTimezone = useUserTimezone();

  // Estado principal: admin ve lista, operador ve editor directamente
  const [editingOrgId, setEditingOrgId] = useState<string | null>(null);
  const [editingOrgName, setEditingOrgName] = useState<string>('');

  // Lista de organizaciones (admin)
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [orgConfigs, setOrgConfigs] = useState<Record<string, OrgConfigSummary>>({});
  const [loadingAccounts, setLoadingAccounts] = useState(false);
  const [searchFilter, setSearchFilter] = useState('');

  // Editor state
  const [config, setConfig] = useState<GlobalConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);

  // Form state
  const [corporateQueueName, setCorporateQueueName] = useState('');
  const [pollingMinutes, setPollingMinutes] = useState(5);
  const [bootstrapDomains, setBootstrapDomains] = useState('');
  const [searchIps, setSearchIps] = useState<string[]>(['']);
  const [searchRanges, setSearchRanges] = useState<string[]>(['']);
  const [connectivityChecks, setConnectivityChecks] = useState<ConnectivityCheck[]>([]);
  const [locale, setLocale] = useState('');

  // Auto-update state
  const [autoUpdateEnabled, setAutoUpdateEnabled] = useState(false);
  const [targetVersion, setTargetVersion] = useState<string | null>(null);
  const [autoReregisterEnabled, setAutoReregisterEnabled] = useState(false);
  const [togglingAutoUpdate, setTogglingAutoUpdate] = useState(false);
  const [availableVersions, setAvailableVersions] = useState<Array<{ version: string }>>([]);

  // === EFFECTS ===

  useEffect(() => {
    if (user?.role === 'admin') {
      loadAccounts();
    } else if (user?.role === 'operator' || user?.role === 'readonly') {
      // Operador va directo a editar su organización
      if (user?.organization_id) {
        setEditingOrgId(user.organization_id);
        setEditingOrgName('');
      }
    }
  }, [user]);

  // Cargar config cuando se entra en modo edición
  useEffect(() => {
    if (editingOrgId) {
      loadConfig(editingOrgId);
      loadOrgUpdateState(editingOrgId);
    }
  }, [editingOrgId]);

  // Cargar versiones disponibles
  useEffect(() => {
    const loadVersions = async () => {
      try {
        const response = await apiClient.get('/updates/versions');
        setAvailableVersions(
          (response.data || []).map((v: { version: string }) => ({ version: v.version }))
        );
      } catch {
        setAvailableVersions([]);
      }
    };
    if (user?.role === 'admin' || user?.role === 'operator') {
      loadVersions();
    }
  }, [user?.role]);

  // === LOADERS ===

  const loadAccounts = async () => {
    try {
      setLoadingAccounts(true);
      const response = await apiClient.get('/organizations/?skip=0&limit=1000');
      const data = response.data;
      const items: Account[] = data.items || [];
      setAccounts(items);

      // Cargar resumen de config para cada organización
      const configs: Record<string, OrgConfigSummary> = {};
      await Promise.all(
        items.map(async (acc) => {
          try {
            const res = await apiClient.get(`/config/global?organization_id=${acc.id}`);
            const d = res.data;
            // Intentar obtener action config activa
            let activeActionConfigName: string | null = null;
            try {
              const actionConfigs = await listActionConfigs(acc.id);
              const active = actionConfigs.find((c) => c.is_active);
              activeActionConfigName = active?.name ?? null;
            } catch { /* sin action config */ }

            configs[acc.id] = {
              organization_id: acc.id,
              corporate_queue_name: d.corporate_queue_name || '',
              pending_task_polling_minutes: d.pending_task_polling_minutes || 5,
              bootstrap_domains: d.bootstrap_domains || '',
              search_targets: d.search_targets || null,
              connectivity_checks: d.connectivity_checks || [],
              locale: d.locale || '',
              updated_at: d.updated_at || '',
              exists: !!d.id,
              activeActionConfig: activeActionConfigName,
            };
          } catch {
            configs[acc.id] = {
              organization_id: acc.id,
              corporate_queue_name: '',
              pending_task_polling_minutes: 5,
              bootstrap_domains: '',
              search_targets: null,
              connectivity_checks: [],
              locale: '',
              updated_at: '',
              exists: false,
              activeActionConfig: null,
            };
          }
        })
      );
      setOrgConfigs(configs);
    } catch (error: unknown) {
      const err = error as { detail?: string; message?: string };
      console.error('Error al cargar organizaciones:', err.detail || err.message);
    } finally {
      setLoadingAccounts(false);
    }
  };

  const loadOrgUpdateState = async (orgId: string) => {
    try {
      const acc = await organizationsApi.get(orgId);
      setAutoUpdateEnabled(acc.auto_update_enabled ?? false);
      setTargetVersion(acc.target_version ?? null);
      setAutoReregisterEnabled(acc.auto_reregister_enabled ?? false);
    } catch {
      setAutoUpdateEnabled(false);
      setTargetVersion(null);
      setAutoReregisterEnabled(false);
    }
  };

  const loadConfig = async (orgId: string) => {
    try {
      setLoading(true);
      let url = '/config/global';
      if (user?.role === 'admin') {
        url += `?organization_id=${orgId}`;
      }

      const response = await apiClient.get(url);
      const data: GlobalConfig = response.data;

      if (!data.id) {
        setConfig(null);
        setCorporateQueueName(data.corporate_queue_name || '');
        setPollingMinutes(data.pending_task_polling_minutes || 5);
        setBootstrapDomains(data.bootstrap_domains || '');
        setSearchIps(['']);
        setSearchRanges(['']);
        setConnectivityChecks([]);
        setLocale('');
        setHasChanges(false);
        return;
      }

      setConfig(data);
      setCorporateQueueName(data.corporate_queue_name);
      setPollingMinutes(data.pending_task_polling_minutes);
      setBootstrapDomains(data.bootstrap_domains);

      if (data.search_targets) {
        setSearchIps(data.search_targets.ips || ['']);
        setSearchRanges(data.search_targets.ranges || ['']);
      } else {
        setSearchIps(['']);
        setSearchRanges(['']);
      }

      const configData = data as GlobalConfig & {
        connectivity_checks?: ConnectivityCheck[];
        locale?: string;
      };
      setConnectivityChecks(configData.connectivity_checks || []);
      setLocale(configData.locale || '');
      setHasChanges(false);
    } catch (error: unknown) {
      const err = error as { detail?: string; message?: string };
      console.error('Error al cargar configuración:', err.detail || err.message);
    } finally {
      setLoading(false);
    }
  };

  // === HANDLERS ===

  const handleSave = async () => {
    if (!corporateQueueName.trim()) {
      alert(t('validationQueueRequired'));
      return;
    }
    if (pollingMinutes < 1 || pollingMinutes > 1440) {
      alert(t('validationPollingRange'));
      return;
    }
    if (!editingOrgId) return;

    try {
      setSaving(true);
      const validIps = searchIps.filter((ip) => ip.trim());
      const validRanges = searchRanges.filter((range) => range.trim());

      const searchTargets: SearchTargets | null =
        validIps.length > 0 || validRanges.length > 0
          ? {
              ...(validIps.length > 0 && { ips: validIps }),
              ...(validRanges.length > 0 && { ranges: validRanges }),
            }
          : null;

      const updateData: GlobalConfigUpdate = {
        corporate_queue_name: corporateQueueName.trim(),
        pending_task_polling_minutes: pollingMinutes,
        bootstrap_domains: bootstrapDomains.trim(),
        search_targets: searchTargets,
        connectivity_checks: connectivityChecks,
        locale: locale,
      };

      let url = '/config/global';
      if (user?.role === 'admin') {
        url += `?organization_id=${editingOrgId}`;
      }

      const response = await apiClient.put(url, updateData);
      const data: GlobalConfig = response.data;
      setConfig(data);
      setHasChanges(false);
      alert(t('saveSuccess'));
    } catch (error: unknown) {
      const err = error as { message?: string };
      alert(err.message || t('saveError'));
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    if (!config) return;
    setCorporateQueueName(config.corporate_queue_name);
    setPollingMinutes(config.pending_task_polling_minutes);
    setBootstrapDomains(config.bootstrap_domains);
    if (config.search_targets) {
      setSearchIps(config.search_targets.ips || ['']);
      setSearchRanges(config.search_targets.ranges || ['']);
    } else {
      setSearchIps(['']);
      setSearchRanges(['']);
    }
    const configData = config as GlobalConfig & {
      connectivity_checks?: ConnectivityCheck[];
      locale?: string;
    };
    setConnectivityChecks(configData.connectivity_checks || []);
    setLocale(configData.locale || '');
    setHasChanges(false);
  };

  const handleAutoUpdateToggle = async (enabled: boolean) => {
    if (!editingOrgId) return;
    setTogglingAutoUpdate(true);
    try {
      await apiClient.patch(`/organizations/${editingOrgId}/auto-update`, { enabled });
      setAutoUpdateEnabled(enabled);
    } catch { /* revert silently */ }
    finally { setTogglingAutoUpdate(false); }
  };

  const handleReregisterToggle = async (enabled: boolean) => {
    if (!editingOrgId) return;
    setTogglingAutoUpdate(true);
    try {
      await apiClient.put(`/organizations/${editingOrgId}`, { auto_reregister_enabled: enabled });
      setAutoReregisterEnabled(enabled);
    } catch { /* revert silently */ }
    finally { setTogglingAutoUpdate(false); }
  };

  const handlePinVersion = async (version: string | null) => {
    if (!editingOrgId) return;
    setTogglingAutoUpdate(true);
    try {
      await apiClient.put(`/updates/pin/${editingOrgId}`, { version });
      setTargetVersion(version);
    } catch { /* revert silently */ }
    finally { setTogglingAutoUpdate(false); }
  };

  // Search targets helpers
  const addSearchIp = () => { setSearchIps([...searchIps, '']); setHasChanges(true); };
  const removeSearchIp = (index: number) => { setSearchIps(searchIps.filter((_, i) => i !== index)); setHasChanges(true); };
  const updateSearchIp = (index: number, value: string) => { const n = [...searchIps]; n[index] = value; setSearchIps(n); setHasChanges(true); };
  const addSearchRange = () => { setSearchRanges([...searchRanges, '']); setHasChanges(true); };
  const removeSearchRange = (index: number) => { setSearchRanges(searchRanges.filter((_, i) => i !== index)); setHasChanges(true); };
  const updateSearchRange = (index: number, value: string) => { const n = [...searchRanges]; n[index] = value; setSearchRanges(n); setHasChanges(true); };

  const handleBackToList = () => {
    setEditingOrgId(null);
    setEditingOrgName('');
    setConfig(null);
    setHasChanges(false);
  };

  // === FILTERED ACCOUNTS ===
  const filteredAccounts = accounts.filter((acc) =>
    acc.name.toLowerCase().includes(searchFilter.toLowerCase())
  );

  // === LOADING STATE ===
  if (loading || (user?.role === 'admin' && loadingAccounts && !editingOrgId)) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">{tCommon('loading')}</p>
        </div>
      </div>
    );
  }

  // === ADMIN: CARDS VIEW (lista de organizaciones) ===
  if (user?.role === 'admin' && !editingOrgId) {
    return (
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-gray-900">{t('title')}</h1>
            <p className="mt-2 text-gray-600">{t('subtitle')}</p>
          </div>
        </div>

        {/* Barra de búsqueda */}
        <div className="bg-white rounded-lg shadow p-4">
          <div className="flex items-center gap-3">
            <Search className="h-5 w-5 text-gray-400" />
            <Input
              type="text"
              value={searchFilter}
              onChange={(e) => setSearchFilter(e.target.value)}
              placeholder={t('searchOrgsPlaceholder')}
              className="max-w-sm"
            />
            {searchFilter && (
              <Button variant="ghost" size="sm" onClick={() => setSearchFilter('')}>
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>

        {/* Cards de organizaciones */}
        {filteredAccounts.length === 0 ? (
          <div className="bg-white rounded-lg shadow p-12 text-center">
            <Building2 className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-4 text-lg font-medium text-gray-900">{t('noOrgsFound')}</h3>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {filteredAccounts.map((acc) => {
              const cfg = orgConfigs[acc.id];
              return (
                <div
                  key={acc.id}
                  className="bg-white rounded-lg shadow hover:shadow-md transition-shadow border border-gray-100"
                >
                  <div className="p-5">
                    {/* Header de la card */}
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-lg bg-blue-100 flex items-center justify-center">
                          <Building2 className="h-5 w-5 text-blue-600" />
                        </div>
                        <div>
                          <h3 className="font-semibold text-gray-900">{acc.name}</h3>
                          <Badge variant={acc.is_active ? 'default' : 'secondary'} className="text-xs mt-0.5">
                            {acc.is_active ? tCommon('active') : tCommon('inactive')}
                          </Badge>
                        </div>
                      </div>
                    </div>

                    {/* Resumen de configuración */}
                    {cfg ? (
                      <div className="space-y-2 text-sm">
                        {cfg.exists ? (
                          <>
                            <div className="flex items-center gap-2 text-gray-600">
                              <Printer className="h-3.5 w-3.5 flex-shrink-0" />
                              <span className="truncate">
                                {t('cardQueue')}: <span className="font-medium text-gray-900">{cfg.corporate_queue_name || '—'}</span>
                              </span>
                            </div>
                            <div className="flex items-center gap-2 text-gray-600">
                              <RefreshCw className="h-3.5 w-3.5 flex-shrink-0" />
                              <span>
                                {t('cardPolling')}: <span className="font-medium text-gray-900">{cfg.pending_task_polling_minutes} min</span>
                              </span>
                            </div>
                            <div className="flex items-center gap-2 text-gray-600">
                              <Wifi className="h-3.5 w-3.5 flex-shrink-0" />
                              <span>
                                {t('cardChecks')}: <span className="font-medium text-gray-900">{cfg.connectivity_checks.length}</span>
                              </span>
                            </div>
                            <div className="flex items-center gap-2 text-gray-600">
                              <Download className="h-3.5 w-3.5 flex-shrink-0" />
                              <span>
                                {t('cardAutoUpdate')}: <Badge variant={acc.auto_update_enabled ? 'default' : 'secondary'} className="text-xs">
                                  {acc.auto_update_enabled ? t('cardEnabled') : t('cardDisabled')}
                                </Badge>
                              </span>
                            </div>
                            <div className="flex items-center gap-2 text-gray-600">
                              <Cog className="h-3.5 w-3.5 flex-shrink-0" />
                              <span>
                                {t('cardActions')}: <span className="font-medium text-gray-900">
                                  {cfg.activeActionConfig || t('cardNoActions')}
                                </span>
                              </span>
                            </div>
                          </>
                        ) : (
                          <div className="flex items-center gap-2 text-amber-600">
                            <AlertCircle className="h-4 w-4" />
                            <span>{t('cardNoConfig')}</span>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="animate-pulse space-y-2">
                        <div className="h-4 bg-gray-200 rounded w-3/4"></div>
                        <div className="h-4 bg-gray-200 rounded w-1/2"></div>
                      </div>
                    )}

                    {/* Botón editar */}
                    <div className="mt-4 pt-3 border-t border-gray-100">
                      <Button
                        variant="outline"
                        size="sm"
                        className="w-full"
                        onClick={() => {
                          setEditingOrgId(acc.id);
                          setEditingOrgName(acc.name);
                        }}
                      >
                        <Pencil className="mr-2 h-4 w-4" />
                        {t('cardEditConfig')}
                      </Button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  // === EDITOR VIEW (admin editando una org, u operador con su org) ===
  return (
    <div className="space-y-6">
      {/* Header con botón volver (solo admin) */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          {user?.role === 'admin' && (
            <Button variant="ghost" size="sm" onClick={handleBackToList}>
              <ArrowLeft className="h-4 w-4" />
            </Button>
          )}
          <div>
            <h1 className="text-2xl font-bold text-gray-900">
              {editingOrgName ? t('editingOrg', { name: editingOrgName }) : t('orgTitle')}
            </h1>
            <p className="mt-1 text-sm text-gray-600">{t('orgDesc')}</p>
          </div>
        </div>
        <div className="flex gap-2">
          {hasChanges && (
            <Button variant="outline" onClick={handleReset} disabled={saving}>
              <RotateCcw className="mr-2 h-4 w-4" />
              {t('discard')}
            </Button>
          )}
          <Button onClick={handleSave} disabled={saving || !hasChanges}>
            <Save className="mr-2 h-4 w-4" />
            {saving ? t('saving') : t('save')}
          </Button>
        </div>
      </div>

      {/* Loading del editor */}
      {loading ? (
        <div className="flex items-center justify-center h-48">
          <div className="text-center">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600 mx-auto"></div>
            <p className="mt-3 text-gray-600">{tCommon('loading')}</p>
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Alerta de jerarquía */}
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <div className="flex">
              <Info className="h-5 w-5 text-blue-600 mr-3 flex-shrink-0 mt-0.5" />
              <div>
                <h3 className="text-sm font-medium text-blue-900">{t('hierarchyTitle')}</h3>
                <p className="mt-1 text-sm text-blue-700">{t('hierarchyMsg')}</p>
                <div className="mt-2 text-xs text-blue-600 font-mono">{t('hierarchy')}</div>
              </div>
            </div>
          </div>

          {/* === TÓPICO 1: IMPRESIÓN === */}
          <div className="bg-white rounded-lg shadow">
            <div className="p-6">
              <div className="flex items-center gap-3 mb-5">
                <div className="w-9 h-9 rounded-lg bg-purple-100 flex items-center justify-center">
                  <Printer className="h-5 w-5 text-purple-600" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-gray-900">{t('topicPrinting')}</h2>
                  <p className="text-sm text-gray-500">{t('topicPrintingDesc')}</p>
                </div>
              </div>

              <div className="space-y-5">
                {/* Cola Corporativa */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {t('corpQueue')}
                  </label>
                  <Input
                    type="text"
                    value={corporateQueueName}
                    onChange={(e) => { setCorporateQueueName(e.target.value); setHasChanges(true); }}
                    placeholder={t('corpQueuePlaceholder')}
                    className="max-w-md"
                  />
                  <p className="mt-1 text-sm text-gray-500">{t('corpQueueHelper')}</p>
                </div>

                {/* Intervalo de Polling */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {t('pollingInterval')}
                  </label>
                  <Input
                    type="number"
                    min="1"
                    max="1440"
                    value={pollingMinutes}
                    onChange={(e) => { setPollingMinutes(parseInt(e.target.value) || 1); setHasChanges(true); }}
                    className="max-w-xs"
                  />
                  <p className="mt-1 text-sm text-gray-500">{t('pollingHelper')}</p>
                </div>

                {/* Locale */}
                <LocaleSelector
                  value={locale}
                  onChange={(value) => { setLocale(value); setHasChanges(true); }}
                />
              </div>
            </div>
          </div>

          {/* === TÓPICO 2: RED Y DESCUBRIMIENTO === */}
          <div className="bg-white rounded-lg shadow">
            <div className="p-6">
              <div className="flex items-center gap-3 mb-5">
                <div className="w-9 h-9 rounded-lg bg-green-100 flex items-center justify-center">
                  <Network className="h-5 w-5 text-green-600" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-gray-900">{t('topicNetwork')}</h2>
                  <p className="text-sm text-gray-500">{t('topicNetworkDesc')}</p>
                </div>
              </div>

              <div className="space-y-5">
                {/* Dominios de Bootstrap */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {t('bootstrapDomains')}
                  </label>
                  <Input
                    type="text"
                    value={bootstrapDomains}
                    onChange={(e) => { setBootstrapDomains(e.target.value); setHasChanges(true); }}
                    placeholder={t('bootstrapPlaceholder')}
                    className="max-w-md"
                  />
                  <p className="mt-1 text-sm text-gray-500">{t('bootstrapHelper')}</p>
                </div>

                {/* IPs de Búsqueda */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {t('printerIps')}
                  </label>
                  <div className="space-y-2">
                    {searchIps.map((ip, index) => (
                      <div key={index} className="flex gap-2">
                        <Input
                          type="text"
                          value={ip}
                          onChange={(e) => updateSearchIp(index, e.target.value)}
                          placeholder="192.168.1.100"
                          className="max-w-md"
                        />
                        {searchIps.length > 1 && (
                          <Button type="button" variant="outline" size="sm" onClick={() => removeSearchIp(index)}>
                            <X className="h-4 w-4" />
                          </Button>
                        )}
                      </div>
                    ))}
                  </div>
                  <Button type="button" variant="outline" size="sm" onClick={addSearchIp} className="mt-2">
                    <Plus className="mr-2 h-4 w-4" />
                    {t('addIp')}
                  </Button>
                  <p className="mt-1 text-sm text-gray-500">{t('printerIpsHelper')}</p>
                </div>

                {/* Rangos de Búsqueda */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {t('printerRanges')}
                  </label>
                  <div className="space-y-2">
                    {searchRanges.map((range, index) => (
                      <div key={index} className="flex gap-2">
                        <Input
                          type="text"
                          value={range}
                          onChange={(e) => updateSearchRange(index, e.target.value)}
                          placeholder="192.168.1.0/24"
                          className="max-w-md"
                        />
                        {searchRanges.length > 1 && (
                          <Button type="button" variant="outline" size="sm" onClick={() => removeSearchRange(index)}>
                            <X className="h-4 w-4" />
                          </Button>
                        )}
                      </div>
                    ))}
                  </div>
                  <Button type="button" variant="outline" size="sm" onClick={addSearchRange} className="mt-2">
                    <Plus className="mr-2 h-4 w-4" />
                    {t('addRange')}
                  </Button>
                  <p className="mt-1 text-sm text-gray-500">{t('printerRangesHelper')}</p>
                </div>
              </div>
            </div>
          </div>

          {/* === TÓPICO 3: CONECTIVIDAD === */}
          <div className="bg-white rounded-lg shadow">
            <div className="p-6">
              <div className="flex items-center gap-3 mb-5">
                <div className="w-9 h-9 rounded-lg bg-orange-100 flex items-center justify-center">
                  <Wifi className="h-5 w-5 text-orange-600" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-gray-900">{t('topicConnectivity')}</h2>
                  <p className="text-sm text-gray-500">{t('topicConnectivityDesc')}</p>
                </div>
              </div>

              <ConnectivityCheckEditor
                checks={connectivityChecks}
                onChange={(checks) => { setConnectivityChecks(checks); setHasChanges(true); }}
              />
            </div>
          </div>

          {/* === TÓPICO 4: ACTUALIZACIONES Y RE-REGISTRO === */}
          <div className="bg-white rounded-lg shadow">
            <div className="p-6">
              <div className="flex items-center gap-3 mb-5">
                <div className="w-9 h-9 rounded-lg bg-blue-100 flex items-center justify-center">
                  <Download className="h-5 w-5 text-blue-600" />
                </div>
                <div>
                  <h2 className="text-lg font-semibold text-gray-900">{t('updatesTitle')}</h2>
                  <p className="text-sm text-gray-500">{t('updatesDesc')}</p>
                </div>
              </div>

              <div className="space-y-4">
                {/* Toggle de auto-actualización */}
                <div className="flex items-center justify-between p-4 border rounded-lg">
                  <div>
                    <Label className="text-sm font-medium">{t('autoUpdateLabel')}</Label>
                    <p className="text-xs text-gray-500 mt-1">
                      {autoUpdateEnabled ? t('autoUpdateEnabledDesc') : t('autoUpdateDisabledDesc')}
                    </p>
                  </div>
                  <Switch
                    checked={autoUpdateEnabled}
                    onCheckedChange={handleAutoUpdateToggle}
                    disabled={togglingAutoUpdate}
                  />
                </div>

                {/* Selector de versión pineada */}
                <div className="flex items-center gap-3 p-4 border rounded-lg">
                  <Pin className="h-4 w-4 text-gray-500 flex-shrink-0" />
                  <div className="flex items-center gap-2 flex-1">
                    <span className="text-sm text-gray-700">{t('pinnedVersionLabel')}</span>
                    <select
                      className="text-sm border rounded px-2 py-1 bg-white"
                      value={targetVersion ?? ''}
                      onChange={(e) => handlePinVersion(e.target.value || null)}
                      disabled={togglingAutoUpdate}
                    >
                      <option value="">{t('pinnedVersionLatest')}</option>
                      {availableVersions.map((v) => (
                        <option key={v.version} value={v.version}>{v.version}</option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* Nota contextual */}
                {autoUpdateEnabled && targetVersion && (
                  <p className="text-xs text-amber-600 px-4">{t('pinnedVersionNote', { version: targetVersion })}</p>
                )}
                {autoUpdateEnabled && !targetVersion && (
                  <p className="text-xs text-gray-500 px-4">{t('latestVersionNote')}</p>
                )}

                {/* Toggle de re-registro automático */}
                <div className="flex items-center justify-between p-4 border rounded-lg">
                  <div>
                    <Label className="text-sm font-medium">{t('autoReregisterLabel')}</Label>
                    <p className="text-xs text-gray-500 mt-1">
                      {autoReregisterEnabled ? t('autoReregisterEnabledDesc') : t('autoReregisterDisabledDesc')}
                    </p>
                  </div>
                  <Switch
                    checked={autoReregisterEnabled}
                    onCheckedChange={handleReregisterToggle}
                    disabled={togglingAutoUpdate}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* === TÓPICO 5: ACCIONES ADMINISTRATIVAS === */}
          {editingOrgId && (
            <ActionConfigSection organizationId={editingOrgId} />
          )}

          {/* Advertencia si no hay configuración */}
          {!config && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
              <div className="flex">
                <AlertCircle className="h-5 w-5 text-yellow-600 mr-3 flex-shrink-0 mt-0.5" />
                <div>
                  <h3 className="text-sm font-medium text-yellow-900">{t('noConfigTitle')}</h3>
                  <p className="mt-1 text-sm text-yellow-700">{t('noConfigMsg')}</p>
                </div>
              </div>
            </div>
          )}

          {/* Estado de la configuración */}
          {config && (
            <div className="bg-gray-50 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-900 mb-2">{tCommon('status')}</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-gray-600">{t('lastUpdated')}</span>
                  <span className="ml-2 text-gray-900">
                    {formatDateWithTimezone(config.updated_at, userTimezone)}
                  </span>
                </div>
                <div>
                  <span className="text-gray-600">{t('created')}</span>
                  <span className="ml-2 text-gray-900">
                    {formatDateWithTimezone(config.created_at, userTimezone)}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
