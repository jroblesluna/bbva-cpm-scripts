/**
 * Página de gestión de IPs públicas pendientes de autorización.
 * 
 * Solo accesible para administradores.
 * Permite autorizar o rechazar IPs desde las cuales clientes intentaron conectarse.
 */

'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { 
  Globe, 
  CheckCircle, 
  XCircle, 
  Clock,
  AlertCircle,
  RefreshCw,
  Search,
  Building2
} from 'lucide-react'
import { formatDateWithTimezone } from '@/lib/dateUtils'
import { useUserTimezone } from '@/hooks/useUserTimezone'

interface PendingIP {
  id: string
  ip_address: string
  description: string | null
  first_seen: string
  created_at: string
}

interface Account {
  id: string
  name: string
  is_active: boolean
}

export default function PendingIPsPage() {
  const queryClient = useQueryClient()
  const userTimezone = useUserTimezone()
  const [searchTerm, setSearchTerm] = useState('')
  const [authorizingIP, setAuthorizingIP] = useState<PendingIP | null>(null)
  const [selectedAccountId, setSelectedAccountId] = useState('')
  const [customDescription, setCustomDescription] = useState('')

  // Query para IPs pendientes
  const { data: pendingIPs, isLoading, error } = useQuery({
    queryKey: ['pending-ips'],
    queryFn: async () => {
      const response = await api.get('/accounts/public-ips/pending')
      return response.data as PendingIP[]
    },
  })

  // Query para cuentas
  const { data: accountsData } = useQuery({
    queryKey: ['accounts'],
    queryFn: async () => {
      const response = await api.get('/accounts/')
      return response.data
    },
  })

  // Mutation para autorizar IP
  const authorizeMutation = useMutation({
    mutationFn: async ({ ipId, accountId, description }: { ipId: string; accountId: string; description?: string }) => {
      const response = await api.post(`/accounts/public-ips/${ipId}/authorize`, {
        account_id: accountId,
        description: description || undefined,
      })
      return response.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pending-ips'] })
      queryClient.invalidateQueries({ queryKey: ['accounts'] })
      setAuthorizingIP(null)
      setSelectedAccountId('')
      setCustomDescription('')
    },
  })

  // Mutation para rechazar IP
  const rejectMutation = useMutation({
    mutationFn: async (ipId: string) => {
      await api.delete(`/accounts/public-ips/${ipId}/reject`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pending-ips'] })
    },
  })

  const handleAuthorize = () => {
    if (!authorizingIP || !selectedAccountId) return
    
    authorizeMutation.mutate({
      ipId: authorizingIP.id,
      accountId: selectedAccountId,
      description: customDescription || undefined,
    })
  }

  const handleReject = (ip: PendingIP) => {
    if (confirm(`¿Estás seguro de rechazar la IP ${ip.ip_address}? Esta acción no se puede deshacer.`)) {
      rejectMutation.mutate(ip.id)
    }
  }

  // Filtrar IPs por búsqueda
  const filteredIPs = pendingIPs?.filter(ip =>
    ip.ip_address.toLowerCase().includes(searchTerm.toLowerCase())
  ) || []

  const accounts = accountsData?.items || []

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto">
        <h1 className="text-3xl font-bold text-gray-900 mb-8">IPs Públicas Pendientes</h1>
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
        <h1 className="text-3xl font-bold text-gray-900 mb-8">IPs Públicas Pendientes</h1>
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Error al cargar IPs pendientes. Por favor, intenta de nuevo.
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
          <h1 className="text-3xl font-bold text-gray-900">IPs Públicas Pendientes</h1>
          <p className="text-gray-600 mt-2">
            Autoriza o rechaza IPs desde las cuales clientes intentaron conectarse
          </p>
        </div>
        <Button onClick={() => queryClient.invalidateQueries({ queryKey: ['pending-ips'] })}>
          <RefreshCw className="w-4 h-4 mr-2" />
          Actualizar
        </Button>
      </div>

      {/* Estadísticas */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Total Pendientes</p>
                <p className="text-3xl font-bold text-gray-900">{pendingIPs?.length || 0}</p>
              </div>
              <Clock className="w-12 h-12 text-amber-600" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Cuentas Activas</p>
                <p className="text-3xl font-bold text-gray-900">{accounts.filter((a: Account) => a.is_active).length}</p>
              </div>
              <Building2 className="w-12 h-12 text-blue-600" />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Filtradas</p>
                <p className="text-3xl font-bold text-gray-900">{filteredIPs.length}</p>
              </div>
              <Search className="w-12 h-12 text-green-600" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Búsqueda */}
      <Card className="mb-6">
        <CardContent className="p-4">
          <div className="flex items-center">
            <Search className="w-5 h-5 text-gray-400 mr-3" />
            <Input
              type="text"
              placeholder="Buscar por dirección IP..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="flex-1"
            />
          </div>
        </CardContent>
      </Card>

      {/* Lista de IPs pendientes */}
      <div className="space-y-4">
        {filteredIPs.length > 0 ? (
          filteredIPs.map((ip) => (
            <Card key={ip.id} className="hover:shadow-md transition">
              <CardContent className="p-6">
                <div className="flex items-start justify-between">
                  <div className="flex items-start flex-1">
                    <div className="rounded-full p-3 bg-amber-100 mr-4">
                      <Globe className="w-6 h-6 text-amber-600" />
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center mb-2">
                        <h3 className="text-xl font-semibold text-gray-900 mr-3">
                          {ip.ip_address}
                        </h3>
                        <Badge variant="secondary">
                          <Clock className="w-3 h-3 mr-1" />
                          Pendiente
                        </Badge>
                      </div>

                      {ip.description && (
                        <p className="text-sm text-gray-600 mb-2">{ip.description}</p>
                      )}

                      <div className="flex items-center text-xs text-gray-500 space-x-4">
                        <div className="flex items-center">
                          <Clock className="w-3 h-3 mr-1" />
                          Primera vez: {formatDateWithTimezone(ip.first_seen, userTimezone)}
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center space-x-2 ml-4">
                    <Button
                      variant="default"
                      size="sm"
                      onClick={() => setAuthorizingIP(ip)}
                      disabled={authorizeMutation.isPending || rejectMutation.isPending}
                    >
                      <CheckCircle className="w-4 h-4 mr-1" />
                      Autorizar
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      onClick={() => handleReject(ip)}
                      disabled={authorizeMutation.isPending || rejectMutation.isPending}
                    >
                      <XCircle className="w-4 h-4 mr-1" />
                      Rechazar
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))
        ) : (
          <Card>
            <CardContent className="p-12 text-center">
              <Globe className="w-16 h-16 text-gray-300 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-gray-900 mb-2">
                No hay IPs pendientes
              </h3>
              <p className="text-gray-600 mb-4">
                {searchTerm
                  ? 'No se encontraron IPs con ese criterio de búsqueda.'
                  : 'Todas las IPs han sido autorizadas o rechazadas.'}
              </p>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Modal de autorización */}
      {authorizingIP && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <Card className="max-w-md w-full">
            <CardHeader>
              <CardTitle>Autorizar IP Pública</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <Alert>
                <Globe className="h-4 w-4" />
                <AlertDescription>
                  <strong>IP:</strong> {authorizingIP.ip_address}
                </AlertDescription>
              </Alert>

              {authorizeMutation.error && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>
                    {(authorizeMutation.error as any)?.response?.data?.detail || 'Error al autorizar IP'}
                  </AlertDescription>
                </Alert>
              )}

              <div className="space-y-2">
                <Label htmlFor="account">Cuenta *</Label>
                <select
                  id="account"
                  value={selectedAccountId}
                  onChange={(e) => setSelectedAccountId(e.target.value)}
                  className="w-full px-3 py-2 border rounded-md"
                  disabled={authorizeMutation.isPending}
                >
                  <option value="">Selecciona una cuenta...</option>
                  {accounts
                    .filter((account: Account) => account.is_active)
                    .map((account: Account) => (
                      <option key={account.id} value={account.id}>
                        {account.name}
                      </option>
                    ))}
                </select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="description">Descripción (opcional)</Label>
                <Input
                  id="description"
                  type="text"
                  placeholder="Ej: Oficina Principal Lima"
                  value={customDescription}
                  onChange={(e) => setCustomDescription(e.target.value)}
                  disabled={authorizeMutation.isPending}
                />
              </div>

              <div className="flex justify-end space-x-3">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setAuthorizingIP(null)
                    setSelectedAccountId('')
                    setCustomDescription('')
                  }}
                  disabled={authorizeMutation.isPending}
                >
                  Cancelar
                </Button>
                <Button
                  type="button"
                  onClick={handleAuthorize}
                  disabled={!selectedAccountId || authorizeMutation.isPending}
                >
                  {authorizeMutation.isPending ? 'Autorizando...' : 'Autorizar'}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
