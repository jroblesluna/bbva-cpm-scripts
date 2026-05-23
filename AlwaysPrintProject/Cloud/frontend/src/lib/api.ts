/**
 * Cliente API con axios para comunicación con el backend.
 * 
 * Incluye:
 * - Configuración base de axios
 * - Interceptors para autenticación
 * - Manejo de errores
 * - Funciones helper para todas las entidades
 */

import axios, { AxiosError, AxiosInstance, AxiosRequestConfig } from 'axios'
import type {
  User,
  UserCreate,
  UserUpdate,
  UserPasswordChange,
  LoginRequest,
  TokenResponse,
  Organization,
  OrganizationCreate,
  OrganizationUpdate,
  PublicIPCreate,
  Workstation,
  WorkstationUpdate,
  WorkstationStats,
  WorkstationFilter,
  WorkstationListResponse,
  VLAN,
  VLANCreate,
  VLANUpdate,
  GlobalConfig,
  GlobalConfigUpdate,
  VLANConfig,
  VLANConfigUpdate,
  WorkstationConfig,
  WorkstationConfigUpdate,
  EffectiveConfig,
  Message,
  MessageCreate,
  MessageStats,
  MessageListResponse,
  AuditLog,
  AuditLogSearch,
  AuditLogListResponse,
  AuditLogStats,
  ApiError,
  Device,
  DeviceCreate,
  DeviceUpdate,
  LogAnalysisResponse,
  LogAnalysisListResponse,
  LogAnalysisTodayCheckResponse,
} from '@/types'

// ============================================================================
// CONFIGURACIÓN BASE
// ============================================================================

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || ''
const API_V1_PREFIX = '/api/v1'

// ============================================================================
// OBTENCIÓN DE IP PRIVADA DEL CLIENTE
// ============================================================================

let cachedPrivateIP: string | null = null

/**
 * Obtiene la IP privada del cliente usando WebRTC.
 * Se cachea para no repetir la detección en cada request.
 */
function detectPrivateIP(): void {
  if (typeof window === 'undefined' || typeof RTCPeerConnection === 'undefined') return

  try {
    const pc = new RTCPeerConnection({ iceServers: [] })
    pc.createDataChannel('')
    pc.createOffer().then((offer) => pc.setLocalDescription(offer)).catch(() => {})
    pc.onicecandidate = (event) => {
      if (!event || !event.candidate || !event.candidate.candidate) return
      const parts = event.candidate.candidate.split(' ')
      const ip = parts[4]
      // Filtrar solo IPs privadas (10.x, 172.16-31.x, 192.168.x)
      if (ip && /^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.)/.test(ip)) {
        cachedPrivateIP = ip
        pc.close()
      }
    }
    // Timeout para cerrar la conexión si no se detecta IP
    setTimeout(() => { try { pc.close() } catch {} }, 3000)
  } catch {
    // WebRTC no disponible, se usará la IP del servidor
  }
}

// Iniciar detección al cargar el módulo
if (typeof window !== 'undefined') {
  detectPrivateIP()
}

/**
 * Instancia de axios configurada para el backend.
 */
