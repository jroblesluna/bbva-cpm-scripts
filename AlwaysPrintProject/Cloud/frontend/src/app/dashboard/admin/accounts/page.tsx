/**
 * Página de gestión de organizaciones.
 * 
 * Solo accesible para administradores.
 * Incluye gestión de IPs públicas para auto-asignación de workstations.
 */

'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { accountsApi } from '@/lib/api'
import { COMMON_TIMEZONES, formatDateWithTimezone, getTimezoneName } from '@/lib/dateUtils'
import { useUserTimezone } from '@/hooks/useUserTimezone'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { 
  Building2, 
  Plus, 
  Search, 
  Edit, 
  Trash2, 
  Globe,
  AlertCircle,
  CheckCircle,
  X,
  Network,
  Users,
  Monitor
} from 'lucide-react'
import type { Account, AccountCreate, AccountUpdate, PublicIPCreate } from '@/types'

export default function AccountsPage() {
  const queryClient = useQueryClient()
  const userTimezone = useUserTimezone()
  const [searchTerm, setSearchTerm] = useState('')
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [editingAccount, setEditingAccount] = useState<Account | null>(null)
  const [managingIPsAccount, setManagingIPsAccount] = useState<Account | null>(null)

  // Query para listar cuentas
  const { data: accounts, isLoading, error } = useQuery({
    queryKey: ['accounts'],
    queryFn: () => accountsApi.list(),
  })

  // Mutation para crear cuenta
  const createMutation = useMutation({
    mutationFn: (data: AccountCreate) => accountsApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      setShowCreateForm(false)
    },
  })

  // Mutation para actualizar cuenta
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: AccountUpdate }) => 
      accountsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      setEditingAccount(null)
    },
  })

  // Mutation para eliminar cuenta
  const deleteMutation = useMutation({
    mutationFn: (id: string) => accountsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
    },
  })

  // Mutation para agregar IP pública
  const addIPMutation = useMutation({
    mutationFn: ({ accountId, data }: { accountId: string; data: PublicIPCreate }) =>
      accountsApi.addPublicIP(accountId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
    },
  })

  // Mutation para eliminar IP pública
  const removeIPMutation = useMutation({
    mutationFn: ({ accountId, ipId }: { accountId: string; ipId: string }) =>
      accountsApi.removePublicIP(accountId, ipId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
    },
  })

  // Filtrar cuentas por búsqueda
  const filteredAccounts = Array.isArray(accounts) 
    ? accounts.filter(account =>
        account.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        account.description?.toLowerCase().includes(searchTerm.toLowerCase())
      )
    : []

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-8">Organizaciones</h1>
        <div className="animate-pulse space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-32 bg-gray-200 rounded-lg"></div>
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="max-w-7xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-8">Organizaciones</h1>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Error al cargar organizaciones. Por favor, intenta de nuevo.
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
          <h1 className="text-3xl font-bold text-gray-900">Organizaciones</h1>
          <p className="text-gray-600 mt-2">
            Gestiona las organizaciones que usan el sistema (BBVA, Ripley, etc.)
          </p>
        </div>
        <Button onClick={() => setShowCreateForm(true)}>
          <Plus className="w-4 h-4 mr-2" />
          Nueva Organización
        </Button>
      </div>

      {/* Barra de búsqueda */}
      <Card className="mb-6">
        <CardContent className="p-4">
          <div className="flex items-center">
            <Search className="w-5 h-5 text-gray-400 mr-3" />
            <Input
              type="text"
              placeholder="Buscar por nombre o descripción..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="flex-1"
            />
          </div>
        </CardContent>
      </Card>

      {/* Formulario de creación */}
      {showCreateForm && (
        <Card className="mb-6 border-blue-200 bg-blue-50">
          <CardHeader>
            <CardTitle>Nueva Organización</CardTitle>
          </CardHeader>
          <CardContent>
            <AccountForm
              onSubmit={(data) => createMutation.mutate(data as AccountCreate)}
              onCancel={() => setShowCreateForm(false)}
              isLoading={createMutation.isPending}
              error={createMutation.error?.detail}
            />
          </CardContent>
        </Card>
      )}

      {/* Formulario de edición */}
      {editingAccount && (
        <Card className="mb-6 border-amber-200 bg-amber-50">
          <CardHeader>
            <CardTitle>Editar Organización: {editingAccount.name}</CardTitle>
          </CardHeader>
          <CardContent>
            <AccountForm
              initialData={editingAccount}
              onSubmit={(data) => updateMutation.mutate({ id: editingAccount.id, data })}
              onCancel={() => setEditingAccount(null)}
              isLoading={updateMutation.isPending}
              error={updateMutation.error?.detail}
            />
          </CardContent>
        </Card>
      )}

      {/* Modal de gestión de IPs */}
      {managingIPsAccount && (
        <Card className="mb-6 border-green-200 bg-green-50">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Gestionar IPs Públicas: {managingIPsAccount.name}</CardTitle>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setManagingIPsAccount(null)}
            >
              <X className="w-4 h-4" />
            </Button>
          </CardHeader>
          <CardContent>
            <IPManagementForm
              account={managingIPsAccount}
              onAddIP={(data) => addIPMutation.mutate({ accountId: managingIPsAccount.id, data })}
              onRemoveIP={(ipId) => removeIPMutation.mutate({ accountId: managingIPsAccount.id, ipId })}
              isLoading={addIPMutation.isPending || removeIPMutation.isPending}
              error={addIPMutation.error?.detail || removeIPMutation.error?.detail}
            />
          </CardContent>
        </Card>
      )}

      {/* Lista de cuentas */}
      <div className="space-y-4">
        {filteredAccounts && filteredAccounts.length > 0 ? (
          filteredAccounts.map((account) => (
            <Card key={account.id} className="hover:shadow-md transition">
              <CardContent className="p-6">
                <div className="flex items-start justify-between">
                  <div className="flex items-start flex-1">
                    <div className="bg-blue-100 rounded-full p-3 mr-4">
                      <Building2 className="w-6 h-6 text-blue-600" />
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center mb-2">
                        <h3 className="text-xl font-semibold text-gray-900 mr-3">
                          {account.name}
                        </h3>
                        <Badge variant={account.is_active ? 'default' : 'secondary'}>
                          {account.is_active ? 'Activa' : 'Inactiva'}
                        </Badge>
                      </div>
                      
                      {account.description && (
                        <p className="text-gray-600 mb-3">{account.description}</p>
                      )}

                      <div className="flex items-center text-sm text-gray-500 space-x-4">
                        <div className="flex items-center">
                          <Globe className="w-4 h-4 mr-1" />
                          {account.public_ips?.length || 0} IPs públicas
                        </div>
                        <div className="flex items-center">
                          <Monitor className="w-4 h-4 mr-1" />
                          Workstations (por implementar)
                        </div>
                        <div className="flex items-center">
                          <Users className="w-4 h-4 mr-1" />
                          Usuarios (por implementar)
                        </div>
                        <div className="flex items-center">
                          <CheckCircle className="w-4 h-4 mr-1" />
                          Creada: {formatDateWithTimezone(account.created_at, userTimezone)}
                        </div>
                      </div>

                      {/* IPs públicas */}
                      {account.public_ips && account.public_ips.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {account.public_ips.map((ip) => (
                            <Badge key={ip.id} variant="outline" className="text-xs">
                              {ip.ip_address}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center space-x-2 ml-4">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setManagingIPsAccount(account)}
                      title="Gestionar IPs públicas"
                    >
                      <Network className="w-4 h-4 mr-1" />
                      IPs
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setEditingAccount(account)}
                      title="Editar cuenta"
                    >
                      <Edit className="w-4 h-4" />
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        if (confirm(`¿Eliminar la cuenta "${account.name}"? Esta acción eliminará todos los usuarios, workstations y configuraciones asociadas. No se puede deshacer.`)) {
                          deleteMutation.mutate(account.id)
                        }
                      }}
                      disabled={deleteMutation.isPending}
                      title="Eliminar cuenta"
                    >
                      <Trash2 className="w-4 h-4 text-red-600" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))
        ) : (
          <Card>
            <CardContent className="p-12 text-center">
              <Building2 className="w-16 h-16 text-gray-300 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-gray-900 mb-2">
                No hay cuentas
              </h3>
              <p className="text-gray-600 mb-4">
                {searchTerm
                  ? 'No se encontraron cuentas con ese criterio de búsqueda.'
                  : 'Comienza creando la primera cuenta del sistema.'}
              </p>
              {!searchTerm && (
                <Button onClick={() => setShowCreateForm(true)}>
                  <Plus className="w-4 h-4 mr-2" />
                  Nueva Cuenta
                </Button>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}

// Componente de formulario de cuenta (crear/editar)
function AccountForm({
  initialData,
  onSubmit,
  onCancel,
  isLoading,
  error,
}: {
  initialData?: Account
  onSubmit: (data: AccountCreate | AccountUpdate) => void
  onCancel: () => void
  isLoading: boolean
  error?: string
}) {
  const [formData, setFormData] = useState<AccountCreate>({
    name: initialData?.name || '',
    description: initialData?.description || '',
    is_active: initialData?.is_active ?? true,
    timezone: initialData?.timezone || 'UTC',
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit(formData)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="name">Nombre *</Label>
          <Input
            id="name"
            type="text"
            placeholder="BBVA, Ripley, etc."
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            required
            disabled={isLoading}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="description">Descripción</Label>
          <Input
            id="description"
            type="text"
            placeholder="Descripción de la organización"
            value={formData.description || ''}
            onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            disabled={isLoading}
          />
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="timezone">Zona Horaria *</Label>
        <select
          id="timezone"
          value={formData.timezone}
          onChange={(e) => setFormData({ ...formData, timezone: e.target.value })}
          disabled={isLoading}
          className="w-full px-3 py-2 border rounded-md"
          required
        >
          {COMMON_TIMEZONES.map((tz) => (
            <option key={tz.value} value={tz.value}>
              {tz.label}
            </option>
          ))}
        </select>
        <p className="text-xs text-gray-500">
          Los usuarios de esta organización heredarán esta zona horaria por defecto
        </p>
      </div>

      <div className="flex items-center space-x-2">
        <input
          type="checkbox"
          id="is_active"
          checked={formData.is_active}
          onChange={(e) => setFormData({ ...formData, is_active: e.target.checked })}
          disabled={isLoading}
          className="rounded"
        />
        <Label htmlFor="is_active" className="cursor-pointer">
          Organización activa
        </Label>
      </div>

      <div className="flex justify-end space-x-3">
        <Button type="button" variant="outline" onClick={onCancel} disabled={isLoading}>
          Cancelar
        </Button>
        <Button type="submit" disabled={isLoading}>
          {isLoading ? (initialData ? 'Actualizando...' : 'Creando...') : (initialData ? 'Actualizar' : 'Crear Organización')}
        </Button>
      </div>
    </form>
  )
}

// Componente de gestión de IPs públicas
function IPManagementForm({
  account,
  onAddIP,
  onRemoveIP,
  isLoading,
  error,
}: {
  account: Account
  onAddIP: (data: PublicIPCreate) => void
  onRemoveIP: (ipId: string) => void
  isLoading: boolean
  error?: string
}) {
  const [newIP, setNewIP] = useState('')
  const [newIPDescription, setNewIPDescription] = useState('')

  const handleAddIP = (e: React.FormEvent) => {
    e.preventDefault()
    
    // Validación básica de IP
    const ipRegex = /^(\d{1,3}\.){3}\d{1,3}$/
    if (!ipRegex.test(newIP)) {
      alert('Por favor, ingresa una dirección IP válida (ej: 192.168.1.1)')
      return
    }

    onAddIP({
      ip_address: newIP,
      description: newIPDescription || undefined,
    })

    // Limpiar formulario
    setNewIP('')
    setNewIPDescription('')
  }

  return (
    <div className="space-y-6">
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Formulario para agregar IP */}
      <div className="border-b pb-4">
        <h3 className="text-sm font-medium text-gray-900 mb-3">Agregar Nueva IP Pública</h3>
        <form onSubmit={handleAddIP} className="space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label htmlFor="ip_address">Dirección IP *</Label>
              <Input
                id="ip_address"
                type="text"
                placeholder="192.168.1.1"
                value={newIP}
                onChange={(e) => setNewIP(e.target.value)}
                required
                disabled={isLoading}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="ip_description">Descripción</Label>
              <Input
                id="ip_description"
                type="text"
                placeholder="Oficina principal, sucursal, etc."
                value={newIPDescription}
                onChange={(e) => setNewIPDescription(e.target.value)}
                disabled={isLoading}
              />
            </div>
          </div>

          <div className="flex justify-end">
            <Button type="submit" disabled={isLoading} size="sm">
              <Plus className="w-4 h-4 mr-2" />
              Agregar IP
            </Button>
          </div>
        </form>
      </div>

      {/* Lista de IPs existentes */}
      <div>
        <h3 className="text-sm font-medium text-gray-900 mb-3">
          IPs Públicas Registradas ({account.public_ips?.length || 0})
        </h3>
        
        {account.public_ips && account.public_ips.length > 0 ? (
          <div className="space-y-2">
            {account.public_ips.map((ip) => (
              <div
                key={ip.id}
                className="flex items-center justify-between p-3 bg-white border rounded-lg hover:shadow-sm transition"
              >
                <div className="flex items-center flex-1">
                  <Globe className="w-5 h-5 text-blue-600 mr-3" />
                  <div>
                    <p className="font-mono text-sm font-medium text-gray-900">
                      {ip.ip_address}
                    </p>
                    {ip.description && (
                      <p className="text-xs text-gray-500">{ip.description}</p>
                    )}
                  </div>
                </div>

                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    if (confirm(`¿Eliminar la IP ${ip.ip_address}? Las workstations que se conecten desde esta IP ya no se asignarán automáticamente a esta cuenta.`)) {
                      onRemoveIP(ip.id)
                    }
                  }}
                  disabled={isLoading}
                >
                  <Trash2 className="w-4 h-4 text-red-600" />
                </Button>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-8 bg-gray-50 rounded-lg border-2 border-dashed">
            <Globe className="w-12 h-12 text-gray-300 mx-auto mb-3" />
            <p className="text-sm text-gray-600">
              No hay IPs públicas registradas para esta cuenta.
            </p>
            <p className="text-xs text-gray-500 mt-1">
              Agrega IPs para que las workstations se asignen automáticamente.
            </p>
          </div>
        )}
      </div>

      {/* Información adicional */}
      <Alert>
        <AlertCircle className="h-4 w-4" />
        <AlertDescription className="text-xs">
          <strong>Auto-asignación:</strong> Cuando una workstation se conecta desde una de estas IPs públicas,
          se asignará automáticamente a esta cuenta. Esto permite gestionar múltiples sucursales u oficinas.
        </AlertDescription>
      </Alert>
    </div>
  )
}
