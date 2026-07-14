/**
 * Hook de WebSocket.
 * 
 * Proporciona:
 * - Conexión automática con token JWT
 * - Estado de conexión
 * - Manejo de mensajes tipado
 * - Reconexión automática
 */

'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { getWebSocketClient, destroyWebSocketClient } from '@/lib/websocket'
import { WebSocketStatus } from '@/types'
import type { OperatorMessage } from '@/types'

type MessageHandler = (message: OperatorMessage) => void

interface UseWebSocketOptions {
  token?: string
  autoConnect?: boolean
  onMessage?: MessageHandler
}

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const { token, autoConnect = true, onMessage } = options
  
  const [status, setStatus] = useState<WebSocketStatus>(WebSocketStatus.DISCONNECTED)
  const [error, setError] = useState<Error | null>(null)
  const wsClientRef = useRef(getWebSocketClient({
    onStatusChange: setStatus,
    onError: setError,
  }))

  /**
   * Conectar al WebSocket.
   */
  const connect = useCallback((connectToken?: string) => {
    const finalToken = connectToken || token || localStorage.getItem('access_token')
    
    if (!finalToken) {
      setError(new Error('Token JWT requerido para conectar'))
      return
    }

    wsClientRef.current.connect(finalToken)
  }, [token])

  /**
   * Desconectar del WebSocket.
   */
  const disconnect = useCallback(() => {
    wsClientRef.current.disconnect()
  }, [])

  /**
   * Agregar handler de mensajes.
   */
  const addMessageHandler = useCallback((handler: MessageHandler) => {
    return wsClientRef.current.addMessageHandler(handler)
  }, [])

  /**
   * Enviar mensaje al WebSocket.
   */
  const send = useCallback((message: Record<string, unknown>): boolean => {
    return wsClientRef.current.send(message)
  }, [])

  /**
   * Auto-conectar al montar si autoConnect es true.
   * Delay de 100ms para evitar race condition con React Strict Mode (doble mount en dev).
   */
  useEffect(() => {
    if (autoConnect) {
      const timer = setTimeout(() => connect(), 100)
      return () => {
        clearTimeout(timer)
        disconnect()
      }
    }

    return () => {
      disconnect()
    }
  }, [autoConnect, connect, disconnect])

  /**
   * Agregar handler de mensajes si se proporciona.
   */
  useEffect(() => {
    if (onMessage) {
      const removeHandler = addMessageHandler(onMessage)
      return removeHandler
    }
  }, [onMessage, addMessageHandler])

  return {
    status,
    error,
    isConnected: status === WebSocketStatus.CONNECTED,
    isConnecting: status === WebSocketStatus.CONNECTING,
    isDisconnected: status === WebSocketStatus.DISCONNECTED,
    connect,
    disconnect,
    addMessageHandler,
    send,
  }
}
