/**
 * Tests unitarios para useRemoteTerminal.
 *
 * Verifica:
 * - executeCommand agrega entrada al historial y llama API con parámetros correctos
 * - Historial se actualiza con stdout al recibir respuesta exitosa
 * - Historial se actualiza con error al recibir error HTTP 408 (timeout)
 * - Historial se actualiza con error al recibir error HTTP 409 (desconexión)
 * - Historial se actualiza con error al recibir error HTTP 500 (genérico)
 * - clearHistory vacía el array de historial
 * - copyHistory formatea entradas y copia al clipboard
 * - No permite ejecución concurrente (prevención de doble ejecución)
 *
 * Requirements: 2.1, 2.5, 2.6, 2.7, 3.5, 4.2
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useRemoteTerminal } from '../useRemoteTerminal'

// ============================================================================
// MOCKS
// ============================================================================

// Mock next-intl
const mockTranslations: Record<string, string> = {
  remoteTerminalTimeout: 'Timeout — el comando no respondió en 45 segundos',
  remoteTerminalWsDisconnected: 'La workstation se desconectó durante la ejecución',
  remoteTerminalError: 'Error al ejecutar el comando',
  remoteTerminalNoOutput: '(sin salida)',
}

vi.mock('next-intl', () => ({
  useTranslations: () => (key: string) => mockTranslations[key] || key,
}))

// Mock workstationsApi.sendCommand
const mockSendCommand = vi.fn()

vi.mock('@/lib/api', () => ({
  workstationsApi: {
    sendCommand: (...args: unknown[]) => mockSendCommand(...args),
  },
}))

// Mock crypto.randomUUID para IDs predecibles
let uuidCounter = 0
vi.stubGlobal('crypto', {
  randomUUID: () => `test-uuid-${++uuidCounter}`,
})

// Mock navigator.clipboard
const mockWriteText = vi.fn().mockResolvedValue(undefined)
Object.defineProperty(navigator, 'clipboard', {
  value: { writeText: mockWriteText },
  writable: true,
})

// ============================================================================
// TESTS
// ============================================================================

describe('useRemoteTerminal', () => {
  const workstationId = 'ws-001'

  beforeEach(() => {
    vi.clearAllMocks()
    uuidCounter = 0
    mockSendCommand.mockReset()
  })

  // --------------------------------------------------------------------------
  // executeCommand: agrega entrada al historial y llama API
  // --------------------------------------------------------------------------

  it('executeCommand agrega entrada al historial y llama API con parámetros correctos', async () => {
    mockSendCommand.mockResolvedValue({ success: true, stdout: 'resultado' })

    const { result } = renderHook(() => useRemoteTerminal(workstationId))

    await act(async () => {
      await result.current.executeCommand('dir')
    })

    // Verifica que se llamó al API con los parámetros correctos
    expect(mockSendCommand).toHaveBeenCalledWith(
      'ws-001',
      'execute_remote_command',
      { command: 'dir' }
    )

    // Verifica que se agregó la entrada al historial
    expect(result.current.history).toHaveLength(1)
    expect(result.current.history[0].command).toBe('dir')
    expect(result.current.history[0].id).toBe('test-uuid-1')
  })

  // --------------------------------------------------------------------------
  // Respuesta exitosa: historial se actualiza con stdout
  // --------------------------------------------------------------------------

  it('actualiza historial con stdout al recibir respuesta exitosa', async () => {
    mockSendCommand.mockResolvedValue({ success: true, stdout: 'contenido del directorio' })

    const { result } = renderHook(() => useRemoteTerminal(workstationId))

    await act(async () => {
      await result.current.executeCommand('dir')
    })

    const entry = result.current.history[0]
    expect(entry.output).toBe('contenido del directorio')
    expect(entry.isError).toBe(false)
    expect(entry.isLoading).toBe(false)
  })

  it('muestra "(sin salida)" cuando stdout está vacío', async () => {
    mockSendCommand.mockResolvedValue({ success: true, stdout: '' })

    const { result } = renderHook(() => useRemoteTerminal(workstationId))

    await act(async () => {
      await result.current.executeCommand('echo')
    })

    expect(result.current.history[0].output).toBe('(sin salida)')
    expect(result.current.history[0].isError).toBe(false)
  })

  it('marca como error cuando la workstation reporta success=false', async () => {
    mockSendCommand.mockResolvedValue({ success: false, output: 'comando no encontrado' })

    const { result } = renderHook(() => useRemoteTerminal(workstationId))

    await act(async () => {
      await result.current.executeCommand('invalidcmd')
    })

    const entry = result.current.history[0]
    expect(entry.output).toBe('comando no encontrado')
    expect(entry.isError).toBe(true)
    expect(entry.isLoading).toBe(false)
  })

  // --------------------------------------------------------------------------
  // Errores HTTP: 408, 409, 500
  // --------------------------------------------------------------------------

  it('muestra mensaje de timeout al recibir error HTTP 408', async () => {
    mockSendCommand.mockRejectedValue({ status: 408 })

    const { result } = renderHook(() => useRemoteTerminal(workstationId))

    await act(async () => {
      await result.current.executeCommand('long-running-cmd')
    })

    const entry = result.current.history[0]
    expect(entry.output).toBe('Timeout — el comando no respondió en 45 segundos')
    expect(entry.isError).toBe(true)
    expect(entry.isLoading).toBe(false)
  })

  it('muestra mensaje de desconexión al recibir error HTTP 409', async () => {
    mockSendCommand.mockRejectedValue({ status: 409 })

    const { result } = renderHook(() => useRemoteTerminal(workstationId))

    await act(async () => {
      await result.current.executeCommand('some-cmd')
    })

    const entry = result.current.history[0]
    expect(entry.output).toBe('La workstation se desconectó durante la ejecución')
    expect(entry.isError).toBe(true)
    expect(entry.isLoading).toBe(false)
  })

  it('muestra mensaje genérico al recibir error HTTP 500', async () => {
    mockSendCommand.mockRejectedValue({ status: 500 })

    const { result } = renderHook(() => useRemoteTerminal(workstationId))

    await act(async () => {
      await result.current.executeCommand('failing-cmd')
    })

    const entry = result.current.history[0]
    expect(entry.output).toBe('Error al ejecutar el comando')
    expect(entry.isError).toBe(true)
    expect(entry.isLoading).toBe(false)
  })

  it('muestra detail del error cuando está disponible', async () => {
    mockSendCommand.mockRejectedValue({ status: 500, detail: 'Error interno específico' })

    const { result } = renderHook(() => useRemoteTerminal(workstationId))

    await act(async () => {
      await result.current.executeCommand('failing-cmd')
    })

    expect(result.current.history[0].output).toBe('Error interno específico')
  })

  // --------------------------------------------------------------------------
  // clearHistory: vacía el array
  // --------------------------------------------------------------------------

  it('clearHistory vacía el array de historial', async () => {
    mockSendCommand.mockResolvedValue({ success: true, stdout: 'output1' })

    const { result } = renderHook(() => useRemoteTerminal(workstationId))

    // Ejecutar dos comandos
    await act(async () => {
      await result.current.executeCommand('cmd1')
    })
    await act(async () => {
      await result.current.executeCommand('cmd2')
    })

    expect(result.current.history).toHaveLength(2)

    // Limpiar
    act(() => {
      result.current.clearHistory()
    })

    expect(result.current.history).toHaveLength(0)
  })

  // --------------------------------------------------------------------------
  // copyHistory: formatea entradas y copia al clipboard
  // --------------------------------------------------------------------------

  it('copyHistory formatea historial y copia al clipboard', async () => {
    mockSendCommand
      .mockResolvedValueOnce({ success: true, stdout: 'resultado1' })
      .mockResolvedValueOnce({ success: true, stdout: 'resultado2' })

    const { result } = renderHook(() => useRemoteTerminal(workstationId))

    await act(async () => {
      await result.current.executeCommand('cmd1')
    })
    await act(async () => {
      await result.current.executeCommand('cmd2')
    })

    await act(async () => {
      await result.current.copyHistory()
    })

    expect(mockWriteText).toHaveBeenCalledWith(
      '$ cmd1\nresultado1\n\n$ cmd2\nresultado2'
    )
  })

  it('copyHistory no incluye entradas pendientes (isLoading)', async () => {
    // Simular un comando pendiente que nunca resuelve
    let resolvePromise: (value: unknown) => void
    mockSendCommand.mockImplementation(() => new Promise(resolve => {
      resolvePromise = resolve
    }))

    const { result } = renderHook(() => useRemoteTerminal(workstationId))

    // Iniciar comando sin await (queda pendiente)
    act(() => {
      result.current.executeCommand('pending-cmd')
    })

    // El historial tiene una entrada pendiente
    await waitFor(() => {
      expect(result.current.history).toHaveLength(1)
    })
    expect(result.current.history[0].isLoading).toBe(true)

    // Copiar — debe filtrar la entrada pendiente
    await act(async () => {
      await result.current.copyHistory()
    })

    expect(mockWriteText).toHaveBeenCalledWith('')

    // Cleanup: resolver la promesa pendiente
    await act(async () => {
      resolvePromise!({ success: true, stdout: 'done' })
    })
  })

  // --------------------------------------------------------------------------
  // Prevención de ejecución concurrente
  // --------------------------------------------------------------------------

  it('no permite ejecutar si ya hay un comando en progreso', async () => {
    let resolveFirst: (value: unknown) => void
    mockSendCommand.mockImplementation(() => new Promise(resolve => {
      resolveFirst = resolve
    }))

    const { result } = renderHook(() => useRemoteTerminal(workstationId))

    // Iniciar primer comando (queda pendiente)
    act(() => {
      result.current.executeCommand('first-cmd')
    })

    await waitFor(() => {
      expect(result.current.isExecuting).toBe(true)
    })

    // Intentar segundo comando mientras primero está en curso
    await act(async () => {
      await result.current.executeCommand('second-cmd')
    })

    // Solo se llamó al API una vez (el segundo fue bloqueado)
    expect(mockSendCommand).toHaveBeenCalledTimes(1)
    expect(mockSendCommand).toHaveBeenCalledWith('ws-001', 'execute_remote_command', { command: 'first-cmd' })

    // Solo hay una entrada en historial
    expect(result.current.history).toHaveLength(1)
    expect(result.current.history[0].command).toBe('first-cmd')

    // Cleanup: resolver la promesa
    await act(async () => {
      resolveFirst!({ success: true, stdout: 'done' })
    })

    // Ahora isExecuting debe ser false
    expect(result.current.isExecuting).toBe(false)
  })

  it('permite ejecutar otro comando después de que el primero termina', async () => {
    mockSendCommand
      .mockResolvedValueOnce({ success: true, stdout: 'out1' })
      .mockResolvedValueOnce({ success: true, stdout: 'out2' })

    const { result } = renderHook(() => useRemoteTerminal(workstationId))

    await act(async () => {
      await result.current.executeCommand('cmd1')
    })

    expect(result.current.isExecuting).toBe(false)

    await act(async () => {
      await result.current.executeCommand('cmd2')
    })

    expect(mockSendCommand).toHaveBeenCalledTimes(2)
    expect(result.current.history).toHaveLength(2)
    expect(result.current.history[1].output).toBe('out2')
  })

  // --------------------------------------------------------------------------
  // Estado isExecuting
  // --------------------------------------------------------------------------

  it('isExecuting es true mientras se espera respuesta del API', async () => {
    let resolvePromise: (value: unknown) => void
    mockSendCommand.mockImplementation(() => new Promise(resolve => {
      resolvePromise = resolve
    }))

    const { result } = renderHook(() => useRemoteTerminal(workstationId))

    expect(result.current.isExecuting).toBe(false)

    act(() => {
      result.current.executeCommand('test-cmd')
    })

    await waitFor(() => {
      expect(result.current.isExecuting).toBe(true)
    })

    await act(async () => {
      resolvePromise!({ success: true, stdout: 'ok' })
    })

    expect(result.current.isExecuting).toBe(false)
  })

  // --------------------------------------------------------------------------
  // Timestamp en entradas
  // --------------------------------------------------------------------------

  it('cada entrada del historial tiene un timestamp válido', async () => {
    mockSendCommand.mockResolvedValue({ success: true, stdout: 'ok' })

    const before = new Date()
    const { result } = renderHook(() => useRemoteTerminal(workstationId))

    await act(async () => {
      await result.current.executeCommand('test')
    })

    const after = new Date()
    const timestamp = result.current.history[0].timestamp

    expect(timestamp).toBeInstanceOf(Date)
    expect(timestamp.getTime()).toBeGreaterThanOrEqual(before.getTime())
    expect(timestamp.getTime()).toBeLessThanOrEqual(after.getTime())
  })
})
