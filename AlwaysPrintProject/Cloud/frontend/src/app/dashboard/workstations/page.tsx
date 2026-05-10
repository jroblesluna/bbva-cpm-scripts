/**
 * Página de gestión de workstations.
 * 
 * Accesible para Admin (todas las cuentas) y Operador (su cuenta).
 * Incluye listado con filtros, detalle, y asignación a cuentas.
 */

'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { workstationsApi, accountsApi } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { 
  Monitor, 
  Search, 
  Filter,
  AlertCircle,
  CheckCircle,
  XCircle,
  Network,
  Building2,
  User,
  Calendar,
  Activity,
  Edit,
  RefreshCw
} from 'lucide-react'
import { formatDateWithTimezone } from '@/lib/dateUtils'
import { useUserTimezone } from '@/hooks/useUserTimezone'
import type { Workstation, WorkstationUpdate, Account } from '@/types'

export default function WorkstationsPage() {
  const queryClient = useQueryClient()
  const userTimezone = useUserTimezone()
  const [searchTerm, setSearchTerm] = useState('')
  const [filterOnline, setFilterOnline] = useState<boolean | undefined>(undefined)
  const [filterContingency, setFilterContingency] = useState<boolean | undefined>(undefined)
  const [filterAccountId, setFilterAccountId] = useState<string | undefined>(undefined)
  const [selectedWorkstation, setSelectedWorkstation] = useState<Workstation | null>(null)
  const [editingWorkstation, setEditingWorkstation] = useState<Workstation | null>(null)

  // Query para listar workstations
  const { data: workstationsData, isLoading, error } = useQuery({
    queryKey: ['workstations', searchTerm, filterOnline, filterContingency, filterAccountId],
    queryFn: () => workstationsApi.list({
      search: searchTerm || undefined,
      is_online: filterOnline,
      contingency_active: filterContingency,
      account_id: filterAccountId,
    }),
  })

  // Query para estadísticas
  const { data: stats } = useQuery({
    queryKey: ['workstations', 'stats'],
    queryFn: () => workstationsApi.stats(),
  })

  // Query para cuentas (para filtro)
  const { data: accounts } = useQuery({
    queryKey: ['accounts'],
    queryFn: () => accountsApi.list(),
  })

  // Mutation para actualizar workstation
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: WorkstationUpdate }) =>
      workstationsApi.update(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workstations'] })
      setEditingWorkstation(null)
    },
  })

  const workstations = workstationsData?.items || []

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-8">Workstations</h1>
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
        <h1 className="text-3xl font-bold text-gray-900 mb-8">Workstations</h1>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Error al cargar workstations. Por favor, intenta de nuevo.
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
          <h1 className="text-3xl font-bold text-gray-900">Workstations</h1>
          <p className="text-gray-600 mt-2">
            Gestiona las estaciones de trabajo conectadas al sistema
          </p>
        </div>
        <Button onClick={() => queryClient.invalidateQueries({ queryKey: ['workstations'] })}>
          <RefreshCw className="w-4 h-4 mr-2" />
          Actualizar
        </Button>
      </div>

      {/* Estadísticas */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-6">
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">Total</p>
                  <p className="text-3xl font-bold text-gray-900">{stats.total}</p>
                </div>
                <Monitor className="w-12 h-12 text-blue-600" />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">En Línea</p>
                  <p className="text-3xl font-bold text-green-600">{stats.online}</p>
                </div>
                <CheckCircle className="w-12 h-12 text-green-600" />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">Fuera de Línea</p>
                  <p className="text-3xl font-bold text-gray-600">{stats.offline}</p>
                </div>
                <XCircle className="w-12 h-12 text-gray-400" />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-600">Contingencia</p>
                  <p className="text-3xl font-bold text-amber-600">{stats.contingency_active}</p>
                </div>
                <Activity className="w-12 h-12 text-amber-600" />
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Filtros */}
      <Card className="mb-6">
        <CardContent className="p-4">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            {/* Búsqueda */}
            <div className="md:col-span-2">
              <div className="flex items-center">
                <Search className="w-5 h-5 text-gray-400 mr-3" />
                <Input
                  type="text"
                  placeholder="Buscar por IP o hostname..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="flex-1"
                />
              </div>
            </div>

            {/* Filtro por estado */}
            <div>
              <select
                value={filterOnline === undefined ? 'all' : filterOnline ? 'online' : 'offline'}
                onChange={(e) => {
                  const value = e.target.value
                  setFilterOnline(value === 'all' ? undefined : value === 'online')
                }}
                className="w-full px-3 py-2 border rounded-md"
              >
                <option value="all">Todos los estados</option>
                <option value="online">En línea</option>
                <option value="offline">Fuera de línea</option>
              </select>
            </div>

            {/* Filtro por cuenta */}
            <div>
              <select
                value={filterAccountId || 'all'}
                onChange={(e) => {
                  const value = e.target.value
                  setFilterAccountId(value === 'all' ? undefined : value)
                }}
                className="w-full px-3 py-2 border rounded-md"
              >
                <option value="all">Todas las cuentas</option>
                {Array.isArray(accounts) && accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Filtros adicionales */}
          <div className="flex items-center space-x-4 mt-4">
            <label className="flex items-center space-x-2 cursor-pointer">
              <input
                type="checkbox"
                checked={filterContingency === true}
                onChange={(e) => setFilterContingency(e.target.checked ? true : undefined)}
                className="rounded"
              />
              <span className="text-sm text-gray-700">Solo en contingencia</span>
            </label>

            {(searchTerm || filterOnline !== undefined || filterContingency !== undefined || filterAccountId) && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setSearchTerm('')
                  setFilterOnline(undefined)
                  setFilterContingency(undefined)
                  setFilterAccountId(undefined)
                }}
              >
                Limpiar filtros
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Formulario de edición */}
      {editingWorkstation && (
        <Card className="mb-6 border-amber-200 bg-amber-50">
          <CardHeader>
            <CardTitle>Editar Workstation: {editingWorkstation.ip_private}</CardTitle>
          </CardHeader>
          <CardContent>
            <WorkstationForm
              workstation={editingWorkstation}
              accounts={accounts || []}
              onSubmit={(data) => updateMutation.mutate({ id: editingWorkstation.id, data })}
              onCancel={() => setEditingWorkstation(null)}
              isLoading={updateMutation.isPending}
              error={updateMutation.error?.detail}
            />
          </CardContent>
        </Card>
      )}

      {/* Lista de workstations */}
      <div className="space-y-4">
        {workstations.length > 0 ? (
          workstations.map((workstation) => (
            <Card key={workstation.id} className="hover:shadow-md transition">
              <CardContent className="p-6">
                <div className="flex items-start justify-between">
                  <div className="flex items-start flex-1">
                    <div className={`rounded-full p-3 mr-4 ${
                      workstation.is_online ? 'bg-green-100' : 'bg-gray-100'
                    }`}>
                      <Monitor className={`w-6 h-6 ${
                        workstation.is_online ? 'text-green-600' : 'text-gray-400'
                      }`} />
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center mb-2">
                        <h3 className="text-xl font-semibold text-gray-900 mr-3">
                          {workstation.ip_private}
                        </h3>
                        <Badge variant={workstation.is_online ? 'default' : 'secondary'}>
                          {workstation.is_online ? 'En línea' : 'Fuera de línea'}
                        </Badge>
                        {workstation.contingency_active && (
                          <Badge variant="destructive" className="ml-2">
                            Contingencia
                          </Badge>
                        )}
                      </div>

                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm text-gray-600 mb-3">
                        {workstation.hostname && (
                          <div className="flex items-center">
                            <Monitor className="w-4 h-4 mr-1" />
                            {workstation.hostname}
                          </div>
                        )}
                        {workstation.current_user && (
                          <div className="flex items-center">
                            <User className="w-4 h-4 mr-1" />
                            {workstation.current_user}
                          </div>
                        )}
                        {workstation.vlan_id && (
                          <div className="flex items-center">
                            <Network className="w-4 h-4 mr-1" />
                            VLAN: {workstation.vlan_id}
                          </div>
                        )}
                        {workstation.account && (
                          <div className="flex items-center">
                            <Building2 className="w-4 h-4 mr-1" />
                            {workstation.account.name}
                          </div>
                        )}
                      </div>

                      <div className="flex items-center text-xs text-gray-500 space-x-4">
                        <div className="flex items-center">
                          <Calendar className="w-3 h-3 mr-1" />
                          Registrada: {formatDateWithTimezone(workstation.first_seen, userTimezone)}
                        </div>
                        {workstation.last_connection && (
                          <div className="flex items-center">
                            <Activity className="w-3 h-3 mr-1" />
                            Última conexión: {formatDateWithTimezone(workstation.last_connection, userTimezone)}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center space-x-2 ml-4">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setSelectedWorkstation(workstation)}
                      title="Ver detalles"
                    >
                      Ver Detalles
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setEditingWorkstation(workstation)}
                      title="Editar workstation"
                    >
                      <Edit className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))
        ) : (
          <Card>
            <CardContent className="p-12 text-center">
              <Monitor className="w-16 h-16 text-gray-300 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-gray-900 mb-2">
                No hay workstations
              </h3>
              <p className="text-gray-600 mb-4">
                {searchTerm || filterOnline !== undefined || filterContingency !== undefined || filterAccountId
                  ? 'No se encontraron workstations con esos criterios de búsqueda.'
                  : 'Las workstations aparecerán aquí cuando se conecten al sistema.'}
              </p>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Modal de detalles */}
      {selectedWorkstation && (
        <WorkstationDetailModal
          workstation={selectedWorkstation}
          onClose={() => setSelectedWorkstation(null)}
        />
      )}
    </div>
  )
}