export const apiClient: AxiosInstance = axios.create({
  baseURL: `${API_BASE_URL}${API_V1_PREFIX}`,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ============================================================================
// INTERCEPTORS
// ============================================================================

/**
 * Interceptor de request para agregar token JWT.
 */
apiClient.interceptors.request.use(
  (config) => {
    // No enviar token si el header Authorization ya fue explícitamente seteado (incluso vacío)
    if (config.headers.Authorization !== undefined) {
      // Si se seteó explícitamente vacío, eliminarlo para no enviar header
      if (!config.headers.Authorization) {
        delete config.headers.Authorization
      }
    } else {
      // Obtener token del localStorage
      const token = localStorage.getItem('access_token')
      if (token) {
        config.headers.Authorization = `Bearer ${token}`
      }
    }

    // Enviar IP privada del cliente si está disponible
    if (cachedPrivateIP) {
      config.headers['X-Client-Private-IP'] = cachedPrivateIP
    }
    
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

/**
 * Interceptor de response para manejo de errores.
 */
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiError>) => {
    // Si es 401 (Unauthorized), limpiar token y redirigir a login
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('user')
      
      // Solo redirigir si no estamos ya en login
      if (typeof window !== 'undefined' && !window.location.pathname.includes('/login')) {
        window.location.href = '/login'
      }
    }
    
    // Transformar error a formato consistente
    const apiError: ApiError = {
      detail: error.response?.data?.detail || error.message || 'Error desconocido',
      status: error.response?.status,
    }
    
    return Promise.reject(apiError)
  }
)

// ============================================================================
// SETUP INICIAL
// ============================================================================

export const setupApi = {
  /**
   * Verificar si el sistema necesita configuración inicial.
   * Acepta un AbortSignal opcional para cancelar la petición.
   * No envía token de autenticación (endpoint público).
   */
  getStatus: async (signal?: AbortSignal): Promise<{ needs_setup: boolean; message: string }> => {
    const response = await apiClient.get<{ needs_setup: boolean; message: string }>('/setup/status', {
      signal,
      headers: { Authorization: '' },
    })
    return response.data
  },

  /**
   * Inicializar el sistema con el primer usuario admin.
   */
  initialize: async (data: {
    email: string
    password: string
    full_name: string
    language?: string
  }): Promise<{ success: boolean; message: string; user: any }> => {
    const response = await apiClient.post<{ success: boolean; message: string; user: any }>(
      '/setup/initialize',
      data
    )
    return response.data
  },
}

// ============================================================================
// AUTENTICACIÓN
// ============================================================================

export const authApi = {
  /**
   * Login de usuario.
   */
  login: async (credentials: LoginRequest): Promise<TokenResponse> => {
    const response = await apiClient.post<TokenResponse>('/auth/login', credentials)
    return response.data
  },

  /**
   * Logout de usuario.
   */
  logout: async (): Promise<void> => {
    await apiClient.post('/auth/logout')
  },

  /**
   * Obtener usuario actual.
   */
  me: async (): Promise<User> => {
    const response = await apiClient.get<User>('/auth/me')
    return response.data
  },

  /**
   * Solicitar reset de contraseña.
   */
  requestPasswordReset: async (email: string): Promise<void> => {
    await apiClient.post('/auth/password-reset', { email })
  },

  confirmPasswordReset: async (token: string, new_password: string): Promise<void> => {
    await apiClient.post('/auth/password-reset/confirm', { token, new_password })
  },
}

// ============================================================================
// ORGANIZACIONES
// ============================================================================

export const organizationsApi = {
  /**
   * Listar todas las organizaciones (solo Admin).
   */
  list: async (): Promise<Organization[]> => {
    const response = await apiClient.get<{ items: Organization[] }>('/organizations/')
    return response.data.items
  },

  /**
   * Obtener organización por ID.
   */
  get: async (id: string): Promise<Organization> => {
    const response = await apiClient.get<Organization>(`/organizations/${id}`)
    return response.data
  },

  /**
   * Crear nueva organización (solo Admin).
   */
  create: async (data: OrganizationCreate): Promise<Organization> => {
    const response = await apiClient.post<Organization>('/organizations/', data)
    return response.data
  },

  /**
   * Actualizar organización (solo Admin).
   */
  update: async (id: string, data: OrganizationUpdate): Promise<Organization> => {
    const response = await apiClient.put<Organization>(`/organizations/${id}`, data)
    return response.data
  },

  /**
   * Eliminar organización (solo Admin).
   */
  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/organizations/${id}`)
  },

  /**
   * Agregar IP pública a organización.
   */
  addPublicIP: async (id: string, data: PublicIPCreate): Promise<Organization> => {
    const response = await apiClient.post<Organization>(`/organizations/${id}/public-ips`, data)
    return response.data
  },

  /**
   * Eliminar IP pública de organización.
   */
  removePublicIP: async (organizationId: string, ipId: string): Promise<void> => {
    await apiClient.delete(`/organizations/${organizationId}/public-ips/${ipId}`)
  },

  /**
   * Listar IPs públicas pendientes de autorización (solo Admin).
   */
  listPendingIPs: async (): Promise<any[]> => {
    const response = await apiClient.get<any[]>('/organizations/public-ips/pending')
    return response.data
  },

  /**
   * Autorizar IP pública y asignarla a una organización (solo Admin).
   */
  authorizeIP: async (ipId: string, data: { organization_id: string; description?: string }): Promise<any> => {
    const response = await apiClient.post<any>(`/organizations/public-ips/${ipId}/authorize`, data)
    return response.data
  },

  /**
   * Rechazar IP pública pendiente (solo Admin).
   */
  rejectIP: async (ipId: string): Promise<void> => {
    await apiClient.delete(`/organizations/public-ips/${ipId}/reject`)
  },

  /**
   * Activar/desactivar contingencia forzada para una organización.
   */
  toggleForcedContingency: async (id: string, enabled: boolean): Promise<{ forced_contingency: boolean }> => {
    const response = await apiClient.patch<{ forced_contingency: boolean }>(
      `/organizations/${id}/forced-contingency`,
      { enabled }
    )
    return response.data
  },
}


// ============================================================================
// USUARIOS
// ============================================================================

export const usersApi = {
  /**
   * Listar usuarios.
   */
  list: async (): Promise<User[]> => {
    const response = await apiClient.get<{ items: User[] }>('/users/')
    return response.data.items
  },

  /**
   * Obtener usuario por ID.
   */
  get: async (id: string): Promise<User> => {
    const response = await apiClient.get<User>(`/users/${id}`)
    return response.data
  },

  /**
   * Crear nuevo usuario.
   */
  create: async (data: UserCreate): Promise<User> => {
    const response = await apiClient.post<User>('/users/', data)
    return response.data
  },

  /**
   * Actualizar usuario.
   */
  update: async (id: string, data: UserUpdate): Promise<User> => {
    const response = await apiClient.put<User>(`/users/${id}`, data)
    return response.data
  },

  /**
   * Eliminar usuario.
   */
  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/users/${id}`)
  },

  /**
   * Cambiar contraseña de usuario.
   */
  changePassword: async (id: string, data: UserPasswordChange): Promise<void> => {
    await apiClient.put(`/users/${id}/password`, data)
  },

  /**
   * Actualizar idioma del usuario autenticado.
   */
  updateLanguage: async (language: string): Promise<{ language: string }> => {
    const response = await apiClient.patch<{ language: string }>('/users/me/language', null, {
      params: { language },
    })
    return response.data
  },
}

