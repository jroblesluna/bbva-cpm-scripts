/**
 * Página de configuración del sistema.
 *
 * Estructura jerárquica de configuración:
 * 1. Configuración Global (sistema) - Aplica a todas las organizaciones
 * 2. Configuración por Organización - Sobrescribe la global para esa organización
 * 3. Configuración por VLAN - Sobrescribe la de organización para esa VLAN
 * 4. Configuración por Workstation - Sobrescribe todo lo anterior para esa workstation
 *
 * Esta página permite gestionar los niveles 1 y 2.
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
  Settings,
  Save,
  RotateCcw,
  Plus,
  X,
  Info,
  AlertCircle,
  Building2,
  Globe,
  RefreshCw,
  Pin,
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { ConnectivityCheckEditor } from '@/components/ConnectivityCheckEditor';
import { LocaleSelector } from '@/components/LocaleSelector';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import type {
  GlobalConfig,
  GlobalConfigUpdate,
  SearchTargets,
  ConnectivityCheck,
} from '@/types/config';

interface Account {
  id: string;
  name: string;
  timezone: string;
}

type ConfigTab = 'global' | 'organization';

export default function ConfigPage() {
  const { user } = useAuth();
  const t = useTranslations('config');
  const userTimezone = useUserTimezone();
  const tCommon = useTranslations('common');
  const [activeTab, setActiveTab] = useState<ConfigTab>('organization');
  const [config, setConfig] = useState<GlobalConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);

  // Selector de organización (solo para Admin en tab de organización)
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [selectedOrgId, setSelectedOrgId] = useState<string>('');
  const [loadingAccounts, setLoadingAccounts] = useState(false);

  // Form state
  const [corporateQueueName, setCorporateQueueName] = useState('');
  const [pollingMinutes, setPollingMinutes] = useState(5);
  const [bootstrapDomains, setBootstrapDomains] = useState('');
  const [searchIps, setSearchIps] = useState<string[]>(['']);
  const [searchRanges, setSearchRanges] = useState<string[]>(['']);
  const [connectivityChecks, setConnectivityChecks] = useState<ConnectivityCheck[]>([]);
  const [locale, setLocale] = useState('');

  // Estado de auto-actualización por organización
  const [autoUpdateEnabled, setAutoUpdateEnabled] = useState(false);
  const [targetVersion, setTargetVersion] = useState<string | null>(null);
  const [autoReregisterEnabled, setAutoReregisterEnabled] = useState(false);
  const [togglingAutoUpdate, setTogglingAutoUpdate] = useState(false);
  const [availableVersions, setAvailableVersions] = useState<Array<{ version: string }>>([]);

  // Obtener nombre de la organización seleccionada para placeholders
  const getSelectedAccountName = (): string => {
    if (user?.role === 'admin' && selectedOrgId) {
      const account = accounts.find((a) => a.id === selectedOrgId);
      return account?.name || 'Organización';
    }
    // Para operadores, obtener el nombre de su cuenta desde user (si está disponible)
    // Por ahora retornamos un nombre genérico
    return 'Organización';
  };

  const queuePlaceholder = `Lexmark${getSelectedAccountName().replace(/\s+/g, '')}`;
  const domainPlaceholder = `${getSelectedAccountName().toLowerCase().replace(/\s+/g, '')}.com,${getSelectedAccountName().toLowerCase().replace(/\s+/g, '')}.local`;

  // Cargar organizaciones (solo para Admin)
  useEffect(() => {
    if (user?.role === 'admin') {
      loadAccounts();
    } else if (user?.role === 'operator' || user?.role === 'readonly') {
      // Para operadores, cargar configuración inmediatamente
      loadConfig();
    }
  }, [user]);

  // Cargar configuración cuando se selecciona una organización (solo Admin)
  useEffect(() => {
    if (user?.role === 'admin' && selectedOrgId) {
      loadConfig();
      loadOrgUpdateState(selectedOrgId);
    }
  }, [selectedOrgId]);

  // Cargar versiones disponibles (para selector de versión pineada)
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
    if (user?.role === 'admin') {
      loadVersions();
    }
  }, [user?.role]);

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

  // Para operadores, cargar su propio estado de auto-update
  useEffect(() => {
    if (user?.role === 'operator' && user?.organization_id) {
      loadOrgUpdateState(user.organization_id);
    }
  }, [user]);

  const loadAccounts = async () => {
    try {
      setLoadingAccounts(true);
      const response = await apiClient.get('/organizations/?skip=0&limit=1000');

      const data = response.data;
      setAccounts(data.items || []);
      if (data.items && data.items.length > 0) {
        setSelectedOrgId(data.items[0].id);
      }
    } catch (error: any) {
      const msg =
        error?.response?.data?.detail ||
        error?.response?.data?.message ||
        error?.message ||
        'Error al cargar organizaciones';
      console.error('Error al cargar organizaciones:', msg, error?.response?.status);
      alert(msg);
    } finally {
      setLoadingAccounts(false);
    }
  };

  const loadConfig = async () => {
    try {
      setLoading(true);

      // Construir URL con account_id si es Admin
      let url = '/config/global';
      if (user?.role === 'admin') {
        if (!selectedOrgId) {
          setLoading(false);
          return;
        }
        url += `?organization_id=${selectedOrgId}`;
      }

      const response = await apiClient.get(url);
      const data: GlobalConfig = response.data;

      // Si id es null, significa que no existe configuración en BD (valores por defecto)
      if (!data.id) {
        setConfig(null);
        // Usar valores por defecto del backend
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

      // Configuración existente
      setConfig(data);

      // Cargar valores en el formulario
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

      // Cargar connectivity_checks y locale desde la respuesta
      const configData = data as GlobalConfig & {
        connectivity_checks?: ConnectivityCheck[];
        locale?: string;
      };
      setConnectivityChecks(configData.connectivity_checks || []);
      setLocale(configData.locale || '');

      setHasChanges(false);
    } catch (error: any) {
      const msg =
        error?.response?.data?.detail ||
        error?.response?.data?.message ||
        error?.message ||
        'Error al cargar configuración';
      console.error('Error al cargar configuración:', msg, error?.response?.status);
      alert(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    // Validar
    if (!corporateQueueName.trim()) {
      alert('El nombre de la cola corporativa es requerido');
      return;
    }

    if (pollingMinutes < 1 || pollingMinutes > 1440) {
      alert('El intervalo de polling debe estar entre 1 y 1440 minutos');
      return;
    }

    // Validar que Admin haya seleccionado organización
    if (user?.role === 'admin' && !selectedOrgId) {
      alert('Debes seleccionar una organización');
      return;
    }

    try {
      setSaving(true);

      // Preparar search_targets
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

      // Construir URL con account_id si es Admin
      let url = '/config/global';
      if (user?.role === 'admin') {
        url += `?organization_id=${selectedOrgId}`;
      }

      const response = await apiClient.put(url, updateData);
      const data: GlobalConfig = response.data;
      setConfig(data);
      setHasChanges(false);
      alert('Configuración guardada exitosamente');
    } catch (error: any) {
      console.error('Error:', error);
      alert(error.message || 'Error al guardar configuración');
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

    // Restaurar connectivity_checks y locale
    const configData = config as GlobalConfig & {
      connectivity_checks?: ConnectivityCheck[];
      locale?: string;
    };
    setConnectivityChecks(configData.connectivity_checks || []);
    setLocale(configData.locale || '');

    setHasChanges(false);
  };

  const addSearchIp = () => {
    setSearchIps([...searchIps, '']);
    setHasChanges(true);
  };

  // === Handlers de auto-actualización ===

  const handleAutoUpdateToggle = async (enabled: boolean) => {
    const orgId = user?.role === 'admin' ? selectedOrgId : user?.organization_id;
    if (!orgId) return;

    setTogglingAutoUpdate(true);
    try {
      await apiClient.patch(`/organizations/${orgId}/auto-update`, { enabled });
      setAutoUpdateEnabled(enabled);
    } catch {
      // Revertir en caso de error
    } finally {
      setTogglingAutoUpdate(false);
    }
  };

  const handleReregisterToggle = async (enabled: boolean) => {
    const orgId = user?.role === 'admin' ? selectedOrgId : user?.organization_id;
    if (!orgId) return;

    setTogglingAutoUpdate(true);
    try {
      await apiClient.put(`/organizations/${orgId}`, { auto_reregister_enabled: enabled });
      setAutoReregisterEnabled(enabled);
    } catch {
      // Revertir en caso de error
    } finally {
      setTogglingAutoUpdate(false);
    }
  };

  const handlePinVersion = async (version: string | null) => {
    const orgId = user?.role === 'admin' ? selectedOrgId : user?.organization_id;
    if (!orgId) return;

    setTogglingAutoUpdate(true);
    try {
      await apiClient.put(`/updates/pin/${orgId}`, { version });
      setTargetVersion(version);
    } catch {
      // Revertir en caso de error
    } finally {
      setTogglingAutoUpdate(false);
    }
  };

  const removeSearchIp = (index: number) => {
    setSearchIps(searchIps.filter((_, i) => i !== index));
    setHasChanges(true);
  };

  const updateSearchIp = (index: number, value: string) => {
    const newIps = [...searchIps];
    newIps[index] = value;
    setSearchIps(newIps);
    setHasChanges(true);
  };

  const addSearchRange = () => {
    setSearchRanges([...searchRanges, '']);
    setHasChanges(true);
  };

  const removeSearchRange = (index: number) => {
    setSearchRanges(searchRanges.filter((_, i) => i !== index));
    setHasChanges(true);
  };

  const updateSearchRange = (index: number, value: string) => {
    const newRanges = [...searchRanges];
    newRanges[index] = value;
    setSearchRanges(newRanges);
    setHasChanges(true);
  };

  if (loading || (user?.role === 'admin' && loadingAccounts)) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Cargando configuración...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900">{t('title')}</h1>
        <p className="mt-2 text-gray-600">{t('subtitle')}</p>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex space-x-8">
          <button
            onClick={() => setActiveTab('organization')}
            className={`
              py-4 px-1 border-b-2 font-medium text-sm flex items-center gap-2
              ${
                activeTab === 'organization'
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }
            `}
          >
            <Building2 className="h-5 w-5" />
            {t('tabOrg')}
          </button>

          {user?.role === 'admin' && (
            <button
              onClick={() => setActiveTab('global')}
              className={`
                py-4 px-1 border-b-2 font-medium text-sm flex items-center gap-2
                ${
                  activeTab === 'global'
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }
              `}
            >
              <Globe className="h-5 w-5" />
              {t('tabGlobal')}
            </button>
          )}
        </nav>
      </div>

      {/* Tab: Configuración por Organización */}
      {activeTab === 'organization' && (
        <div className="space-y-6">
          {/* Header de la sección */}
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-semibold text-gray-900">{t('orgTitle')}</h2>
              <p className="mt-1 text-sm text-gray-600">{t('orgDesc')}</p>
            </div>
            <div className="flex gap-2">
              {hasChanges && (
                <Button variant="outline" onClick={handleReset} disabled={saving}>
                  <RotateCcw className="mr-2 h-4 w-4" />
                  {t('discard')}
                </Button>
              )}
              <Button
                onClick={handleSave}
                disabled={
                  saving || !hasChanges || (user?.role === 'admin' && !selectedOrgId)
                }
              >
                <Save className="mr-2 h-4 w-4" />
                {saving ? t('saving') : t('save')}
              </Button>
            </div>
          </div>

          {/* Selector de Organización (solo para Admin) */}
          {user?.role === 'admin' && (
            <div className="bg-white rounded-lg shadow p-4">
              <label className="block text-sm font-medium text-gray-700 mb-2">
                {t('selectOrg')}
              </label>
              <select
                value={selectedOrgId}
                onChange={(e) => {
                  setSelectedOrgId(e.target.value);
                  setHasChanges(false);
                }}
                className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">{t('selectOrg')}</option>
                {accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.name}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-sm text-gray-500">{t('selectOrgHelper')}</p>
            </div>
          )}

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

          {/* Formulario */}
          <div className="bg-white rounded-lg shadow">
            <div className="p-6 space-y-6">
              {/* Cola Corporativa */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('corpQueue')}
                </label>
                <Input
                  type="text"
                  value={corporateQueueName}
                  onChange={(e) => {
                    setCorporateQueueName(e.target.value);
                    setHasChanges(true);
                  }}
                  placeholder={`Ej: ${queuePlaceholder}`}
                  className="max-w-md"
                  disabled={user?.role === 'admin' && !selectedOrgId}
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
                  onChange={(e) => {
                    setPollingMinutes(parseInt(e.target.value) || 1);
                    setHasChanges(true);
                  }}
                  className="max-w-xs"
                  disabled={user?.role === 'admin' && !selectedOrgId}
                />
                <p className="mt-1 text-sm text-gray-500">{t('pollingHelper')}</p>
              </div>

              {/* Dominios de Bootstrap */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('bootstrapDomains')}
                </label>
                <Input
                  type="text"
                  value={bootstrapDomains}
                  onChange={(e) => {
                    setBootstrapDomains(e.target.value);
                    setHasChanges(true);
                  }}
                  placeholder={`Ej: ${domainPlaceholder}`}
                  className="max-w-md"
                  disabled={user?.role === 'admin' && !selectedOrgId}
                />
              </div>

              {/* Objetivos de Búsqueda - IPs */}
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
                        placeholder="Ej: 192.168.1.100"
                        className="max-w-md"
                        disabled={user?.role === 'admin' && !selectedOrgId}
                      />
                      {searchIps.length > 1 && (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => removeSearchIp(index)}
                          disabled={user?.role === 'admin' && !selectedOrgId}
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={addSearchIp}
                  className="mt-2"
                  disabled={user?.role === 'admin' && !selectedOrgId}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  {t('addIp')}
                </Button>
                <p className="mt-1 text-sm text-gray-500">{t('printerIpsHelper')}</p>
              </div>

              {/* Objetivos de Búsqueda - Rangos */}
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
                        placeholder="Ej: 192.168.1.0/24"
                        className="max-w-md"
                        disabled={user?.role === 'admin' && !selectedOrgId}
                      />
                      {searchRanges.length > 1 && (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => removeSearchRange(index)}
                          disabled={user?.role === 'admin' && !selectedOrgId}
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={addSearchRange}
                  className="mt-2"
                  disabled={user?.role === 'admin' && !selectedOrgId}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  {t('addRange')}
                </Button>
                <p className="mt-1 text-sm text-gray-500">{t('printerRangesHelper')}</p>
              </div>

              {/* Checks de Conectividad */}
              <div>
                <ConnectivityCheckEditor
                  checks={connectivityChecks}
                  onChange={(checks) => {
                    setConnectivityChecks(checks);
                    setHasChanges(true);
                  }}
                />
              </div>

              {/* Selector de Locale */}
              <div>
                <LocaleSelector
                  value={locale}
                  onChange={(value) => {
                    setLocale(value);
                    setHasChanges(true);
                  }}
                />
              </div>
            </div>
          </div>

          {/* Información adicional */}
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

          {/* Advertencia si no hay configuración */}
          {!config && selectedOrgId && (
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

          {/* Sección de Actualizaciones y Re-registro por Organización */}
          {(selectedOrgId || user?.role !== 'admin') && (
            <div className="bg-white rounded-lg shadow">
              <div className="p-6 space-y-5">
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">{t('updatesTitle')}</h3>
                  <p className="text-sm text-gray-600 mt-1">{t('updatesDesc')}</p>
                </div>

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

                {/* Explicación contextual */}
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
          )}

          {/* Mensaje cuando Admin no ha seleccionado organización */}
          {user?.role === 'admin' && !selectedOrgId && !loadingAccounts && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <div className="flex">
                <Info className="h-5 w-5 text-blue-600 mr-3 flex-shrink-0 mt-0.5" />
                <div>
                  <h3 className="text-sm font-medium text-blue-900">{t('selectOrgTitle')}</h3>
                  <p className="mt-1 text-sm text-blue-700">{t('selectOrgMsg')}</p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Tab: Configuración Global del Sistema */}
      {activeTab === 'global' && user?.role === 'admin' && (
        <div className="space-y-6">
          {/* Header de la sección */}
          <div>
            <h2 className="text-xl font-semibold text-gray-900">{t('systemConfigTitle')}</h2>
            <p className="mt-1 text-sm text-gray-600">{t('systemConfigMsg')}</p>
          </div>

          {/* Alerta informativa */}
          <div className="bg-purple-50 border border-purple-200 rounded-lg p-4">
            <div className="flex">
              <Info className="h-5 w-5 text-purple-600 mr-3 flex-shrink-0 mt-0.5" />
              <div>
                <h3 className="text-sm font-medium text-purple-900">
                  {t('systemConfigTitle')}
                </h3>
                <p className="mt-1 text-sm text-purple-700">{t('systemConfigMsg')}</p>
                <div className="mt-2 text-xs text-purple-600 font-mono">
                  {t('systemHierarchy')}
                </div>
              </div>
            </div>
          </div>

          {/* Contenido del tab global */}
          <div className="bg-white rounded-lg shadow p-6">
            <div className="text-center py-12">
              <Globe className="mx-auto h-16 w-16 text-gray-400" />
              <h3 className="mt-4 text-lg font-medium text-gray-900">
                Configuración Global del Sistema
              </h3>
              <p className="mt-2 text-sm text-gray-500 max-w-md mx-auto">
                Esta sección permite configurar parámetros que se aplican a todas las
                organizaciones. Actualmente, la configuración se gestiona a nivel de
                organización.
              </p>
              <p className="mt-4 text-xs text-gray-400">{t('comingSoon')}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
