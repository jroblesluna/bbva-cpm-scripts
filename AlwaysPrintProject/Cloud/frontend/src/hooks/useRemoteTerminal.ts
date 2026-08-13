/**
 * Hook para gestión de terminal remota en workstations.
 *
 * Proporciona:
 * - Ejecución de comandos OS remotos via WebSocket
 * - Historial de comandos de la sesión (estado local)
 * - Copia de historial al portapapeles
 * - Manejo de errores HTTP diferenciados (timeout, desconexión, genérico)
 * - Prevención de ejecución concurrente
 */

'use client'

import { useState, useCallback, useRef } from 'react'
import { useTranslations } from 'next-intl'
import { workstationsApi } from '@/lib/api'

// ============================================================================
// INTERFACES
// ============================================================================

export interface CommandHistoryEntry {
  /** UUID generado en frontend para key de React */
  id: string
  /** Comando ejecutado */
  command: string
  /** stdout o mensaje de error */
  output: string | null
  /** Distinguir error de éxito */
  isError: boolean
  /** Momento de ejecución */
  timestamp: Date
  /** En espera de respuesta */
  isLoading: boolean
}

export interface UseRemoteTerminalReturn {
  history: CommandHistoryEntry[]
  isExecuting: boolean
  executeCommand: (command: string) => Promise<void>
  clearHistory: () => void
  copyHistory: () => Promise<void>
}

// ============================================================================
// HOOK
// ============================================================================

/**
 * Hook para ejecutar comandos remotos en una workstation y mantener historial de sesión.
 *
 * @param workstationId - ID de la workstation destino
 */
export function useRemoteTerminal(workstationId: string): UseRemoteTerminalReturn {
  const t = useTranslations('workstations')
  const [history, setHistory] = useState<CommandHistoryEntry[]>([])
  const isExecutingRef = useRef(false)
  const [isExecuting, setIsExecuting] = useState(false)

  /**
   * Ejecuta un comando remoto en la workstation.
   * Previene ejecución concurrente — si ya hay un comando en curso, no hace nada.
   */
  const executeCommand = useCallback(async (command: string) => {
    // Prevenir ejecución concurrente
    if (isExecutingRef.current) return

    isExecutingRef.current = true
    setIsExecuting(true)

    const entryId = crypto.randomUUID()
    const entry: CommandHistoryEntry = {
      id: entryId,
      command,
      output: null,
      isError: false,
      timestamp: new Date(),
      isLoading: true,
    }

    // Agregar entrada pendiente al historial
    setHistory(prev => [...prev, entry])

    try {
      const response = await workstationsApi.sendCommand(
        workstationId,
        'execute_remote_command',
        { command }
      )

      // Respuesta exitosa — extraer stdout del response
      // El backend retorna el contenido completo de la respuesta de la workstation
      const data = response as unknown as { success?: boolean; stdout?: string; output?: string }
      let output: string | null = null
      let isError = false

      if (data.success === false) {
        // La workstation reportó error
        output = data.output || data.stdout || t('remoteTerminalError')
        isError = true
      } else {
        // Éxito — mostrar stdout o indicar sin salida
        output = data.stdout || data.output || t('remoteTerminalNoOutput')
      }

      setHistory(prev =>
        prev.map(h =>
          h.id === entryId
            ? { ...h, output, isError, isLoading: false }
            : h
        )
      )
    } catch (error: unknown) {
      const apiError = error as { status?: number; detail?: string }
      let errorMessage: string

      if (apiError.status === 408) {
        errorMessage = t('remoteTerminalTimeout')
      } else if (apiError.status === 409) {
        errorMessage = t('remoteTerminalWsDisconnected')
      } else {
        errorMessage = apiError.detail || t('remoteTerminalError')
      }

      setHistory(prev =>
        prev.map(h =>
          h.id === entryId
            ? { ...h, output: errorMessage, isError: true, isLoading: false }
            : h
        )
      )
    } finally {
      isExecutingRef.current = false
      setIsExecuting(false)
    }
  }, [workstationId, t])

  /**
   * Limpia el historial de comandos de la sesión.
   */
  const clearHistory = useCallback(() => {
    setHistory([])
  }, [])

  /**
   * Copia el historial formateado al portapapeles.
   * Formato: "$ {command}\n{output}\n" por cada entrada.
   */
  const copyHistory = useCallback(async () => {
    const text = history
      .filter(entry => !entry.isLoading)
      .map(entry => {
        const output = entry.output || t('remoteTerminalNoOutput')
        return `$ ${entry.command}\n${output}`
      })
      .join('\n\n')

    await navigator.clipboard.writeText(text)
  }, [history, t])

  return {
    history,
    isExecuting,
    executeCommand,
    clearHistory,
    copyHistory,
  }
}
