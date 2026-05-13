'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Plus, Trash2 } from 'lucide-react'
import type { ConnectivityCheck } from '@/types/config'

/**
 * Tipo de check de conectividad soportado.
 */
type CheckType = ConnectivityCheck['type']

/**
 * Props del componente ConnectivityCheckEditor.
 */
interface ConnectivityCheckEditorProps {
  checks: ConnectivityCheck[]
  onChange: (checks: ConnectivityCheck[]) => void
}

/**
 * Estado del formulario del modal para agregar un check.
 */
interface CheckFormState {
  id: string
  type: CheckType
  url: string
  host: string
  hostname: string
  port: string
  timeout_ms: string
}

/**
 * Estado inicial del formulario.
 */
const INITIAL_FORM_STATE: CheckFormState = {
  id: '',
  type: 'http',
  url: '',
  host: '',
  hostname: '',
  port: '',
  timeout_ms: '5000',
}

/**
 * Máximo de checks permitidos por configuración.
 */
const MAX_CHECKS = 50

/**
 * Obtiene el valor de URL/Host para mostrar en la tabla según el tipo de check.
 */
function getDisplayValue(check: ConnectivityCheck): string {
  switch (check.type) {
    case 'http':
      return check.url || ''
    case 'tcp':
    case 'ping':
      return check.host || ''
    case 'dns':
      return check.hostname || ''
    default:
      return ''
  }
}

/**
 * Etiquetas en español para los tipos de check.
 */
const TYPE_LABELS: Record<CheckType, string> = {
  http: 'HTTP',
  tcp: 'TCP',
  ping: 'Ping',
  dns: 'DNS',
}

/**
 * Editor de checks de conectividad.
 * Muestra una tabla con los checks existentes y permite agregar/eliminar checks
 * mediante un modal con campos condicionales según el tipo seleccionado.
 */
