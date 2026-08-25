/**
 * Página de gestión de usuarios.
 * 
 * Solo accesible para Admin.
 * Incluye CRUD completo de usuarios con timezone.
 */

'use client'

import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { usersApi, organizationsApi } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import {
  Users,
  Plus,
  Edit,
  Trash2,
  AlertCircle,
  Mail,
  Building2,
  Shield,
  ShieldCheck,
  Clock,
  X,
  ChevronLeft,
  ChevronRight,
  Activity,
  Search,
  CheckCircle,
  XCircle,
  LayoutGrid,
  List,
  RefreshCw,
} from 'lucide-react'
import { useTranslations } from 'next-intl'
import { useRouter } from 'next/navigation'
import { formatDateWithTimezone, COMMON_TIMEZONES } from '@/lib/dateUtils'
import { useUserTimezone } from '@/hooks/useUserTimezone'
import { useAuth } from '@/hooks/useAuth'
import type { User, UserCreate, UserUpdate, Organization } from '@/types'

function formatApiError(error: any): string | undefined {
  if (!error) return undefined
  const detail = error?.detail ?? error?.message ?? error
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((e: any) => e?.msg || JSON.stringify(e)).join(', ')
  return JSON.stringify(detail)
}

export default function UsersPage() {
  const queryClient = useQueryClient()
  const userTimezone = useUserTimezone()
  const { user: currentUser, refreshUser } = useAuth()
  const t = useTranslations('users')
  const tCommon = useTranslations('common')
  const tTimeline = useTranslations('timeline')
  const router = useRouter()
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [deletingUser, setDeletingUser] = useState<User | null>(null)
  const [searchTerm, setSearchTerm] = useState('')
  const [filterRole, setFilterRole] = useState<'admin' | 'operator' | undefined>(undefined)
  const [filterActive, setFilterActive] = useState<boolean | undefined>(undefined)
  const [filterOrgId, setFilterOrgId] = useState<string | undefined>(undefined)
  const [viewMode, setViewMode] = useState<'cards' | 'table'>('cards')
  const [page, setPage] = useState(1)
  const pageSize = 10
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date())

  // Query para listar usuarios
  const { data: usersData, isLoading, isFetching, error } = useQuery({
    queryKey: ['users'],
    queryFn: () => usersApi.list(),
  })

  useEffect(() => {
    if (usersData && !isFetching) {
      setLastUpdated(new Date())
    }
  }, [usersData, isFetching])

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ['users'] })
  }

  // Query para organizaciones (solo admin)
  const isAdmin = currentUser?.role === 'admin'
  const { data: accounts } = useQuery({
    queryKey: ['accounts'],
    queryFn: () => organizationsApi.list(),
    enabled: isAdmin,
  })

  // Mutation para crear usuario
  const createMutation = useMutation({
    mutationFn: (data: UserCreate) => usersApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setShowCreateForm(false)
    },
  })

  // Mutation para actualizar usuario
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UserUpdate }) =>
      usersApi.update(id, data),
    onSuccess: async (updatedUser) => {
      // Si el usuario actualizado es el usuario actual, refrescar sus datos y recargar
      if (currentUser && updatedUser.id === currentUser.id) {
        await refreshUser()
        // Recargar la página para que todos los componentes usen el nuevo timezone
        window.location.reload()
      } else {
        // Si es otro usuario, solo invalidar queries
        queryClient.invalidateQueries({ queryKey: ['users'] })
        setEditingUser(null)
      }
    },
  })

  // Mutation para eliminar usuario
  const deleteMutation = useMutation({
    mutationFn: (id: string) => usersApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] })
      setDeletingUser(null)
    },
  })

  useEffect(() => { setPage(1) }, [searchTerm, filterRole, filterActive, filterOrgId])

  const users = usersData || []

  const stats = {
    total: users.length,
    admins: users.filter((u) => u.role === 'admin').length,
    operators: users.filter((u) => u.role === 'operator').length,
    active: users.filter((u) => u.is_active).length,
    inactive: users.filter((u) => !u.is_active).length,
  }

  const search = searchTerm.trim().toLowerCase()
  const filteredUsers = users.filter((u) => {
    if (search && !u.full_name.toLowerCase().includes(search) && !u.email.toLowerCase().includes(search)) return false
    if (filterRole && u.role !== filterRole) return false
    if (filterActive !== undefined && u.is_active !== filterActive) return false
    if (filterOrgId && u.organization_id !== filterOrgId) return false
    return true
  })

  const hasActiveFilters = !!searchTerm || filterRole !== undefined || filterActive !== undefined || !!filterOrgId
  const clearFilters = () => {
    setSearchTerm('')
    setFilterRole(undefined)
    setFilterActive(undefined)
    setFilterOrgId(undefined)
    setPage(1)
  }

  const totalUsers = filteredUsers.length
  const totalPages = Math.ceil(totalUsers / pageSize)
  const paginatedUsers = filteredUsers.slice((page - 1) * pageSize, page * pageSize)
  const paginationStart = totalUsers === 0 ? 0 : (page - 1) * pageSize + 1
  const paginationEnd = Math.min(page * pageSize, totalUsers)

  if (isLoading) {
    return (
      <div className="max-w-screen-2xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-8">{t('title')}</h1>
        <div className="animate-pulse space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 bg-gray-200 rounded-lg"></div>
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="max-w-screen-2xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-8">{t('title')}</h1>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Error al cargar usuarios. Por favor, intenta de nuevo.
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  return (
    <div className="max-w-screen-2xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-8 gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">{t('title')}</h1>
          <p className="text-gray-600 mt-2">{t('subtitle')}</p>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <Button onClick={() => setShowCreateForm(true)}>
            <Plus className="w-4 h-4 mr-2" />
            {t('newUser')}
          </Button>
          <div className="flex items-center gap-1">
            <span className="text-xs text-gray-400">
              {tCommon('lastUpdated', { time: formatDateWithTimezone(lastUpdated, userTimezone) })}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleRefresh}
              disabled={isFetching}
              title={tCommon('refresh')}
              className="h-6 w-6 p-0 text-gray-400 hover:text-gray-600"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </div>
      </div>

      {/* Cards de estadísticas */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3 md:gap-4 mb-6">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-600 truncate">{t('total')}</p>
                <p className="text-2xl lg:text-3xl font-bold text-gray-900">{stats.total}</p>
              </div>
              <Users className="w-8 h-8 lg:w-10 lg:h-10 shrink-0 text-blue-600" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-600 truncate">{t('admins')}</p>
                <p className="text-2xl lg:text-3xl font-bold text-gray-900">{stats.admins}</p>
              </div>
              <ShieldCheck className="w-8 h-8 lg:w-10 lg:h-10 shrink-0 text-purple-600" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-600 truncate">{t('operators')}</p>
                <p className="text-2xl lg:text-3xl font-bold text-gray-900">{stats.operators}</p>
              </div>
              <Shield className="w-8 h-8 lg:w-10 lg:h-10 shrink-0 text-gray-500" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-600 truncate">{t('active')}</p>
                <p className="text-2xl lg:text-3xl font-bold text-gray-900">{stats.active}</p>
              </div>
              <CheckCircle className="w-8 h-8 lg:w-10 lg:h-10 shrink-0 text-green-600" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm font-medium text-gray-600 truncate">{t('inactive')}</p>
                <p className="text-2xl lg:text-3xl font-bold text-gray-900">{stats.inactive}</p>
              </div>
              <XCircle className={`w-8 h-8 lg:w-10 lg:h-10 shrink-0 ${stats.inactive > 0 ? 'text-red-500' : 'text-gray-400'}`} />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Filtros */}
      <Card className="mb-6">
        <CardContent className="p-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="md:col-span-2">
              <div className="flex items-center">
                <Search className="w-5 h-5 text-gray-400 mr-3" />
                <Input
                  type="text"
                  placeholder={t('searchPlaceholder')}
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="flex-1"
                />
              </div>
            </div>
            {isAdmin && (
              <div>
                <select
                  value={filterOrgId || 'all'}
                  onChange={(e) => setFilterOrgId(e.target.value === 'all' ? undefined : e.target.value)}
                  className="w-full px-3 py-2 border rounded-md"
                >
                  <option value="all">{t('allAccounts')}</option>
                  {Array.isArray(accounts) &&
                    accounts.map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.name}
                      </option>
                    ))}
                </select>
              </div>
            )}
          </div>
          <div className="flex items-center justify-between mt-4 flex-wrap gap-3">
            <div className="flex items-center gap-2 flex-wrap">
              <button
                onClick={() => setFilterRole(filterRole === 'admin' ? undefined : 'admin')}
                className={`flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium transition-all select-none ${
                  filterRole === 'admin'
                    ? 'border-purple-300 bg-purple-50 text-purple-700'
                    : 'border-gray-200 bg-white text-gray-500 hover:border-gray-300 hover:text-gray-700'
                }`}
              >
                <span className={`flex w-3.5 h-3.5 items-center justify-center rounded-sm border shrink-0 transition-colors ${filterRole === 'admin' ? 'border-purple-500 bg-purple-500' : 'border-gray-300 bg-white'}`}>
                  {filterRole === 'admin' && <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M2 5l2.5 2.5L8 3"/></svg>}
                </span>
                {t('roleAdmin')}
              </button>
              <button
                onClick={() => setFilterRole(filterRole === 'operator' ? undefined : 'operator')}
                className={`flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium transition-all select-none ${
                  filterRole === 'operator'
                    ? 'border-blue-300 bg-blue-50 text-blue-700'
                    : 'border-gray-200 bg-white text-gray-500 hover:border-gray-300 hover:text-gray-700'
                }`}
              >
                <span className={`flex w-3.5 h-3.5 items-center justify-center rounded-sm border shrink-0 transition-colors ${filterRole === 'operator' ? 'border-blue-500 bg-blue-500' : 'border-gray-300 bg-white'}`}>
                  {filterRole === 'operator' && <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M2 5l2.5 2.5L8 3"/></svg>}
                </span>
                {t('roleOperator')}
              </button>
              <button
                onClick={() => setFilterActive(filterActive === true ? undefined : true)}
                className={`flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium transition-all select-none ${
                  filterActive === true
                    ? 'border-emerald-300 bg-emerald-50 text-emerald-700'
                    : 'border-gray-200 bg-white text-gray-500 hover:border-gray-300 hover:text-gray-700'
                }`}
              >
                <span className={`flex w-3.5 h-3.5 items-center justify-center rounded-sm border shrink-0 transition-colors ${filterActive === true ? 'border-emerald-500 bg-emerald-500' : 'border-gray-300 bg-white'}`}>
                  {filterActive === true && <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M2 5l2.5 2.5L8 3"/></svg>}
                </span>
                {t('active')}
              </button>
              <button
                onClick={() => setFilterActive(filterActive === false ? undefined : false)}
                className={`flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium transition-all select-none ${
                  filterActive === false
                    ? 'border-red-300 bg-red-50 text-red-700'
                    : 'border-gray-200 bg-white text-gray-500 hover:border-gray-300 hover:text-gray-700'
                }`}
              >
                <span className={`flex w-3.5 h-3.5 items-center justify-center rounded-sm border shrink-0 transition-colors ${filterActive === false ? 'border-red-500 bg-red-500' : 'border-gray-300 bg-white'}`}>
                  {filterActive === false && <svg className="w-2.5 h-2.5 text-white" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M2 5l2.5 2.5L8 3"/></svg>}
                </span>
                {t('inactive')}
              </button>
              {hasActiveFilters && (
                <Button variant="outline" size="sm" onClick={clearFilters}>
                  {tCommon('clearFilters')}
                </Button>
              )}
            </div>
            <div className="flex items-center gap-1 border rounded-md p-0.5">
              <Button
                variant={viewMode === 'cards' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('cards')}
                title={tCommon('viewCards')}
                className="h-8 w-8 p-0"
              >
                <LayoutGrid className="w-4 h-4" />
              </Button>
              <Button
                variant={viewMode === 'table' ? 'default' : 'ghost'}
                size="sm"
                onClick={() => setViewMode('table')}
                title={tCommon('viewTable')}
                className="h-8 w-8 p-0"
              >
                <List className="w-4 h-4" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Modal de creación */}
      {showCreateForm && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <Card className="max-w-2xl w-full max-h-[90vh] overflow-y-auto">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>{t('createTitle')}</CardTitle>
              <Button variant="ghost" size="sm" onClick={() => setShowCreateForm(false)} className="h-8 w-8 p-0">
                <X className="w-4 h-4" />
              </Button>
            </CardHeader>
            <CardContent>
              <UserForm
                accounts={accounts || []}
                isAdmin={isAdmin}
                currentUser={currentUser}
                onSubmit={(data) => createMutation.mutate(data as UserCreate)}
                onCancel={() => setShowCreateForm(false)}
                isLoading={createMutation.isPending}
                error={formatApiError(createMutation.error)}
              />
            </CardContent>
          </Card>
        </div>
      )}

      {/* Modal de edición */}
      {editingUser && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <Card className="max-w-2xl w-full max-h-[90vh] overflow-y-auto">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>{t('editTitle', { email: editingUser.email })}</CardTitle>
              <Button variant="ghost" size="sm" onClick={() => setEditingUser(null)} className="h-8 w-8 p-0">
                <X className="w-4 h-4" />
              </Button>
            </CardHeader>
            <CardContent>
              <UserForm
                user={editingUser}
                accounts={accounts || []}
                isAdmin={isAdmin}
                currentUser={currentUser}
                onSubmit={(data) => updateMutation.mutate({ id: editingUser.id, data })}
                onCancel={() => setEditingUser(null)}
                isLoading={updateMutation.isPending}
                error={formatApiError(updateMutation.error)}
              />
            </CardContent>
          </Card>
        </div>
      )}

      {/* Lista de usuarios */}
      {paginatedUsers.length > 0 ? (
        viewMode === 'cards' ? (
          <div className="flex flex-col gap-4">
            {paginatedUsers.map((user) => (
              <UserCard
                key={user.id}
                user={user}
                userTimezone={userTimezone}
                isAdmin={isAdmin}
                t={t}
                onViewActivity={() => router.push(`/dashboard/admin/users/${user.id}/activity`)}
                onEdit={() => setEditingUser(user)}
                onDelete={() => setDeletingUser(user)}
              />
            ))}
          </div>
        ) : (
          <UserTable
            users={paginatedUsers}
            userTimezone={userTimezone}
            isAdmin={isAdmin}
            t={t}
            onViewActivity={(user) => router.push(`/dashboard/admin/users/${user.id}/activity`)}
            onEdit={setEditingUser}
            onDelete={setDeletingUser}
          />
        )
      ) : (
        <Card>
          <CardContent className="p-12 text-center">
            <Users className="w-16 h-16 text-gray-300 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">
              {t('emptyTitle')}
            </h3>
            <p className="text-gray-600 mb-4">{t('emptyMessage')}</p>
            {hasActiveFilters ? (
              <Button variant="outline" onClick={clearFilters}>
                {tCommon('clearFilters')}
              </Button>
            ) : (
              <Button onClick={() => setShowCreateForm(true)}>
                <Plus className="w-4 h-4 mr-2" />
                {t('createBtn')}
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      {/* Paginación */}
      {totalUsers > 0 && totalPages > 1 && (
        <div className="bg-white rounded-lg shadow px-4 py-3 flex items-center justify-between border border-gray-200 mt-4 sm:px-6">
          <div className="flex-1 flex items-center justify-between">
            <p className="text-sm text-gray-700">
              {t('pagination', { start: paginationStart, end: paginationEnd, total: totalUsers })}
            </p>
            <div className="flex items-center gap-2">
              {page > 1 && (
                <Button variant="outline" size="sm" onClick={() => setPage(1)}>
                  {tCommon('first')}
                </Button>
              )}
              <Button variant="outline" size="sm" onClick={() => setPage(page - 1)} disabled={page <= 1}>
                <ChevronLeft className="h-4 w-4 mr-1" />
                {tCommon('previous')}
              </Button>
              <span className="text-sm text-gray-600 px-2">
                {t('pageNumber', { page })}
              </span>
              <Button variant="outline" size="sm" onClick={() => setPage(page + 1)} disabled={page >= totalPages}>
                {tCommon('next')}
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Modal de confirmación de eliminación */}
      {deletingUser && (
        <DeleteConfirmModal
          user={deletingUser}
          onConfirm={() => deleteMutation.mutate(deletingUser.id)}
          onCancel={() => setDeletingUser(null)}
          isLoading={deleteMutation.isPending}
          error={formatApiError(deleteMutation.error)}
        />
      )}
    </div>
  )
}

// Vista de tarjeta individual de usuario
function UserCard({
  user,
  userTimezone,
  isAdmin,
  t,
  onViewActivity,
  onEdit,
  onDelete,
}: {
  user: User
  userTimezone: string
  isAdmin: boolean
  t: ReturnType<typeof useTranslations>
  onViewActivity: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  const tTimeline = useTranslations('timeline')
  return (
    <Card className="hover:shadow-md transition">
      <CardContent className="p-4">
        <div className="flex items-start justify-between">
          <div className="flex items-start flex-1 min-w-0">
            <div className="rounded-full p-2 bg-blue-100 mr-3 shrink-0">
              <Users className="w-4 h-4 text-blue-600" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center flex-wrap gap-2 mb-1.5">
                <h3 className="text-base font-semibold text-gray-900">
                  {user.full_name}
                </h3>
                <Badge variant={user.role === 'admin' ? 'default' : 'secondary'}>
                  {user.role === 'admin' ? t('roleAdmin') : t('roleOperator')}
                </Badge>
                {!user.is_active && (
                  <Badge variant="destructive">{t('inactive')}</Badge>
                )}
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs text-gray-600 mb-2">
                <div className="flex items-center min-w-0">
                  <Mail className="w-3.5 h-3.5 mr-1 shrink-0" />
                  <span className="truncate">{user.email}</span>
                </div>
                {user.organization && (
                  <div className="flex items-center min-w-0">
                    <Building2 className="w-3.5 h-3.5 mr-1 shrink-0" />
                    <span className="truncate">{user.organization.name}</span>
                  </div>
                )}
                {user.timezone && (
                  <div className="flex items-center min-w-0">
                    <Clock className="w-3.5 h-3.5 mr-1 shrink-0" />
                    <span className="truncate">{user.timezone}</span>
                  </div>
                )}
              </div>
              <div className="flex items-center text-xs text-gray-500">
                Creado: {formatDateWithTimezone(user.created_at, userTimezone)}
              </div>
            </div>
          </div>

          <div className="flex items-center space-x-2 ml-4 shrink-0">
            <Button variant="outline" size="sm" onClick={onViewActivity} title={tTimeline('viewActivity')}>
              <Activity className="w-4 h-4" />
            </Button>
            <Button variant="outline" size="sm" onClick={onEdit} title="Editar usuario">
              <Edit className="w-4 h-4" />
            </Button>
            {isAdmin && (
              <Button
                variant="outline"
                size="sm"
                onClick={onDelete}
                title="Eliminar usuario"
                className="text-red-600 hover:text-red-700"
              >
                <Trash2 className="w-4 h-4" />
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

// Vista de tabla de usuarios
function UserTable({
  users,
  userTimezone,
  isAdmin,
  t,
  onViewActivity,
  onEdit,
  onDelete,
}: {
  users: User[]
  userTimezone: string
  isAdmin: boolean
  t: ReturnType<typeof useTranslations>
  onViewActivity: (user: User) => void
  onEdit: (user: User) => void
  onDelete: (user: User) => void
}) {
  const tTimeline = useTranslations('timeline')
  return (
    <Card>
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('fullNameLabel')}</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('emailLabel')}</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('roleLabel')}</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('orgLabel')}</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('statusLabel')}</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">{t('title')}</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {users.map((user) => (
              <tr key={user.id} className="hover:bg-muted/50">
                <td className="px-4 py-3 font-medium text-gray-900 whitespace-nowrap">{user.full_name}</td>
                <td className="px-4 py-3 text-gray-600 whitespace-nowrap">{user.email}</td>
                <td className="px-4 py-3">
                  <Badge variant={user.role === 'admin' ? 'default' : 'secondary'}>
                    {user.role === 'admin' ? t('roleAdmin') : t('roleOperator')}
                  </Badge>
                </td>
                <td className="px-4 py-3 text-gray-600 whitespace-nowrap">{user.organization?.name ?? '—'}</td>
                <td className="px-4 py-3">
                  {user.is_active ? (
                    <Badge className="bg-green-100 text-green-800">{t('active')}</Badge>
                  ) : (
                    <Badge variant="destructive">{t('inactive')}</Badge>
                  )}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-2">
                    <Button variant="outline" size="sm" onClick={() => onViewActivity(user)} title={tTimeline('viewActivity')}>
                      <Activity className="w-4 h-4" />
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => onEdit(user)} title="Editar usuario">
                      <Edit className="w-4 h-4" />
                    </Button>
                    {isAdmin && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => onDelete(user)}
                        title="Eliminar usuario"
                        className="text-red-600 hover:text-red-700"
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

// Componente de formulario de usuario
function UserForm({
  user,
  accounts,
  isAdmin,
  currentUser: parentUser,
  onSubmit,
  onCancel,
  isLoading,
  error,
}: {
  user?: User
  accounts: Organization[]
  isAdmin?: boolean
  currentUser?: User | null
  onSubmit: (data: UserCreate | UserUpdate) => void
  onCancel: () => void
  isLoading: boolean
  error?: string
}) {
  const { user: currentUser } = useAuth()
  const t = useTranslations('users')
  const tCommon = useTranslations('common')
  const isEdit = !!user
  const isEditingSelf = isEdit && currentUser && user.id === currentUser.id

  const [formData, setFormData] = useState<any>({
    email: user?.email || '',
    password: '',
    full_name: user?.full_name || '',
    role: user?.role || 'operator',
    organization_id: user?.organization_id || '',
    timezone: user?.timezone || '',
    language: user?.language || 'en',
    is_active: user?.is_active ?? true,
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    
    // Preparar datos
    const data: any = {
      email: formData.email,
      full_name: formData.full_name,
      role: isAdmin ? formData.role : 'operator',
      organization_id: isAdmin ? (formData.organization_id || undefined) : (currentUser?.organization_id || undefined),
      timezone: formData.timezone || undefined,
      language: formData.language || 'en',
    }
    
    if (isEdit) {
      // En edición, no enviar password si está vacío
      if (formData.password) {
        data.password = formData.password
      }
      data.is_active = formData.is_active
    } else {
      // En creación, password es obligatorio
      data.password = formData.password
    }
    
    onSubmit(data)
  }

  // Obtener timezone de la organización seleccionada
  const accountList = Array.isArray(accounts) ? accounts : []
  const selectedAccount = accountList.find(a => a.id === formData.organization_id)
  const inheritedTimezone = selectedAccount?.timezone || 'UTC'

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Email */}
        <div className="space-y-2">
          <Label htmlFor="email">{t('emailLabel')}</Label>
          <Input
            id="email"
            type="email"
            placeholder={t('emailPlaceholder')}
            value={formData.email}
            onChange={(e) => setFormData({ ...formData, email: e.target.value })}
            disabled={isLoading}
            required
          />
        </div>

        {/* Nombre completo */}
        <div className="space-y-2">
          <Label htmlFor="full_name">{t('fullNameLabel')}</Label>
          <Input
            id="full_name"
            type="text"
            placeholder={t('fullNamePlaceholder')}
            value={formData.full_name}
            onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
            disabled={isLoading}
            required
          />
        </div>

        {/* Contraseña */}
        <div className="space-y-2">
          <Label htmlFor="password">
            {t('passwordLabel')}
            {isEdit && <span className="text-xs text-gray-500 ml-2">{t('passwordHint')}</span>}
          </Label>
          <Input
            id="password"
            type="password"
            placeholder={isEdit ? '••••••••' : t('passwordPlaceholder')}
            value={formData.password}
            onChange={(e) => setFormData({ ...formData, password: e.target.value })}
            disabled={isLoading}
            required={!isEdit}
          />
        </div>

        {/* Rol */}
        <div className="space-y-2">
          <Label htmlFor="role">{t('roleLabel')}</Label>
          <select
            id="role"
            value={isAdmin ? formData.role : 'operator'}
            onChange={(e) => setFormData({ ...formData, role: e.target.value })}
            disabled={isLoading || !isAdmin}
            className="w-full px-3 py-2 border rounded-md"
            required
          >
            <option value="operator">{t('roleOperator')}</option>
            {isAdmin && <option value="admin">{t('roleAdmin')}</option>}
          </select>
        </div>

        {/* Organización (solo admin) */}
        {isAdmin && (
        <div className="space-y-2">
          <Label htmlFor="organization_id">
            {t('orgLabel')}
            {formData.role === 'operator' && (
              <span className="text-red-500 ml-1">*</span>
            )}
          </Label>
          <select
            id="organization_id"
            value={formData.organization_id}
            onChange={(e) => setFormData({ ...formData, organization_id: e.target.value })}
            disabled={isLoading}
            className={`w-full px-3 py-2 border rounded-md ${formData.role === 'operator' && !formData.organization_id ? 'border-red-400' : ''}`}
          >
            <option value="">{t('timezoneDefault')}</option>
            {accountList.map((account) => (
              <option key={account.id} value={account.id}>{account.name}</option>
            ))}
          </select>
        </div>
        )}

        {/* Timezone */}
        <div className="space-y-2">
          <Label htmlFor="timezone">
            {t('timezoneLabel')}
            {formData.organization_id && (
              <span className="text-xs text-gray-500 ml-2">
                {t('timezoneInherit', { timezone: inheritedTimezone })}
              </span>
            )}
          </Label>
          <select
            id="timezone"
            value={formData.timezone}
            onChange={(e) => setFormData({ ...formData, timezone: e.target.value })}
            disabled={isLoading}
            className="w-full px-3 py-2 border rounded-md"
          >
            <option value="">{t('timezoneDefault')}</option>
            {COMMON_TIMEZONES.map((tz) => (
              <option key={tz.value} value={tz.value}>{tz.label}</option>
            ))}
          </select>
        </div>

        {/* Idioma */}
        <div className="space-y-2">
          <Label htmlFor="language">{t('languageLabel')}</Label>
          <select
            id="language"
            value={formData.language}
            onChange={(e) => setFormData({ ...formData, language: e.target.value })}
            disabled={isLoading}
            className="w-full px-3 py-2 border rounded-md"
          >
            <option value="en">English</option>
            <option value="es">Español</option>
          </select>
        </div>

        {/* Estado (solo en edición) */}
        {isEdit && (
          <div className="space-y-2">
            <Label htmlFor="is_active">
              {t('statusLabel')}
              {isEditingSelf && (
                <span className="text-xs text-amber-600 ml-2">{t('statusWarning')}</span>
              )}
            </Label>
            <select
              id="is_active"
              value={formData.is_active ? 'true' : 'false'}
              onChange={(e) => setFormData({ ...formData, is_active: e.target.value === 'true' })}
              disabled={isLoading || !!isEditingSelf}
              className="w-full px-3 py-2 border rounded-md disabled:bg-gray-100 disabled:cursor-not-allowed"
            >
              <option value="true">{t('statusActive')}</option>
              <option value="false">{t('statusInactive')}</option>
            </select>
            {isEditingSelf && (
              <p className="text-xs text-gray-500">{t('selfDeactivateNote')}</p>
            )}
          </div>
        )}
      </div>

      <Alert>
        <AlertCircle className="h-4 w-4" />
        <AlertDescription className="text-xs">
          {t('timezoneNote', { timezone: inheritedTimezone })}
        </AlertDescription>
      </Alert>

      <div className="flex justify-end space-x-3">
        <Button type="button" variant="outline" onClick={onCancel} disabled={isLoading}>
          {tCommon('cancel')}
        </Button>
        <Button
          type="submit"
          disabled={isLoading || (formData.role === 'operator' && !formData.organization_id)}
        >
          {isLoading ? (isEdit ? tCommon('updating') : tCommon('creating')) : (isEdit ? t('updateBtn') : t('createBtn'))}
        </Button>
      </div>
    </form>
  )
}

// Modal de confirmación de eliminación
function DeleteConfirmModal({
  user,
  onConfirm,
  onCancel,
  isLoading,
  error,
}: {
  user: User
  onConfirm: () => void
  onCancel: () => void
  isLoading: boolean
  error?: string
}) {
  const t = useTranslations('users')
  const tCommon = useTranslations('common')

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <Card className="max-w-md w-full">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-red-600">{t('deleteTitle')}</CardTitle>
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={isLoading}>
            <X className="w-5 h-5" />
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <p className="text-gray-700">
            {t('deleteConfirm', { name: user.full_name, email: user.email })}
          </p>

          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{t('deleteWarning')}</AlertDescription>
          </Alert>

          <div className="flex justify-end space-x-3">
            <Button variant="outline" onClick={onCancel} disabled={isLoading}>
              {tCommon('cancel')}
            </Button>
            <Button variant="destructive" onClick={onConfirm} disabled={isLoading}>
              {isLoading ? tCommon('deleting') : t('deleteBtn')}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
