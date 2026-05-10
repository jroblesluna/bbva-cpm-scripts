/**
 * Página de configuración global de la organización.
 * 
 * Permite configurar parámetros que se aplican a todas las workstations:
 * - Nombre de la cola corporativa
 * - Objetivos de búsqueda de impresoras (IPs y rangos)
 * - Intervalo de polling de tareas pendientes
 * - Dominios de bootstrap
 */

'use client'

import { useState, useEffect } from 'react'
import { useAuth } from '@/hooks/useAuth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  Settings,
  Save,
  RotateCcw,
  Plus,
  X,
  Info,
  AlertCircle,
} from 'lucide-react'
import type { GlobalConfig, GlobalConfigUpdate, SearchTargets } from '@/types/config'

interface Account {
  id: string
  name: string
  timezone: string
}

export default function ConfigPage() {
  const { user, getAuthHeaders } = useAuth()
  const [config, setConfig] = useState<GlobalConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hasChanges, setHasChanges] = useState(false)

  // Selector de organización (solo para Admin)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [selectedAccountId, setSelectedAccountId] = useState<string>('')
  const [loadingAccounts, setLoadingAccounts] = useState(false)

  // Form state
  const [corporateQueueName, setCorporateQueueName] = useState('')
  const [pollingMinutes, setPollingMinutes] = useState(5)
  const [bootstrapDomains, setBootstrapDomains] = useState('')
  const [searchIps, setSearchIps] = useState<string[]>([''])
  const [searchRanges, setSearchRanges] = useState<string[]>([''])

  // Cargar organizaciones (solo para Admin)
  useEffect(() => {
    if (user?.role === 'admin') {
      loadAccounts()
    } else if (user?.role === 'operator' || user?.role === 'readonly') {
      // Para operadores, cargar configuración inmediatamente
      loadConfig()
    }
  }, [user])

  // Cargar configuración cuando se selecciona una organización (solo Admin)
  useEffect(() => {
    if (user?.role === 'admin' && selectedAccountId) {
      loadConfig()
    }
  }, [selectedAccountId])

  const loadAccounts = async () => {
    try {
      setLoadingAccounts(true)
      const response = await fetch('http://localhost:8000/api/v1/accounts/?skip=0&limit=1000', {
        headers: getAuthHeaders(),
      })

      if (!response.ok) {
        throw new Error('Error al cargar organizaciones')
      }

      const data = await response.json()
      setAccounts(data.items || [])
      
      // Seleccionar la primera organización por defecto
      if (data.items && data.items.length > 0) {
        setSelectedAccountId(data.items[0].id)
      }
    } catch (error) {
      console.error('Error:', error)
      alert('Error al cargar organizaciones')
    } finally {
      setLoadingAccounts(false)
    }
  }

  const loadConfig = async () => {
    try {
      setLoading(true)
      
      // Construir URL con account_id si es Admin
      let url = 'http://localhost:8000/api/v1/config/global'
      if (user?.role === 'admin') {
        if (!selectedAccountId) {
          setLoading(false)
          return
        }
        url += `?account_id=${selectedAccountId}`
      }
      
      const response = await fetch(url, {
        headers: getAuthHeaders(),
      })

      if (!response.ok) {
        if (response.status === 404) {
          // No hay configuración, usar valores por defecto (esto es normal)
          console.log('No existe configuración global para esta organización')
          setConfig(null)
          // Resetear formulario a valores por defecto
          setCorporateQueueName('')
          setPollingMinutes(5)
          setBootstrapDomains('')
          setSearchIps([''])
          setSearchRanges([''])
          setHasChanges(false)
          return
        }
        const errorData = await response.json().catch(() => ({ detail: 'Error desconocido' }))
        throw new Error(errorData.detail || 'Error al cargar configuración')
      }

      const data: GlobalConfig = await response.json()
      setConfig(data)

      // Cargar valores en el formulario
      setCorporateQueueName(data.corporate_queue_name)
      setPollingMinutes(data.pending_task_polling_minutes)
      setBootstrapDomains(data.bootstrap_domains)

      if (data.search_targets) {
        setSearchIps(data.search_targets.ips || [''])
        setSearchRanges(data.search_targets.ranges || [''])
      } else {
        setSearchIps([''])
        setSearchRanges([''])
      }
      
      setHasChanges(false)
    } catch (error: any) {
      console.error('Error al cargar configuración:', error)
      alert(error.message || 'Error al cargar configuración')
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    // Validar
    if (!corporateQueueName.trim()) {
      alert('El nombre de la cola corporativa es requerido')
      return
    }

    if (pollingMinutes < 1 || pollingMinutes > 1440) {
      alert('El intervalo de polling debe estar entre 1 y 1440 minutos')
      return
    }

    // Validar que Admin haya seleccionado organización
    if (user?.role === 'admin' && !selectedAccountId) {
      alert('Debes seleccionar una organización')
      return
    }

    try {
      setSaving(true)

      // Preparar search_targets
      const validIps = searchIps.filter((ip) => ip.trim())
      const validRanges = searchRanges.filter((range) => range.trim())

      const searchTargets: SearchTargets | null =
        validIps.length > 0 || validRanges.length > 0
          ? {
              ...(validIps.length > 0 && { ips: validIps }),
              ...(validRanges.length > 0 && { ranges: validRanges }),
            }
          : null

      const updateData: GlobalConfigUpdate = {
        corporate_queue_name: corporateQueueName.trim(),
        pending_task_polling_minutes: pollingMinutes,
        bootstrap_domains: bootstrapDomains.trim(),
        search_targets: searchTargets,
      }

      // Construir URL con account_id si es Admin
      let url = 'http://localhost:8000/api/v1/config/global'
      if (user?.role === 'admin') {
        url += `?account_id=${selectedAccountId}`
      }

      const response = await fetch(url, {
        method: 'PUT',
        headers: {
          ...getAuthHeaders(),
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(updateData),
      })

      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Error al guardar configuración')
      }

      const data: GlobalConfig = await response.json()
      setConfig(data)
      setHasChanges(false)
      alert('Configuración guardada exitosamente')
    } catch (error: any) {
      console.error('Error:', error)
      alert(error.message || 'Error al guardar configuración')
    } finally {
      setSaving(false)
    }
  }

  const handleReset = () => {
    if (!config) return

    setCorporateQueueName(config.corporate_queue_name)
    setPollingMinutes(config.pending_task_polling_minutes)
    setBootstrapDomains(config.bootstrap_domains)

    if (config.search_targets) {
      setSearchIps(config.search_targets.ips || [''])
      setSearchRanges(config.search_targets.ranges || [''])
    } else {
      setSearchIps([''])
      setSearchRanges([''])
    }

    setHasChanges(false)
  }

  const addSearchIp = () => {
    setSearchIps([...searchIps, ''])
    setHasChanges(true)
  }

  const removeSearchIp = (index: number) => {
    setSearchIps(searchIps.filter((_, i) => i !== index))
    setHasChanges(true)
  }

  const updateSearchIp = (index: number, value: string) => {
    const newIps = [...searchIps]
    newIps[index] = value
    setSearchIps(newIps)
    setHasChanges(true)
  }

  const addSearchRange = () => {
    setSearchRanges([...searchRanges, ''])
    setHasChanges(true)
  }

  const removeSearchRange = (index: number) => {
    setSearchRanges(searchRanges.filter((_, i) => i !== index))
    setHasChanges(true)
  }

  const updateSearchRange = (index: number, value: string) => {
    const newRanges = [...searchRanges]
    newRanges[index] = value
    setSearchRanges(newRanges)
    setHasChanges(true)
  }

  if (loading || (user?.role === 'admin' && loadingAccounts)) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Cargando configuración...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Configuración Global</h1>
          <p className="mt-2 text-gray-600">
            Configuración que se aplica a todas las workstations de tu organización
          </p>
        </div>
        <div className="flex gap-2">
          {hasChanges && (
            <Button variant="outline" onClick={handleReset} disabled={saving}>
              <RotateCcw className="mr-2 h-4 w-4" />
              Descartar
            </Button>
          )}
          <Button onClick={handleSave} disabled={saving || !hasChanges || (user?.role === 'admin' && !selectedAccountId)}>
            <Save className="mr-2 h-4 w-4" />
            {saving ? 'Guardando...' : 'Guardar Cambios'}
          </Button>
        </div>
      </div>

      {/* Selector de Organización (solo para Admin) */}
      {user?.role === 'admin' && (
        <div className="bg-white rounded-lg shadow p-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Organización *
          </label>
          <select
            value={selectedAccountId}
            onChange={(e) => {
              setSelectedAccountId(e.target.value)
              setHasChanges(false)
            }}
            className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Seleccionar organización...</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.name}
              </option>
            ))}
          </select>
          <p className="mt-1 text-sm text-gray-500">
            Selecciona la organización para configurar
          </p>
        </div>
      )}

      {/* Alerta de jerarquía */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <div className="flex">
          <Info className="h-5 w-5 text-blue-600 mr-3 flex-shrink-0 mt-0.5" />
          <div>
            <h3 className="text-sm font-medium text-blue-900">Jerarquía de Configuración</h3>
            <p className="mt-1 text-sm text-blue-700">
              Esta configuración se aplica a nivel global. Puede ser sobrescrita por configuración
              específica de VLAN o workstation individual.
            </p>
          </div>
        </div>
      </div>

      {/* Formulario */}
      <div className="bg-white rounded-lg shadow">
        <div className="p-6 space-y-6">
          {/* Cola Corporativa */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Nombre de la Cola Corporativa *
            </label>
            <Input
              type="text"
              value={corporateQueueName}
              onChange={(e) => {
                setCorporateQueueName(e.target.value)
                setHasChanges(true)
              }}
              placeholder="Ej: LexmarkBBVA"
              className="max-w-md"
              disabled={user?.role === 'admin' && !selectedAccountId}
            />
            <p className="mt-1 text-sm text-gray-500">
              Nombre de la cola de impresión corporativa en Windows
            </p>
          </div>

          {/* Intervalo de Polling */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Intervalo de Polling (minutos) *
            </label>
            <Input
              type="number"
              min="1"
              max="1440"
              value={pollingMinutes}
              onChange={(e) => {
                setPollingMinutes(parseInt(e.target.value) || 1)
                setHasChanges(true)
              }}
              className="max-w-xs"
              disabled={user?.role === 'admin' && !selectedAccountId}
            />
            <p className="mt-1 text-sm text-gray-500">
              Frecuencia con la que las workstations consultan por tareas pendientes (1-1440 minutos)
            </p>
          </div>

          {/* Dominios de Bootstrap */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Dominios de Bootstrap
            </label>
            <Input
              type="text"
              value={bootstrapDomains}
              onChange={(e) => {
                setBootstrapDomains(e.target.value)
                setHasChanges(true)
              }}
              placeholder="Ej: bbva.com,bbva.local"
              className="max-w-md"
              disabled={user?.role === 'admin' && !selectedAccountId}
            />
            <p className="mt-1 text-sm text-gray-500">
              Dominios separados por comas para configuración inicial
            </p>
          </div>

          {/* Objetivos de Búsqueda - IPs */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              IPs de Búsqueda de Impresoras
            </label>
            <div className="space-y-2">
              {searchIps.map((ip, index) => (
                <div key={index} className="flex gap-2">
                  <Input
                    type="text"
                    value={ip}
                    onChange={(e) => updateSearchIp(index, e.target.value)}
                    placeholder="Ej: 192.168.1.100"
                    className="max-w-md"
                    disabled={user?.role === 'admin' && !selectedAccountId}
                  />
                  {searchIps.length > 1 && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => removeSearchIp(index)}
                      disabled={user?.role === 'admin' && !selectedAccountId}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              ))}
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={addSearchIp}
              className="mt-2"
              disabled={user?.role === 'admin' && !selectedAccountId}
            >
              <Plus className="mr-2 h-4 w-4" />
              Agregar IP
            </Button>
            <p className="mt-1 text-sm text-gray-500">
              IPs específicas donde buscar impresoras disponibles
            </p>
          </div>

          {/* Objetivos de Búsqueda - Rangos */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Rangos de Búsqueda de Impresoras
            </label>
            <div className="space-y-2">
              {searchRanges.map((range, index) => (
                <div key={index} className="flex gap-2">
                  <Input
                    type="text"
                    value={range}
                    onChange={(e) => updateSearchRange(index, e.target.value)}
                    placeholder="Ej: 192.168.1.0/24"
                    className="max-w-md"
                    disabled={user?.role === 'admin' && !selectedAccountId}
                  />
                  {searchRanges.length > 1 && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => removeSearchRange(index)}
                      disabled={user?.role === 'admin' && !selectedAccountId}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              ))}
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={addSearchRange}
              className="mt-2"
              disabled={user?.role === 'admin' && !selectedAccountId}
            >
              <Plus className="mr-2 h-4 w-4" />
              Agregar Rango
            </Button>
            <p className="mt-1 text-sm text-gray-500">
              Rangos CIDR donde buscar impresoras (ej: 192.168.1.0/24)
            </p>
          </div>
        </div>
      </div>

      {/* Información adicional */}
      {config && (
        <div className="bg-gray-50 rounded-lg p-4">
          <h3 className="text-sm font-medium text-gray-900 mb-2">Información</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-gray-600">Última actualización:</span>
              <span className="ml-2 text-gray-900">
                {new Date(config.updated_at).toLocaleString('es-PE')}
              </span>
            </div>
            <div>
              <span className="text-gray-600">Creado:</span>
              <span className="ml-2 text-gray-900">
                {new Date(config.created_at).toLocaleString('es-PE')}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Advertencia si no hay configuración */}
      {!config && selectedAccountId && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <div className="flex">
            <AlertCircle className="h-5 w-5 text-yellow-600 mr-3 flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="text-sm font-medium text-yellow-900">
                No hay configuración global
              </h3>
              <p className="mt-1 text-sm text-yellow-700">
                Esta organización aún no tiene configuración global. Completa el formulario y guarda
                los cambios para crear la configuración inicial.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Mensaje cuando Admin no ha seleccionado organización */}
      {user?.role === 'admin' && !selectedAccountId && !loadingAccounts && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <div className="flex">
            <Info className="h-5 w-5 text-blue-600 mr-3 flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="text-sm font-medium text-blue-900">
                Selecciona una organización
              </h3>
              <p className="mt-1 text-sm text-blue-700">
                Selecciona una organización del selector superior para ver o editar su configuración global.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
