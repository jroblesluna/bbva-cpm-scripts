/**
 * Sección de Terminal Remota para workstations.
 *
 * Permite a usuarios Admin/Operator ejecutar comandos OS arbitrarios
 * en una workstation remota y visualizar la salida en tiempo real.
 *
 * Características:
 * - Input con estilo terminal y prompt ">"
 * - Historial de comandos con timestamp y output
 * - Estilo diferenciado para errores
 * - Auto-scroll al agregar nuevas entradas
 * - Botones de copiar historial y limpiar
 * - Submit con Enter y botón
 * - Navegación por historial con flechas (task 4.2)
 */

'use client'

import { useRef, useEffect, useState, useCallback } from 'react'
import { useTranslations } from 'next-intl'
import { Terminal, Loader2, Copy, Trash2, WifiOff, Send } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/hooks/useAuth'
import { useRemoteTerminal } from '@/hooks/useRemoteTerminal'
import { useToast } from '@/hooks/use-toast'

// === TIPOS ===

interface RemoteTerminalSectionProps {
  workstationId: string
  isOnline: boolean
}

// === COMPONENTE ===

export function RemoteTerminalSection({ workstationId, isOnline }: RemoteTerminalSectionProps) {
  const t = useTranslations('workstations')
  const { isAdmin, isOperator } = useAuth()
  const { toast } = useToast()
  const { history, isExecuting, executeCommand, clearHistory, copyHistory } = useRemoteTerminal(workstationId)

  const [inputValue, setInputValue] = useState('')
  const [historyIndex, setHistoryIndex] = useState(-1)
  const [savedInput, setSavedInput] = useState('')

  const inputRef = useRef<HTMLInputElement>(null)
  const outputRef = useRef<HTMLDivElement>(null)

  // === AUTO-SCROLL ===
  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight
    }
  }, [history])

  // === FOCUS DESPUÉS DE EJECUCIÓN ===
  useEffect(() => {
    if (!isExecuting && inputRef.current) {
      inputRef.current.focus()
    }
  }, [isExecuting])

  // === CONTROL DE ACCESO ===
  // Solo Admin u Operator pueden ver esta sección
  if (!isAdmin() && !isOperator()) {
    return null
  }

  // === HANDLERS ===

  const handleSubmit = useCallback(async () => {
    const trimmed = inputValue.trim()
    if (!trimmed || isExecuting) return

    setInputValue('')
    setHistoryIndex(-1)
    setSavedInput('')
    await executeCommand(trimmed)
  }, [inputValue, isExecuting, executeCommand])

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleSubmit()
      return
    }

    // Navegación por historial de comandos ejecutados
    const executedCommands = history
      .filter(entry => !entry.isLoading)
      .map(entry => entry.command)

    if (e.key === 'ArrowUp') {
      e.preventDefault()
      if (executedCommands.length === 0) return

      if (historyIndex === -1) {
        // Guardar input actual antes de navegar
        setSavedInput(inputValue)
      }

      const newIndex = historyIndex === -1
        ? executedCommands.length - 1
        : Math.max(0, historyIndex - 1)

      setHistoryIndex(newIndex)
      setInputValue(executedCommands[newIndex])
      return
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (historyIndex === -1) return

      if (historyIndex >= executedCommands.length - 1) {
        // Volver al input guardado
        setHistoryIndex(-1)
        setInputValue(savedInput)
      } else {
        const newIndex = historyIndex + 1
        setHistoryIndex(newIndex)
        setInputValue(executedCommands[newIndex])
      }
      return
    }
  }, [history, historyIndex, inputValue, savedInput, handleSubmit])

  const handleCopyHistory = useCallback(async () => {
    await copyHistory()
    toast({ title: t('remoteTerminalCopied') })
  }, [copyHistory, toast, t])

  // === FORMATEO DE TIMESTAMP ===
  const formatTimestamp = (date: Date): string => {
    return date.toLocaleTimeString('es-ES', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  }

  // === RENDER: WORKSTATION OFFLINE ===
  if (!isOnline) {
    return (
      <div className="space-y-2">
        <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wide">
          <div className="flex items-center gap-1.5">
            <Terminal className="w-3.5 h-3.5" />
            {t('remoteTerminal')}
          </div>
        </h3>
        <div className="flex items-center gap-2 p-3 bg-gray-50 border border-gray-200 rounded-lg">
          <WifiOff className="w-4 h-4 text-gray-400 shrink-0" />
          <p className="text-sm text-gray-500">{t('remoteTerminalOffline')}</p>
        </div>
      </div>
    )
  }

  // === RENDER: TERMINAL ACTIVA ===
  const canSubmit = inputValue.trim().length > 0 && !isExecuting
  const hasHistory = history.length > 0

  return (
    <div className="space-y-2">
      {/* Header de sección */}
      <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wide">
        <div className="flex items-center gap-1.5">
          <Terminal className="w-3.5 h-3.5" />
          {t('remoteTerminal')}
        </div>
      </h3>

      {/* Área de output */}
      <div
        ref={outputRef}
        className="bg-gray-900 rounded-t-lg p-3 font-mono text-xs max-h-80 overflow-y-auto min-h-[120px]"
      >
        {history.length === 0 ? (
          <p className="text-gray-500 italic text-center py-4">
            {t('remoteTerminalPlaceholder')}
          </p>
        ) : (
          <div className="space-y-3">
            {history.map((entry) => (
              <div key={entry.id} className="space-y-0.5">
                {/* Timestamp y comando */}
                <div className="flex items-start gap-2">
                  <span className="text-gray-600 shrink-0 select-none">
                    [{formatTimestamp(entry.timestamp)}]
                  </span>
                  <span className="text-cyan-400 shrink-0 select-none">$</span>
                  <span className="text-gray-100 break-all">{entry.command}</span>
                </div>

                {/* Output o loading */}
                {entry.isLoading ? (
                  <div className="flex items-center gap-2 pl-4 mt-1">
                    <Loader2 className="w-3 h-3 text-cyan-400 animate-spin" />
                    <span className="text-gray-500 animate-pulse">
                      {t('remoteTerminalExecuting')}
                    </span>
                  </div>
                ) : entry.output ? (
                  <pre
                    className={`pl-4 mt-0.5 whitespace-pre-wrap break-all ${
                      entry.isError ? 'text-red-400' : 'text-green-400'
                    }`}
                  >
                    {entry.output}
                  </pre>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Área de input */}
      <div className="flex items-center gap-2 bg-gray-800 rounded-b-lg p-2 -mt-2">
        <span className="text-cyan-400 font-mono text-sm pl-1 select-none">&gt;</span>
        <input
          ref={inputRef}
          type="text"
          value={inputValue}
          onChange={(e) => {
            setInputValue(e.target.value)
            // Reset historyIndex al escribir manualmente
            if (historyIndex !== -1) {
              setHistoryIndex(-1)
            }
          }}
          onKeyDown={handleKeyDown}
          disabled={isExecuting}
          placeholder={t('remoteTerminalPlaceholder')}
          className="flex-1 bg-transparent border-none outline-none text-gray-100 font-mono text-xs placeholder:text-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
          autoComplete="off"
          spellCheck={false}
        />
        <Button
          variant="ghost"
          size="sm"
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="h-7 px-2 text-cyan-400 hover:text-cyan-300 hover:bg-gray-700 disabled:opacity-30"
          title={t('remoteTerminalExecute')}
        >
          {isExecuting ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Send className="w-3.5 h-3.5" />
          )}
        </Button>
      </div>

      {/* Botones de acción (visibles cuando hay historial) */}
      {hasHistory && (
        <div className="flex items-center gap-2 justify-end">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleCopyHistory}
            className="h-7 text-xs text-gray-500 hover:text-gray-700"
          >
            <Copy className="w-3 h-3 mr-1" />
            {t('remoteTerminalCopyHistory')}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={clearHistory}
            disabled={isExecuting}
            className="h-7 text-xs text-gray-500 hover:text-gray-700"
          >
            <Trash2 className="w-3 h-3 mr-1" />
            {t('remoteTerminalClearHistory')}
          </Button>
        </div>
      )}
    </div>
  )
}
