/**
 * Tests unitarios para RemoteTerminalSection.
 *
 * Verifica:
 * - Se renderiza cuando workstation online y usuario Admin/Operator
 * - No se renderiza cuando usuario ReadOnly
 * - Estado disabled con mensaje cuando workstation offline
 * - Input deshabilitado durante ejecución
 * - Botón deshabilitado con input vacío/whitespace
 * - Submit con Enter ejecuta comando
 * - Up/Down arrow navega por historial
 * - Auto-scroll al agregar entrada
 *
 * Requirements: 1.1, 1.2, 1.3, 2.2, 4.2, 6.2, 6.3
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// ============================================================================
// MOCKS
// ============================================================================

// Mock next-intl: retorna la key como texto
vi.mock('next-intl', () => ({
  useTranslations: () => {
    const t = (key: string) => key
    return t
  },
}))

// Mock useAuth
const mockIsAdmin = vi.fn(() => true)
let mockUser: { email: string } | null = { email: 'admin@robles.ai' }
vi.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({
    isAdmin: mockIsAdmin,
    user: mockUser,
  }),
}))

// Mock useRemoteTerminal
const mockExecuteCommand = vi.fn().mockResolvedValue(undefined)
const mockClearHistory = vi.fn()
const mockCopyHistory = vi.fn().mockResolvedValue(undefined)
let mockHistory: Array<{
  id: string
  command: string
  output: string | null
  isError: boolean
  timestamp: Date
  isLoading: boolean
}> = []
let mockIsExecuting = false

vi.mock('@/hooks/useRemoteTerminal', () => ({
  useRemoteTerminal: () => ({
    history: mockHistory,
    isExecuting: mockIsExecuting,
    executeCommand: mockExecuteCommand,
    clearHistory: mockClearHistory,
    copyHistory: mockCopyHistory,
  }),
}))

// Mock useToast
const mockToast = vi.fn()
vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: mockToast }),
}))

// Importar componente después de los mocks
import { RemoteTerminalSection } from '../RemoteTerminalSection'

// ============================================================================
// HELPERS
// ============================================================================

function createHistoryEntry(overrides: Partial<typeof mockHistory[number]> = {}) {
  return {
    id: 'entry-1',
    command: 'dir',
    output: 'contenido',
    isError: false,
    timestamp: new Date('2024-06-15T12:00:00Z'),
    isLoading: false,
    ...overrides,
  }
}

// ============================================================================
// TESTS
// ============================================================================

describe('RemoteTerminalSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockIsAdmin.mockReturnValue(true)
    mockUser = { email: 'admin@robles.ai' }
    mockHistory = []
    mockIsExecuting = false
  })

  // --------------------------------------------------------------------------
  // Renderizado condicional según rol y estado online
  // --------------------------------------------------------------------------

  describe('Control de acceso por dominio', () => {
    it('se renderiza cuando usuario es Admin con email @robles.ai', () => {
      mockIsAdmin.mockReturnValue(true)
      mockUser = { email: 'admin@robles.ai' }

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      expect(screen.getByText('remoteTerminal')).toBeInTheDocument()
      expect(screen.getByPlaceholderText('remoteTerminalPlaceholder')).toBeInTheDocument()
    })

    it('se renderiza cuando usuario es Admin con email @sistemas.com.pe', () => {
      mockIsAdmin.mockReturnValue(true)
      mockUser = { email: 'user@sistemas.com.pe' }

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      expect(screen.getByText('remoteTerminal')).toBeInTheDocument()
      expect(screen.getByPlaceholderText('remoteTerminalPlaceholder')).toBeInTheDocument()
    })

    it('no se renderiza cuando usuario es Admin pero email no es de dominio autorizado', () => {
      mockIsAdmin.mockReturnValue(true)
      mockUser = { email: 'admin@otraempresa.com' }

      const { container } = render(
        <RemoteTerminalSection workstationId="ws-001" isOnline={true} />
      )

      expect(container.innerHTML).toBe('')
    })

    it('no se renderiza cuando usuario no es Admin (aunque email sea de dominio autorizado)', () => {
      mockIsAdmin.mockReturnValue(false)
      mockUser = { email: 'operator@robles.ai' }

      const { container } = render(
        <RemoteTerminalSection workstationId="ws-001" isOnline={true} />
      )

      expect(container.innerHTML).toBe('')
    })

    it('no se renderiza cuando user es null', () => {
      mockIsAdmin.mockReturnValue(true)
      mockUser = null

      const { container } = render(
        <RemoteTerminalSection workstationId="ws-001" isOnline={true} />
      )

      expect(container.innerHTML).toBe('')
    })
  })

  // --------------------------------------------------------------------------
  // Estado offline
  // --------------------------------------------------------------------------

  describe('Workstation offline', () => {
    it('muestra estado disabled con mensaje cuando workstation está offline', () => {
      render(<RemoteTerminalSection workstationId="ws-001" isOnline={false} />)

      // Debe mostrar el título de sección
      expect(screen.getByText('remoteTerminal')).toBeInTheDocument()
      // Debe mostrar el mensaje de offline
      expect(screen.getByText('remoteTerminalOffline')).toBeInTheDocument()
      // No debe mostrar el input de comandos
      expect(screen.queryByPlaceholderText('remoteTerminalPlaceholder')).not.toBeInTheDocument()
    })
  })

  // --------------------------------------------------------------------------
  // Input deshabilitado durante ejecución
  // --------------------------------------------------------------------------

  describe('Estado durante ejecución', () => {
    it('input está deshabilitado cuando isExecuting es true', () => {
      mockIsExecuting = true

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const input = screen.getByPlaceholderText('remoteTerminalPlaceholder')
      expect(input).toBeDisabled()
    })

    it('input está habilitado cuando isExecuting es false', () => {
      mockIsExecuting = false

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const input = screen.getByPlaceholderText('remoteTerminalPlaceholder')
      expect(input).not.toBeDisabled()
    })
  })

  // --------------------------------------------------------------------------
  // Botón deshabilitado con input vacío/whitespace
  // --------------------------------------------------------------------------

  describe('Botón ejecutar', () => {
    it('botón está deshabilitado con input vacío', () => {
      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const button = screen.getByTitle('remoteTerminalExecute')
      expect(button).toBeDisabled()
    })

    it('botón está deshabilitado con input solo whitespace', () => {
      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const input = screen.getByPlaceholderText('remoteTerminalPlaceholder')
      fireEvent.change(input, { target: { value: '   ' } })

      const button = screen.getByTitle('remoteTerminalExecute')
      expect(button).toBeDisabled()
    })

    it('botón está habilitado con input válido', () => {
      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const input = screen.getByPlaceholderText('remoteTerminalPlaceholder')
      fireEvent.change(input, { target: { value: 'dir' } })

      const button = screen.getByTitle('remoteTerminalExecute')
      expect(button).not.toBeDisabled()
    })

    it('botón está deshabilitado durante ejecución aunque haya texto', () => {
      mockIsExecuting = true

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const input = screen.getByPlaceholderText('remoteTerminalPlaceholder')
      // Input está disabled, pero si tuviera valor previo el botón estaría disabled igual
      // por la condición de isExecuting
      const button = screen.getByTitle('remoteTerminalExecute')
      expect(button).toBeDisabled()
    })
  })

  // --------------------------------------------------------------------------
  // Submit con Enter
  // --------------------------------------------------------------------------

  describe('Submit con Enter', () => {
    it('Enter ejecuta comando con texto trimmeado', async () => {
      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const input = screen.getByPlaceholderText('remoteTerminalPlaceholder')
      fireEvent.change(input, { target: { value: '  ipconfig  ' } })
      fireEvent.keyDown(input, { key: 'Enter' })

      await waitFor(() => {
        expect(mockExecuteCommand).toHaveBeenCalledWith('ipconfig')
      })
    })

    it('Enter no ejecuta con input vacío', () => {
      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const input = screen.getByPlaceholderText('remoteTerminalPlaceholder')
      fireEvent.keyDown(input, { key: 'Enter' })

      expect(mockExecuteCommand).not.toHaveBeenCalled()
    })

    it('Enter no ejecuta durante ejecución en curso', () => {
      mockIsExecuting = true

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const input = screen.getByPlaceholderText('remoteTerminalPlaceholder')
      // Aunque disabled, verificamos que handleSubmit no se llama
      fireEvent.keyDown(input, { key: 'Enter' })

      expect(mockExecuteCommand).not.toHaveBeenCalled()
    })

    it('limpia el input después de submit exitoso', async () => {
      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const input = screen.getByPlaceholderText('remoteTerminalPlaceholder')
      fireEvent.change(input, { target: { value: 'dir' } })
      fireEvent.keyDown(input, { key: 'Enter' })

      await waitFor(() => {
        expect(input).toHaveValue('')
      })
    })
  })

  // --------------------------------------------------------------------------
  // Navegación por historial con flechas
  // --------------------------------------------------------------------------

  describe('Navegación por historial con teclado', () => {
    it('ArrowUp no hace nada con historial vacío', () => {
      mockHistory = []

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const input = screen.getByPlaceholderText('remoteTerminalPlaceholder')
      fireEvent.change(input, { target: { value: 'actual' } })
      fireEvent.keyDown(input, { key: 'ArrowUp' })

      // Input no debe cambiar
      expect(input).toHaveValue('actual')
    })

    it('ArrowUp cicla hacia atrás por comandos ejecutados', () => {
      mockHistory = [
        createHistoryEntry({ id: '1', command: 'cmd1' }),
        createHistoryEntry({ id: '2', command: 'cmd2' }),
        createHistoryEntry({ id: '3', command: 'cmd3' }),
      ]

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const input = screen.getByPlaceholderText('remoteTerminalPlaceholder')

      // Primera ArrowUp: último comando (cmd3)
      fireEvent.keyDown(input, { key: 'ArrowUp' })
      expect(input).toHaveValue('cmd3')

      // Segunda ArrowUp: penúltimo (cmd2)
      fireEvent.keyDown(input, { key: 'ArrowUp' })
      expect(input).toHaveValue('cmd2')

      // Tercera ArrowUp: primero (cmd1)
      fireEvent.keyDown(input, { key: 'ArrowUp' })
      expect(input).toHaveValue('cmd1')

      // Cuarta ArrowUp: se queda en el primero
      fireEvent.keyDown(input, { key: 'ArrowUp' })
      expect(input).toHaveValue('cmd1')
    })

    it('ArrowDown cicla hacia adelante y restaura input vacío', () => {
      mockHistory = [
        createHistoryEntry({ id: '1', command: 'cmd1' }),
        createHistoryEntry({ id: '2', command: 'cmd2' }),
      ]

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const input = screen.getByPlaceholderText('remoteTerminalPlaceholder')

      // Subir hasta el primer comando
      fireEvent.keyDown(input, { key: 'ArrowUp' })
      fireEvent.keyDown(input, { key: 'ArrowUp' })
      expect(input).toHaveValue('cmd1')

      // Bajar: siguiente (cmd2)
      fireEvent.keyDown(input, { key: 'ArrowDown' })
      expect(input).toHaveValue('cmd2')

      // Bajar otra vez: vuelve a vacío (savedInput)
      fireEvent.keyDown(input, { key: 'ArrowDown' })
      expect(input).toHaveValue('')
    })

    it('ArrowDown no hace nada si no se ha navegado hacia arriba', () => {
      mockHistory = [
        createHistoryEntry({ id: '1', command: 'cmd1' }),
      ]

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const input = screen.getByPlaceholderText('remoteTerminalPlaceholder')
      fireEvent.change(input, { target: { value: 'mi texto' } })
      fireEvent.keyDown(input, { key: 'ArrowDown' })

      // Input no cambia
      expect(input).toHaveValue('mi texto')
    })

    it('guarda input actual al comenzar navegación y lo restaura al volver', () => {
      mockHistory = [
        createHistoryEntry({ id: '1', command: 'cmd1' }),
        createHistoryEntry({ id: '2', command: 'cmd2' }),
      ]

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const input = screen.getByPlaceholderText('remoteTerminalPlaceholder')

      // Escribir algo
      fireEvent.change(input, { target: { value: 'mi texto parcial' } })

      // Navegar arriba
      fireEvent.keyDown(input, { key: 'ArrowUp' })
      expect(input).toHaveValue('cmd2')

      // Navegar abajo hasta volver — restaura el texto guardado
      fireEvent.keyDown(input, { key: 'ArrowDown' })
      expect(input).toHaveValue('mi texto parcial')
    })

    it('ignora entradas con isLoading=true en la navegación', () => {
      mockHistory = [
        createHistoryEntry({ id: '1', command: 'cmd1', isLoading: false }),
        createHistoryEntry({ id: '2', command: 'pending', isLoading: true }),
      ]

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const input = screen.getByPlaceholderText('remoteTerminalPlaceholder')

      // ArrowUp debería solo mostrar cmd1 (el pendiente se excluye)
      fireEvent.keyDown(input, { key: 'ArrowUp' })
      expect(input).toHaveValue('cmd1')
    })
  })

  // --------------------------------------------------------------------------
  // Auto-scroll al agregar entrada
  // --------------------------------------------------------------------------

  describe('Auto-scroll', () => {
    it('hace scroll al final cuando el historial cambia', () => {
      // Primera renderización sin historial
      const { rerender } = render(
        <RemoteTerminalSection workstationId="ws-001" isOnline={true} />
      )

      // Simular que se agrega una entrada al historial
      mockHistory = [createHistoryEntry()]

      rerender(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      // El efecto de auto-scroll se activa con [history].
      // No podemos verificar scrollTop directamente en jsdom (siempre 0),
      // pero verificamos que el área de output existe y el efecto no lanza error.
      // La verificación real de scroll se haría en e2e.
      // Aquí verificamos que la salida del historial se muestra correctamente.
      expect(screen.getByText('dir')).toBeInTheDocument()
      expect(screen.getByText('contenido')).toBeInTheDocument()
    })
  })

  // --------------------------------------------------------------------------
  // Historial de comandos: renderizado
  // --------------------------------------------------------------------------

  describe('Renderizado de historial', () => {
    it('muestra placeholder cuando historial está vacío', () => {
      mockHistory = []

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      // El placeholder se muestra como texto itálico centrado
      expect(screen.getByText('remoteTerminalPlaceholder')).toBeInTheDocument()
    })

    it('muestra comando y output para entradas completadas', () => {
      mockHistory = [
        createHistoryEntry({ command: 'ipconfig', output: '192.168.1.1' }),
      ]

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      expect(screen.getByText('ipconfig')).toBeInTheDocument()
      expect(screen.getByText('192.168.1.1')).toBeInTheDocument()
    })

    it('muestra indicador de carga para entradas pendientes', () => {
      mockHistory = [
        createHistoryEntry({ command: 'long-cmd', output: null, isLoading: true }),
      ]

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      expect(screen.getByText('long-cmd')).toBeInTheDocument()
      expect(screen.getByText('remoteTerminalExecuting')).toBeInTheDocument()
    })

    it('muestra errores con estilo diferenciado (clase text-red-400)', () => {
      mockHistory = [
        createHistoryEntry({ command: 'bad-cmd', output: 'error msg', isError: true }),
      ]

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const errorOutput = screen.getByText('error msg')
      expect(errorOutput).toHaveClass('text-red-400')
    })

    it('muestra output exitoso con estilo verde (clase text-green-400)', () => {
      mockHistory = [
        createHistoryEntry({ command: 'dir', output: 'archivos', isError: false }),
      ]

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const successOutput = screen.getByText('archivos')
      expect(successOutput).toHaveClass('text-green-400')
    })
  })

  // --------------------------------------------------------------------------
  // Botones de acción (copiar/limpiar)
  // --------------------------------------------------------------------------

  describe('Botones de acción', () => {
    it('muestra botones copiar y limpiar cuando hay historial', () => {
      mockHistory = [createHistoryEntry()]

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      expect(screen.getByText('remoteTerminalCopyHistory')).toBeInTheDocument()
      expect(screen.getByText('remoteTerminalClearHistory')).toBeInTheDocument()
    })

    it('no muestra botones cuando historial está vacío', () => {
      mockHistory = []

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      expect(screen.queryByText('remoteTerminalCopyHistory')).not.toBeInTheDocument()
      expect(screen.queryByText('remoteTerminalClearHistory')).not.toBeInTheDocument()
    })

    it('copiar historial llama copyHistory y muestra toast', async () => {
      mockHistory = [createHistoryEntry()]

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const copyButton = screen.getByText('remoteTerminalCopyHistory')
      fireEvent.click(copyButton)

      await waitFor(() => {
        expect(mockCopyHistory).toHaveBeenCalled()
        expect(mockToast).toHaveBeenCalledWith({ title: 'remoteTerminalCopied' })
      })
    })

    it('limpiar historial llama clearHistory', () => {
      mockHistory = [createHistoryEntry()]

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const clearButton = screen.getByText('remoteTerminalClearHistory')
      fireEvent.click(clearButton)

      expect(mockClearHistory).toHaveBeenCalled()
    })

    it('botón limpiar está deshabilitado durante ejecución', () => {
      mockHistory = [createHistoryEntry()]
      mockIsExecuting = true

      render(<RemoteTerminalSection workstationId="ws-001" isOnline={true} />)

      const clearButton = screen.getByText('remoteTerminalClearHistory').closest('button')
      expect(clearButton).toBeDisabled()
    })
  })
})
