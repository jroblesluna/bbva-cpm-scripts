'use client'

import { useEffect, useState } from 'react'
import { RefreshCw, Server } from 'lucide-react'

/**
 * Página de mantenimiento.
 * Verifica primero si el backend realmente está caído.
 * Si responde OK, redirige al dashboard inmediatamente.
 * Si no responde, muestra la pantalla de mantenimiento con auto-retry.
 */
export default function MaintenancePage() {
  const [checking, setChecking] = useState(true)
  const [backendDown, setBackendDown] = useState(false)

  const checkBackend = async () => {
    try {
      const resp = await fetch(`${process.env.NEXT_PUBLIC_API_URL || ''}/api/v1/health`, {
        method: 'GET',
        signal: AbortSignal.timeout(5000),
      })
      if (resp.ok) {
        window.location.href = '/dashboard'
        return
      }
    } catch {
      // No responde
    }
    setBackendDown(true)
    setChecking(false)
  }

  useEffect(() => {
    checkBackend()
    const interval = setInterval(checkBackend, 10000)
    return () => clearInterval(interval)
  }, [])

  if (checking && !backendDown) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Verificando estado del servicio...</p>
        </div>
      </div>
    )
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
          El servidor está reiniciándose o en mantenimiento.
          Se reconectará automáticamente cuando esté disponible.
        </p>
        <button
          onClick={() => { setChecking(true); checkBackend() }}
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
