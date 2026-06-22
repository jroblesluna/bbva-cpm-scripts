/**
 * Página de login.
 */

'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import Image from 'next/image'
import { useAuth } from '@/hooks/useAuth'
import { useTranslations } from 'next-intl'
import { setupApi } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'

export default function LoginPage() {
  const router = useRouter()
  const { login, isLoading, error } = useAuth()
  const t = useTranslations('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isCheckingSetup, setIsCheckingSetup] = useState(true)

  // Verificar si el sistema necesita setup
  useEffect(() => {
    let cancelled = false

    const checkSetup = async () => {
      try {
        // Timeout corto para no bloquear la UI si el backend no responde
        const controller = new AbortController()
        const timeoutId = setTimeout(() => controller.abort(), 5000)

        const status = await setupApi.getStatus(controller.signal)
        clearTimeout(timeoutId)

        if (cancelled) return

        if (status.needs_setup) {
          // Redirigir a setup si no hay usuarios
          router.push('/setup')
        } else {
          setIsCheckingSetup(false)
        }
      } catch (error: unknown) {
        if (cancelled) return
        // Si falla (timeout, red, backend caído), mostrar login igualmente
        console.error('Error al verificar setup:', error)
        setIsCheckingSetup(false)
      }
    }

    checkSetup()

    return () => {
      cancelled = true
    }
  }, [router])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    try {
      await login({ email, password })
    } catch (error: any) {
      if (process.env.NODE_ENV === 'development' && error?.status !== 401 && error?.status !== 422) {
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
          <p className="mt-4 text-gray-600">{t('verifying')}</p>
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
            {t('title')}
          </CardTitle>
          <CardDescription className="text-center">
            {t('subtitle')}
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
              <Label htmlFor="email">{t('email')}</Label>
              <Input
                id="email"
                type="email"
                placeholder={t('emailPlaceholder')}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                disabled={isLoading}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">{t('password')}</Label>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
                disabled={isLoading}
              />
            </div>

            <Button type="submit" className="w-full" disabled={isLoading}>
              {isLoading ? t('submitting') : t('submit')}
            </Button>

            <p className="text-center text-sm text-gray-500">
              <Link href="/forgot-password" className="text-blue-600 hover:underline">
                {t('forgotPassword')}
              </Link>
            </p>
          </form>

          <div className="mt-6 text-center text-sm text-gray-500">
            <p>{t('footer1')}</p>
            <p className="mt-1">{t('footer2')}</p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
