/**
 * Página dedicada de edición de organización con tabs.
 * Consolida toda la configuración por organización en un solo lugar.
 */

'use client'

import { useState, useEffect, useRef } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { apiClient, organizationsApi, logAnalysisApi } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useTranslations } from 'next-intl'
import { useUserTimezone } from '@/hooks/useUserTimezone'
import { formatDateWithTimezone, COMMON_TIMEZONES } from '@/lib/dateUtils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ConnectivityCheckEditor } from '@/components/ConnectivityCheckEditor'
import { LocaleSelector } from '@/components/LocaleSelector'
import { ActionConfigSection } from '@/components/config/ActionConfigSection'
import {
  ArrowLeft, Save, RotateCcw, Building2, Printer, Network, Wifi,
  Download, Cog, Globe, Plus, X, Trash2, Info, AlertCircle, Pin,
} from 'lucide-react'
import type { Organization, OrganizationUpdate, PublicIPCreate } from '@/types'
import type { GlobalConfig, GlobalConfigUpdate, SearchTargets, ConnectivityCheck } from '@/types/config'

type TabKey = 'general' | 'printing' | 'network' | 'connectivity' | 'updates' | 'actions' | 'ips'

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
]

export default function EditOrganizationPage() {
  const params = useParams()
  const router = useRouter()
  const orgId = params.id as string
  const { isAdmin } = useAuth()
  const t = useTranslations('orgEdit')
  const tCommon = useTranslations('common')
  const tConfig = useTranslations('config')
  const tAccounts = useTranslations('accounts')
  const userTimezone = useUserTimezone()

  const [activeTab, setActiveTab] = useState<TabKey>('general')

  // === GENERAL TAB STATE ===
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [timezone, setTimezone] = useState('UTC')
  const [language, setLanguage] = useState('en')
  const [isActive, setIsActive] = useState(true)
  const [llmModelId, setLlmModelId] = useState<string | null>(null)
  const [openaiApiKey, setOpenaiApiKey] = useState<string | null>(null)
  const [googleMapsApiKey, setGoogleMapsApiKey] = useState<string | null>(null)
  const [jitterWindowSeconds, setJitterWindowSeconds] = useState(30)
  const [jitterWindowError, setJitterWindowError] = useState('')
  const [activeWorkstationCount, setActiveWorkstationCount] = useState<number>(0)
  const [debouncedJitterWindow, setDebouncedJitterWindow] = useState(30)
  const jitterDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [generalDirty, setGeneralDirty] = useState(false)
  const [savingGeneral, setSavingGeneral] = useState(false)

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
  const [ipToDelete, setIpToDelete] = useState<{ id: string; ip: string } | null>(null)

  // === QUERIES ===
  const { data: org, isLoading: orgLoading, refetch: refetchOrg } = useQuery({
    queryKey: ['organization', orgId],
    queryFn: () => organizationsApi.get(orgId),
    enabled: !!orgId,
  })

  const { data: modelsData } = useQuery({
    queryKey: ['llm-models'],
    queryFn: () => logAnalysisApi.listModels(),
    staleTime: 5 * 60 * 1000,
  })

  // === LOAD ORG DATA ===
  useEffect(() => {
    if (org) {
      setName(org.name)
      setDescription(org.description || '')
      setTimezone(org.timezone)
      setLanguage(org.language)
      setIsActive(org.is_active)
      setLlmModelId(org.llm_model_id || null)
      setOpenaiApiKey(org.openai_api_key || null)
      setGoogleMapsApiKey(org.google_maps_api_key ?? null)
      setJitterWindowSeconds(org.jitter_window_seconds ?? 30)
      setAutoUpdateEnabled(org.auto_update_enabled)
      setTargetVersion(org.target_version)
      setAutoReregisterEnabled(org.auto_reregister_enabled)
      setGeneralDirty(false)
    }
  }, [org])

  // === LOAD CONFIG ===
  useEffect(() => {
    if (!orgId) return
    const loadConfig = async () => {
      try {
        const res = await apiClient.get(`/config/global?organization_id=${orgId}`)
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
  }, [orgId])

  // === LOAD VERSIONS ===
  useEffect(() => {
    const loadVersions = async () => {
      try {
        const res = await apiClient.get('/updates/versions')
        setAvailableVersions((res.data || []).map((v: { version: string }) => ({ version: v.version })))
      } catch { setAvailableVersions([]) }
    }
    loadVersions()
  }, [])

  // === CARGAR WORKSTATIONS ACTIVAS DE LA ORG (para cálculo de jitter) ===
  useEffect(() => {
    if (!orgId) return
    const loadActiveCount = async () => {
      try {
        const res = await apiClient.get(`/workstations/`, { params: { organization_id: orgId, is_online: true, page_size: 1 } })
        setActiveWorkstationCount(res.data?.total ?? 0)
      } catch {
        setActiveWorkstationCount(0)
      }
    }
    loadActiveCount()
  }, [orgId])

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
      const data: OrganizationUpdate = { name, description, is_active: isActive, timezone, language, llm_model_id: llmModelId, openai_api_key: openaiApiKey, google_maps_api_key: googleMapsApiKey, jitter_window_seconds: jitterWindowSeconds }
      await organizationsApi.update(orgId, data)
      setGeneralDirty(false)
      refetchOrg()
    } catch (e: unknown) {
      const err = e as { detail?: string; message?: string }
      alert(err.detail || err.message || 'Error')
    } finally { setSavingGeneral(false) }
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
      await apiClient.put(`/config/global?organization_id=${orgId}`, updateData)
      setConfigDirty(false)
      setConfigExists(true)
      alert(tConfig('saveSuccess'))
    } catch (e: unknown) {
      const err = e as { message?: string }
      alert(err.message || tConfig('saveError'))
    } finally { setSavingConfig(false) }
  }

  // === HANDLERS: UPDATES ===
  const handleAutoUpdateToggle = async (enabled: boolean) => {
    setTogglingUpdate(true)
    try {
      await apiClient.patch(`/organizations/${orgId}/auto-update`, { enabled })
      setAutoUpdateEnabled(enabled)
    } catch { /* silently */ }
    finally { setTogglingUpdate(false) }
  }

  const handleReregisterToggle = async (enabled: boolean) => {
    setTogglingUpdate(true)
    try {
      await apiClient.put(`/organizations/${orgId}`, { auto_reregister_enabled: enabled })
      setAutoReregisterEnabled(enabled)
    } catch { /* silently */ }
    finally { setTogglingUpdate(false) }
  }

  const handlePinVersion = async (version: string | null) => {
    setTogglingUpdate(true)
    try {
      await apiClient.put(`/updates/pin/${orgId}`, { version })
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
      await organizationsApi.addPublicIP(orgId, { ip_address: newIp, description: newIpDesc || undefined })
      setNewIp('')
      setNewIpDesc('')
      refetchOrg()
    } catch (e: unknown) {
      const err = e as { detail?: string }
      alert(err.detail || 'Error')
    } finally { setSavingIp(false) }
  }

  const handleRemoveIp = (ipId: string, ipAddress: string) => {
    setIpToDelete({ id: ipId, ip: ipAddress })
  }

  const confirmDeleteIp = async () => {
    if (!ipToDelete) return
    const { id } = ipToDelete
    setIpToDelete(null)
    setSavingIp(true)
    try {
      await organizationsApi.removePublicIP(orgId, id)
      refetchOrg()
    } catch { /* silently */ }
    finally { setSavingIp(false) }
  }

  // === SEARCH TARGETS HELPERS ===
  const addSearchIp = () => { setSearchIps([...searchIps, '']); setConfigDirty(true) }
  const removeSearchIp = (i: number) => { setSearchIps(searchIps.filter((_, idx) => idx !== i)); setConfigDirty(true) }
  const updateSearchIp = (i: number, v: string) => { const n = [...searchIps]; n[i] = v; setSearchIps(n); setConfigDirty(true) }
  const addSearchRange = () => { setSearchRanges([...searchRanges, '']); setConfigDirty(true) }
  const removeSearchRange = (i: number) => { setSearchRanges(searchRanges.filter((_, idx) => idx !== i)); setConfigDirty(true) }
  const updateSearchRange = (i: number, v: string) => { const n = [...searchRanges]; n[i] = v; setSearchRanges(n); setConfigDirty(true) }

  // === LLM MODEL SELECTOR ===
  const providers = Array.from(new Set(modelsData?.models?.map((m: { provider: string }) => m.provider) || []))
  providers.sort()
  const currentModel = modelsData?.models?.find((m: { model_id: string }) => m.model_id === llmModelId)
  const [selectedProvider, setSelectedProvider] = useState<string>('')
  useEffect(() => {
    if (currentModel) setSelectedProvider(currentModel.provider)
  }, [currentModel])
  const filteredModels = modelsData?.models?.filter((m: { provider: string }) => m.provider === selectedProvider) || []

  // === LOADING ===
  if (orgLoading) {
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
        <p className="mt-4 text-gray-600">Organización no encontrada</p>
        <Button variant="outline" className="mt-4" onClick={() => router.push('/dashboard/admin/organizations')}>
          <ArrowLeft className="mr-2 h-4 w-4" /> {tCommon('back')}
        </Button>
      </div>
    )
  }

  // === RENDER ===
  return (
    <div className="space-y-6">
      {/* Header + Tabs + Content en una sola card */}
      <div className="bg-white rounded-lg shadow">
        {/* Header */}
        <div className="p-6 pb-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Button variant="outline" size="sm" onClick={() => router.push('/dashboard/admin/organizations')} className="h-9 w-9 p-0">
                <ArrowLeft className="h-4 w-4" />
              </Button>
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
            <div className="flex items-center gap-3">
              <Badge variant={org.is_active ? 'default' : 'secondary'} className="text-xs px-3 py-1">
                {org.is_active ? tCommon('active') : tCommon('inactive')}
              </Badge>
              {org.forced_contingency && (
                <Badge variant="destructive" className="text-xs px-3 py-1">Contingencia</Badge>
              )}
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

            <div className="flex items-center space-x-2">
              <input type="checkbox" id="is_active" checked={isActive} onChange={(e) => { setIsActive(e.target.checked); setGeneralDirty(true) }} className="rounded" />
              <Label htmlFor="is_active" className="cursor-pointer">{tAccounts('activeLabel')}</Label>
            </div>

            {/* LLM Model */}
            <div className="space-y-2">
              <Label>{tAccounts('llmModelLabel')}</Label>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <select value={selectedProvider} onChange={(e) => { setSelectedProvider(e.target.value); setLlmModelId(null); setGeneralDirty(true) }} className="w-full px-3 py-2 border rounded-md text-sm">
                  <option value="">{tAccounts('llmProviderSelect')}</option>
                  {providers.map((p) => (<option key={p} value={p}>{p}</option>))}
                </select>
                <select value={llmModelId || ''} onChange={(e) => { setLlmModelId(e.target.value || null); setGeneralDirty(true) }} className="w-full px-3 py-2 border rounded-md text-sm" disabled={!selectedProvider}>
                  <option value="">{selectedProvider ? tAccounts('llmModelSelect') : `${tAccounts('llmModelDefault')}${modelsData?.default_model_id ? ` (${modelsData.default_model_id})` : ''}`}</option>
                  {filteredModels.map((m: { model_id: string; model_name: string }) => (<option key={m.model_id} value={m.model_id}>{m.model_name}</option>))}
                </select>
              </div>
              <p className="text-xs text-gray-500">{tAccounts('llmModelHelper')}</p>
            </div>

            {/* OpenAI Key */}
            <div className="space-y-2">
              <Label>{tAccounts('openaiKeyLabel')}</Label>
              <Input type="password" placeholder={tAccounts('openaiKeyPlaceholder')} value={openaiApiKey || ''} onChange={(e) => { setOpenaiApiKey(e.target.value || null); setGeneralDirty(true) }} />
              <p className="text-xs text-gray-500">{tAccounts('openaiKeyHelper')}</p>
            </div>

            {/* Google Maps API Key */}
            <div className="space-y-2">
              <Label htmlFor="google-maps-api-key">{t('googleMapsApiKey')}</Label>
              <Input
                id="google-maps-api-key"
                type="password"
                value={googleMapsApiKey ?? ''}
                onChange={(e) => { setGoogleMapsApiKey(e.target.value || null); setGeneralDirty(true) }}
                placeholder="AIza..."
              />
              <p className="text-xs text-muted-foreground mt-1">
                {t('googleMapsApiKeyHelper')}{' '}
                <a
                  href="https://console.cloud.google.com/google/maps-apis/credentials"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:underline"
                >
                  Google Cloud Console
                </a>
              </p>
            </div>

            {/* Jitter Window */}
            <div className="space-y-2">
              <Label>{t('jitterWindowLabel')}</Label>
              <Input
                type="number"
                min={5}
                max={300}
                step={1}
                value={jitterWindowSeconds}
                onChange={(e) => {
                  const v = parseInt(e.target.value, 10) || 0
                  setJitterWindowSeconds(v)
                  setGeneralDirty(true)
                  setJitterWindowError(isNaN(v) || v < 5 || v > 300 ? t('jitterWindowValidation') : '')
                }}
                className="max-w-xs"
              />
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
          <ActionConfigSection organizationId={orgId} hideHeader />
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
                      <Button variant="outline" size="sm" onClick={() => handleRemoveIp(ip.id, ip.ip_address)} disabled={savingIp}>
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
        </div>
      </div>

      <Dialog open={!!ipToDelete} onOpenChange={(open) => { if (!open) setIpToDelete(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{tCommon('confirmDelete')}</DialogTitle>
            <DialogDescription>
              {ipToDelete && tAccounts('deleteIpConfirm', { ip: ipToDelete.ip })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIpToDelete(null)}>
              {tCommon('cancel')}
            </Button>
            <Button variant="destructive" onClick={confirmDeleteIp}>
              {tCommon('delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
