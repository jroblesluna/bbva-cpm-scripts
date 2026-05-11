/**
 * Layout del dashboard con navegación y protección de rutas.
 */

'use client'

import { useEffect } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import Image from 'next/image'
import { useAuth } from '@/hooks/useAuth'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { LanguageSelector } from '@/components/LanguageSelector'
import {
  LayoutDashboard,
  Monitor,
  Network,
  Settings,
  MessageSquare,
  FileText,
  Users,
  Building2,
  LogOut,
  Menu,
  X,
  Globe,
} from 'lucide-react'
import { useState } from 'react'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const { user, isAuthenticated, isLoading, logout, isAdmin } = useAuth()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const t = useTranslations('nav')

  const navigation = [
    { key: 'dashboard', href: '/dashboard', icon: LayoutDashboard },
    { key: 'workstations', href: '/dashboard/workstations', icon: Monitor },
    { key: 'vlans', href: '/dashboard/vlans', icon: Network },
    { key: 'config', href: '/dashboard/config', icon: Settings },
    { key: 'messages', href: '/dashboard/messages', icon: MessageSquare },
    { key: 'audit', href: '/dashboard/audit', icon: FileText },
    { key: 'accounts', href: '/dashboard/admin/accounts', icon: Building2, adminOnly: true },
    { key: 'users', href: '/dashboard/admin/users', icon: Users, adminOnly: true },
    { key: 'pendingIps', href: '/dashboard/admin/pending-ips', icon: Globe, adminOnly: true },
  ]

  // Redirigir a login si no está autenticado
  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login')
    }
  }, [isAuthenticated, isLoading, router])

  // Mostrar loading mientras verifica autenticación
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">{t('loading')}</p>
        </div>
      </div>
    )
  }

  // No mostrar nada si no está autenticado (se redirigirá)
  if (!isAuthenticated) {
    return null
  }

  // Filtrar navegación según rol
  const filteredNavigation = navigation.filter((item) => {
    if (item.adminOnly) {
      return isAdmin()
    }
    return true
  })

  const roleLabel = user?.role === 'admin' ? t('admin') : t('operator')

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Sidebar móvil */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="fixed inset-0 bg-gray-900/80" onClick={() => setSidebarOpen(false)} />
          <div className="fixed inset-y-0 left-0 w-64 bg-white shadow-xl flex flex-col">
            <div className="flex h-16 items-center justify-between px-4 border-b">
              <div className="flex items-center space-x-2">
                <Image
                  src="/alwaysprint-logo.png"
                  alt="AlwaysPrint"
                  width={32}
                  height={32}
                  className="rounded"
                />
                <h1 className="text-xl font-bold text-gray-900">AlwaysPrint</h1>
              </div>
              <button onClick={() => setSidebarOpen(false)}>
                <X className="h-6 w-6 text-gray-500" />
              </button>
            </div>
            <nav className="flex-1 space-y-1 px-2 py-4 overflow-y-auto">
              {filteredNavigation.map((item) => {
                const isActive = pathname === item.href
                return (
                  <Link
                    key={item.key}
                    href={item.href}
                    onClick={() => setSidebarOpen(false)}
                    className={`flex items-center px-3 py-2 text-sm font-medium rounded-md ${
                      isActive
                        ? 'bg-blue-50 text-blue-600'
                        : 'text-gray-700 hover:bg-gray-50 hover:text-gray-900'
                    }`}
                  >
                    <item.icon className="mr-3 h-5 w-5" />
                    {t(item.key as any)}
                  </Link>
                )
              })}
            </nav>
            {/* Información de usuario y logout en móvil */}
            <div className="flex-shrink-0 border-t border-gray-200 p-4">
              <div className="flex items-center mb-3">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900 truncate">{user?.full_name}</p>
                  <p className="text-xs text-gray-500 truncate">{user?.email}</p>
                  <Badge variant="secondary" className="mt-1">
                    {roleLabel}
                  </Badge>
                </div>
              </div>
              <div className="flex items-center gap-2 mb-2">
                <LanguageSelector />
              </div>
              <Button
                variant="outline"
                size="sm"
                className="w-full"
                onClick={() => {
                  setSidebarOpen(false)
                  logout()
                }}
              >
                <LogOut className="mr-2 h-4 w-4" />
                {t('logout')}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Sidebar desktop */}
      <div className="hidden lg:fixed lg:inset-y-0 lg:flex lg:w-64 lg:flex-col">
        <div className="flex flex-col flex-grow bg-white border-r border-gray-200">
          <div className="flex h-16 items-center px-4 border-b">
            <div className="flex items-center space-x-2">
              <Image
                src="/alwaysprint-logo.png"
                alt="AlwaysPrint"
                width={32}
                height={32}
                className="rounded"
              />
              <h1 className="text-xl font-bold text-gray-900">AlwaysPrint</h1>
            </div>
          </div>
          <nav className="flex-1 space-y-1 px-2 py-4">
            {filteredNavigation.map((item) => {
              const isActive = pathname === item.href
              return (
                <Link
                  key={item.key}
                  href={item.href}
                  className={`flex items-center px-3 py-2 text-sm font-medium rounded-md ${
                    isActive
                      ? 'bg-blue-50 text-blue-600'
                      : 'text-gray-700 hover:bg-gray-50 hover:text-gray-900'
                  }`}
                >
                  <item.icon className="mr-3 h-5 w-5" />
                  {t(item.key as any)}
                </Link>
              )
            })}
          </nav>
          <div className="flex-shrink-0 border-t border-gray-200 p-4">
            <div className="flex items-center mb-2">
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900 truncate">{user?.full_name}</p>
                <p className="text-xs text-gray-500 truncate">{user?.email}</p>
                <Badge variant="secondary" className="mt-1">
                  {roleLabel}
                </Badge>
              </div>
            </div>
            <div className="mb-2">
              <LanguageSelector />
            </div>
            <Button
              variant="outline"
              size="sm"
              className="w-full mt-1"
              onClick={logout}
            >
              <LogOut className="mr-2 h-4 w-4" />
              {t('logout')}
            </Button>
          </div>
        </div>
      </div>

      {/* Contenido principal */}
      <div className="lg:pl-64">
        {/* Header móvil */}
        <div className="sticky top-0 z-40 flex h-16 items-center gap-x-4 border-b border-gray-200 bg-white px-4 shadow-sm lg:hidden">
          <button onClick={() => setSidebarOpen(true)}>
            <Menu className="h-6 w-6 text-gray-500" />
          </button>
          <div className="flex items-center space-x-2">
            <Image
              src="/alwaysprint-logo.png"
              alt="AlwaysPrint"
              width={24}
              height={24}
              className="rounded"
            />
            <h1 className="text-lg font-semibold text-gray-900">AlwaysPrint</h1>
          </div>
        </div>

        {/* Contenido */}
        <main className="py-8 px-4 sm:px-6 lg:px-8">{children}</main>
      </div>
    </div>
  )
}
