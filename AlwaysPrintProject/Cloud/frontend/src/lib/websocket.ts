/**
 * Cliente WebSocket para comunicación en tiempo real con el backend.
 * 
 * Características:
 * - Reconexión automática
 * - Manejo de eventos tipado
 * - Autenticación con JWT
 * - Heartbeat automático
 */

import {
  WebSocketStatus,
} from '@/types'

import type {
  OperatorMessage,
  WorkstationConnectedMessage,
  WorkstationDisconnectedMessage,
  ContingencyToggleMessage,
  MessageDeliveredMessage,
  CommandResultNotification,
  ConnectionStatsMessage,
} from '@/types'

// ============================================================================
// TIPOS
// ============================================================================

type MessageHandler = (message: OperatorMessage) => void

interface WebSocketClientOptions {
  url?: string
  token?: string
  reconnectInterval?: number
  maxReconnectAttempts?: number
  onStatusChange?: (status: WebSocketStatus) => void
  onError?: (error: Error) => void
}

// ============================================================================
// CLIENTE WEBSOCKET
// ============================================================================

export class WebSocketClient {
  private ws: WebSocket | null = null
  private url: string
  private token: string | null
  private reconnectInterval: number
  private maxReconnectAttempts: number
  private reconnectAttempts: number = 0
  private reconnectTimeout: NodeJS.Timeout | null = null
  private messageHandlers: Set<MessageHandler> = new Set()
  private status: WebSocketStatus = WebSocketStatus.DISCONNECTED
  private onStatusChange?: (status: WebSocketStatus) => void
  private onError?: (error: Error) => void
  private heartbeatInterval: NodeJS.Timeout | null = null

  constructor(options: WebSocketClientOptions = {}) {
    const wsUrl = options.url || process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000'
    this.url = `${wsUrl}/ws/operator`
    this.token = options.token || null
    this.reconnectInterval = options.reconnectInterval || 5000
    this.maxReconnectAttempts = options.maxReconnectAttempts || 10
    this.onStatusChange = options.onStatusChange
    this.onError = options.onError
  }

  /**
   * Conectar al WebSocket.
   */
  connect(token?: string): void {
    if (token) {
      this.token = token
    }

    if (!this.token) {
      const error = new Error('Token JWT requerido para conectar WebSocket')
      this.handleError(error)
      return
    }

    // Si ya está conectado, no hacer nada
    if (this.ws?.readyState === WebSocket.OPEN) {
      return
    }

    this.setStatus(WebSocketStatus.CONNECTING)

    try {
      // Agregar token como query parameter
      const wsUrlWithToken = `${this.url}?token=${this.token}`
      this.ws = new WebSocket(wsUrlWithToken)

      this.ws.onopen = this.handleOpen.bind(this)
      this.ws.onmessage = this.handleMessage.bind(this)
      this.ws.onerror = this.handleWebSocketError.bind(this)
      this.ws.onclose = this.handleClose.bind(this)
    } catch (error) {
      this.handleError(error as Error)
    }
  }

