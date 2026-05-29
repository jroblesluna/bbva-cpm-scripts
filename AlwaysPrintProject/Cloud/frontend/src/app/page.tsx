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

  // Mostrar error cuando el backend no está disponible
  if (backendError) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center max-w-md">
          <div className="mx-auto h-16 w-16 text-red-500 mb-4">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-gray-900 mb-2">Servicio no disponible</h2>
          <p className="text-gray-600 mb-6">
            No se pudo conectar con el servidor. El servicio puede estar reiniciándose o en mantenimiento.
          </p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors"
          >
            Reintentar
          </button>
        </div>
      </div>
    )
  }

  return null
}