// Componente de formulario de edición
function WorkstationForm({
  workstation,
  accounts,
  onSubmit,
  onCancel,
  isLoading,
  error,
}: {
  workstation: Workstation
  accounts: Account[]
  onSubmit: (data: WorkstationUpdate) => void
  onCancel: () => void
  isLoading: boolean
  error?: string
}) {
  const [formData, setFormData] = useState<WorkstationUpdate>({
    hostname: workstation.hostname || undefined,
    os_serial: workstation.os_serial || undefined,
    current_user: workstation.current_user || undefined,
    account_id: workstation.account_id || undefined,
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
          <Label htmlFor="hostname">Hostname</Label>
          <Input
            id="hostname"
            type="text"
            placeholder="DESKTOP-ABC123"
            value={formData.hostname || ''}
            onChange={(e) => setFormData({ ...formData, hostname: e.target.value || undefined })}
            disabled={isLoading}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="os_serial">Serial del SO</Label>
          <Input
            id="os_serial"
            type="text"
            placeholder="XXXXX-XXXXX-XXXXX"
            value={formData.os_serial || ''}
            onChange={(e) => setFormData({ ...formData, os_serial: e.target.value || undefined })}
            disabled={isLoading}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="current_user">Usuario Actual</Label>
          <Input
            id="current_user"
            type="text"
            placeholder="usuario@dominio.com"
            value={formData.current_user || ''}
            onChange={(e) => setFormData({ ...formData, current_user: e.target.value || undefined })}
            disabled={isLoading}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="account_id">Cuenta</Label>
          <select
            id="account_id"
            value={formData.account_id || ''}
            onChange={(e) => setFormData({ ...formData, account_id: e.target.value || undefined })}
            disabled={isLoading}
            className="w-full px-3 py-2 border rounded-md"
          >
            <option value="">Sin asignar</option>
            {Array.isArray(accounts) && accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <Alert>
        <AlertCircle className="h-4 w-4" />
        <AlertDescription className="text-xs">
          <strong>Nota:</strong> La asignación de cuenta también puede hacerse automáticamente
          cuando la workstation se conecta desde una IP pública registrada en una cuenta.
        </AlertDescription>
      </Alert>

      <div className="flex justify-end space-x-3">
        <Button type="button" variant="outline" onClick={onCancel} disabled={isLoading}>
          Cancelar
        </Button>
        <Button type="submit" disabled={isLoading}>
          {isLoading ? 'Actualizando...' : 'Actualizar'}
        </Button>
      </div>
    </form>
  )
}

// Modal de detalles de workstation
function WorkstationDetailModal({
  workstation,
  onClose,
}: {
  workstation: Workstation
  onClose: () => void
}) {
  const userTimezone = useUserTimezone()
  
  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <Card className="max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Detalles de Workstation</CardTitle>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <XCircle className="w-5 h-5" />
          </Button>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Estado */}
          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-2">Estado</h3>
            <div className="flex items-center space-x-2">
              <Badge variant={workstation.is_online ? 'default' : 'secondary'}>
                {workstation.is_online ? 'En línea' : 'Fuera de línea'}
              </Badge>
              {workstation.contingency_active && (
                <Badge variant="destructive">Contingencia Activa</Badge>
              )}
            </div>
          </div>

          {/* Información de red */}
          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-2">Información de Red</h3>
            <dl className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <dt className="text-gray-600">IP Privada</dt>
                <dd className="font-mono font-medium">{workstation.ip_private}</dd>
              </div>
              {workstation.vlan_id && (
                <div>
                  <dt className="text-gray-600">VLAN</dt>
                  <dd className="font-medium">{workstation.vlan_id}</dd>
                </div>
              )}
            </dl>
          </div>

          {/* Información del sistema */}
          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-2">Información del Sistema</h3>
            <dl className="grid grid-cols-2 gap-4 text-sm">
              {workstation.hostname && (
                <div>
                  <dt className="text-gray-600">Hostname</dt>
                  <dd className="font-medium">{workstation.hostname}</dd>
                </div>
              )}
              {workstation.os_serial && (
                <div>
                  <dt className="text-gray-600">Serial del SO</dt>
                  <dd className="font-mono text-xs">{workstation.os_serial}</dd>
                </div>
              )}
              {workstation.current_user && (
                <div>
                  <dt className="text-gray-600">Usuario Actual</dt>
                  <dd className="font-medium">{workstation.current_user}</dd>
                </div>
              )}
            </dl>
          </div>

          {/* Cuenta */}
          {workstation.account && (
            <div>
              <h3 className="text-sm font-medium text-gray-700 mb-2">Cuenta</h3>
              <div className="flex items-center">
                <Building2 className="w-5 h-5 text-blue-600 mr-2" />
                <span className="font-medium">{workstation.account.name}</span>
              </div>
            </div>
          )}

          {/* Fechas */}
          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-2">Fechas</h3>
            <dl className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <dt className="text-gray-600">Primera Conexión</dt>
                <dd className="font-medium">
                  {formatDateWithTimezone(workstation.first_seen, userTimezone)}
                </dd>
              </div>
              {workstation.last_connection && (
                <div>
                  <dt className="text-gray-600">Última Conexión</dt>
                  <dd className="font-medium">
                    {formatDateWithTimezone(workstation.last_connection, userTimezone)}
                  </dd>
                </div>
              )}
            </dl>
          </div>

          {/* ID */}
          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-2">ID</h3>
            <code className="text-xs bg-gray-100 px-2 py-1 rounded">
              {workstation.id}
            </code>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
