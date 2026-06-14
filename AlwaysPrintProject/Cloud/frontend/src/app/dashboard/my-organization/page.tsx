/**
 * Página de configuración de la organización del operador.
 * Permite ver y editar la configuración de su propia organización
 * sin necesidad de acceso a la gestión de organizaciones (admin).
 */

'use client'

import { useState, useEffect, useRef } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { useTranslations } from 'next-intl'
import { useUserTimezone } from '@/hooks/useUserTimezone'
import { formatDateWithTimezone, COMMON_TIMEZONES } from '@/lib/dateUtils'
import { apiClient, organizationsApi, workstationsApi } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ConnectivityCheckEditor } from '@/components/ConnectivityCheckEditor'
import { LocaleSelector } from '@/components/LocaleSelector'
import { ActionConfigSection } from '@/components/config/ActionConfigSection'
import { useToast } from '@/hooks/use-toast'
import {
  Save,
  Building2,
  Printer,
  Network,
  Wifi,
  Download,
  Cog,
  Plus,
  X,
  AlertCircle,
  Info,
  Pin,
  Globe,
  Trash2,
  Server,
  RotateCcw,
  RefreshCw,
  ShieldAlert,
} from 'lucide-react'
import { Switch } from '@/components/ui/switch'
import type { Organization } from '@/types'
import type { GlobalConfig, GlobalConfigUpdate, SearchTargets, ConnectivityCheck } from '@/types/config'

type TabKey = 'general' | 'printing' | 'network' | 'connectivity' | 'updates' | 'actions' | 'ips' | 'control'

interface TabDef {
  key: TabKey
  labelKey: string
  icon: React.ComponentType<{ className?: string }>
}

const TABS: TabDef[] = [
  { key: 'general', labelKey: 'tabGeneral', icon: Building2 },
  { key: 'printing', labelKey: 'tabPrinting', icon: Printer },
  { key: 'network', labelKey: 'tabNetwork', icon: Network },
  { key: 'connectivity', labelKey: 'tabConnectivity', icon: Wifi },
  { key: 'updates', labelKey: 'tabUpdates', icon: Download },
  { key: 'actions', labelKey: 'tabActions', icon: Cog },
  { key: 'ips', labelKey: 'tabIps', icon: Globe },
  { key: 'control', labelKey: 'tabControl', icon: Server },
]

