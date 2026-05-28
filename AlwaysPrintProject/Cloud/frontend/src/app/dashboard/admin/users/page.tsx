/**
 * Página de gestión de usuarios.
 * 
 * Solo accesible para Admin.
 * Incluye CRUD completo de usuarios con timezone.
 */

'use client'

import { useState } from 'react'
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
  Clock,
  X,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import { useTranslations } from 'next-intl'
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
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [deletingUser, setDeletingUser] = useState<User | null>(null)
  const [page, setPage] = useState(1)
  const pageSize = 10

  // Query para listar usuarios
  const { data: usersData, isLoading, error } = useQuery({
    queryKey: ['users'],
    queryFn: () => usersApi.list(),
  })

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

  const users = usersData || []
  const totalUsers = users.length
  const totalPages = Math.ceil(totalUsers / pageSize)
  const paginatedUsers = users.slice((page - 1) * pageSize, page * pageSize)
  const paginationStart = (page - 1) * pageSize + 1
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
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">{t('title')}</h1>
          <p className="text-gray-600 mt-2">{t('subtitle')}</p>
        </div>
        <Button onClick={() => setShowCreateForm(true)}>
          <Plus className="w-4 h-4 mr-2" />
          {t('newUser')}
        </Button>
      </div>

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
      <div className="space-y-4">
        {users.length > 0 ? (
          paginatedUsers.map((user) => (
            <Card key={user.id} className="hover:shadow-md transition">
              <CardContent className="p-6">
                <div className="flex items-start justify-between">
                  <div className="flex items-start flex-1">
                    <div className="rounded-full p-3 bg-blue-100 mr-4">
                      <Users className="w-6 h-6 text-blue-600" />
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center mb-2">
                        <h3 className="text-xl font-semibold text-gray-900 mr-3">
                          {user.full_name}
                        </h3>
                        <Badge variant={user.role === 'admin' ? 'default' : 'secondary'}>
                          {user.role === 'admin' ? t('roleAdmin') : t('roleOperator')}
                        </Badge>
                        {!user.is_active && (
                          <Badge variant="destructive" className="ml-2">
                            Inactivo
                          </Badge>
                        )}
                      </div>

                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm text-gray-600 mb-3">
                        <div className="flex items-center">
                          <Mail className="w-4 h-4 mr-1" />
                          {user.email}
                        </div>
                        {user.organization && (
                          <div className="flex items-center">
                            <Building2 className="w-4 h-4 mr-1" />
                            {user.organization.name}
                          </div>
                        )}
                        {user.timezone && (
                          <div className="flex items-center">
                            <Clock className="w-4 h-4 mr-1" />
                            {user.timezone}
                          </div>
                        )}
                        <div className="flex items-center">
                          <Shield className="w-4 h-4 mr-1" />
                          {user.role === 'admin' ? 'Admin' : 'Operador'}
                        </div>
                      </div>

                      <div className="flex items-center text-xs text-gray-500">
                        Creado: {formatDateWithTimezone(user.created_at, userTimezone)}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center space-x-2 ml-4">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setEditingUser(user)}
                      title="Editar usuario"
                    >
                      <Edit className="w-4 h-4" />
                    </Button>
                    {isAdmin && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setDeletingUser(user)}
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
          ))
        ) : (
          <Card>
            <CardContent className="p-12 text-center">
              <Users className="w-16 h-16 text-gray-300 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-gray-900 mb-2">
                {t('emptyTitle')}
              </h3>
              <p className="text-gray-600 mb-4">{t('emptyMessage')}</p>
              <Button onClick={() => setShowCreateForm(true)}>
                <Plus className="w-4 h-4 mr-2" />
                {t('createBtn')}
              </Button>
            </CardContent>
          </Card>
        )}
      </div>

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
