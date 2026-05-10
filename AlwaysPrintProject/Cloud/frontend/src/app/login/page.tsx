/**
 * Página de login.
 */

'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import Image from 'next/image'
import { useAuth } from '@/hooks/useAuth'
import { setupApi } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'

export default function LoginPage() {
  const router = useRouter()
  const { login, isLoading, error } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isCheckingSetup, setIsCheckingSetup] = useState(true)

  // Verificar si el sistema necesita setup
  useEffect(() => {
    const checkSetup = async () => {
      try {
        const status = await setupApi.getStatus()
        if (status.needs_setup) {
          // Redirigir a setup si no hay usuarios
          router.push('/setup')
        } else {
          setIsCheckingSetup(false)
        }
      } catch (error) {
        console.error('Error al verificar setup:', error)
        setIsCheckingSetup(false)
      }
    }

    checkSetup()
  }, [router])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    try {
      await login({ email, password })
      // La redirección se maneja en el hook useAuth
    } catch (error: any) {
      // El error ya se maneja en el hook useAuth y se muestra en el Alert
      // Solo logueamos errores inesperados (no 401)
      if (process.env.NODE_ENV === 'development' && error?.status !== 401) {
        console.error('Error inesperado en login:', error)
      }
    }
  }

  // Mostrar loading mientras verifica setup
  if (isCheckingSetup) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Verificando configuración...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <div className="flex justify-center mb-4">
            <Image
              src="/alwaysprint-logo.png"
              alt="AlwaysPrint"
              width={80}
              height={80}
              className="rounded-lg"
            />
          </div>
          <CardTitle className="text-2xl font-bold text-center">
            AlwaysPrint Cloud Manager
          </CardTitle>
          <CardDescription className="text-center">
            Ingresa tus credenciales para acceder al sistema
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <div className="space-y-2">
              <Label htmlFor="email">Correo electrónico</Label>
              <Input
                id="email"
                type="email"
                placeholder="usuario@ejemplo.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                disabled={isLoading}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">Contraseña</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={isLoading}
              />
            </div>

            <Button type="submit" className="w-full" disabled={isLoading}>
              {isLoading ? 'Iniciando sesión...' : 'Iniciar sesión'}
            </Button>
          </form>

          <div className="mt-6 text-center text-sm text-gray-500">
            <p>© 2026 Inversiones On Line SAC</p>
            <p className="mt-1">Producto de la familia de automatización Robles.AI</p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
