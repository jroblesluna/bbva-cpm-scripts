/**
 * Página principal - Redirige a setup o dashboard según el estado del sistema.
 */

'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { setupApi } from '@/lib/api'

export default function Home() {
  const router = useRouter()
  const [isChecking, setIsChecking] = useState(true)
  const [backendError, setBackendError] = useState(false)

  useEffect(() => {
    const checkSetupStatus = async () => {
      try {
        const status = await setupApi.getStatus()
        
        if (status.needs_setup) {
          // Si necesita setup, redirigir a /setup
          router.push('/setup')
        } else {
          // Si ya está configurado, redirigir a /dashboard
          router.push('/dashboard')
        }
      } catch (error: unknown) {
        console.error('Error al verificar estado de setup:', error)
        // Distinguir entre error de red (backend caído) y respuesta del backend
        const isNetworkError =
          error instanceof Error &&
          ('code' in error || error.message === 'Network Error' || error.message.includes('ECONNREFUSED'))
        const responseStatus = (error as { response?: { status?: number } })?.response?.status

        if (isNetworkError || !responseStatus) {
          // Backend no disponible: mostrar error, NO redirigir a setup
          setBackendError(true)
          setIsChecking(false)
          return
        }
        // Si el backend respondió con error (ej: 500), también es error de backend
        setBackendError(true)
      } finally {
        setIsChecking(false)
      }
    }

    checkSetupStatus()
  }, [router])

  // Mostrar loading mientras verifica
  if (isChecking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Verificando configuración...</p>
        </div>
      </div>
    )
  }

  // Mostrar error cuando el backend no está disponible — redirigir a /maintenance
  if (backendError) {
    if (typeof window !== 'undefined') {
      window.location.href = '/maintenance'
    }
    return null
  }

  return null
}