export function ConnectivityCheckEditor({ checks, onChange }: ConnectivityCheckEditorProps) {
  const [modalOpen, setModalOpen] = useState(false)
  const [form, setForm] = useState<CheckFormState>(INITIAL_FORM_STATE)
  const [errors, setErrors] = useState<Record<string, string>>({})

  /**
   * Abre el modal para agregar un nuevo check.
   */
  const handleOpenModal = () => {
    setForm(INITIAL_FORM_STATE)
    setErrors({})
    setModalOpen(true)
  }

  /**
   * Cierra el modal sin guardar.
   */
  const handleCloseModal = () => {
    setModalOpen(false)
    setForm(INITIAL_FORM_STATE)
    setErrors({})
  }

  /**
   * Valida el formulario y retorna los errores encontrados.
   */
  const validateForm = (): Record<string, string> => {
    const newErrors: Record<string, string> = {}

    // Validar ID
    if (!form.id.trim()) {
      newErrors.id = 'El ID es requerido'
    } else if (checks.some((c) => c.id === form.id.trim())) {
      newErrors.id = 'El ID ya existe. Debe ser único'
    }

    // Validar máximo de checks
    if (checks.length >= MAX_CHECKS) {
      newErrors.general = `Se alcanzó el máximo de ${MAX_CHECKS} checks`
    }

    // Validar campos según tipo
    switch (form.type) {
      case 'http':
        if (!form.url.trim()) {
          newErrors.url = 'La URL es requerida para tipo HTTP'
        }
        break
      case 'tcp':
        if (!form.host.trim()) {
          newErrors.host = 'El host es requerido para tipo TCP'
        }
        if (!form.port.trim()) {
          newErrors.port = 'El puerto es requerido para tipo TCP'
        } else {
          const portNum = parseInt(form.port, 10)
          if (isNaN(portNum) || portNum < 1 || portNum > 65535) {
            newErrors.port = 'El puerto debe ser un número entre 1 y 65535'
          }
        }
        break
      case 'ping':
        if (!form.host.trim()) {
          newErrors.host = 'El host es requerido para tipo Ping'
        }
        break
      case 'dns':
        if (!form.hostname.trim()) {
          newErrors.hostname = 'El hostname es requerido para tipo DNS'
        }
        break
    }

    // Validar timeout
    if (!form.timeout_ms.trim()) {
      newErrors.timeout_ms = 'El timeout es requerido'
    } else {
      const timeoutNum = parseInt(form.timeout_ms, 10)
      if (isNaN(timeoutNum) || timeoutNum < 100 || timeoutNum > 30000) {
        newErrors.timeout_ms = 'El timeout debe ser entre 100 y 30000 ms'
      }
    }

    return newErrors
  }

  /**
   * Maneja el envío del formulario del modal.
   */
  const handleSubmit = () => {
    const validationErrors = validateForm()
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors)
      return
    }

    const newCheck: ConnectivityCheck = {
      id: form.id.trim(),
      type: form.type,
      timeout_ms: parseInt(form.timeout_ms, 10),
    }

    // Agregar campos según tipo
    switch (form.type) {
      case 'http':
        newCheck.url = form.url.trim()
        break
      case 'tcp':
        newCheck.host = form.host.trim()
        newCheck.port = parseInt(form.port, 10)
        break
      case 'ping':
        newCheck.host = form.host.trim()
        break
      case 'dns':
        newCheck.hostname = form.hostname.trim()
        break
    }

    onChange([...checks, newCheck])
    handleCloseModal()
  }

  /**
   * Elimina un check por su ID.
   */
  const handleDelete = (checkId: string) => {
    onChange(checks.filter((c) => c.id !== checkId))
  }

  /**
   * Actualiza un campo del formulario.
   */
  const updateField = (field: keyof CheckFormState, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }))
    // Limpiar error del campo al modificarlo
    if (errors[field]) {
      setErrors((prev) => {
        const next = { ...prev }
        delete next[field]
        return next
      })
    }
  }

  return (
    <div className="space-y-4">
      {/* Header de la sección */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-medium text-gray-900">Checks de Conectividad</h3>
          <p className="text-sm text-gray-500">
            Define los endpoints que las workstations deben monitorear ({checks.length}/{MAX_CHECKS})
          </p>
        </div>
        <Button
          type="button"
          onClick={handleOpenModal}
          disabled={checks.length >= MAX_CHECKS}
          size="sm"
        >
          <Plus className="mr-2 h-4 w-4" />
          Agregar check
        </Button>
      </div>

      {/* Tabla de checks existentes */}
      {checks.length > 0 ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead>Tipo</TableHead>
              <TableHead>URL/Host</TableHead>
              <TableHead>Timeout (ms)</TableHead>
              <TableHead className="w-[80px]">Acciones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {checks.map((check) => (
              <TableRow key={check.id}>
                <TableCell className="font-mono text-sm">{check.id}</TableCell>
                <TableCell>
                  <span className="inline-flex items-center rounded-md bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 ring-1 ring-inset ring-blue-700/10">
                    {TYPE_LABELS[check.type]}
                  </span>
                </TableCell>
                <TableCell className="text-sm text-gray-600 max-w-[300px] truncate">
                  {getDisplayValue(check)}
                </TableCell>
                <TableCell className="text-sm">{check.timeout_ms}</TableCell>
                <TableCell>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => handleDelete(check.id)}
                    className="h-8 w-8 text-red-600 hover:text-red-700 hover:bg-red-50"
                    aria-label={`Eliminar check ${check.id}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : (
        <div className="text-center py-8 border border-dashed border-gray-300 rounded-lg">
          <p className="text-sm text-gray-500">
            No hay checks de conectividad configurados
          </p>
          <p className="text-xs text-gray-400 mt-1">
            Haz clic en &quot;Agregar check&quot; para comenzar
          </p>
        </div>
      )}

      {/* Modal para agregar check */}
      {modalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          role="dialog"
          aria-modal="true"
          aria-labelledby="modal-title"
        >
          {/* Overlay */}
          <div
            className="fixed inset-0 bg-black/50"
            onClick={handleCloseModal}
            aria-hidden="true"
          />

          {/* Contenido del modal */}
          <div className="relative z-10 bg-white rounded-lg shadow-xl w-full max-w-md mx-4 p-6">
            <h2 id="modal-title" className="text-lg font-semibold text-gray-900 mb-4">
              Agregar check de conectividad
            </h2>

            {/* Error general */}
            {errors.general && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md">
                <p className="text-sm text-red-700">{errors.general}</p>
              </div>
            )}

            <div className="space-y-4">
              {/* Campo ID */}
              <div>
                <Label htmlFor="check-id">ID</Label>
                <Input
                  id="check-id"
                  type="text"
                  value={form.id}
                  onChange={(e) => updateField('id', e.target.value)}
                  placeholder="Ej: check-google-dns"
                  className="mt-1"
                />
                {errors.id && (
                  <p className="mt-1 text-sm text-red-600">{errors.id}</p>
                )}
              </div>

              {/* Campo Tipo */}
              <div>
                <Label htmlFor="check-type">Tipo</Label>
                <select
                  id="check-type"
                  value={form.type}
                  onChange={(e) => updateField('type', e.target.value as CheckType)}
                  className="mt-1 flex h-10 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2"
                >
                  <option value="http">HTTP</option>
                  <option value="tcp">TCP</option>
                  <option value="ping">Ping</option>
                  <option value="dns">DNS</option>
                </select>
              </div>

              {/* Campo URL (solo para HTTP) */}
              {form.type === 'http' && (
                <div>
                  <Label htmlFor="check-url">URL</Label>
                  <Input
                    id="check-url"
                    type="text"
                    value={form.url}
                    onChange={(e) => updateField('url', e.target.value)}
                    placeholder="Ej: https://api.ejemplo.com/health"
                    className="mt-1"
                  />
                  {errors.url && (
                    <p className="mt-1 text-sm text-red-600">{errors.url}</p>
                  )}
                </div>
              )}

              {/* Campo Host (para TCP y Ping) */}
              {(form.type === 'tcp' || form.type === 'ping') && (
                <div>
                  <Label htmlFor="check-host">Host</Label>
                  <Input
                    id="check-host"
                    type="text"
                    value={form.host}
                    onChange={(e) => updateField('host', e.target.value)}
                    placeholder="Ej: 192.168.1.1"
                    className="mt-1"
                  />
                  {errors.host && (
                    <p className="mt-1 text-sm text-red-600">{errors.host}</p>
                  )}
                </div>
              )}

              {/* Campo Hostname (solo para DNS) */}
              {form.type === 'dns' && (
                <div>
                  <Label htmlFor="check-hostname">Hostname</Label>
                  <Input
                    id="check-hostname"
                    type="text"
                    value={form.hostname}
                    onChange={(e) => updateField('hostname', e.target.value)}
                    placeholder="Ej: api.ejemplo.com"
                    className="mt-1"
                  />
                  {errors.hostname && (
                    <p className="mt-1 text-sm text-red-600">{errors.hostname}</p>
                  )}
                </div>
              )}

              {/* Campo Port (solo para TCP) */}
              {form.type === 'tcp' && (
                <div>
                  <Label htmlFor="check-port">Puerto</Label>
                  <Input
                    id="check-port"
                    type="number"
                    min="1"
                    max="65535"
                    value={form.port}
                    onChange={(e) => updateField('port', e.target.value)}
                    placeholder="Ej: 443"
                    className="mt-1"
                  />
                  {errors.port && (
                    <p className="mt-1 text-sm text-red-600">{errors.port}</p>
                  )}
                </div>
              )}

              {/* Campo Timeout */}
              <div>
                <Label htmlFor="check-timeout">Timeout (ms)</Label>
                <Input
                  id="check-timeout"
                  type="number"
                  min="100"
                  max="30000"
                  value={form.timeout_ms}
                  onChange={(e) => updateField('timeout_ms', e.target.value)}
                  placeholder="5000"
                  className="mt-1"
                />
                {errors.timeout_ms && (
                  <p className="mt-1 text-sm text-red-600">{errors.timeout_ms}</p>
                )}
                <p className="mt-1 text-xs text-gray-500">
                  Valor entre 100 y 30000 milisegundos
                </p>
              </div>
            </div>

            {/* Botones del modal */}
            <div className="mt-6 flex justify-end gap-3">
              <Button type="button" variant="outline" onClick={handleCloseModal}>
                Cancelar
              </Button>
              <Button type="button" onClick={handleSubmit}>
                Agregar
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
