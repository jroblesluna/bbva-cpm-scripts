'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { setupApi, restoreApi, RestoreStatusResponse } from '@/lib/api'
import { validateBackupZip, BackupZipErrorCode, BackupZipManifestSummary } from '@/lib/backupZipValidation'

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { CheckCircle, AlertCircle, Upload, Loader2, FileArchive } from 'lucide-react'

// ============================================================================
// PANTALLA DE PROGRESO DE RESTAURACIÓN
// ============================================================================

function RestoreProgressScreen() {
  const t = useTranslations('backup')
  const router = useRouter()
  const [restoreStatus, setRestoreStatus] = useState<RestoreStatusResponse>({ status: 'restoring' })
  const [countdown, setCountdown] = useState(3)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const tablesListRef = useRef<HTMLDivElement | null>(null)

  const getStageLabel = useCallback((stage: string | null | undefined): string => {
    if (!stage) return ''
    const stageMap: Record<string, string> = {
      validating: t('restoreStageValidating'),
      cleaning: t('restoreStageCleaning'),
      restoring_db: t('restoreStageRestoringDb'),
      restoring_images: t('restoreStageRestoringImages'),
      rebuilding_urls: t('restoreStageRebuildingUrls'),
      verifying: t('restoreStageVerifying'),
    }
    return stageMap[stage] || stage
  }, [t])

  useEffect(() => {
    const poll = async () => {
      try {
        const status = await restoreApi.getStatus()
        setRestoreStatus(status)

        if (status.status === 'completed' || status.status === 'failed') {
          if (pollRef.current) {
            clearInterval(pollRef.current)
            pollRef.current = null
          }
        }
      } catch {
        // Ignorar errores de polling
      }
    }

    poll()
    pollRef.current = setInterval(poll, 3000)

    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  // Countdown para redirección cuando completado — el updater de setCountdown
  // debe ser puro (sin side effects), así que solo baja el número acá.
  useEffect(() => {
    if (restoreStatus.status === 'completed') {
      countdownRef.current = setInterval(() => {
        setCountdown((prev) => (prev <= 1 ? 0 : prev - 1))
      }, 1000)
    }

    return () => {
      if (countdownRef.current) clearInterval(countdownRef.current)
    }
  }, [restoreStatus.status])

  // Navegación (side effect real) separada del cálculo del countdown de arriba.
  useEffect(() => {
    if (restoreStatus.status === 'completed' && countdown === 0) {
      router.push('/login')
    }
  }, [restoreStatus.status, countdown, router])

  // Auto-scroll al final de la lista de tablas cuando llega una nueva
  useEffect(() => {
    if (tablesListRef.current) {
      tablesListRef.current.scrollTop = tablesListRef.current.scrollHeight
    }
  }, [restoreStatus.tables_detail])

  if (restoreStatus.status === 'completed') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
        <Card className="w-full max-w-md">
          <CardContent className="p-6">
            <div className="text-center">
              <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-green-100 mb-4">
                <CheckCircle className="h-6 w-6 text-green-600" />
              </div>
              <h3 className="text-lg font-medium text-gray-900 mb-2">{t('restoreCompleted')}</h3>
              <p className="text-sm text-gray-500">
                {t('restoreCompletedRedirect', { seconds: countdown })}
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (restoreStatus.status === 'failed') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
        <Card className="w-full max-w-md">
          <CardContent className="p-6">
            <div className="text-center">
              <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-red-100 mb-4">
                <AlertCircle className="h-6 w-6 text-red-600" />
              </div>
              <h3 className="text-lg font-medium text-gray-900 mb-2">{t('restoreFailed')}</h3>
              {restoreStatus.error && (
                <p className="text-sm text-red-600 mb-4">{restoreStatus.error}</p>
              )}
              <Button onClick={() => window.location.reload()} variant="outline">
                {t('restoreRetry')}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  // Status: restoring
  const tablesDetail = restoreStatus.tables_detail ?? []
  const hasTablesDetail = tablesDetail.length > 0

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <Card className={`w-full ${hasTablesDetail ? 'max-w-lg' : 'max-w-md'}`}>
        <CardContent className="p-6">
          <div className="text-center">
            <Loader2 className="h-10 w-10 text-blue-600 animate-spin mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">{t('restoreInProgress')}</h3>
            <p className="text-sm text-gray-600 mb-4">
              {getStageLabel(restoreStatus.stage)}
            </p>

            {/* Barra de progreso */}
            <div className="w-full bg-gray-200 rounded-full h-3 mb-2">
              <div
                className="bg-blue-600 h-3 rounded-full transition-all duration-500"
                style={{ width: `${restoreStatus.progress ?? 0}%` }}
              />
            </div>
            <p className="text-xs text-gray-500 mb-4">
              {t('restoreUploadProgress', { percent: restoreStatus.progress ?? 0 })}
            </p>

            <p className="text-xs text-amber-600 font-medium">
              {t('restoreDoNotClose')}
            </p>
          </div>

          {/* Detalle tabla por tabla (solo durante restoring_db) */}
          {hasTablesDetail && (
            <div className="mt-4 text-left">
              <div className="flex items-center justify-between mb-1">
                <p className="text-xs font-medium text-gray-700">
                  {t('restoreTablesProgress')}
                </p>
                {restoreStatus.tables_total != null && restoreStatus.tables_done != null && (
                  <p className="text-xs text-gray-500">
                    {restoreStatus.tables_done} / {restoreStatus.tables_total}
                  </p>
                )}
              </div>
              <div
                ref={tablesListRef}
                className="max-h-40 overflow-y-auto rounded-md border bg-gray-50 divide-y divide-gray-100"
              >
                {tablesDetail.map((row, i) => {
                  const isCurrent = row.table === restoreStatus.current_table && i === tablesDetail.length - 1
                  return (
                    <div
                      key={row.table}
                      className={`flex items-center justify-between px-2 py-1 text-xs ${
                        isCurrent ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-600'
                      }`}
                    >
                      <span className="flex items-center gap-1.5 truncate">
                        {isCurrent ? (
                          <Loader2 className="h-3 w-3 shrink-0 animate-spin" />
                        ) : (
                          <CheckCircle className="h-3 w-3 shrink-0 text-green-600" />
                        )}
                        <span className="truncate">{row.table}</span>
                      </span>
                      <span className="shrink-0 text-gray-500">{row.count}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

// ============================================================================
// FORMULARIO DE RESTORE
// ============================================================================

const CLIENT_ZIP_ERROR_KEYS: Record<BackupZipErrorCode, string> = {
  MISSING_MANIFEST: 'restoreClientErrorMissingManifest',
  BAD_PASSWORD: 'restoreClientErrorBadPassword',
  CORRUPT: 'restoreClientErrorCorrupt',
  INVALID_JSON: 'restoreClientErrorInvalidJson',
  MISSING_VERSION: 'restoreClientErrorMissingVersion',
  MISSING_TABLES: 'restoreClientErrorMissingTables',
  MISSING_TOTAL_RECORDS: 'restoreClientErrorMissingTotalRecords',
  MISSING_FILES: 'restoreClientErrorMissingFiles',
  UNKNOWN: 'restoreClientErrorUnknown',
}

/** Construye el mensaje de error con el detalle de diagnóstico (carpeta envolvente o archivos encontrados) si existe. */
function buildZipErrorMessage(
  t: ReturnType<typeof useTranslations>,
  result: { error?: BackupZipErrorCode; detail?: string },
  file: string
): string {
  if (result.error === 'MISSING_MANIFEST' && result.detail?.startsWith('wrapped:')) {
    const folder = result.detail.slice('wrapped:'.length)
    return t('restoreClientErrorWrappedFolder', { file, folder })
  }
  if (result.error === 'MISSING_MANIFEST' && result.detail?.startsWith('found:')) {
    const found = result.detail.slice('found:'.length)
    return t('restoreClientErrorMissingManifestFound', { file, found })
  }
  return t(CLIENT_ZIP_ERROR_KEYS[result.error ?? 'UNKNOWN'], { file })
}

function RestoreForm({ onRestoreStarted }: { onRestoreStarted: () => void }) {
  const t = useTranslations('backup')
  const [dbFile, setDbFile] = useState<File | null>(null)
  const [imagesFile, setImagesFile] = useState<File | null>(null)
  const [password, setPassword] = useState('')
  const [isUploading, setIsUploading] = useState(false)
  const [uploadStage, setUploadStage] = useState<'validating' | 'db' | 'images' | null>(null)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [dbManifest, setDbManifest] = useState<BackupZipManifestSummary | null>(null)
  const [imagesManifest, setImagesManifest] = useState<BackupZipManifestSummary | null>(null)
  const submittingRef = useRef(false)

  // Cambiar el archivo (o quitarlo) limpia el error/manifest viejo — ya no aplica al nuevo archivo.
  const handleDbFileChange = (file: File | null) => {
    setDbFile(file)
    setError(null)
    setDbManifest(null)
  }
  const handleImagesFileChange = (file: File | null) => {
    setImagesFile(file)
    setError(null)
    setImagesManifest(null)
  }

  const handleRestore = async () => {
    if (!dbFile || !imagesFile) return
    // Guard síncrono contra doble-submit: setIsUploading(true) no oculta el botón
    // hasta el próximo render, así que un doble-click rápido puede disparar esto
    // dos veces y mandar dos flujos de upload/start en paralelo.
    if (submittingRef.current) return
    submittingRef.current = true

    setError(null)
    setIsUploading(true)
    setDbManifest(null)
    setImagesManifest(null)

    try {
      // 0. Validar manifests en el navegador ANTES de subir (evita subir ZIPs grandes inválidos).
      //    El backend valida igual — esto solo da feedback rápido sin gastar ancho de banda.
      setUploadStage('validating')
      const pwd = password || undefined

      const dbValidation = await validateBackupZip(dbFile, pwd, 'db')
      if (!dbValidation.valid) {
        setError(buildZipErrorMessage(t, dbValidation, 'db.zip'))
        setIsUploading(false)
        setUploadStage(null)
        submittingRef.current = false
        return
      }
      setDbManifest(dbValidation.manifest ?? null)

      const imagesValidation = await validateBackupZip(imagesFile, pwd, 'images')
      if (!imagesValidation.valid) {
        setError(buildZipErrorMessage(t, imagesValidation, 'images.zip'))
        setIsUploading(false)
        setUploadStage(null)
        submittingRef.current = false
        return
      }
      setImagesManifest(imagesValidation.manifest ?? null)

      // 1. Obtener presigned URLs
      const { db_upload_url, images_upload_url } = await restoreApi.getPresignedUrls(
        dbFile.size,
        imagesFile.size
      )

      // 2. Upload DB ZIP
      setUploadStage('db')
      setUploadProgress(0)
      await restoreApi.uploadToS3(db_upload_url, dbFile, (percent) => {
        setUploadProgress(percent)
      })

      // 3. Upload Images ZIP
      setUploadStage('images')
      setUploadProgress(0)
      await restoreApi.uploadToS3(images_upload_url, imagesFile, (percent) => {
        setUploadProgress(percent)
      })

      // 4. Iniciar restore
      await restoreApi.start(password || undefined)

      // 5. Cambiar a pantalla de progreso
      onRestoreStarted()
    } catch {
      // El restore es fire-and-forget en el backend: aunque esta request se
      // cancele/falle del lado del cliente (ej. timeout), el backend puede
      // haberla recibido y ya estar restaurando. Antes de mostrar error,
      // confirmamos el estado real con /status en vez de asumir que no pasó nada.
      try {
        const status = await restoreApi.getStatus()
        if (status.status === 'restoring' || status.status === 'completed') {
          onRestoreStarted()
          return
        }
      } catch {
        // Si ni siquiera se pudo consultar el status, cae al error genérico abajo.
      }
      setError(t('uploadError'))
      setIsUploading(false)
      setUploadStage(null)
      submittingRef.current = false
    }
  }

  const manifestSummary = (dbManifest || imagesManifest) && (
    <div className="rounded-md border bg-gray-50 p-3 space-y-1.5">
      <p className="text-xs font-medium text-gray-700 flex items-center gap-1.5">
        <CheckCircle className="h-3.5 w-3.5 text-green-600" />
        {t('restoreManifestValid')}
      </p>
      {dbManifest && (
        <p className="text-xs text-gray-600">
          {t('restoreManifestDb', {
            tables: dbManifest.tableCount ?? 0,
            records: (dbManifest.totalRecords ?? 0).toLocaleString(),
          })}
        </p>
      )}
      {imagesManifest && (
        <p className="text-xs text-gray-600">
          {t('restoreManifestImages', {
            images: imagesManifest.totalImages ?? 0,
            size: formatBytes(imagesManifest.totalSize ?? 0),
          })}
        </p>
      )}
      {dbManifest?.generatedAt && (
        <p className="text-xs text-gray-400">
          {t('restoreManifestGeneratedAt', { date: new Date(dbManifest.generatedAt).toLocaleString() })}
        </p>
      )}
    </div>
  )

  if (isUploading) {
    if (uploadStage === 'validating') {
      return (
        <div className="space-y-4">
          <Alert>
            <FileArchive className="h-4 w-4" />
            <AlertDescription>{t('restoreValidatingFiles')}</AlertDescription>
          </Alert>
          {manifestSummary}
          <div className="flex items-center justify-center py-2">
            <Loader2 className="h-6 w-6 text-blue-600 animate-spin" />
          </div>
          <p className="text-xs text-amber-600 font-medium text-center">
            {t('restoreDoNotClose')}
          </p>
        </div>
      )
    }

    return (
      <div className="space-y-4">
        <Alert>
          <Upload className="h-4 w-4" />
          <AlertDescription>{t('restoreUploading')}</AlertDescription>
        </Alert>

        {manifestSummary}

        <div className="space-y-2">
          <p className="text-sm font-medium text-gray-700">
            {uploadStage === 'db' ? t('restoreUploadingDb') : t('restoreUploadingImages')}
          </p>
          <div className="w-full bg-gray-200 rounded-full h-2.5">
            <div
              className="bg-blue-600 h-2.5 rounded-full transition-all duration-300"
              style={{ width: `${uploadProgress}%` }}
            />
          </div>
          <p className="text-xs text-gray-500 text-right">
            {t('restoreUploadProgress', { percent: uploadProgress })}
          </p>
        </div>

        <p className="text-xs text-amber-600 font-medium text-center">
          {t('restoreDoNotClose')}
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="text-center mb-2">
        <p className="text-sm text-gray-500">{t('restoreDescription')}</p>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* DB ZIP input */}
      <div className="space-y-2">
        <Label>{t('restoreDbFile')}</Label>
        <div className="flex items-center gap-2">
          <label className="flex-1 cursor-pointer">
            <div className="flex items-center gap-2 px-3 py-2 border rounded-md hover:bg-gray-50 text-sm">
              <FileArchive className="h-4 w-4 text-gray-400" />
              <span className={dbFile ? 'text-gray-900' : 'text-gray-400'}>
                {dbFile ? dbFile.name : t('noFileSelected')}
              </span>
            </div>
            <input
              type="file"
              accept=".zip"
              className="hidden"
              onChange={(e) => handleDbFileChange(e.target.files?.[0] || null)}
            />
          </label>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              const input = document.createElement('input')
              input.type = 'file'
              input.accept = '.zip'
              input.onchange = (e) => {
                const file = (e.target as HTMLInputElement).files?.[0]
                if (file) handleDbFileChange(file)
              }
              input.click()
            }}
          >
            {t('selectFile')}
          </Button>
        </div>
      </div>

      {/* Images ZIP input */}
      <div className="space-y-2">
        <Label>{t('restoreImagesFile')}</Label>
        <div className="flex items-center gap-2">
          <label className="flex-1 cursor-pointer">
            <div className="flex items-center gap-2 px-3 py-2 border rounded-md hover:bg-gray-50 text-sm">
              <FileArchive className="h-4 w-4 text-gray-400" />
              <span className={imagesFile ? 'text-gray-900' : 'text-gray-400'}>
                {imagesFile ? imagesFile.name : t('noFileSelected')}
              </span>
            </div>
            <input
              type="file"
              accept=".zip"
              className="hidden"
              onChange={(e) => handleImagesFileChange(e.target.files?.[0] || null)}
            />
          </label>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              const input = document.createElement('input')
              input.type = 'file'
              input.accept = '.zip'
              input.onchange = (e) => {
                const file = (e.target as HTMLInputElement).files?.[0]
                if (file) handleImagesFileChange(file)
              }
              input.click()
            }}
          >
            {t('selectFile')}
          </Button>
        </div>
      </div>

      {/* Password field */}
      <div className="space-y-2">
        <Label htmlFor="restore-password">{t('restorePasswordField')}</Label>
        <Input
          id="restore-password"
          type="password"
          placeholder={t('restorePasswordPlaceholder')}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>

      {/* Restore button */}
      <Button
        className="w-full"
        disabled={!dbFile || !imagesFile}
        onClick={handleRestore}
      >
        {t('restoreBtn')}
      </Button>
    </div>
  )
}

// ============================================================================
// PÁGINA PRINCIPAL DE SETUP
// ============================================================================

export default function SetupPage() {
  const router = useRouter()
  const t = useTranslations('backup')
  const [formData, setFormData] = useState({
    email: '',
    password: '',
    confirmPassword: '',
    full_name: '',
    language: 'en',
  })
  const [isLoading, setIsLoading] = useState(false)
  const [isChecking, setIsChecking] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)
  const [activeTab, setActiveTab] = useState<'create' | 'restore'>('create')
  const [showRestoreProgress, setShowRestoreProgress] = useState(false)

  // Verificar si el sistema ya está inicializado o si hay restore en progreso
  useEffect(() => {
    const controller = new AbortController()

    const checkStatus = async () => {
      try {
        const setupStatus = await setupApi.getStatus(controller.signal)

        if (!setupStatus.needs_setup && !setupStatus.restore_in_progress) {
          router.replace('/login')
          return
        }

        if (setupStatus.restore_in_progress) {
          setShowRestoreProgress(true)
          setIsChecking(false)
          return
        }

        // También verificar estado del restore directamente
        try {
          const restoreStatus = await restoreApi.getStatus()
          if (restoreStatus.status === 'restoring') {
            setShowRestoreProgress(true)
            setIsChecking(false)
            return
          }
        } catch {
          // Si falla, no pasa nada — continuamos normal
        }

        setIsChecking(false)
      } catch {
        // Si falla la verificación, mostrar el formulario
        setIsChecking(false)
      }
    }

    checkStatus()
    return () => controller.abort()
  }, [router])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)

    if (formData.password !== formData.confirmPassword) {
      setError('Passwords do not match')
      return
    }

    if (formData.password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }

    if (formData.password.length > 72) {
      setError('Password cannot exceed 72 characters')
      return
    }

    setIsLoading(true)

    try {
      await setupApi.initialize({
        email: formData.email,
        password: formData.password,
        full_name: formData.full_name,
        language: formData.language,
      })

      setSuccess(true)

      setTimeout(() => {
        router.push('/login')
      }, 2000)
    } catch (error: any) {
      setError(error.detail || 'Error creating administrator account')
      setIsLoading(false)
    }
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setFormData({ ...formData, [e.target.name]: e.target.value })
  }

  // Si hay restore en progreso, mostrar pantalla de progreso
  if (showRestoreProgress) {
    return <RestoreProgressScreen />
  }

  if (success) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
        <Card className="w-full max-w-md">
          <CardContent className="p-6">
            <div className="text-center">
              <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-green-100 mb-4">
                <CheckCircle className="h-6 w-6 text-green-600" />
              </div>
              <h3 className="text-lg font-medium text-gray-900 mb-2">Setup Complete!</h3>
              <p className="text-sm text-gray-500">
                Administrator account created successfully. Redirecting to sign in...
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  if (isChecking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
        <p className="text-gray-500">Verifying system status...</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl font-bold text-center">Initial Setup</CardTitle>
          <CardDescription className="text-center">
            Welcome to AlwaysPrint Cloud Manager. Create the first administrator account or restore from a backup.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Tabs */}
          <div className="flex border-b mb-4">
            <button
              type="button"
              className={`px-4 py-2 text-sm transition-colors ${
                activeTab === 'create'
                  ? 'border-b-2 border-blue-600 font-medium text-blue-600'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
              onClick={() => setActiveTab('create')}
            >
              {t('tabCreateAdmin')}
            </button>
            <button
              type="button"
              className={`px-4 py-2 text-sm transition-colors ${
                activeTab === 'restore'
                  ? 'border-b-2 border-blue-600 font-medium text-blue-600'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
              onClick={() => setActiveTab('restore')}
            >
              {t('tabRestore')}
            </button>
          </div>

          {/* Tab: Create Admin */}
          {activeTab === 'create' && (
            <form onSubmit={handleSubmit} className="space-y-4">
              {error && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}

              <div className="space-y-2">
                <Label htmlFor="full_name">Full Name</Label>
                <Input
                  id="full_name"
                  name="full_name"
                  type="text"
                  placeholder="John Smith"
                  value={formData.full_name}
                  onChange={handleChange}
                  required
                  disabled={isLoading}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="email">Email Address</Label>
                <Input
                  id="email"
                  name="email"
                  type="email"
                  placeholder="admin@example.com"
                  value={formData.email}
                  onChange={handleChange}
                  required
                  disabled={isLoading}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  placeholder="••••••••"
                  value={formData.password}
                  onChange={handleChange}
                  required
                  disabled={isLoading}
                  minLength={8}
                  maxLength={72}
                />
                <p className="text-xs text-gray-500">Between 8 and 72 characters</p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="confirmPassword">Confirm Password</Label>
                <Input
                  id="confirmPassword"
                  name="confirmPassword"
                  type="password"
                  placeholder="••••••••"
                  value={formData.confirmPassword}
                  onChange={handleChange}
                  required
                  disabled={isLoading}
                  minLength={8}
                  maxLength={72}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="language">System Language</Label>
                <select
                  id="language"
                  name="language"
                  value={formData.language}
                  onChange={handleChange}
                  disabled={isLoading}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <option value="en">English</option>
                  <option value="es">Español</option>
                </select>
                <p className="text-xs text-gray-500">
                  Default language for the administrator and new accounts.
                </p>
              </div>

              <Button type="submit" className="w-full" disabled={isLoading}>
                {isLoading ? 'Creating account...' : 'Create Administrator Account'}
              </Button>
            </form>
          )}

          {/* Tab: Restore Backup */}
          {activeTab === 'restore' && (
            <RestoreForm onRestoreStarted={() => setShowRestoreProgress(true)} />
          )}

          <div className="mt-6 text-center text-sm text-gray-500">
            <p>&copy; 2026 Inversiones On Line SAC</p>
            <p className="mt-1">Robles.AI Automation Product Family</p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
