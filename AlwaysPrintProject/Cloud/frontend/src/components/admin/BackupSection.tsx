/**
 * Sección de Backup & Restore para Corporate Admins.
 * Solo visible para usuarios con dominio @robles.ai o @sistemas.com.pe.
 * Permite generar backups del sistema, descargar archivos y eliminar backups existentes.
 */

'use client'

import { useState, useEffect, useCallback } from 'react'
import { useTranslations } from 'next-intl'
import { Database, Download, Trash2, RefreshCw, Loader2, CheckCircle2, XCircle, Lock, AlertTriangle } from 'lucide-react'

import { useAuth } from '@/hooks/useAuth'
import { backupApi, BackupStatusResponse } from '@/lib/api'

// === CONSTANTES ===

const ALLOWED_DOMAINS = ['@robles.ai', '@sistemas.com.pe']
const POLL_INTERVAL = 5000

// === HELPERS ===

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

// === COMPONENTE ===

export function BackupSection() {
  const t = useTranslations('backup')
  const { isAdmin, user } = useAuth()

  const [status, setStatus] = useState<BackupStatusResponse>({ status: 'idle' })
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [initialLoading, setInitialLoading] = useState(true)
  const [factoryResetLoading, setFactoryResetLoading] = useState(false)
  const [resetAcknowledged, setResetAcknowledged] = useState(false)

  // Control de acceso: solo Corporate Admin de dominios autorizados
  const userEmail = user?.email?.toLowerCase() ?? ''
  const isAllowedDomain = ALLOWED_DOMAINS.some(domain => userEmail.endsWith(domain))

  // Fetch de estado actual del backup
  const fetchStatus = useCallback(async () => {
    try {
      const data = await backupApi.getStatus()
      setStatus(data)
    } catch {
      // Silenciar errores de polling
    } finally {
      setInitialLoading(false)
    }
  }, [])

  // Fetch inicial al montar el componente
  useEffect(() => {
    if (isAdmin() && isAllowedDomain) {
      fetchStatus()
    } else {
      setInitialLoading(false)
    }
  }, [isAdmin, isAllowedDomain, fetchStatus])

  // Polling cada 5s mientras el estado es "generating"
  useEffect(() => {
    if (!isAdmin() || !isAllowedDomain || status.status !== 'generating') return
    const interval = setInterval(fetchStatus, POLL_INTERVAL)
    return () => clearInterval(interval)
  }, [isAdmin, isAllowedDomain, status.status, fetchStatus])

  // Resetear checkbox cuando cambia el status del backup
  useEffect(() => {
    setResetAcknowledged(false)
  }, [status.status])

  // Generar backup
  const handleGenerate = async () => {
    setLoading(true)
    try {
      await backupApi.generate(password || undefined)
      setPassword('')
      // Pequeño delay para que el backend actualice el status
      setTimeout(fetchStatus, 1000)
    } catch {
      // El error se reflejará en el status al siguiente polling
    } finally {
      setLoading(false)
    }
  }

  // Descargar archivo
  const handleDownload = async (fileType: 'db' | 'images') => {
    try {
      const data = await backupApi.getDownloadUrl(fileType)
      window.open(data.presigned_url, '_blank')
    } catch {
      // Error silencioso en descarga
    }
  }

  // Eliminar backup
  const handleDelete = async () => {
    if (!confirm(t('deleteConfirmMessage'))) return
    try {
      await backupApi.deleteBackup()
      await fetchStatus()
    } catch {
      // Error silencioso
    }
  }

  // Factory reset — fire-and-forget, redirect inmediato
  const handleFactoryReset = async () => {
    const confirmText = prompt(t('factoryResetConfirmTitle') + '\n\n' + t('factoryResetConfirmMessage') + '\n\n' + t('factoryResetConfirmType'))
    if (confirmText !== 'RESET') return

    setFactoryResetLoading(true)
    try {
      await backupApi.factoryReset()
    } catch {
      // Ignorar errores — el reset ya se disparó o el token ya es inválido
    }
    // Limpiar localStorage y redirigir inmediatamente a setup
    localStorage.removeItem('access_token')
    localStorage.removeItem('user')
    window.location.href = '/setup'
  }

  // No mostrar si no es Corporate Admin con dominio autorizado
  if (!isAdmin() || !isAllowedDomain) return null

  // Loading inicial
  if (initialLoading) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
        <div className="flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
          <span className="text-sm text-gray-500">{t('generating')}</span>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
      {/* Header */}
      <div className="flex items-center gap-2 mb-2">
        <Database className="w-5 h-5 text-blue-600" />
        <h2 className="text-lg font-semibold">{t('title')}</h2>
      </div>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">{t('description')}</p>

      {/* Estado: Idle — Sin backup previo */}
      {status.status === 'idle' && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <span className="w-2 h-2 bg-gray-400 rounded-full" />
            {t('statusIdle')}
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">
              <span className="flex items-center gap-1">
                <Lock className="w-3.5 h-3.5" />
                {t('passwordField')}
              </span>
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t('passwordPlaceholder')}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-700 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
          <button
            onClick={handleGenerate}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-md text-sm font-medium disabled:opacity-50 transition-colors"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Database className="w-4 h-4" />
            )}
            {loading ? t('generating') : t('generateBtn')}
          </button>
        </div>
      )}

      {/* Estado: Generating — Backup en progreso */}
      {status.status === 'generating' && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin text-blue-500" />
            <span className="text-sm font-medium">{status.stage || t('statusGenerating')}</span>
          </div>
          <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2.5">
            <div
              className="bg-blue-600 h-2.5 rounded-full transition-all duration-500"
              style={{ width: `${status.progress || 0}%` }}
            />
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400">{status.progress || 0}%</p>
        </div>
      )}

      {/* Estado: Completed — Backup disponible */}
      {status.status === 'completed' && (
        <div className="space-y-4">
          {/* Información del backup */}
          <div className="p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-md">
            <div className="flex items-center gap-2 mb-1">
              <CheckCircle2 className="w-4 h-4 text-green-600 dark:text-green-400" />
              <span className="text-sm font-medium text-green-700 dark:text-green-400">
                {t('statusCompleted')}
              </span>
            </div>
            <p className="text-xs text-green-600 dark:text-green-500 ml-6">
              {t('generatedAt', { date: status.generated_at ? new Date(status.generated_at).toLocaleString() : '' })}
            </p>
            <p className="text-xs text-green-600 dark:text-green-500 ml-6">
              {t('hasPassword', { value: status.has_password ? t('hasPasswordYes') : t('hasPasswordNo') })}
            </p>
          </div>

          {/* Botones de descarga */}
          <div className="flex flex-col sm:flex-row gap-2">
            <button
              onClick={() => handleDownload('db')}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-md text-sm font-medium transition-colors"
            >
              <Download className="w-4 h-4" />
              {t('downloadDb')} ({formatBytes(status.db_zip_size || 0)})
            </button>
            <button
              onClick={() => handleDownload('images')}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-md text-sm font-medium transition-colors"
            >
              <Download className="w-4 h-4" />
              {t('downloadImages')} ({formatBytes(status.images_zip_size || 0)})
            </button>
          </div>

          {/* Acciones adicionales */}
          <div className="flex gap-2 pt-2 border-t border-gray-200 dark:border-gray-700">
            <button
              onClick={handleGenerate}
              disabled={loading}
              className="flex items-center gap-2 px-3 py-1.5 bg-gray-100 hover:bg-gray-200 dark:bg-gray-700 dark:hover:bg-gray-600 rounded-md text-sm transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              {t('generateNew')}
            </button>
            <button
              onClick={handleDelete}
              className="flex items-center gap-2 px-3 py-1.5 bg-red-50 hover:bg-red-100 dark:bg-red-900/20 dark:hover:bg-red-900/40 text-red-600 dark:text-red-400 rounded-md text-sm transition-colors"
            >
              <Trash2 className="w-3.5 h-3.5" />
              {t('deleteBtn')}
            </button>
          </div>
        </div>
      )}

      {/* Estado: Failed — Error en generación */}
      {status.status === 'failed' && (
        <div className="space-y-3">
          <div className="p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-md">
            <div className="flex items-center gap-2 mb-1">
              <XCircle className="w-4 h-4 text-red-600 dark:text-red-400" />
              <span className="text-sm font-medium text-red-700 dark:text-red-400">
                {t('statusFailed')}
              </span>
            </div>
            {status.error && (
              <p className="text-xs text-red-600 dark:text-red-500 ml-6">{status.error}</p>
            )}
          </div>
          <button
            onClick={handleGenerate}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-md text-sm font-medium disabled:opacity-50 transition-colors"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <RefreshCw className="w-4 h-4" />
            )}
            {t('errorRetry')}
          </button>
        </div>
      )}

      {/* Factory Reset — siempre visible para Corporate Admin */}
      <div className="mt-6 pt-4 border-t border-red-200 dark:border-red-800">
        <div className="flex items-center gap-2 mb-3">
          <AlertTriangle className="w-4 h-4 text-red-600" />
          <span className="text-sm font-semibold text-red-700 dark:text-red-400">{t('factoryResetConfirmTitle')}</span>
        </div>

        {/* Caso: Backup disponible → ofrecer descarga */}
        {status.status === 'completed' && (
          <div className="mb-3 space-y-2">
            <p className="text-xs text-gray-600 dark:text-gray-400">{t('factoryResetBackupAvailable')}</p>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => handleDownload('db')}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 hover:bg-blue-100 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400 rounded-md text-xs font-medium transition-colors"
              >
                <Download className="w-3.5 h-3.5" />
                {t('downloadDb')} ({formatBytes(status.db_zip_size || 0)})
              </button>
              <button
                onClick={() => handleDownload('images')}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 hover:bg-blue-100 dark:bg-blue-900/20 text-blue-700 dark:text-blue-400 rounded-md text-xs font-medium transition-colors"
              >
                <Download className="w-3.5 h-3.5" />
                {t('downloadImages')} ({formatBytes(status.images_zip_size || 0)})
              </button>
            </div>
          </div>
        )}

        {/* Caso: No hay backup → advertencia */}
        {status.status !== 'completed' && status.status !== 'generating' && (
          <div className="mb-3">
            <p className="text-xs text-amber-700 dark:text-amber-400">{t('factoryResetNoBackup')}</p>
          </div>
        )}

        {/* Checkbox de confirmación */}
        {status.status !== 'generating' && (
          <label className="flex items-start gap-2 mb-3 cursor-pointer">
            <input
              type="checkbox"
              checked={resetAcknowledged}
              onChange={(e) => setResetAcknowledged(e.target.checked)}
              className="mt-0.5 w-4 h-4 rounded border-gray-300 text-red-600 focus:ring-red-500"
            />
            <span className="text-xs text-gray-700 dark:text-gray-300">
              {status.status === 'completed'
                ? t('factoryResetCheckboxWithBackup')
                : t('factoryResetCheckboxNoBackup')
              }
            </span>
          </label>
        )}

        {/* Botón de Factory Reset */}
        <button
          onClick={handleFactoryReset}
          disabled={!resetAcknowledged || factoryResetLoading || status.status === 'generating'}
          className="flex items-center gap-2 px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white rounded-md text-xs font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {factoryResetLoading ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <AlertTriangle className="w-3.5 h-3.5" />
          )}
          {t('factoryResetBtn')}
        </button>
      </div>
    </div>
  )
}
