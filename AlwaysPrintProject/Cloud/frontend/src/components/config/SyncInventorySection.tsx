/**
 * Sección de Sincronización de Inventario en la página de System Configuration.
 *
 * Permite a Corporate Admins ejecutar los 11 pasos de sincronización
 * (6 core + 5 post-procesamiento) desde la UI web, equivalente al
 * pipeline completo de sync_inventory.sh.
 *
 * Control de acceso: solo usuarios con email en dominios autorizados
 * (@robles.ai, @sistemas.com.pe) pueden ver esta sección.
 */

'use client'

import { useState, useEffect, useRef } from 'react'
import { useTranslations } from 'next-intl'
import { AlertTriangle, Database, FileSpreadsheet, Loader2, PlayCircle, Upload, FileText, X } from 'lucide-react'

import { useAuth } from '@/hooks/useAuth'
import { organizationsApi, syncInventoryApi } from '@/lib/api'
import type { Organization } from '@/types'
import type { StepResult } from '@/types/sync-inventory'

// === CONSTANTES ===

const ALLOWED_DOMAINS = ['@robles.ai', '@sistemas.com.pe']

const STEPS = [
  { step: 1, requiresCsv: true, category: 'csv' },
  { step: 2, requiresCsv: true, category: 'csv' },
  { step: 3, requiresCsv: true, category: 'csv' },
  { step: 4, requiresCsv: false, category: 'db' },
  { step: 5, requiresCsv: false, category: 'db' },
  { step: 6, requiresCsv: false, category: 'db' },
  { step: 7, requiresCsv: false, category: 'post' },
  { step: 8, requiresCsv: false, category: 'post' },
  { step: 9, requiresCsv: false, category: 'post' },
  { step: 10, requiresCsv: false, category: 'post' },
  { step: 11, requiresCsv: false, category: 'post' },
]

const REQUIRED_CSV_COLUMNS = [
  'VLAN_CODE', 'VLAN_NAME', 'IP', 'MODELO', 'SERIE',
  'UBICACION', 'DIRECCION', 'DISTRITO', 'PROVINCIA',
  'DEPARTAMENTO', 'TIPO'
]

// === COMPONENTE ===

