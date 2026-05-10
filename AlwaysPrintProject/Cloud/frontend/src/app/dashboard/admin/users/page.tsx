/**
 * Página de gestión de usuarios.
 * 
 * Solo accesible para Admin.
 * Incluye CRUD completo de usuarios con timezone.
 */

'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { usersApi, accountsApi } from '@/lib/api'
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
  X
} from 'lucide-react'
import { formatDateWithTimezone, COMMON_TIMEZONES } from '@/lib/dateUtils'
import { useUserTimezone } from '@/hooks/useUserTimezone'
import { useAuth } from '@/hooks/useAuth'
import type { User, UserCreate, UserUpdate, Account } from '@/types'

export default function UsersPage() {
  const queryClient = useQueryClient()
  const userTimezone = useUserTimezone()
  const { user: currentUser, refreshUser } = useAuth()
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [deletingUser, setDeletingUser] = useState<User | null>(null)

  // Query para listar usuarios
  const { data: usersData, isLoading, error } = useQuery({
    queryKey: ['users'],
    queryFn: () => usersApi.list(),
  })

  // Query para organizaciones
  const { data: accounts } = useQuery({
    queryKey: ['accounts'],
    queryFn: () => accountsApi.list(),
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

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-8">Usuarios</h1>
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
      <div className="max-w-7xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-8">Usuarios</h1>
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
    <div className="max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Usuarios</h1>
          <p className="text-gray-600 mt-2">
            Gestiona los usuarios del sistema
          </p>
        </div>
        <Button onClick={() => setShowCreateForm(true)}>
          <Plus className="w-4 h-4 mr-2" />
          Nuevo Usuario
        </Button>
      </div>

      {/* Formulario de creación */}
      {showCreateForm && (
        <Card className="mb-6 border-blue-200 bg-blue-50">
          <CardHeader>
            <CardTitle>Crear Nuevo Usuario</CardTitle>
          </CardHeader>
          <CardContent>
            <UserForm
              accounts={accounts || []}
              onSubmit={(data) => createMutation.mutate(data as UserCreate)}
              onCancel={() => setShowCreateForm(false)}
              isLoading={createMutation.isPending}
              error={(createMutation.error as any)?.detail}
            />
          </CardContent>
        </Card>
      )}

      {/* Formulario de edición */}
      {editingUser && (
        <Card className="mb-6 border-amber-200 bg-amber-50">
          <CardHeader>
            <CardTitle>Editar Usuario: {editingUser.email}</CardTitle>
          </CardHeader>
          <CardContent>
            <UserForm
              user={editingUser}
              accounts={accounts || []}
              onSubmit={(data) => updateMutation.mutate({ id: editingUser.id, data })}
              onCancel={() => setEditingUser(null)}
              isLoading={updateMutation.isPending}
              error={(updateMutation.error as any)?.detail}
            />
          </CardContent>
        </Card>
      )}

      {/* Lista de usuarios */}
      <div className="space-y-4">
        {users.length > 0 ? (
          users.map((user) => (
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
                          {user.role === 'admin' ? 'Administrador' : 'Operador'}
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
                        {user.account && (
                          <div className="flex items-center">
                            <Building2 className="w-4 h-4 mr-1" />
                            {user.account.name}
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
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setDeletingUser(user)}
                      title="Eliminar usuario"
                      className="text-red-600 hover:text-red-700"
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
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
                No hay usuarios
              </h3>
              <p className="text-gray-600 mb-4">
                Crea el primer usuario del sistema.
              </p>
              <Button onClick={() => setShowCreateForm(true)}>
                <Plus className="w-4 h-4 mr-2" />
                Crear Usuario
              </Button>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Modal de confirmación de eliminación */}
      {deletingUser && (
        <DeleteConfirmModal
          user={deletingUser}
          onConfirm={() => deleteMutation.mutate(deletingUser.id)}
          onCancel={() => setDeletingUser(null)}
          isLoading={deleteMutation.isPending}
          error={(deleteMutation.error as any)?.detail}
        />
      )}
    </div>
  )
}

// Componente de formulario de usuario
function UserForm({
  user,
  accounts,
  onSubmit,
  onCancel,
  isLoading,
  error,
}: {
  user?: User
  accounts: Account[]
  onSubmit: (data: UserCreate | UserUpdate) => void
  onCancel: () => void
  isLoading: boolean
  error?: string
}) {
  const { user: currentUser } = useAuth()
  const isEdit = !!user
  const isEditingSelf = isEdit && currentUser && user.id === currentUser.id
  
  const [formData, setFormData] = useState<any>({
    email: user?.email || '',
    password: '',
    full_name: user?.full_name || '',
    role: user?.role || 'operator',
    account_id: user?.account_id || '',
    timezone: user?.timezone || '',
    is_active: user?.is_active ?? true,
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    
    // Preparar datos
    const data: any = {
      email: formData.email,
      full_name: formData.full_name,
      role: formData.role,
      account_id: formData.account_id || undefined,
      timezone: formData.timezone || undefined,
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
  const selectedAccount = accounts.find(a => a.id === formData.account_id)
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
          <Label htmlFor="email">Email *</Label>
          <Input
            id="email"
            type="email"
            placeholder="usuario@ejemplo.com"
            value={formData.email}
            onChange={(e) => setFormData({ ...formData, email: e.target.value })}
            disabled={isLoading}
            required
          />
        </div>

        {/* Nombre completo */}
        <div className="space-y-2">
          <Label htmlFor="full_name">Nombre Completo *</Label>
          <Input
            id="full_name"
            type="text"
            placeholder="Juan Pérez"
            value={formData.full_name}
            onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
            disabled={isLoading}
            required
          />
        </div>

        {/* Contraseña */}
        <div className="space-y-2">
          <Label htmlFor="password">
            Contraseña {!isEdit && '*'}
            {isEdit && <span className="text-xs text-gray-500 ml-2">(dejar vacío para no cambiar)</span>}
          </Label>
          <Input
            id="password"
            type="password"
            placeholder={isEdit ? '••••••••' : 'Contraseña segura'}
            value={formData.password}
            onChange={(e) => setFormData({ ...formData, password: e.target.value })}
            disabled={isLoading}
            required={!isEdit}
          />
        </div>

        {/* Rol */}
        <div className="space-y-2">
          <Label htmlFor="role">Rol *</Label>
          <select
            id="role"
            value={formData.role}
            onChange={(e) => setFormData({ ...formData, role: e.target.value })}
            disabled={isLoading}
            className="w-full px-3 py-2 border rounded-md"
            required
          >
            <option value="operator">Operador</option>
            <option value="admin">Administrador</option>
          </select>
        </div>

        {/* Organización */}
        <div className="space-y-2">
          <Label htmlFor="account_id">Organización</Label>
          <select
            id="account_id"
            value={formData.account_id}
            onChange={(e) => setFormData({ ...formData, account_id: e.target.value })}
            disabled={isLoading}
            className="w-full px-3 py-2 border rounded-md"
          >
            <option value="">Sin asignar</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.name}
              </option>
            ))}
          </select>
        </div>

        {/* Timezone */}
        <div className="space-y-2">
          <Label htmlFor="timezone">
            Zona Horaria
            {formData.account_id && (
              <span className="text-xs text-gray-500 ml-2">
                (heredará {inheritedTimezone} si no se especifica)
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
            <option value="">Heredar de organización</option>
            {COMMON_TIMEZONES.map((tz) => (
              <option key={tz.value} value={tz.value}>
                {tz.label}
              </option>
            ))}
          </select>
        </div>

        {/* Estado (solo en edición) */}
        {isEdit && (
          <div className="space-y-2">
            <Label htmlFor="is_active">
              Estado
              {isEditingSelf && (
                <span className="text-xs text-amber-600 ml-2">
                  (no puedes desactivar tu propio usuario)
                </span>
              )}
            </Label>
            <select
              id="is_active"
              value={formData.is_active ? 'true' : 'false'}
              onChange={(e) => setFormData({ ...formData, is_active: e.target.value === 'true' })}
              disabled={isLoading || isEditingSelf}
              className="w-full px-3 py-2 border rounded-md disabled:bg-gray-100 disabled:cursor-not-allowed"
            >
              <option value="true">Activo</option>
              <option value="false">Inactivo</option>
            </select>
            {isEditingSelf && (
              <p className="text-xs text-gray-500">
                Por seguridad, no puedes cambiar el estado de tu propio usuario.
              </p>
            )}
          </div>
        )}
      </div>

      <Alert>
        <AlertCircle className="h-4 w-4" />
        <AlertDescription className="text-xs">
          <strong>Nota:</strong> Si no se especifica una zona horaria, el usuario heredará
          la zona horaria de su organización ({inheritedTimezone}). Los administradores sin
          organización usarán UTC por defecto.
        </AlertDescription>
      </Alert>

      <div className="flex justify-end space-x-3">
        <Button type="button" variant="outline" onClick={onCancel} disabled={isLoading}>
          Cancelar
        </Button>
        <Button type="submit" disabled={isLoading}>
          {isLoading ? (isEdit ? 'Actualizando...' : 'Creando...') : (isEdit ? 'Actualizar' : 'Crear')}
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
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <Card className="max-w-md w-full">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-red-600">Confirmar Eliminación</CardTitle>
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
            ¿Estás seguro de que deseas eliminar al usuario <strong>{user.full_name}</strong> ({user.email})?
          </p>

          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              Esta acción no se puede deshacer. Todos los datos asociados al usuario se perderán.
            </AlertDescription>
          </Alert>

          <div className="flex justify-end space-x-3">
            <Button variant="outline" onClick={onCancel} disabled={isLoading}>
              Cancelar
            </Button>
            <Button 
              variant="destructive" 
              onClick={onConfirm} 
              disabled={isLoading}
            >
              {isLoading ? 'Eliminando...' : 'Eliminar Usuario'}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