  /**
   * Desconectar del WebSocket.
   */
  disconnect(): void {
    // Limpiar timeout de reconexión
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout)
      this.reconnectTimeout = null
    }

    // Limpiar heartbeat
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval)
      this.heartbeatInterval = null
    }

    // Cerrar conexión
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }

    this.reconnectAttempts = 0
    this.setStatus(WebSocketStatus.DISCONNECTED)
  }

  /**
   * Agregar handler de mensajes.
   */
  addMessageHandler(handler: MessageHandler): () => void {
    this.messageHandlers.add(handler)

    // Retornar función para remover el handler
    return () => {
      this.messageHandlers.delete(handler)
    }
  }

  /**
   * Obtener estado actual.
   */
  getStatus(): WebSocketStatus {
    return this.status
  }

  /**
   * Verificar si está conectado.
   */
  isConnected(): boolean {
    return this.status === WebSocketStatus.CONNECTED
  }

  // ==========================================================================
  // HANDLERS PRIVADOS
  // ==========================================================================

  private handleOpen(): void {
    console.log('[WebSocket] Conectado')
    this.reconnectAttempts = 0
    this.setStatus(WebSocketStatus.CONNECTED)

    // Iniciar heartbeat (ping cada 30s)
    this.startHeartbeat()
  }

  private handleMessage(event: MessageEvent): void {
    try {
      const message: OperatorMessage = JSON.parse(event.data)
      
      // Notificar a todos los handlers
      this.messageHandlers.forEach((handler) => {
        try {
          handler(message)
        } catch (error) {
          console.error('[WebSocket] Error en handler:', error)
        }
      })
    } catch (error) {
      console.error('[WebSocket] Error al parsear mensaje:', error)
    }
  }

  private handleWebSocketError(event: Event): void {
    console.error('[WebSocket] Error:', event)
    const error = new Error('Error de conexión WebSocket')
    this.handleError(error)
  }

  private handleClose(event: CloseEvent): void {
    console.log('[WebSocket] Desconectado:', event.code, event.reason)
    
    // Limpiar heartbeat
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval)
      this.heartbeatInterval = null
    }

    this.setStatus(WebSocketStatus.DISCONNECTED)

    // Intentar reconectar si no fue cierre intencional
    if (event.code !== 1000 && this.reconnectAttempts < this.maxReconnectAttempts) {
      this.scheduleReconnect()
    }
  }

  private handleError(error: Error): void {
    console.error('[WebSocket] Error:', error)
    this.setStatus(WebSocketStatus.ERROR)
    
    if (this.onError) {
      this.onError(error)
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimeout) {
      return
    }

    this.reconnectAttempts++
    const delay = this.reconnectInterval * Math.min(this.reconnectAttempts, 5)

    console.log(
      `[WebSocket] Reconectando en ${delay}ms (intento ${this.reconnectAttempts}/${this.maxReconnectAttempts})`
    )

    this.reconnectTimeout = setTimeout(() => {
      this.reconnectTimeout = null
      this.connect()
    }, delay)
  }

  private setStatus(status: WebSocketStatus): void {
    if (this.status !== status) {
      this.status = status
      
      if (this.onStatusChange) {
        this.onStatusChange(status)
      }
    }
  }

  private startHeartbeat(): void {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval)
    }

    // Verifica que la conexión siga abierta cada 30s.
    // Si no lo está, fuerza reconexión (el backend ya hace ping propio).
    this.heartbeatInterval = setInterval(() => {
      if (this.ws && this.ws.readyState !== WebSocket.OPEN) {
        this.handleClose({ code: 1006, reason: 'heartbeat: connection lost' } as CloseEvent)
      }
    }, 30000)
  }
}

// ============================================================================
// INSTANCIA SINGLETON
// ============================================================================

let wsClient: WebSocketClient | null = null

/**
 * Obtener instancia singleton del cliente WebSocket.
 */
export function getWebSocketClient(options?: WebSocketClientOptions): WebSocketClient {
  if (!wsClient) {
    wsClient = new WebSocketClient(options)
  }
  return wsClient
}

/**
 * Destruir instancia singleton.
 */
export function destroyWebSocketClient(): void {
  if (wsClient) {
    wsClient.disconnect()
    wsClient = null
  }
}

// ============================================================================
// HELPERS PARA TIPOS DE MENSAJES
// ============================================================================

export function isWorkstationConnected(
  message: OperatorMessage
): message is WorkstationConnectedMessage {
  return message.type === 'workstation_connected'
}

export function isWorkstationDisconnected(
  message: OperatorMessage
): message is WorkstationDisconnectedMessage {
  return message.type === 'workstation_disconnected'
}

export function isContingencyToggle(
  message: OperatorMessage
): message is ContingencyToggleMessage {
  return message.type === 'contingency_toggle'
}

export function isMessageDelivered(
  message: OperatorMessage
): message is MessageDeliveredMessage {
  return message.type === 'message_delivered'
}

export function isCommandResult(
  message: OperatorMessage
): message is CommandResultNotification {
  return message.type === 'command_result'
}

export function isConnectionStats(
  message: OperatorMessage
): message is ConnectionStatsMessage {
  return message.type === 'connection_stats'
}