export function SyncInventorySection() {
  const t = useTranslations('syncInventory')
  const { isAdmin, user } = useAuth()

  // === ESTADO INTERNO ===

  const [organizations, setOrganizations] = useState<Organization[]>([])
  const [loadingOrgs, setLoadingOrgs] = useState(true)
  const [selectedOrgId, setSelectedOrgId] = useState<string | null>(null)
  const [csvFile, setCsvFile] = useState<File | null>(null)
  const [csvRowCount, setCsvRowCount] = useState<number | null>(null)
  const [csvError, setCsvError] = useState<string | null>(null)
  const [dryRun, setDryRun] = useState(true)
  const [selectedStep, setSelectedStep] = useState<number | null>(null)
  const [isExecuting, setIsExecuting] = useState(false)
  const [results, setResults] = useState<StepResult[]>([])

  // === CONTROL DE ACCESO ===

  const userEmail = user?.email?.toLowerCase() ?? ''
  const isAllowedDomain = ALLOWED_DOMAINS.some(domain => userEmail.endsWith(domain))

  // === FETCH DE ORGANIZACIONES ===

  useEffect(() => {
    const fetchOrgs = async () => {
      try {
        setLoadingOrgs(true)
        const orgs = await organizationsApi.list()
        setOrganizations(orgs)
        if (orgs.length > 0) {
          setSelectedOrgId(orgs[0].id)
        }
      } catch (error) {
        console.error('Error al obtener organizaciones:', error)
      } finally {
        setLoadingOrgs(false)
      }
    }
    fetchOrgs()
  }, [])

  // === REF PARA INPUT DE ARCHIVO ===

  const fileInputRef = useRef<HTMLInputElement>(null)

  // === HANDLER DE CSV ===

  const handleCsvUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (e) => {
      try {
        const text = e.target?.result as string
        const lines = text.split(/\r?\n/).filter(line => line.trim() !== '')

        if (lines.length === 0) {
          setCsvFile(null)
          setCsvRowCount(null)
          setCsvError(t('errors.csvInvalid'))
          return
        }

        // Parsear headers (primera línea)
        const headers = lines[0].split(',').map(h => h.trim().toUpperCase())
        const missingColumns = REQUIRED_CSV_COLUMNS.filter(
          col => !headers.includes(col)
        )

        if (missingColumns.length > 0) {
          setCsvFile(null)
          setCsvRowCount(null)
          setCsvError(t('errors.missingColumns', { columns: missingColumns.join(', ') }))
        } else {
          setCsvFile(file)
          setCsvRowCount(lines.length - 1) // Excluir header
          setCsvError(null)
        }
      } catch {
        setCsvFile(null)
        setCsvRowCount(null)
        setCsvError(t('errors.csvInvalid'))
      }
    }
    reader.readAsText(file)
  }

  const handleRemoveCsv = () => {
    setCsvFile(null)
    setCsvRowCount(null)
    setCsvError(null)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  // === HANDLER DE EJECUCIÓN ===

  const handleExecute = async () => {
    if (!selectedStep || !selectedOrgId) return

    // Verificar que CSV está presente si el paso lo requiere
    const stepRequiresCsv = selectedStep >= 1 && selectedStep <= 3
    const runAllRequiresCsv = selectedStep === 12
    if ((stepRequiresCsv || runAllRequiresCsv) && !csvFile) {
      setCsvError(t('errors.csvRequired'))
      return
    }

    setCsvError(null)
    setIsExecuting(true)
    setResults([])

    try {
      const response = await syncInventoryApi.execute({
        step: selectedStep,
        dry_run: dryRun,
        organization_id: selectedOrgId,
        csv_file: csvFile || undefined,
      })
      setResults(response.steps_executed)
    } catch (error: unknown) {
      const err = error as { detail?: string; status?: number; code?: string }
      if (err.code === 'ECONNABORTED' || err.status === 408) {
        setCsvError(t('errors.timeout'))
      } else if (err.status === 403) {
        setCsvError(err.detail || t('errors.executionFailed'))
      } else if (err.status === 422) {
        setCsvError(err.detail || t('errors.csvInvalid'))
      } else {
        setCsvError(err.detail || t('errors.executionFailed'))
      }
    } finally {
      setIsExecuting(false)
    }
  }

  // === CONTROL DE ACCESO: retornar null si no es Corporate Admin ===

  if (!isAdmin() || !isAllowedDomain) {
    return null
  }

  return (
    <div className="bg-white rounded-lg shadow p-6 space-y-6">
      {/* Encabezado de sección */}
      <div className="flex items-start gap-3">
        <Database className="w-6 h-6 text-blue-600 mt-0.5" />
        <div>
          <h2 className="text-xl font-semibold text-gray-900">{t('title')}</h2>
          <p className="mt-1 text-sm text-gray-600">{t('description')}</p>
        </div>
      </div>

      {/* Selector de organización */}
      <div>
        <label
          htmlFor="sync-org-selector"
          className="block text-sm font-medium text-gray-700 mb-1"
        >
          {t('organizationSelector.label')}
        </label>
        {loadingOrgs ? (
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <Loader2 className="w-4 h-4 animate-spin" />
          </div>
        ) : (
          <select
            id="sync-org-selector"
            value={selectedOrgId || ''}
            onChange={(e) => setSelectedOrgId(e.target.value)}
            className="block w-full max-w-xs rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
          >
            {organizations.map((org) => (
              <option key={org.id} value={org.id}>
                {org.name}
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Área de upload de CSV */}
      <div className="space-y-2">
        <label className="block text-sm font-medium text-gray-700">
          {t('buttons.uploadCsv')}
        </label>

        {/* Zona de upload */}
        {!csvFile ? (
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="w-full max-w-md border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-blue-400 hover:bg-blue-50 transition-colors cursor-pointer"
          >
            <Upload className="w-8 h-8 text-gray-400 mx-auto mb-2" />
            <span className="text-sm text-gray-600">{t('csv.dropzone')}</span>
          </button>
        ) : (
          <div className="flex items-center gap-3 w-full max-w-md bg-green-50 border border-green-200 rounded-lg px-4 py-3">
            <FileText className="w-5 h-5 text-green-600 flex-shrink-0" />
            <span className="text-sm text-green-800 truncate">
              {t('csv.fileSelected', { filename: csvFile.name, rows: csvRowCount ?? 0 })}
            </span>
            <button
              type="button"
              onClick={handleRemoveCsv}
              className="ml-auto text-gray-400 hover:text-red-500 transition-colors"
              title={t('csv.remove')}
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Input file oculto */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv"
          onChange={handleCsvUpload}
          className="hidden"
        />

        {/* Error de CSV */}
        {csvError && (
          <p className="text-sm text-red-600 mt-1">{csvError}</p>
        )}
      </div>

      {/* Tarjetas de pasos */}
      <div className="space-y-4">
        {/* Pasos CSV (1-3) */}
        <div>
          <h3 className="text-sm font-medium text-gray-700 mb-2 flex items-center gap-1.5">
            <FileSpreadsheet className="w-4 h-4 text-blue-500" />
            {t('csvSteps')}
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {STEPS.filter(s => s.category === 'csv').map(({ step }) => (
              <button
                key={step}
                type="button"
                onClick={() => setSelectedStep(selectedStep === step ? null : step)}
                disabled={isExecuting}
                className={`text-left p-3 rounded-md border border-l-4 transition-colors ${
                  selectedStep === step
                    ? 'ring-2 ring-blue-500 bg-blue-50 border-l-blue-500'
                    : 'border-l-blue-400 hover:bg-gray-50'
                } ${isExecuting ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-gray-900">
                    {step}. {t(`steps.step${step}.label`)}
                  </span>
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">
                    CSV
                  </span>
                </div>
                <p className="text-xs text-gray-500">
                  {t(`steps.step${step}.description`)}
                </p>
              </button>
            ))}
          </div>
        </div>

        {/* Pasos DB (4-6) */}
        <div>
          <h3 className="text-sm font-medium text-gray-700 mb-2 flex items-center gap-1.5">
            <Database className="w-4 h-4 text-green-500" />
            {t('dbSteps')}
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {STEPS.filter(s => s.category === 'db').map(({ step }) => (
              <button
                key={step}
                type="button"
                onClick={() => setSelectedStep(selectedStep === step ? null : step)}
                disabled={isExecuting}
                className={`text-left p-3 rounded-md border border-l-4 transition-colors ${
                  selectedStep === step
                    ? 'ring-2 ring-blue-500 bg-blue-50 border-l-green-500'
                    : 'border-l-green-400 hover:bg-gray-50'
                } ${isExecuting ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-gray-900">
                    {step}. {t(`steps.step${step}.label`)}
                  </span>
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-green-100 text-green-700">
                    DB
                  </span>
                </div>
                <p className="text-xs text-gray-500">
                  {t(`steps.step${step}.description`)}
                </p>
              </button>
            ))}
          </div>
        </div>

        {/* Pasos Post-procesamiento (7-11) */}
        <div>
          <h3 className="text-sm font-medium text-gray-700 mb-2 flex items-center gap-1.5">
            <PlayCircle className="w-4 h-4 text-purple-500" />
            {t('postSteps')}
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {STEPS.filter(s => s.category === 'post').map(({ step }) => (
              <button
                key={step}
                type="button"
                onClick={() => setSelectedStep(selectedStep === step ? null : step)}
                disabled={isExecuting}
                className={`text-left p-3 rounded-md border border-l-4 transition-colors ${
                  selectedStep === step
                    ? 'ring-2 ring-blue-500 bg-blue-50 border-l-purple-500'
                    : 'border-l-purple-400 hover:bg-gray-50'
                } ${isExecuting ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-medium text-gray-900">
                    {step}. {t(`steps.step${step}.label`)}
                  </span>
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700">
                    POST
                  </span>
                </div>
                <p className="text-xs text-gray-500">
                  {t(`steps.step${step}.description`)}
                </p>
              </button>
            ))}
          </div>
        </div>

        {/* Botón Run All */}
        <button
          type="button"
          onClick={() => setSelectedStep(selectedStep === 12 ? null : 12)}
          disabled={isExecuting}
          className={`w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-md border text-sm font-medium transition-colors ${
            selectedStep === 12
              ? 'ring-2 ring-blue-500 bg-blue-600 text-white border-blue-600'
              : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
          } ${isExecuting ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
        >
          <PlayCircle className="w-4 h-4" />
          {t('buttons.runAll')}
        </button>
      </div>

      {/* Controles de ejecución: toggle dry-run + botón ejecutar */}
      <div className="space-y-3">
        {/* Toggle dry-run */}
        <div className="flex items-center gap-3">
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={dryRun}
              onChange={(e) => setDryRun(e.target.checked)}
              disabled={isExecuting}
              className="sr-only peer"
            />
            <div className="w-9 h-5 bg-gray-200 peer-focus:outline-none peer-focus:ring-2 peer-focus:ring-blue-300 rounded-full peer peer-checked:bg-blue-600 after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:after:translate-x-full" />
          </label>
          <span className="text-sm font-medium text-gray-700">{t('dryRun.toggle')}</span>
        </div>

        {/* Banner dry-run activo */}
        {dryRun && (
          <div className="flex items-center gap-2 px-3 py-2 bg-amber-50 border border-amber-200 rounded-md">
            <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0" />
            <span className="text-sm text-amber-800">{t('dryRun.banner')}</span>
          </div>
        )}

        {/* Botón ejecutar */}
        <button
          type="button"
          onClick={handleExecute}
          disabled={!selectedStep || !selectedOrgId || isExecuting}
          className={`flex items-center justify-center gap-2 px-4 py-2.5 rounded-md text-sm font-medium transition-colors ${
            !selectedStep || !selectedOrgId || isExecuting
              ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
              : 'bg-blue-600 text-white hover:bg-blue-700'
          }`}
        >
          {isExecuting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              {t('execution.running')}
            </>
          ) : (
            <>
              <PlayCircle className="w-4 h-4" />
              {t('buttons.run')}
            </>
          )}
        </button>
      </div>

      {/* Área de output monospace */}
      {results.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-gray-700">{t('output.title')}</h3>
          <div className="max-h-96 overflow-y-auto bg-gray-900 rounded-lg p-4 space-y-3">
            {results.map((result) => (
              <div key={result.step} className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                    result.success
                      ? 'bg-green-100 text-green-800'
                      : 'bg-red-100 text-red-800'
                  }`}>
                    {result.success ? t('execution.completed') : t('execution.error')}
                  </span>
                  <span className="text-xs text-gray-400">
                    {result.step}. {result.name}
                  </span>
                </div>
                <pre className={`text-xs font-mono whitespace-pre-wrap break-words ${
                  result.success ? 'text-green-300' : 'text-red-300'
                }`}>
                  {result.output}
                </pre>
                {result.error && (
                  <pre className="text-xs font-mono text-red-400 whitespace-pre-wrap break-words">
                    {result.error}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