// ============================================================================
// WORKSTATIONS
// ============================================================================

export const workstationsApi = {
  /**
   * Listar workstations con filtros.
   */
  list: async (filters?: WorkstationFilter): Promise<WorkstationListResponse> => {
    const response = await apiClient.get<WorkstationListResponse>('/workstations/', {
      params: filters,
    })
    return response.data
  },

  /**
   * Obtener estadísticas de workstations.
   */
  stats: async (): Promise<WorkstationStats> => {
    const response = await apiClient.get<WorkstationStats>('/workstations/stats')
    return response.data
  },

  /**
   * Obtener workstation por ID.
   */
  get: async (id: string): Promise<Workstation> => {
    const response = await apiClient.get<Workstation>(`/workstations/${id}`)
    return response.data
  },

  /**
   * Actualizar workstation.
   */
  update: async (id: string, data: WorkstationUpdate): Promise<Workstation> => {
    const response = await apiClient.put<Workstation>(`/workstations/${id}`, data)
    return response.data
  },

  /**
   * Obtener configuración efectiva de workstation.
   */
  getConfig: async (id: string): Promise<EffectiveConfig> => {
    const response = await apiClient.get<EffectiveConfig>(`/workstations/${id}/config`)
    return response.data
  },

  /**
   * Actualizar configuración específica de workstation.
   */
  updateConfig: async (id: string, data: WorkstationConfigUpdate): Promise<WorkstationConfig> => {
    const response = await apiClient.put<WorkstationConfig>(`/workstations/${id}/config`, data)
    return response.data
  },

  /**
   * Eliminar override de configuración de workstation.
   */
  deleteConfig: async (id: string): Promise<void> => {
    await apiClient.delete(`/workstations/${id}/config`)
  },

  /**
   * Eliminar workstation del sistema.
   */
  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/workstations/${id}`)
  },

  /**
   * Enviar comando remoto a una workstation.
   * Requiere que la workstation esté online.
   */
  sendCommand: async (
    id: string,
    commandType: 'restart_service' | 'restart_tray' | 'check_update',
    params?: Record<string, unknown>
  ): Promise<{ command_id: string; status: string }> => {
    const response = await apiClient.post<{ command_id: string; status: string }>(
      `/workstations/${id}/command`,
      { command_type: commandType, params: params ?? {} }
    )
    return response.data
  },

  /**
   * Descargar el último archivo de log de una workstation online.
   * Retorna un Blob con el contenido del archivo.
   * Maneja errores de respuesta JSON cuando el backend devuelve error en vez de blob.
   */
  downloadLatestLog: async (id: string): Promise<{ blob: Blob; filename: string }> => {
    try {
      const response = await apiClient.get(`/workstations/${id}/logs/download`, {
        responseType: 'blob',
        timeout: 45000, // 45s timeout (el backend espera 30s máximo)
      })
      // Extraer nombre de archivo del header Content-Disposition
      const contentDisposition = response.headers['content-disposition'] || ''
      const filenameMatch = contentDisposition.match(/filename="?([^";\n]+)"?/)
      const filename = filenameMatch ? filenameMatch[1] : 'alwaysprint.log'
      return { blob: response.data as Blob, filename }
    } catch (error: unknown) {
      // Cuando responseType es 'blob', axios recibe errores JSON como Blob.
      // Intentar extraer el mensaje de error del blob si es posible.
      const apiErr = error as { detail?: string; status?: number }
      if (apiErr.detail) {
        // El interceptor ya transformó el error correctamente
        throw apiErr
      }
      // Si no hay detail, puede ser un error de red o timeout
      const axiosErr = error as { message?: string; code?: string }
      if (axiosErr.code === 'ECONNABORTED' || axiosErr.message?.includes('timeout')) {
        throw { detail: 'Timeout: no se recibió respuesta del servidor.', status: 408 }
      }
      throw { detail: 'Error de conexión al descargar el log.', status: undefined }
    }
  },

  /**
   * Obtener dispositivos (impresoras) disponibles en una VLAN.
   * Se usa para el selector de impresora predeterminada.
   */
  getVlanDevices: async (vlanId: string): Promise<Array<{ id: string; name: string; ip_address: string }>> => {
    const response = await apiClient.get<{ devices: Array<{ id: string; name: string; ip_address: string }> }>(
      `/devices/?vlan_id=${vlanId}&is_active=true`
    )
    return response.data.devices || []
  },

  /**
   * Activar/desactivar contingencia forzada para una workstation.
   */
  toggleForcedContingency: async (id: string, enabled: boolean): Promise<{ forced_contingency: boolean }> => {
    const response = await apiClient.patch<{ forced_contingency: boolean }>(
      `/workstations/${id}/forced-contingency`,
      null,
      { params: { enabled } }
    )
    return response.data
  },
}

// ============================================================================
// VLANS
// ============================================================================

export const vlansApi = {
  /**
   * Listar VLANs, opcionalmente filtradas por organización.
   */
  list: async (filters?: { organization_id?: string }): Promise<VLAN[]> => {
    const response = await apiClient.get<{ vlans: VLAN[] }>('/vlans/', {
      params: filters,
    })
    return response.data.vlans
  },

  /**
   * Obtener VLAN por ID.
   */
  get: async (id: string): Promise<VLAN> => {
    const response = await apiClient.get<VLAN>(`/vlans/${id}`)
    return response.data
  },

  /**
   * Crear nueva VLAN.
   */
  create: async (data: VLANCreate): Promise<VLAN> => {
    const response = await apiClient.post<VLAN>('/vlans/', data)
    return response.data
  },

  /**
   * Actualizar VLAN.
   */
  update: async (id: string, data: VLANUpdate): Promise<VLAN> => {
    const response = await apiClient.put<VLAN>(`/vlans/${id}`, data)
    return response.data
  },

  /**
   * Eliminar VLAN.
   */
  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/vlans/${id}`)
  },

  /**
   * Obtener workstations de una VLAN.
   */
  getWorkstations: async (id: string): Promise<Workstation[]> => {
    const response = await apiClient.get<Workstation[]>(`/vlans/${id}/workstations`)
    return response.data
  },

  /**
   * Obtener configuración de VLAN.
   */
  getConfig: async (id: string): Promise<VLANConfig | null> => {
    const response = await apiClient.get<VLANConfig | null>(`/vlans/${id}/config`)
    return response.data
  },

  /**
   * Actualizar configuración de VLAN.
   */
  updateConfig: async (id: string, data: VLANConfigUpdate): Promise<VLANConfig> => {
    const response = await apiClient.put<VLANConfig>(`/vlans/${id}/config`, data)
    return response.data
  },

  /**
   * Eliminar configuración de VLAN.
   */
  deleteConfig: async (id: string): Promise<void> => {
    await apiClient.delete(`/vlans/${id}/config`)
  },

  /**
   * Activar/desactivar contingencia forzada para una VLAN.
   */
  toggleForcedContingency: async (id: string, enabled: boolean): Promise<{ forced_contingency: boolean }> => {
    const response = await apiClient.patch<{ forced_contingency: boolean }>(
      `/vlans/${id}/forced-contingency`,
      null,
      { params: { enabled } }
    )
    return response.data
  },
}

