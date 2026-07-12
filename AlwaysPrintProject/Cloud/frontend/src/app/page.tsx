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
      // Reintentar hasta 3 veces con 2s entre intentos antes de declarar backend caído.
      // Evita redirecciones falsas a /maintenance por blips transitorios (502, timeout).
      let lastError: unknown = null
      for (let attempt = 1; attempt <= 3; attempt++) {
        try {
          const status = await setupApi.getStatus()
          
          if (status.needs_setup) {
            router.push('/setup')
          } else {
            router.push('/dashboard')
          }
          return
        } catch (error: unknown) {
          lastError = error
          if (attempt < 3) {
            await new Promise(resolve => setTimeout(resolve, 2000))
          }
        }
      }

      // 3 intentos fallidos — ahora sí es un problema real
      console.error('Backend no disponible después de 3 intentos:', lastError)
      const isNetworkError =
        lastError instanceof Error &&
        ('code' in lastError || lastError.message === 'Network Error' || lastError.message.includes('ECONNREFUSED'))
      const responseStatus = (lastError as { response?: { status?: number } })?.response?.status

      if (isNetworkError || !responseStatus) {
        setBackendError(true)
      } else {
        setBackendError(true)
      }
      setIsChecking(false)
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