export default function MyOrganizationPage() {
  const { user } = useAuth()
  const t = useTranslations('orgEdit')
  const tCommon = useTranslations('common')
  const tConfig = useTranslations('config')
  const tAccounts = useTranslations('accounts')
  const userTimezone = useUserTimezone()
  const { toast } = useToast()

  const [activeTab, setActiveTab] = useState<TabKey>('general')
  const [loading, setLoading] = useState(true)
  const [org, setOrg] = useState<Organization | null>(null)

  // === GENERAL TAB STATE ===
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [timezone, setTimezone] = useState('UTC')
  const [language, setLanguage] = useState('en')
  const [llmModelId, setLlmModelId] = useState<string | null>(null)
  const [openaiApiKey, setOpenaiApiKey] = useState<string | null>(null)
  const [generalDirty, setGeneralDirty] = useState(false)
  const [savingGeneral, setSavingGeneral] = useState(false)

  // === JITTER WINDOW STATE ===
  const [jitterWindowSeconds, setJitterWindowSeconds] = useState(30)
  const [jitterWindowPrevious, setJitterWindowPrevious] = useState(30)
  const [jitterWindowError, setJitterWindowError] = useState('')
  const [savingJitter, setSavingJitter] = useState(false)
  const [activeWorkstationCount, setActiveWorkstationCount] = useState<number>(0)
  const [debouncedJitterWindow, setDebouncedJitterWindow] = useState(30)
  const jitterDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // === CONFIG TAB STATE ===
  const [corporateQueueName, setCorporateQueueName] = useState('')
  const [pollingMinutes, setPollingMinutes] = useState(5)
  const [bootstrapDomains, setBootstrapDomains] = useState('')
  const [searchIps, setSearchIps] = useState<string[]>([''])
  const [searchRanges, setSearchRanges] = useState<string[]>([''])
  const [connectivityChecks, setConnectivityChecks] = useState<ConnectivityCheck[]>([])
  const [locale, setLocale] = useState('')
  const [configDirty, setConfigDirty] = useState(false)
  const [savingConfig, setSavingConfig] = useState(false)
  const [configExists, setConfigExists] = useState(false)

  // === UPDATES TAB STATE ===
  const [autoUpdateEnabled, setAutoUpdateEnabled] = useState(false)
  const [targetVersion, setTargetVersion] = useState<string | null>(null)
  const [autoReregisterEnabled, setAutoReregisterEnabled] = useState(false)
  const [togglingUpdate, setTogglingUpdate] = useState(false)
  const [availableVersions, setAvailableVersions] = useState<Array<{ version: string }>>([])

  // === IPS TAB STATE ===
  const [newIp, setNewIp] = useState('')
  const [newIpDesc, setNewIpDesc] = useState('')
  const [savingIp, setSavingIp] = useState(false)

  // === CONTROL TAB STATE ===
  const [forcedContingency, setForcedContingency] = useState(false)
  const [togglingContingency, setTogglingContingency] = useState(false)
  const [sendingOrgCommand, setSendingOrgCommand] = useState(false)
  const [confirmOrgAction, setConfirmOrgAction] = useState<'restart_service' | 'restart_tray' | 'check_update' | null>(null)
  const [confirmContingency, setConfirmContingency] = useState<boolean | null>(null)
  const [deactivateForceAll, setDeactivateForceAll] = useState(false)
  const [vlansWithoutDevices, setVlansWithoutDevices] = useState<{ id: string; name: string }[] | null>(null)
  const [loadingVlansCheck, setLoadingVlansCheck] = useState(false)
  const [showVlansWithoutDevicesList, setShowVlansWithoutDevicesList] = useState(false)

  // === CARGAR ORGANIZACIÓN ===
  useEffect(() => {
    if (!user?.organization_id) return
    const loadOrg = async () => {
      try {
        const res = await apiClient.get('/organizations/me')
        const data = res.data as Organization
        setOrg(data)
        setName(data.name)
        setDescription(data.description || '')
        setTimezone(data.timezone)
        setLanguage(data.language)
        setLlmModelId(data.llm_model_id || null)
        setOpenaiApiKey(data.openai_api_key || null)
        setAutoUpdateEnabled(data.auto_update_enabled)
        setTargetVersion(data.target_version || null)
        setAutoReregisterEnabled(data.auto_reregister_enabled)
        setForcedContingency(data.forced_contingency ?? false)
        setJitterWindowSeconds(data.jitter_window_seconds ?? 30)
        setJitterWindowPrevious(data.jitter_window_seconds ?? 30)
      } catch (e) {
        console.error('Error cargando organización:', e)
      } finally {
        setLoading(false)
      }
    }
    loadOrg()
  }, [user?.organization_id])

  // === CARGAR CONFIG ===
  useEffect(() => {
    if (!user?.organization_id) return
    const loadConfig = async () => {
      try {
        const res = await apiClient.get('/config/global')
        const data = res.data as GlobalConfig & { connectivity_checks?: ConnectivityCheck[]; locale?: string }
        if (data.id) {
          setConfigExists(true)
          setCorporateQueueName(data.corporate_queue_name || '')
          setPollingMinutes(data.pending_task_polling_minutes || 5)
          setBootstrapDomains(data.bootstrap_domains || '')
          setSearchIps(data.search_targets?.ips || [''])
          setSearchRanges(data.search_targets?.ranges || [''])
          setConnectivityChecks(data.connectivity_checks || [])
          setLocale(data.locale || '')
        }
      } catch { /* sin config */ }
    }
    loadConfig()
  }, [user?.organization_id])

  // === CARGAR VERSIONES ===
  useEffect(() => {
    const loadVersions = async () => {
      try {
        const res = await apiClient.get('/updates/versions')
        setAvailableVersions((res.data || []).map((v: { version: string }) => ({ version: v.version })))
      } catch { setAvailableVersions([]) }
    }
    loadVersions()
  }, [])

  // === CARGAR WORKSTATIONS ACTIVAS (para cálculo de jitter) ===
  useEffect(() => {
    if (!user?.organization_id) return
    const loadActiveCount = async () => {
      try {
        const stats = await workstationsApi.stats()
        setActiveWorkstationCount(stats.online)
      } catch {
        // Si falla, dejar N=0 (se mostrará mensaje sin tasa)
        setActiveWorkstationCount(0)
      }
    }
    loadActiveCount()
  }, [user?.organization_id])

  // === DEBOUNCE PARA CÁLCULO DE TASA DE CONEXIONES (300ms) ===
  useEffect(() => {
    if (jitterDebounceRef.current) {
      clearTimeout(jitterDebounceRef.current)
    }
    jitterDebounceRef.current = setTimeout(() => {
      setDebouncedJitterWindow(jitterWindowSeconds)
    }, 300)
    return () => {
      if (jitterDebounceRef.current) {
        clearTimeout(jitterDebounceRef.current)
      }
    }
  }, [jitterWindowSeconds])

  // === HANDLERS: GENERAL ===
  const handleSaveGeneral = async () => {
    setSavingGeneral(true)
    try {
      const data = { name, description, timezone, language, llm_model_id: llmModelId, openai_api_key: openaiApiKey }
      const res = await apiClient.put('/organizations/me', data)
      setOrg(res.data)
      setGeneralDirty(false)
      toast({ title: tCommon('saved'), description: tConfig('saveSuccess') })
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      toast({ title: tCommon('error'), description: err.response?.data?.detail || err.message || 'Error', variant: 'destructive' })
    } finally { setSavingGeneral(false) }
  }

  // === HANDLERS: JITTER WINDOW ===
  const handleJitterWindowChange = (value: string) => {
    const numValue = parseInt(value, 10)
    setJitterWindowSeconds(numValue || 0)
    // Validación client-side
    if (isNaN(numValue) || numValue < 5 || numValue > 300) {
      setJitterWindowError(t('jitterWindowValidation'))
    } else {
      setJitterWindowError('')
    }
  }

  const handleSaveJitter = async () => {
    // Validar antes de enviar
    if (jitterWindowSeconds < 5 || jitterWindowSeconds > 300) {
      setJitterWindowError(t('jitterWindowValidation'))
      return
    }
    setSavingJitter(true)
    try {
      const res = await apiClient.put('/organizations/me', { jitter_window_seconds: jitterWindowSeconds })
      setOrg(res.data)
      setJitterWindowPrevious(jitterWindowSeconds)
      toast({ title: t('jitterWindowSaveSuccess') })
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      toast({ title: t('jitterWindowSaveError'), description: err.response?.data?.detail || err.message || 'Error', variant: 'destructive' })
      // Restaurar valor anterior
      setJitterWindowSeconds(jitterWindowPrevious)
      setJitterWindowError('')
    } finally {
      setSavingJitter(false)
    }
  }

  // === HANDLERS: CONFIG ===
  const handleSaveConfig = async () => {
    if (!corporateQueueName.trim()) { alert(tConfig('validationQueueRequired')); return }
    if (pollingMinutes < 1 || pollingMinutes > 1440) { alert(tConfig('validationPollingRange')); return }
    setSavingConfig(true)
    try {
      const validIps = searchIps.filter(ip => ip.trim())
      const validRanges = searchRanges.filter(r => r.trim())
      const searchTargets: SearchTargets | null = (validIps.length > 0 || validRanges.length > 0)
        ? { ...(validIps.length > 0 && { ips: validIps }), ...(validRanges.length > 0 && { ranges: validRanges }) }
        : null
      const updateData: GlobalConfigUpdate = {
        corporate_queue_name: corporateQueueName.trim(),
        pending_task_polling_minutes: pollingMinutes,
        bootstrap_domains: bootstrapDomains.trim(),
        search_targets: searchTargets,
        connectivity_checks: connectivityChecks,
        locale,
      }
      await apiClient.put('/config/global', updateData)
      setConfigDirty(false)
      setConfigExists(true)
      toast({ title: tCommon('saved'), description: tConfig('saveSuccess') })
    } catch (e: unknown) {
      const err = e as { message?: string }
      toast({ title: tCommon('error'), description: err.message || tConfig('saveError'), variant: 'destructive' })
    } finally { setSavingConfig(false) }
  }

  // === HANDLERS: UPDATES ===
  const handleAutoUpdateToggle = async (enabled: boolean) => {
    setTogglingUpdate(true)
    try {
      await apiClient.patch('/organizations/me/auto-update', { enabled })
      setAutoUpdateEnabled(enabled)
    } catch { /* silently */ }
    finally { setTogglingUpdate(false) }
  }

  const handleReregisterToggle = async (enabled: boolean) => {
    setTogglingUpdate(true)
    try {
      await apiClient.put('/organizations/me', { auto_reregister_enabled: enabled })
      setAutoReregisterEnabled(enabled)
    } catch { /* silently */ }
    finally { setTogglingUpdate(false) }
  }

  const handlePinVersion = async (version: string | null) => {
    setTogglingUpdate(true)
    try {
      await apiClient.put('/organizations/me/pin-version', { version })
      setTargetVersion(version)
    } catch { /* silently */ }
    finally { setTogglingUpdate(false) }
  }

  // === HANDLERS: IPS ===
  const handleAddIp = async (e: React.FormEvent) => {
    e.preventDefault()
    const ipRegex = /^(\d{1,3}\.){3}\d{1,3}$/
    if (!ipRegex.test(newIp)) { alert('IP inválida'); return }
    setSavingIp(true)
    try {
      await apiClient.post('/organizations/me/public-ips', { ip_address: newIp, description: newIpDesc || undefined })
      setNewIp('')
      setNewIpDesc('')
      // Recargar org para actualizar IPs
      const res = await apiClient.get('/organizations/me')
      setOrg(res.data)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      alert(err.response?.data?.detail || 'Error')
    } finally { setSavingIp(false) }
  }

  const handleRemoveIp = async (ipId: string) => {
    setSavingIp(true)
    try {
      await apiClient.delete(`/organizations/me/public-ips/${ipId}`)
      const res = await apiClient.get('/organizations/me')
      setOrg(res.data)
    } catch { /* silently */ }
    finally { setSavingIp(false) }
  }

  // === HANDLERS: CONTROL ===
  const handleRequestToggleContingency = (enabled: boolean) => {
    setDeactivateForceAll(false)
    setShowVlansWithoutDevicesList(false)
    setVlansWithoutDevices(null)
    setConfirmContingency(enabled)
    // Al activar, verificar VLANs sin dispositivos
    if (enabled && user?.organization_id) {
      setLoadingVlansCheck(true)
      organizationsApi.getVlansWithoutDevices(user.organization_id)
        .then(data => setVlansWithoutDevices(data.vlans))
        .catch(() => setVlansWithoutDevices([]))
        .finally(() => setLoadingVlansCheck(false))
    }
  }

  const handleConfirmContingency = async () => {
    if (confirmContingency === null || !user?.organization_id) return
    const enabled = confirmContingency
    setConfirmContingency(null)
    setTogglingContingency(true)
    try {
      await organizationsApi.toggleForcedContingency(user.organization_id, enabled, !enabled ? deactivateForceAll : false)
      setForcedContingency(enabled)
      setDeactivateForceAll(false)
      toast({ title: enabled ? t('controlContingencyActivated') : t('controlContingencyDeactivated') })
    } catch (e: unknown) {
      const err = e as { detail?: string }
      toast({ title: tCommon('error'), description: err.detail || tCommon('error'), variant: 'destructive' })
    } finally {
      setTogglingContingency(false)
    }
  }

  const handleOrgCommand = async (commandType: 'restart_service' | 'restart_tray' | 'check_update') => {
    if (!user?.organization_id) return
    setSendingOrgCommand(true)
    setConfirmOrgAction(null)
    try {
      const res = await organizationsApi.sendCommand(user.organization_id, commandType)
      toast({ title: t('controlCommandSent', { count: res.dispatched }) })
    } catch (e: unknown) {
      const err = e as { detail?: string }
      toast({ title: tCommon('error'), description: err.detail || tCommon('error'), variant: 'destructive' })
    } finally {
      setSendingOrgCommand(false)
    }
  }

  // === SEARCH TARGETS HELPERS ===
  const addSearchIp = () => { setSearchIps([...searchIps, '']); setConfigDirty(true) }
  const removeSearchIp = (i: number) => { setSearchIps(searchIps.filter((_, idx) => idx !== i)); setConfigDirty(true) }
  const updateSearchIp = (i: number, v: string) => { const n = [...searchIps]; n[i] = v; setSearchIps(n); setConfigDirty(true) }
  const addSearchRange = () => { setSearchRanges([...searchRanges, '']); setConfigDirty(true) }
  const removeSearchRange = (i: number) => { setSearchRanges(searchRanges.filter((_, idx) => idx !== i)); setConfigDirty(true) }
  const updateSearchRange = (i: number, v: string) => { const n = [...searchRanges]; n[i] = v; setSearchRanges(n); setConfigDirty(true) }

  // === LOADING ===
  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">{tCommon('loading')}</p>
        </div>
      </div>
    )
  }

  if (!org) {
    return (
      <div className="text-center py-12">
        <AlertCircle className="mx-auto h-12 w-12 text-gray-400" />
        <p className="mt-4 text-gray-600">{tAccounts('noOrg')}</p>
      </div>
    )
  }

  return (
    <>
    <div className="space-y-6">
      {/* Header + Tabs + Content */}
      <div className="bg-white rounded-lg shadow">
        {/* Header */}
        <div className="p-6 pb-0">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-lg bg-blue-100 flex items-center justify-center">
              <Building2 className="h-6 w-6 text-blue-600" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900">{org.name}</h1>
              <p className="text-sm text-gray-500">{t('subtitle')}</p>
            </div>
          </div>
        </div>

        {/* Tabs */}
        <div className="border-b border-gray-200 px-6 mt-6">
          <nav className="flex gap-1 overflow-x-auto -mb-px" aria-label="Tabs">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`flex items-center gap-2 px-4 py-3 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
                  activeTab === tab.key
                    ? 'border-blue-600 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                <tab.icon className="h-4 w-4" />
                {t(tab.labelKey as any)}
              </button>
            ))}
          </nav>
        </div>

        {/* Tab Content */}
        <div className="p-6">
          {/* === TAB: GENERAL === */}
          {activeTab === 'general' && (
            <div className="space-y-5">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>{tAccounts('nameLabel')}</Label>
                  <Input value={name} onChange={(e) => { setName(e.target.value); setGeneralDirty(true) }} />
                </div>
                <div className="space-y-2">
                  <Label>{tAccounts('descriptionLabel')}</Label>
                  <Input value={description} onChange={(e) => { setDescription(e.target.value); setGeneralDirty(true) }} />
                </div>
              </div>

              <div className="space-y-2">
                <Label>{tAccounts('timezoneLabel')}</Label>
                <select value={timezone} onChange={(e) => { setTimezone(e.target.value); setGeneralDirty(true) }} className="w-full px-3 py-2 border rounded-md">
                  {COMMON_TIMEZONES.map((tz) => (<option key={tz.value} value={tz.value}>{tz.label}</option>))}
                </select>
                <p className="text-xs text-gray-500">{tAccounts('timezoneHelper')}</p>
              </div>

              <div className="space-y-2">
                <Label>{tAccounts('languageLabel')}</Label>
                <select value={language} onChange={(e) => { setLanguage(e.target.value); setGeneralDirty(true) }} className="w-full px-3 py-2 border rounded-md">
                  <option value="en">English</option>
                  <option value="es">Español</option>
                </select>
                <p className="text-xs text-gray-500">{tAccounts('languageHelper')}</p>
              </div>

              {/* OpenAI Key */}
              <div className="space-y-2">
                <Label>{tAccounts('openaiKeyLabel')}</Label>
                <Input type="password" placeholder={tAccounts('openaiKeyPlaceholder')} value={openaiApiKey || ''} onChange={(e) => { setOpenaiApiKey(e.target.value || null); setGeneralDirty(true) }} />
                <p className="text-xs text-gray-500">{tAccounts('openaiKeyHelper')}</p>
              </div>

              {/* Jitter Window */}
              <div className="space-y-2">
                <Label>{t('jitterWindowLabel')}</Label>
                <div className="flex items-center gap-3">
                  <Input
                    type="number"
                    min={5}
                    max={300}
                    step={1}
                    value={jitterWindowSeconds}
                    onChange={(e) => handleJitterWindowChange(e.target.value)}
                    className="max-w-xs"
                  />
                  <Button
                    onClick={handleSaveJitter}
                    disabled={savingJitter || !!jitterWindowError || jitterWindowSeconds === jitterWindowPrevious}
                    size="sm"
                  >
                    <Save className="mr-2 h-4 w-4" />
                    {savingJitter ? tCommon('saving') : tCommon('save')}
                  </Button>
                </div>
                {jitterWindowError && (
                  <p className="text-xs text-red-600">{jitterWindowError}</p>
                )}
                <p className="text-xs text-gray-500">{t('jitterWindowHelper')}</p>
                {/* Cálculo dinámico de tasa de conexiones */}
                {activeWorkstationCount > 0 && debouncedJitterWindow >= 5 && debouncedJitterWindow <= 300 ? (
                  <p className="text-xs text-blue-600">
                    {t('jitterWindowCalculation', {
                      window: debouncedJitterWindow,
                      count: activeWorkstationCount,
                      rate: (activeWorkstationCount / debouncedJitterWindow).toFixed(1),
                    })}
                  </p>
                ) : (
                  <p className="text-xs text-amber-600">
                    {t('jitterWindowNoWorkstations')}
                  </p>
                )}
              </div>

              {/* Save button */}
              <div className="flex justify-end gap-2 pt-4 border-t">
                <Button onClick={handleSaveGeneral} disabled={!generalDirty || savingGeneral}>
                  <Save className="mr-2 h-4 w-4" />
                  {savingGeneral ? tCommon('saving') : tCommon('save')}
                </Button>
              </div>
            </div>
          )}

          {/* === TAB: PRINTING === */}
          {activeTab === 'printing' && (
            <div className="space-y-5">
              <Alert>
                <Info className="h-4 w-4" />
                <AlertDescription className="text-xs">{tConfig('hierarchyMsg')}</AlertDescription>
              </Alert>
              <div>
                <Label>{tConfig('corpQueue')}</Label>
                <Input value={corporateQueueName} onChange={(e) => { setCorporateQueueName(e.target.value); setConfigDirty(true) }} placeholder={tConfig('corpQueuePlaceholder')} className="max-w-md mt-2" />
                <p className="mt-1 text-sm text-gray-500">{tConfig('corpQueueHelper')}</p>
              </div>
              <div>
                <Label>{tConfig('pollingInterval')}</Label>
                <Input type="number" min="1" max="1440" value={pollingMinutes} onChange={(e) => { setPollingMinutes(parseInt(e.target.value) || 1); setConfigDirty(true) }} className="max-w-xs mt-2" />
                <p className="mt-1 text-sm text-gray-500">{tConfig('pollingHelper')}</p>
              </div>
              <LocaleSelector value={locale} onChange={(v) => { setLocale(v); setConfigDirty(true) }} />
              <div className="flex justify-end gap-2 pt-4 border-t">
                <Button onClick={handleSaveConfig} disabled={!configDirty || savingConfig}>
                  <Save className="mr-2 h-4 w-4" />
                  {savingConfig ? tCommon('saving') : tCommon('save')}
                </Button>
              </div>
            </div>
          )}

          {/* === TAB: NETWORK === */}
          {activeTab === 'network' && (
            <div className="space-y-5">
              <div>
                <Label>{tConfig('bootstrapDomains')}</Label>
                <Input value={bootstrapDomains} onChange={(e) => { setBootstrapDomains(e.target.value); setConfigDirty(true) }} placeholder={tConfig('bootstrapPlaceholder')} className="max-w-md mt-2" />
                <p className="mt-1 text-sm text-gray-500">{tConfig('bootstrapHelper')}</p>
              </div>
              <div>
                <Label>{tConfig('printerIps')}</Label>
                <div className="space-y-2 mt-2">
                  {searchIps.map((ip, i) => (
                    <div key={i} className="flex gap-2">
                      <Input value={ip} onChange={(e) => updateSearchIp(i, e.target.value)} placeholder="192.168.1.100" className="max-w-md" />
                      {searchIps.length > 1 && <Button variant="outline" size="sm" onClick={() => removeSearchIp(i)}><X className="h-4 w-4" /></Button>}
                    </div>
                  ))}
                </div>
                <Button variant="outline" size="sm" onClick={addSearchIp} className="mt-2"><Plus className="mr-2 h-4 w-4" />{tConfig('addIp')}</Button>
                <p className="mt-1 text-sm text-gray-500">{tConfig('printerIpsHelper')}</p>
              </div>
              <div>
                <Label>{tConfig('printerRanges')}</Label>
                <div className="space-y-2 mt-2">
                  {searchRanges.map((range, i) => (
                    <div key={i} className="flex gap-2">
                      <Input value={range} onChange={(e) => updateSearchRange(i, e.target.value)} placeholder="192.168.1.0/24" className="max-w-md" />
                      {searchRanges.length > 1 && <Button variant="outline" size="sm" onClick={() => removeSearchRange(i)}><X className="h-4 w-4" /></Button>}
                    </div>
                  ))}
                </div>
                <Button variant="outline" size="sm" onClick={addSearchRange} className="mt-2"><Plus className="mr-2 h-4 w-4" />{tConfig('addRange')}</Button>
                <p className="mt-1 text-sm text-gray-500">{tConfig('printerRangesHelper')}</p>
              </div>
              <div className="flex justify-end gap-2 pt-4 border-t">
                <Button onClick={handleSaveConfig} disabled={!configDirty || savingConfig}>
                  <Save className="mr-2 h-4 w-4" />
                  {savingConfig ? tCommon('saving') : tCommon('save')}
                </Button>
              </div>
            </div>
          )}

          {/* === TAB: CONNECTIVITY === */}
          {activeTab === 'connectivity' && (
            <div className="space-y-5">
              <ConnectivityCheckEditor checks={connectivityChecks} onChange={(checks) => { setConnectivityChecks(checks); setConfigDirty(true) }} />
              <div className="flex justify-end gap-2 pt-4 border-t">
                <Button onClick={handleSaveConfig} disabled={!configDirty || savingConfig}>
                  <Save className="mr-2 h-4 w-4" />
                  {savingConfig ? tCommon('saving') : tCommon('save')}
                </Button>
              </div>
            </div>
          )}

          {/* === TAB: UPDATES === */}
          {activeTab === 'updates' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between p-4 border rounded-lg">
                <div>
                  <Label className="text-sm font-medium">{tConfig('autoUpdateLabel')}</Label>
                  <p className="text-xs text-gray-500 mt-1">{autoUpdateEnabled ? tConfig('autoUpdateEnabledDesc') : tConfig('autoUpdateDisabledDesc')}</p>
                </div>
                <Switch checked={autoUpdateEnabled} onCheckedChange={handleAutoUpdateToggle} disabled={togglingUpdate} />
              </div>

              <div className="flex items-center gap-3 p-4 border rounded-lg">
                <Pin className="h-4 w-4 text-gray-500 flex-shrink-0" />
                <div className="flex items-center gap-2 flex-1">
                  <span className="text-sm text-gray-700">{tConfig('pinnedVersionLabel')}</span>
                  <select className="text-sm border rounded px-2 py-1 bg-white" value={targetVersion ?? ''} onChange={(e) => handlePinVersion(e.target.value || null)} disabled={togglingUpdate}>
                    <option value="">{tConfig('pinnedVersionLatest')}</option>
                    {availableVersions.map((v) => (<option key={v.version} value={v.version}>{v.version}</option>))}
                  </select>
                </div>
              </div>

              {autoUpdateEnabled && targetVersion && <p className="text-xs text-amber-600 px-4">{tConfig('pinnedVersionNote', { version: targetVersion })}</p>}
              {autoUpdateEnabled && !targetVersion && <p className="text-xs text-gray-500 px-4">{tConfig('latestVersionNote')}</p>}

              <div className="flex items-center justify-between p-4 border rounded-lg">
                <div>
                  <Label className="text-sm font-medium">{tConfig('autoReregisterLabel')}</Label>
                  <p className="text-xs text-gray-500 mt-1">{autoReregisterEnabled ? tConfig('autoReregisterEnabledDesc') : tConfig('autoReregisterDisabledDesc')}</p>
                </div>
                <Switch checked={autoReregisterEnabled} onCheckedChange={handleReregisterToggle} disabled={togglingUpdate} />
              </div>
            </div>
          )}

          {/* === TAB: ACTIONS === */}
          {activeTab === 'actions' && (
            <ActionConfigSection organizationId={user?.organization_id || ''} hideHeader />
          )}

          {/* === TAB: IPS === */}
          {activeTab === 'ips' && (
            <div className="space-y-6">
              {/* Formulario agregar IP */}
              <div className="border-b pb-4">
                <h3 className="text-sm font-medium text-gray-900 mb-3">{tAccounts('addIpTitle')}</h3>
                <form onSubmit={handleAddIp} className="space-y-3">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div className="space-y-2">
                      <Label>{tAccounts('ipLabel')}</Label>
                      <Input placeholder={tAccounts('ipPlaceholder')} value={newIp} onChange={(e) => setNewIp(e.target.value)} required disabled={savingIp} />
                    </div>
                    <div className="space-y-2">
                      <Label>{tAccounts('ipDescLabel')}</Label>
                      <Input placeholder={tAccounts('ipDescPlaceholder')} value={newIpDesc} onChange={(e) => setNewIpDesc(e.target.value)} disabled={savingIp} />
                    </div>
                  </div>
                  <div className="flex justify-end">
                    <Button type="submit" size="sm" disabled={savingIp}><Plus className="w-4 h-4 mr-2" />{tAccounts('addIpBtn')}</Button>
                  </div>
                </form>
              </div>

              {/* Lista de IPs */}
              <div>
                <h3 className="text-sm font-medium text-gray-900 mb-3">{tAccounts('registeredIps', { count: org.public_ips?.length || 0 })}</h3>
                {org.public_ips && org.public_ips.length > 0 ? (
                  <div className="space-y-2">
                    {org.public_ips.map((ip) => (
                      <div key={ip.id} className="flex items-center justify-between p-3 border rounded-lg hover:shadow-sm transition">
                        <div className="flex items-center flex-1">
                          <Globe className="w-5 h-5 text-blue-600 mr-3" />
                          <div>
                            <p className="font-mono text-sm font-medium text-gray-900">{ip.ip_address}</p>
                            {ip.description && <p className="text-xs text-gray-500">{ip.description}</p>}
                          </div>
                        </div>
                        <Button variant="outline" size="sm" onClick={() => handleRemoveIp(ip.id)} disabled={savingIp}>
                          <Trash2 className="w-4 h-4 text-red-600" />
                        </Button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-center py-8 bg-gray-50 rounded-lg border-2 border-dashed">
                    <Globe className="w-12 h-12 text-gray-300 mx-auto mb-3" />
                    <p className="text-sm text-gray-600">{tAccounts('noIps')}</p>
                    <p className="text-xs text-gray-500 mt-1">{tAccounts('noIpsSuggestion')}</p>
                  </div>
                )}
              </div>

              <Alert>
                <AlertCircle className="h-4 w-4" />
                <AlertDescription className="text-xs">{tAccounts('autoAssignNote')}</AlertDescription>
              </Alert>
            </div>
          )}

          {/* === TAB: CONTROL === */}
          {activeTab === 'control' && (
            <div className="space-y-5">
              <p className="text-sm text-gray-500">{t('controlDesc')}</p>

              {/* Contingencia Forzada */}
              <div className="flex items-center justify-between p-4 border rounded-lg">
                <div className="flex items-center gap-3">
                  <ShieldAlert className={`w-5 h-5 ${forcedContingency ? 'text-orange-600' : 'text-gray-400'}`} />
                  <div>
                    <Label className="text-sm font-medium">{t('controlContingencyLabel')}</Label>
                    <p className="text-xs text-gray-500 mt-1">
                      {forcedContingency ? t('controlContingencyEnabledDesc') : t('controlContingencyDisabledDesc')}
                    </p>
                  </div>
                </div>
                <Button
                  variant={forcedContingency ? 'destructive' : 'outline'}
                  size="sm"
                  disabled={togglingContingency}
                  onClick={() => handleRequestToggleContingency(!forcedContingency)}
                  className={forcedContingency ? '' : 'border-orange-300 text-orange-700 hover:bg-orange-50'}
                >
                  <ShieldAlert className="h-4 w-4 mr-2" />
                  {forcedContingency ? t('controlContingencyDeactivateBtn') : t('controlContingencyActivateBtn')}
                </Button>
              </div>

              {/* Comandos masivos */}
              <div className="border rounded-lg p-4 space-y-3">
                <div>
                  <p className="text-sm font-medium text-gray-900">{t('controlCommandsTitle')}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{t('controlCommandsDesc')}</p>
                </div>
                <div className="flex flex-wrap gap-3 pt-1">
                  <Button
                    variant="outline"
                    disabled={sendingOrgCommand}
                    onClick={() => setConfirmOrgAction('restart_service')}
                  >
                    <RotateCcw className="h-4 w-4 mr-2" />
                    {t('controlRestartService')}
                  </Button>
                  <Button
                    variant="outline"
                    disabled={sendingOrgCommand}
                    onClick={() => setConfirmOrgAction('restart_tray')}
                  >
                    <RefreshCw className="h-4 w-4 mr-2" />
                    {t('controlRestartTray')}
                  </Button>
                  <Button
                    variant="outline"
                    disabled={sendingOrgCommand}
                    onClick={() => setConfirmOrgAction('check_update')}
                  >
                    <Download className="h-4 w-4 mr-2" />
                    {t('controlCheckUpdate')}
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

    </div>

      {/* === MODAL CONFIRMACIÓN CONTINGENCIA === */}
      {confirmContingency !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg shadow-lg p-6 max-w-lg w-full mx-4 space-y-4">
            <div className="flex items-center gap-2">
              <ShieldAlert className={`w-5 h-5 ${confirmContingency ? 'text-orange-600' : 'text-green-600'}`} />
              <h3 className="text-base font-semibold text-gray-900">
                {confirmContingency ? t('controlContingencyConfirmActivateTitle') : t('controlContingencyConfirmDeactivateTitle')}
              </h3>
            </div>
            <p className="text-sm text-gray-600">
              {confirmContingency ? t('controlContingencyConfirmActivateDesc') : t('controlContingencyConfirmDeactivateDesc')}
            </p>
            {/* Alerta al activar */}
            {confirmContingency && (
              <Alert>
                <ShieldAlert className="h-4 w-4" />
                <AlertDescription className="text-xs">
                  {t('controlContingencyWarning')}
                </AlertDescription>
              </Alert>
            )}
            {/* Toggle desactivación — solo al desactivar */}
            {!confirmContingency && (
              <div className="flex items-start justify-between gap-3 p-3 bg-gray-50 border border-gray-200 rounded-lg">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-800">{t('controlDeactivateForceAllLabel')}</p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {deactivateForceAll ? t('controlDeactivateForceAllHint') : t('controlDeactivateSmartHint')}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setDeactivateForceAll(!deactivateForceAll)}
                  className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none ${deactivateForceAll ? 'bg-orange-500' : 'bg-gray-300'}`}
                  role="switch"
                  aria-checked={deactivateForceAll}
                >
                  <span className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform ${deactivateForceAll ? 'translate-x-4' : 'translate-x-0'}`} />
                </button>
              </div>
            )}
            {/* Cargando VLANs sin dispositivos al activar */}
            {confirmContingency && loadingVlansCheck && (
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <RefreshCw className="w-3 h-3 animate-spin" />
                {t('controlCheckingVlans')}
              </div>
            )}
            {/* Warning VLANs sin dispositivos */}
            {confirmContingency && !loadingVlansCheck && vlansWithoutDevices && vlansWithoutDevices.length > 0 && (
              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
                <div className="flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 text-amber-600 mt-0.5 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-amber-800 font-medium">
                      {t('controlVlansWithoutDevicesWarning', { count: vlansWithoutDevices.length })}
                    </p>
                    <button
                      type="button"
                      onClick={() => setShowVlansWithoutDevicesList(!showVlansWithoutDevicesList)}
                      className="text-xs text-amber-700 underline mt-1"
                    >
                      {showVlansWithoutDevicesList ? t('controlVlansHideList') : t('controlVlansSeeMore')}
                    </button>
                    {showVlansWithoutDevicesList && (
                      <ul className="mt-2 space-y-1 max-h-32 overflow-y-auto">
                        {vlansWithoutDevices.map(v => (
                          <li key={v.id} className="text-xs text-amber-700 flex items-center gap-1.5">
                            <Network className="w-3 h-3 shrink-0" />
                            {v.name}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              </div>
            )}
            <div className="flex justify-end gap-3">
              <Button variant="outline" size="sm" onClick={() => setConfirmContingency(null)}>
                {tCommon('cancel')}
              </Button>
              <Button
                size="sm"
                variant={confirmContingency ? 'destructive' : 'default'}
                disabled={togglingContingency}
                onClick={handleConfirmContingency}
                className={confirmContingency ? 'bg-orange-600 hover:bg-orange-700' : ''}
              >
                {togglingContingency
                  ? tCommon('updating')
                  : confirmContingency
                    ? t('controlContingencyActivateBtn')
                    : t('controlContingencyDeactivateBtn')
                }
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* === MODAL CONFIRMACIÓN COMANDO ORG === */}
      {confirmOrgAction && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-lg shadow-lg p-6 max-w-sm w-full mx-4">
            <h3 className="text-base font-semibold text-gray-900 mb-2">{t('controlConfirmTitle')}</h3>
            <p className="text-sm text-gray-600 mb-6">
              {confirmOrgAction === 'restart_service'
                ? t('controlConfirmService')
                : confirmOrgAction === 'restart_tray'
                ? t('controlConfirmTray')
                : t('controlConfirmCheckUpdate')}
            </p>
            <div className="flex justify-end gap-3">
              <Button variant="outline" size="sm" onClick={() => setConfirmOrgAction(null)}>
                {t('controlCancel')}
              </Button>
              <Button
                size="sm"
                disabled={sendingOrgCommand}
                onClick={() => handleOrgCommand(confirmOrgAction)}
              >
                {t('controlConfirm')}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
