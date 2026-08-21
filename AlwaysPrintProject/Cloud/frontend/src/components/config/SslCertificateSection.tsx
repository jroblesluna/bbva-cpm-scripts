/**
 * Sección de estado y renovación de certificado SSL en System Configuration.
 * Solo visible para Corporate Admins (@robles.ai, @sistemas.com.pe).
 */

'use client'

import { useState, useEffect } from 'react'
import { useTranslations } from 'next-intl'
import { Shield, RefreshCw, Loader2, AlertTriangle, CheckCircle2, XCircle } from 'lucide-react'

import { useAuth } from '@/hooks/useAuth'
import apiClient from '@/lib/api'

// === CONSTANTES ===

const ALLOWED_DOMAINS = ['@robles.ai', '@sistemas.com.pe']

interface SslStatus {
  domain: string
  issuer: string | null
  not_before: string | null
  not_after: string | null
  days_remaining: number | null
  status: 'valid' | 'expiring_soon' | 'expired' | 'error'
  message: string
}

// === COMPONENTE ===

export function SslCertificateSection() {
  const t = useTranslations('sslCertificate')
  const { isAdmin, user } = useAuth()

  const [sslStatus, setSslStatus] = useState<SslStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [renewing, setRenewing] = useState(false)
  const [renewResult, setRenewResult] = useState<{ success: boolean; message: string } | null>(null)

  // Control de acceso
  const userEmail = user?.email?.toLowerCase() ?? ''
  const isAllowedDomain = ALLOWED_DOMAINS.some(domain => userEmail.endsWith(domain))

  // Fetch del estado SSL
  const fetchStatus = async () => {
    setLoading(true)
    try {
      const response = await apiClient.get('/admin/ssl/status')
      setSslStatus(response.data)
    } catch {
      setSslStatus(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (isAdmin() && isAllowedDomain) {
      fetchStatus()
    }
  }, [])

  // Renovar certificado
  const handleRenew = async () => {
    setRenewing(true)
    setRenewResult(null)
    try {
      const response = await apiClient.post('/admin/ssl/renew')
      setRenewResult({ success: response.data.success, message: response.data.message })
      if (response.data.success) {
        fetchStatus()
      }
    } catch {
      setRenewResult({ success: false, message: t('renewError') })
    } finally {
      setRenewing(false)
    }
  }

  if (!isAdmin() || !isAllowedDomain) {
    return null
  }

  const statusConfig = {
    valid: { icon: CheckCircle2, color: 'text-green-600', bg: 'bg-green-50 border-green-200', badge: 'bg-green-100 text-green-800' },
    expiring_soon: { icon: AlertTriangle, color: 'text-amber-600', bg: 'bg-amber-50 border-amber-200', badge: 'bg-amber-100 text-amber-800' },
    expired: { icon: XCircle, color: 'text-red-600', bg: 'bg-red-50 border-red-200', badge: 'bg-red-100 text-red-800' },
    error: { icon: XCircle, color: 'text-gray-600', bg: 'bg-gray-50 border-gray-200', badge: 'bg-gray-100 text-gray-800' },
  }

  const config = sslStatus ? statusConfig[sslStatus.status] : statusConfig.error
  const StatusIcon = config.icon

  return (
    <div className="bg-white rounded-lg shadow p-6 space-y-4">
      {/* Encabezado */}
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-3">
          <Shield className="w-6 h-6 text-blue-600 mt-0.5" />
          <div>
            <h2 className="text-xl font-semibold text-gray-900">{t('title')}</h2>
            <p className="mt-1 text-sm text-gray-600">{t('description')}</p>
          </div>
        </div>
        {/* Botón renovar */}
        <button
          onClick={handleRenew}
          disabled={renewing || loading}
          className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            renewing || loading
              ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
              : 'bg-blue-600 text-white hover:bg-blue-700'
          }`}
        >
          {renewing ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              {t('renewing')}
            </>
          ) : (
            <>
              <RefreshCw className="w-4 h-4" />
              {t('renewButton')}
            </>
          )}
        </button>
      </div>

      {/* Estado */}
      {loading ? (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 className="w-4 h-4 animate-spin" />
          {t('loading')}
        </div>
      ) : sslStatus ? (
        <div className={`p-4 rounded-lg border ${config.bg}`}>
          <div className="flex items-center gap-3 mb-3">
            <StatusIcon className={`w-5 h-5 ${config.color}`} />
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${config.badge}`}>
              {t(`status.${sslStatus.status === 'expiring_soon' ? 'expiringSync' : sslStatus.status}`)}
            </span>
            <span className="text-sm text-gray-700">{sslStatus.message}</span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-gray-500 block">{t('domain')}</span>
              <span className="font-mono text-gray-900">{sslStatus.domain}</span>
            </div>
            <div>
              <span className="text-gray-500 block">{t('issuer')}</span>
              <span className="text-gray-900">{sslStatus.issuer || '—'}</span>
            </div>
            <div>
              <span className="text-gray-500 block">{t('expiresOn')}</span>
              <span className="text-gray-900">
                {sslStatus.not_after ? new Date(sslStatus.not_after).toLocaleDateString() : '—'}
              </span>
            </div>
            <div>
              <span className="text-gray-500 block">{t('daysRemaining')}</span>
              <span className={`font-semibold ${
                (sslStatus.days_remaining ?? 0) < 14 ? 'text-red-600' : 'text-green-600'
              }`}>
                {sslStatus.days_remaining ?? '—'}
              </span>
            </div>
          </div>
        </div>
      ) : (
        <p className="text-sm text-red-600">{t('renewError')}</p>
      )}

      {/* Resultado de renovación */}
      {renewResult && (
        <div className={`p-3 rounded-md text-sm ${
          renewResult.success ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'
        }`}>
          {renewResult.message}
        </div>
      )}
    </div>
  )
}
