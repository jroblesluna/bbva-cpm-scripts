/**
 * Layout del dashboard con navegación agrupada y protección de rutas.
 */

'use client'

import { useEffect, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import Image from 'next/image'
import { useAuth } from '@/hooks/useAuth'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { LanguageSelector } from '@/components/LanguageSelector'
import { BuildInfo } from '@/components/BuildInfo'
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
  Activity,
  Wifi,
  Download,
  Printer,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'

// Definición de items de navegación
interface NavItem {
  key: string
  href: string
  icon: React.ComponentType<{ className?: string }>
  adminOnly?: boolean
  subLabel?: string // Sub-encabezado dentro del grupo
}

// Definición de grupos de navegación
interface NavGroup {
  labelKey: string | null // null = sin grupo (top-level)
  items: NavItem[]
  adminOnly?: boolean
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const { user, isAuthenticated, isLoading, logout, isAdmin } = useAuth()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const t = useTranslations('nav')

  // Grupos de navegación
  const navGroups: NavGroup[] = [
    {
      labelKey: null,
      items: [
        { key: 'dashboard', href: '/dashboard', icon: LayoutDashboard },
      ],
    },
    {
      labelKey: 'groupAdmin',
      adminOnly: true,
      items: [
        { key: 'accounts', href: '/dashboard/admin/organizations', icon: Building2, adminOnly: true, subLabel: 'subInfrastructure' },
        { key: 'vlans', href: '/dashboard/vlans', icon: Network, subLabel: 'subInfrastructure' },
        { key: 'workstations', href: '/dashboard/workstations', icon: Monitor, subLabel: 'subInfrastructure' },
        { key: 'pendingIps', href: '/dashboard/admin/pending-ips', icon: Globe, adminOnly: true, subLabel: 'subRequests' },
        { key: 'devices', href: '/dashboard/devices', icon: Printer, subLabel: 'subResources' },
      ],
    },
    {
      labelKey: 'groupMonitoring',
      items: [
        { key: 'telemetry', href: '/dashboard/telemetry', icon: Activity },
        { key: 'connectivity', href: '/dashboard/connectivity', icon: Wifi },
        { key: 'audit', href: '/dashboard/audit', icon: FileText },
        { key: 'messages', href: '/dashboard/messages', icon: MessageSquare },
      ],
    },
    {
      labelKey: 'groupSystem',
      adminOnly: true,
      items: [
        { key: 'users', href: '/dashboard/admin/users', icon: Users, adminOnly: true },
        { key: 'updates', href: '/dashboard/admin/updates', icon: Download, adminOnly: true },
        { key: 'config', href: '/dashboard/config', icon: Settings },
      ],
    },
  ]

  // Filtrar grupos según rol
  const filteredGroups = navGroups
    .filter((group) => !group.adminOnly || isAdmin())
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => !item.adminOnly || isAdmin()),
    }))
    .filter((group) => group.items.length > 0)

  // Estado de expansión de grupos (Administración y Sistema expandidos por defecto)
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {}
    navGroups.forEach((group) => {
      if (group.labelKey) {
        initial[group.labelKey] = group.labelKey === 'groupAdmin' || group.labelKey === 'groupSystem'
      }
    })
    return initial
  })

  // Auto-expandir grupo si contiene la ruta activa
  useEffect(() => {
    filteredGroups.forEach((group) => {
      if (group.labelKey && group.items.some((item) => pathname === item.href)) {
        setExpandedGroups((prev) => ({ ...prev, [group.labelKey!]: true }))
      }
    })
  }, [pathname]) // eslint-disable-line react-hooks/exhaustive-deps

  const toggleGroup = (labelKey: string) => {
    setExpandedGroups((prev) => ({ ...prev, [labelKey]: !prev[labelKey] }))
  }

  // Redirigir a login si no está autenticado
  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.push('/login')
    }
  }, [isAuthenticated, isLoading, router])

  // Redirigir a /no-account si es operador/readonly sin organización asignada
  useEffect(() => {
    if (!isLoading && isAuthenticated && user) {
      const needsAccount = user.role !== 'admin' && !user.organization_id
      const isOnNoAccountPage = pathname === '/dashboard/no-organization'

      if (needsAccount && !isOnNoAccountPage) {
        router.push('/dashboard/no-organization')
      } else if (!needsAccount && isOnNoAccountPage) {
        router.push('/dashboard')
      }
    }
  }, [isLoading, isAuthenticated, user, pathname, router])

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

  const roleLabel = user?.role === 'admin' ? t('admin') : t('operator')

  // Componente reutilizable para renderizar la navegación agrupada
  const renderNavGroups = (onItemClick?: () => void) => (
    <>
      {filteredGroups.map((group, groupIdx) => {
        // Items sin grupo (top-level, ej: Dashboard)
        if (!group.labelKey) {
          return (
            <div key={`group-${groupIdx}`}>
              {group.items.map((item) => {
                const isActive = pathname === item.href
                return (
                  <Link
                    key={item.key}
                    href={item.href}
                    onClick={onItemClick}
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
            </div>
          )
        }

        // Grupos con label colapsable
        const isExpanded = expandedGroups[group.labelKey] ?? true
        return (
          <div key={`group-${groupIdx}`} className="mt-3">
            <button
              onClick={() => toggleGroup(group.labelKey!)}
              className="flex items-center w-full px-3 py-1.5 text-xs font-semibold text-gray-400 uppercase tracking-wide hover:text-gray-600 transition-colors"
            >
              {isExpanded ? (
                <ChevronDown className="h-3 w-3 mr-1.5" />
              ) : (
                <ChevronRight className="h-3 w-3 mr-1.5" />
              )}
              {t(group.labelKey as any)}
            </button>
            {isExpanded && (
              <div className="mt-0.5 ml-1">
                {group.items.map((item, itemIdx) => {
                  const isActive = pathname === item.href
                  // Mostrar sub-encabezado si el item tiene subLabel y es el primero con ese subLabel
                  const showSubLabel = item.subLabel && (itemIdx === 0 || group.items[itemIdx - 1]?.subLabel !== item.subLabel)
                  return (
                    <div key={item.key}>
                      {showSubLabel && (
                        <p className="px-3 pt-2 pb-0.5 text-[10px] font-semibold text-gray-400 uppercase tracking-wider">
                          {t(item.subLabel as any)}
                        </p>
                      )}
                      <Link
                        href={item.href}
                        onClick={onItemClick}
                        className={`flex items-center px-3 py-2 text-sm font-medium rounded-md ${item.subLabel ? 'ml-2 ' : ''}${
                          isActive
                            ? 'bg-blue-50 text-blue-600'
                            : 'text-gray-700 hover:bg-gray-50 hover:text-gray-900'
                        }`}
                      >
                        <item.icon className="mr-3 h-5 w-5" />
                        {t(item.key as any)}
                      </Link>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </>
  )

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
            <nav className="flex-1 px-2 py-4 overflow-y-auto">
              {renderNavGroups(() => setSidebarOpen(false))}
            </nav>
            {/* Información de usuario y logout en móvil */}
            <div className="flex-shrink-0 border-t border-gray-200 p-3 space-y-2">
              <div className="flex items-center gap-3">
                <div className="flex-shrink-0 w-9 h-9 rounded-full bg-blue-600 flex items-center justify-center">
                  <span className="text-sm font-medium text-white">
                    {user?.full_name?.charAt(0)?.toUpperCase() || '?'}
                  </span>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900 truncate">{user?.full_name}</p>
                  <p className="text-xs text-gray-500 truncate">{user?.email}</p>
                </div>
              </div>
              <Badge variant="secondary" className="text-xs font-bold px-2 py-0.5 w-full justify-center">
                {roleLabel}
              </Badge>
              <LanguageSelector />
              <Button
                variant="ghost"
                size="sm"
                className="w-full text-gray-600 hover:text-red-600 hover:bg-red-50"
                onClick={() => {
                  setSidebarOpen(false)
                  logout()
                }}
              >
                <LogOut className="mr-1.5 h-3.5 w-3.5" />
                {t('logout')}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Sidebar desktop */}
      <div className="hidden lg:fixed lg:inset-y-0 lg:flex lg:w-64 lg:flex-col">
        <div className="flex flex-col h-full bg-white border-r border-gray-200">
          <div className="flex-shrink-0 flex h-16 items-center px-4 border-b">
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
          <div className="px-4 py-2 border-b border-gray-100">
            <BuildInfo compact />
          </div>
          <nav className="flex-1 overflow-y-auto px-2 py-4 min-h-0">
            {renderNavGroups()}
          </nav>
          <div className="flex-shrink-0 border-t border-gray-200 p-3 space-y-2">
            <div className="flex items-center gap-3">
              <div className="flex-shrink-0 w-9 h-9 rounded-full bg-blue-600 flex items-center justify-center">
                <span className="text-sm font-medium text-white">
                  {user?.full_name?.charAt(0)?.toUpperCase() || '?'}
                </span>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900 truncate">{user?.full_name}</p>
                <p className="text-xs text-gray-500 truncate">{user?.email}</p>
              </div>
            </div>
            <Badge variant="secondary" className="text-xs font-bold px-2 py-0.5 w-full justify-center">
              {roleLabel}
            </Badge>
            <LanguageSelector />
            <Button
              variant="ghost"
              size="sm"
              className="w-full text-gray-600 hover:text-red-600 hover:bg-red-50"
              onClick={logout}
            >
              <LogOut className="mr-1.5 h-3.5 w-3.5" />
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
          <div className="ml-auto">
            <BuildInfo compact />
          </div>
        </div>

        {/* Contenido */}
        <main className="py-8 px-4 sm:px-6 lg:px-8">{children}</main>
      </div>
    </div>
  )
}
