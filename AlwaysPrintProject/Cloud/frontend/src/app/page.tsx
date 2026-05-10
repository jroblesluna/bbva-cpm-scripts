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
      } catch (error) {
        console.error('Error al verificar estado de setup:', error)
        // En caso de error, asumir que necesita setup
        router.push('/setup')
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

  return null
}
