/**
 * Sección de configuración de Vista Remota.
 * Permite configurar los parámetros de visualización y control remoto
 * de workstations para una organización.
 */

'use client'

import { useState, useEffect } from 'react'
import { useTranslations } from 'next-intl'
import { Eye, Loader2, AlertTriangle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { useToast } from '@/hooks/use-toast'
import { apiClient } from '@/lib/api'

/** Configuración de vista remota de la organización */
export interface RemoteViewConfig {
  enabled: boolean
  modes_allowed: string[]
  default_mode: string
  remote_control_enabled: boolean
  clipboard_sharing_enabled: boolean
  require_user_consent: boolean
  max_concurrent_sessions: number
  session_timeout_minutes: number
  quality_mode: 'auto' | 'manual'
  capture_resolution: string
  compression_quality: number
  viewport_adaptive_downscale: boolean
  stream_max_fps: number
}

/** Valores por defecto cuando no hay configuración guardada */
const DEFAULT_CONFIG: RemoteViewConfig = {
  enabled: false,
  modes_allowed: ['screenshot'],
  default_mode: 'screenshot',
  remote_control_enabled: false,
  clipboard_sharing_enabled: false,
  require_user_consent: true,
  max_concurrent_sessions: 5,
  session_timeout_minutes: 15,
  quality_mode: 'auto',
  capture_resolution: '1280x720',
  compression_quality: 75,
  viewport_adaptive_downscale: true,
  stream_max_fps: 5,
}

/** Resoluciones disponibles para captura */
const RESOLUTIONS = ['1920x1080', '1280x720', '854x480', '640x360']

/** Modos de vista remota disponibles */
const ALL_MODES = ['screenshot', 'stream', 'interactive'] as const

interface RemoteViewSectionProps {
  organizationId: string
}

export function RemoteViewSection({ organizationId }: RemoteViewSectionProps) {
  const t = useTranslations('remoteView')
  const tCommon = useTranslations('common')
  const { toast } = useToast()

  const [config, setConfig] = useState<RemoteViewConfig>(DEFAULT_CONFIG)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  // Cargar configuración existente
  useEffect(() => {
    if (!organizationId) return
    const loadConfig = async () => {
      setLoading(true)
      try {
        const res = await apiClient.get(`/organizations/${organizationId}/remote-view`)
        if (res.data) {
          setConfig({ ...DEFAULT_CONFIG, ...res.data })
        }
      } catch {
        // Sin configuración previa, usar defaults
      } finally {
        setLoading(false)
      }
    }
    loadConfig()
  }, [organizationId])

  // Actualizar un campo y marcar como dirty
  const updateField = <K extends keyof RemoteViewConfig>(field: K, value: RemoteViewConfig[K]) => {
    setConfig(prev => ({ ...prev, [field]: value }))
    setDirty(true)
  }

  // Toggle de modo en modes_allowed
  const toggleMode = (mode: string) => {
    setConfig(prev => {
      const modes = prev.modes_allowed.includes(mode)
        ? prev.modes_allowed.filter(m => m !== mode)
        : [...prev.modes_allowed, mode]
      // Si el modo por defecto ya no está permitido, ajustar
      const defaultMode = modes.includes(prev.default_mode) ? prev.default_mode : (modes[0] || 'screenshot')
      return { ...prev, modes_allowed: modes, default_mode: defaultMode }
    })
    setDirty(true)
  }

  // Guardar configuración
  const handleSave = async () => {
    setSaving(true)
    try {
      await apiClient.patch(`/organizations/${organizationId}/remote-view`, config)
      setDirty(false)
      toast({ title: t('saveSuccess') })
    } catch {
      toast({ title: t('saveError'), variant: 'destructive' })
    } finally {
      setSaving(false)
    }
  }

  // Etiqueta localizada para un modo
  const getModeLabel = (mode: string): string => {
    const map: Record<string, string> = {
      screenshot: t('modeScreenshot'),
      stream: t('modeStream'),
      interactive: t('modeInteractive'),
    }
    return map[mode] || mode
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-4">
        <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
        <span className="text-sm text-gray-500">{tCommon('loading')}</span>
      </div>
    )
  }

  const isManualQuality = config.quality_mode === 'manual'

  return (
    <div className="space-y-6">
      {/* Título de sección */}
      <div className="flex items-center gap-2">
        <Eye className="h-5 w-5 text-blue-600" />
        <div>
          <h3 className="text-sm font-medium text-gray-900">{t('sectionTitle')}</h3>
          <p className="text-xs text-gray-500">{t('sectionDesc')}</p>
        </div>
      </div>

      {/* Toggle master: enabled */}
      <div className="flex items-center justify-between p-4 border rounded-lg">
        <div>
          <Label className="text-sm font-medium">{t('enabledLabel')}</Label>
          <p className="text-xs text-gray-500 mt-1">{t('enabledDesc')}</p>
        </div>
        <Switch
          checked={config.enabled}
          onCheckedChange={(checked) => updateField('enabled', checked)}
        />
      </div>

      {/* Advertencia si está deshabilitado */}
      {!config.enabled && (
        <Alert className="border-amber-200 bg-amber-50">
          <AlertTriangle className="h-4 w-4 text-amber-600" />
          <AlertDescription className="text-xs text-amber-800">
            {t('disabledWarning')}
          </AlertDescription>
        </Alert>
      )}

      {/* Controles restantes (dimmed si disabled) */}
      <div className={`space-y-5 ${!config.enabled ? 'opacity-50 pointer-events-none' : ''}`}>

        {/* Modos disponibles (multi-checkbox) */}
        <div className="space-y-2">
          <Label>{t('modesAllowedLabel')}</Label>
          <p className="text-xs text-gray-500">{t('modesAllowedDesc')}</p>
          <div className="flex flex-wrap gap-4 mt-2">
            {ALL_MODES.map((mode) => (
              <label key={mode} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  className="rounded"
                  checked={config.modes_allowed.includes(mode)}
                  onChange={() => toggleMode(mode)}
                />
                <span className="text-sm">{getModeLabel(mode)}</span>
              </label>
            ))}
          </div>
          {config.modes_allowed.length === 0 && (
            <p className="text-xs text-red-600 mt-1">{t('modesAllowedDesc')}</p>
          )}
        </div>

        {/* Modo por defecto */}
        <div className="space-y-2">
          <Label>{t('defaultModeLabel')}</Label>
          <p className="text-xs text-gray-500">{t('defaultModeDesc')}</p>
          <select
            value={config.default_mode}
            onChange={(e) => updateField('default_mode', e.target.value)}
            className="w-full max-w-xs px-3 py-2 border rounded-md text-sm"
          >
            {config.modes_allowed.map((mode) => (
              <option key={mode} value={mode}>{getModeLabel(mode)}</option>
            ))}
          </select>
        </div>

        {/* Toggle: remote_control_enabled */}
        <div className="flex items-center justify-between p-4 border rounded-lg">
          <div>
            <Label className="text-sm font-medium">{t('remoteControlLabel')}</Label>
            <p className="text-xs text-gray-500 mt-1">{t('remoteControlDesc')}</p>
          </div>
          <Switch
            checked={config.remote_control_enabled}
            onCheckedChange={(checked) => updateField('remote_control_enabled', checked)}
          />
        </div>

        {/* Toggle: clipboard_sharing_enabled */}
        <div className="flex items-center justify-between p-4 border rounded-lg">
          <div>
            <Label className="text-sm font-medium">{t('clipboardLabel')}</Label>
            <p className="text-xs text-gray-500 mt-1">{t('clipboardDesc')}</p>
          </div>
          <Switch
            checked={config.clipboard_sharing_enabled}
            onCheckedChange={(checked) => updateField('clipboard_sharing_enabled', checked)}
          />
        </div>

        {/* Toggle: require_user_consent */}
        <div className="flex items-center justify-between p-4 border rounded-lg">
          <div>
            <Label className="text-sm font-medium">{t('consentLabel')}</Label>
            <p className="text-xs text-gray-500 mt-1">{t('consentDesc')}</p>
          </div>
          <Switch
            checked={config.require_user_consent}
            onCheckedChange={(checked) => updateField('require_user_consent', checked)}
          />
        </div>

        {/* Input numérico: max_concurrent_sessions */}
        <div className="space-y-2">
          <Label>{t('maxSessionsLabel')}</Label>
          <Input
            type="number"
            min={0}
            max={50}
            value={config.max_concurrent_sessions}
            onChange={(e) => updateField('max_concurrent_sessions', Math.min(50, Math.max(0, parseInt(e.target.value) || 0)))}
            className="max-w-xs"
          />
          <p className="text-xs text-gray-500">{t('maxSessionsDesc')}</p>
        </div>

        {/* Input numérico: session_timeout_minutes */}
        <div className="space-y-2">
          <Label>{t('timeoutLabel')}</Label>
          <Input
            type="number"
            min={1}
            max={60}
            value={config.session_timeout_minutes}
            onChange={(e) => updateField('session_timeout_minutes', Math.min(60, Math.max(1, parseInt(e.target.value) || 1)))}
            className="max-w-xs"
          />
          <p className="text-xs text-gray-500">{t('timeoutDesc')}</p>
        </div>

        {/* Select: quality_mode */}
        <div className="space-y-2">
          <Label>{t('qualityModeLabel')}</Label>
          <p className="text-xs text-gray-500">{t('qualityModeDesc')}</p>
          <select
            value={config.quality_mode}
            onChange={(e) => updateField('quality_mode', e.target.value as 'auto' | 'manual')}
            className="w-full max-w-xs px-3 py-2 border rounded-md text-sm"
          >
            <option value="auto">{t('qualityModeAuto')}</option>
            <option value="manual">{t('qualityModeManual')}</option>
          </select>
        </div>

        {/* Campos condicionales: solo visibles en modo manual */}
        {isManualQuality && (
          <>
            {/* Select: capture_resolution */}
            <div className="space-y-2">
              <Label>{t('resolutionLabel')}</Label>
              <p className="text-xs text-gray-500">{t('resolutionDesc')}</p>
              <select
                value={config.capture_resolution}
                onChange={(e) => updateField('capture_resolution', e.target.value)}
                className="w-full max-w-xs px-3 py-2 border rounded-md text-sm"
              >
                {RESOLUTIONS.map((res) => (
                  <option key={res} value={res}>{res}</option>
                ))}
              </select>
            </div>

            {/* Input numérico: compression_quality */}
            <div className="space-y-2">
              <Label>{t('compressionLabel')}</Label>
              <Input
                type="number"
                min={1}
                max={100}
                value={config.compression_quality}
                onChange={(e) => updateField('compression_quality', Math.min(100, Math.max(1, parseInt(e.target.value) || 75)))}
                className="max-w-xs"
              />
              <p className="text-xs text-gray-500">{t('compressionDesc')}</p>
            </div>
          </>
        )}

        {/* Toggle: viewport_adaptive_downscale */}
        <div className="flex items-center justify-between p-4 border rounded-lg">
          <div>
            <Label className="text-sm font-medium">{t('adaptiveLabel')}</Label>
            <p className="text-xs text-gray-500 mt-1">{t('adaptiveDesc')}</p>
          </div>
          <Switch
            checked={config.viewport_adaptive_downscale}
            onCheckedChange={(checked) => updateField('viewport_adaptive_downscale', checked)}
          />
        </div>

        {/* Input numérico: stream_max_fps */}
        <div className="space-y-2">
          <Label>{t('fpsLabel')}</Label>
          <Input
            type="number"
            min={1}
            max={10}
            value={config.stream_max_fps}
            onChange={(e) => updateField('stream_max_fps', Math.min(10, Math.max(1, parseInt(e.target.value) || 5)))}
            className="max-w-xs"
          />
          <p className="text-xs text-gray-500">{t('fpsDesc')}</p>
        </div>
      </div>

      {/* Botón guardar */}
      <div className="flex justify-end gap-2 pt-4 border-t">
        <Button onClick={handleSave} disabled={!dirty || saving}>
          {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          {saving ? tCommon('saving') : tCommon('save')}
        </Button>
      </div>
    </div>
  )
}
