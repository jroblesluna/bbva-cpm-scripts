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
  Account,
  AccountCreate,
  AccountUpdate,
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
} from '@/types'

// ============================================================================
// CONFIGURACIÓN BASE
// ============================================================================

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const API_V1_PREFIX = '/api/v1'

/**
 * Instancia de axios configurada para el backend.
 */
const apiClient: AxiosInstance = axios.create({
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
    // Obtener token del localStorage
    const token = localStorage.getItem('access_token')
    
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
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
   */
  getStatus: async (): Promise<{ needs_setup: boolean; message: string }> => {
    const response = await apiClient.get<{ needs_setup: boolean; message: string }>('/setup/status')
    return response.data
  },

  /**
   * Inicializar el sistema con el primer usuario admin.
   */
  initialize: async (data: {
    email: string
    password: string
    full_name: string
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
// CUENTAS
// ============================================================================

export const accountsApi = {
  /**
   * Listar todas las cuentas (solo Admin).
   */
  list: async (): Promise<Account[]> => {
    const response = await apiClient.get<{ items: Account[] }>('/accounts/')
    return response.data.items
  },

  /**
   * Obtener cuenta por ID.
   */
  get: async (id: string): Promise<Account> => {
    const response = await apiClient.get<Account>(`/accounts/${id}`)
    return response.data
  },

  /**
   * Crear nueva cuenta (solo Admin).
   */
  create: async (data: AccountCreate): Promise<Account> => {
    const response = await apiClient.post<Account>('/accounts/', data)
    return response.data
  },

  /**
   * Actualizar cuenta (solo Admin).
   */
  update: async (id: string, data: AccountUpdate): Promise<Account> => {
    const response = await apiClient.put<Account>(`/accounts/${id}`, data)
    return response.data
  },

  /**
   * Eliminar cuenta (solo Admin).
   */
  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/accounts/${id}`)
  },

  /**
   * Agregar IP pública a cuenta.
   */
  addPublicIP: async (id: string, data: PublicIPCreate): Promise<Account> => {
    const response = await apiClient.post<Account>(`/accounts/${id}/public-ips`, data)
    return response.data
  },

  /**
   * Eliminar IP pública de cuenta.
   */
  removePublicIP: async (accountId: string, ipId: string): Promise<void> => {
    await apiClient.delete(`/accounts/${accountId}/public-ips/${ipId}`)
  },

  /**
   * Listar IPs públicas pendientes de autorización (solo Admin).
   */
  listPendingIPs: async (): Promise<any[]> => {
    const response = await apiClient.get<any[]>('/accounts/public-ips/pending')
    return response.data
  },

  /**
   * Autorizar IP pública y asignarla a una cuenta (solo Admin).
   */
  authorizeIP: async (ipId: string, data: { account_id: string; description?: string }): Promise<any> => {
    const response = await apiClient.post<any>(`/accounts/public-ips/${ipId}/authorize`, data)
    return response.data
  },

  /**
   * Rechazar IP pública pendiente (solo Admin).
   */
  rejectIP: async (ipId: string): Promise<void> => {
    await apiClient.delete(`/accounts/public-ips/${ipId}/reject`)
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
}

// ============================================================================
// VLANS
// ============================================================================

export const vlansApi = {
  /**
   * Listar VLANs.
   */
  list: async (): Promise<VLAN[]> => {
    const response = await apiClient.get<VLAN[]>('/vlans/')
    return response.data
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
   * Buscar logs de auditoría con filtros.
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
