'use client'

import { useEffect, useState } from 'react'
import { RefreshCw, Server } from 'lucide-react'
import { apiClient } from '@/lib/api'

/**
 * Página de mantenimiento.
 * Se muestra cuando el backend no está disponible (network error, 502, 503).
 * Verifica periódicamente si el backend vuelve y redirige automáticamente.
 */
export default function MaintenancePage() {
  const [checking, setChecking] = useState(false)

  useEffect(() => {
    // Verificar cada 10 segundos si el backend volvió
    const interval = setInterval(async () => {
      try {
        setChecking(true)
        const resp = await fetch(`${process.env.NEXT_PUBLIC_API_URL || ''}/api/v1/health`, {
          method: 'GET',
          signal: AbortSignal.timeout(5000),
        })
        if (resp.ok) {
          // Backend disponible — volver al dashboard
          window.location.href = '/dashboard'
        }
      } catch {
        // Sigue sin responder
      } finally {
        setChecking(false)
      }
    }, 10000)

    return () => clearInterval(interval)
  }, [])

  const handleRetry = async () => {
    setChecking(true)
    try {
      const resp = await fetch(`${process.env.NEXT_PUBLIC_API_URL || ''}/api/v1/health`, {
        method: 'GET',
        signal: AbortSignal.timeout(5000),
      })
      if (resp.ok) {
        window.location.href = '/dashboard'
      }
    } catch {
      // Sigue sin responder
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center max-w-md mx-auto p-8">
        <div className="mx-auto w-16 h-16 bg-amber-100 rounded-full flex items-center justify-center mb-6">
          <Server className="w-8 h-8 text-amber-600" />
        </div>
        <h1 className="text-2xl font-bold text-gray-900 mb-2">
          Servicio en mantenimiento
        </h1>
        <p className="text-gray-600 mb-6">
          El servidor está reiniciándose o en mantenimiento. Se reconectará automáticamente cuando esté disponible.
        </p>
        <button
          onClick={handleRetry}
          disabled={checking}
          className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${checking ? 'animate-spin' : ''}`} />
          {checking ? 'Verificando...' : 'Reintentar ahora'}
        </button>
        <p className="mt-4 text-xs text-gray-400">
          Verificando automáticamente cada 10 segundos...
        </p>
      </div>
    </div>
  )
}
