/**
 * Página 404 - Ruta no encontrada
 * 
 * Redirige automáticamente a la raíz en lugar de mostrar un error.
 */

'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export default function NotFound() {
  const router = useRouter()

  useEffect(() => {
    // Redirigir a la raíz automáticamente
    router.push('/')
  }, [router])

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center">
        <h1 className="text-4xl font-bold text-gray-900 mb-4">404</h1>
        <p className="text-gray-600 mb-4">Página no encontrada</p>
        <p className="text-sm text-gray-500">Redirigiendo...</p>
      </div>
    </div>
  )
}