// ============================================================================
// DISPOSITIVOS (IMPRESORAS)
// ============================================================================

export const devicesApi = {
  /**
   * Listar dispositivos, opcionalmente filtrados.
   */
  list: async (filters?: { organization_id?: string; vlan_id?: string; is_active?: boolean; search?: string }): Promise<Device[]> => {
    const response = await apiClient.get<{ devices: Device[] }>('/devices/', {
      params: filters,
    })
    return response.data.devices
  },

  /**
   * Obtener dispositivo por ID.
   */
  get: async (id: string): Promise<Device> => {
    const response = await apiClient.get<Device>(`/devices/${id}`)
    return response.data
  },

  /**
   * Crear nuevo dispositivo.
   */
  create: async (data: DeviceCreate): Promise<Device> => {
    const response = await apiClient.post<Device>('/devices/', data)
    return response.data
  },

  /**
   * Actualizar dispositivo.
   */
  update: async (id: string, data: DeviceUpdate): Promise<Device> => {
    const response = await apiClient.put<Device>(`/devices/${id}`, data)
    return response.data
  },

  /**
   * Eliminar dispositivo.
   */
  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/devices/${id}`)
  },
}

// ============================================================================
// CONFIGURACIÓN GLOBAL
// ============================================================================

export const configApi = {
  /**
   * Obtener configuración global.
   */
  getGlobal: async (): Promise<GlobalConfig> => {
    const response = await apiClient.get<GlobalConfig>('/config/global')
    return response.data
  },

  /**
   * Actualizar configuración global.
   */
  updateGlobal: async (data: GlobalConfigUpdate): Promise<GlobalConfig> => {
    const response = await apiClient.put<GlobalConfig>('/config/global', data)
    return response.data
  },
}

// ============================================================================
// MENSAJES
// ============================================================================

export const messagesApi = {
  /**
   * Listar mensajes con filtros.
   */
  list: async (filters?: Record<string, any>): Promise<MessageListResponse> => {
    const response = await apiClient.get<MessageListResponse>('/messages/', {
      params: filters,
    })
    return response.data
  },

  /**
   * Obtener estadísticas de mensajes.
   */
  stats: async (): Promise<MessageStats> => {
    const response = await apiClient.get<MessageStats>('/messages/stats')
    return response.data
  },

  /**
   * Obtener mensaje por ID.
   */
  get: async (id: string): Promise<Message> => {
    const response = await apiClient.get<Message>(`/messages/${id}`)
    return response.data
  },

  /**
   * Enviar nuevo mensaje.
   */
  send: async (data: MessageCreate): Promise<Message> => {
    const response = await apiClient.post<Message>('/messages/', data)
    return response.data
  },
}

// ============================================================================
// AUDITORÍA
// ============================================================================

export const auditApi = {
  /**
   * Buscar logs de auditoría con filtros y paginación por cursor.
   */
  search: async (filters?: AuditLogSearch): Promise<AuditLogListResponse> => {
    const response = await apiClient.get<AuditLogListResponse>('/audit/', {
      params: filters,
    })
    return response.data
  },

  /**
   * Obtener estadísticas de auditoría.
   */
  stats: async (): Promise<AuditLogStats> => {
    const response = await apiClient.get<AuditLogStats>('/audit/stats')
    return response.data
  },

  /**
   * Obtener actividad reciente.
   */
  recent: async (limit: number = 10): Promise<AuditLog[]> => {
    const response = await apiClient.get<AuditLog[]>('/audit/recent', {
      params: { limit },
    })
    return response.data
  },

  /**
   * Obtener log de auditoría por ID.
   */
  get: async (id: string): Promise<AuditLog> => {
    const response = await apiClient.get<AuditLog>(`/audit/${id}`)
    return response.data
  },
}

// ============================================================================
// LOG ANALYSIS
// ============================================================================

export const logAnalysisApi = {
  /**
   * Obtener historial de análisis de una workstation, paginado.
   */
  list: async (
    workstationId: string,
    params?: { page?: number; page_size?: number }
  ): Promise<LogAnalysisListResponse> => {
    const response = await apiClient.get<LogAnalysisListResponse>(
      `/workstations/${workstationId}/log-analyses`,
      { params }
    )
    return response.data
  },

  /**
   * Obtener un análisis individual por ID.
   */
  get: async (analysisId: string): Promise<LogAnalysisResponse> => {
    const response = await apiClient.get<LogAnalysisResponse>(
      `/log-analyses/${analysisId}`
    )
    return response.data
  },

  /**
   * Verificar si existe un análisis del día actual.
   */
  checkToday: async (workstationId: string): Promise<LogAnalysisTodayCheckResponse> => {
    const response = await apiClient.get<LogAnalysisTodayCheckResponse>(
      `/workstations/${workstationId}/log-analyses/today`
    )
    return response.data
  },

  /**
   * Solicitar análisis de log del día actual de una workstation.
   */
  analyzeLog: async (workstationId: string, overwrite: boolean = false): Promise<LogAnalysisResponse> => {
    const response = await apiClient.post<LogAnalysisResponse>(
      `/workstations/${workstationId}/analyze-log`,
      null,
      { params: { overwrite }, timeout: 120000 }
    )
    return response.data
  },

  /**
   * Listar modelos LLM disponibles en AWS Bedrock.
   */
  listModels: async (): Promise<{ models: Array<{ model_id: string; model_name: string; provider: string }>; default_model_id: string }> => {
    const response = await apiClient.get<{ models: Array<{ model_id: string; model_name: string; provider: string }>; default_model_id: string }>(
      '/workstations/llm-models'
    )
    return response.data
  },
}

// ============================================================================
// HEALTH CHECK
// ============================================================================

export const healthApi = {
  /**
   * Verificar estado del backend.
   */
  check: async (): Promise<{ status: string }> => {
    const response = await apiClient.get<{ status: string }>('/health')
    return response.data
  },
}

// ============================================================================
// EXPORTACIÓN POR DEFECTO
// ============================================================================

export const api = apiClient
export default apiClient
