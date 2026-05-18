/**
 * Página mostrada cuando un operador/readonly no tiene organización asignada.
 * El administrador debe asignarle una cuenta antes de poder usar la plataforma.
 */

'use client'

import { useAuth } from '@/hooks/useAuth'
import { Button } from '@/components/ui/button'
import { Building2, LogOut, AlertCircle } from 'lucide-react'

export default function NoAccountPage() {
  const { user, logout } = useAuth()

  return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="max-w-md w-full text-center space-y-6">
        <div className="mx-auto w-16 h-16 bg-yellow-100 rounded-full flex items-center justify-center">
          <Building2 className="h-8 w-8 text-yellow-600" />
        </div>

        <div className="space-y-2">
          <h1 className="text-2xl font-bold text-gray-900">
            Organización no asignada
          </h1>
          <p className="text-gray-600">
            Tu cuenta <span className="font-medium">{user?.email}</span> no tiene una organización asignada.
          </p>
        </div>

        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-yellow-600 flex-shrink-0 mt-0.5" />
            <div className="text-left text-sm text-yellow-800">
              <p className="font-medium mb-1">¿Qué hacer?</p>
              <p>
                Contacta al administrador del sistema para que te asigne una organización.
                Sin esta asignación no es posible acceder a las funcionalidades de la plataforma.
              </p>
            </div>
          </div>
        </div>

        <Button variant="outline" onClick={logout} className="mt-4">
          <LogOut className="mr-2 h-4 w-4" />
          Cerrar sesión
        </Button>
      </div>
    </div>
  )
}
