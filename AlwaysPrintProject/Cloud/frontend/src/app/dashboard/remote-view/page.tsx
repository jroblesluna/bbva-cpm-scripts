/**
 * Página de Vista Remota.
 * Gestiona múltiples sesiones como tabs horizontales.
 * El tab activo recibe frames; los inactivos envían rv_pause.
 * Al volver a un tab: rv_resume → espera keyframe.
 *
 * Route: /dashboard/remote-view?session={id}&ws={workstation_id}
 */

'use client'

import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { useTranslations } from 'next-intl'
import { X, Monitor } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { SessionTab } from '@/components/remote-view/SessionTab'
import { useWebSocket } from '@/hooks/useWebSocket'
import { remoteViewApi } from '@/lib/api'
import type {
  RemoteViewTab,
  RemoteViewStatus,
  RemoteViewMode,
  RemoteViewMonitor,
  RvInputMessage,
  DeltaTile,
} from '@/types/remote-view'
import type { OperatorMessage } from '@/types'

// ============================================================================
// REDUCER: Estado de tabs de sesiones
// ============================================================================

interface RemoteViewState {
  tabs: RemoteViewTab[]
  activeTabId: string | null
}

type RemoteViewAction =
  | { type: 'ADD_TAB'; tab: RemoteViewTab }
  | { type: 'REMOVE_TAB'; sessionId: string }
  | { type: 'SET_ACTIVE'; sessionId: string }
  | { type: 'UPDATE_STATUS'; sessionId: string; status: RemoteViewStatus }
  | { type: 'UPDATE_MODE'; sessionId: string; mode: RemoteViewMode }
  | { type: 'SET_MONITORS'; sessionId: string; monitors: RemoteViewMonitor[] }

function remoteViewReducer(state: RemoteViewState, action: RemoteViewAction): RemoteViewState {
  switch (action.type) {
    case 'ADD_TAB': {
      // No duplicar tabs para la misma sesión
      if (state.tabs.some((t) => t.sessionId === action.tab.sessionId)) {
        return { ...state, activeTabId: action.tab.sessionId }
      }
      return {
        tabs: [...state.tabs, action.tab],
        activeTabId: action.tab.sessionId,
      }
    }
    case 'REMOVE_TAB': {
      const remaining = state.tabs.filter((t) => t.sessionId !== action.sessionId)
      let newActive = state.activeTabId
      if (state.activeTabId === action.sessionId) {
        newActive = remaining.length > 0 ? remaining[remaining.length - 1].sessionId : null
      }
      return { tabs: remaining, activeTabId: newActive }
    }
    case 'SET_ACTIVE': {
      return { ...state, activeTabId: action.sessionId }
    }
    case 'UPDATE_STATUS': {
      return {
        ...state,
        tabs: state.tabs.map((t) =>
          t.sessionId === action.sessionId ? { ...t, status: action.status } : t
        ),
      }
    }
    case 'UPDATE_MODE': {
      return {
        ...state,
        tabs: state.tabs.map((t) =>
          t.sessionId === action.sessionId ? { ...t, mode: action.mode } : t
        ),
      }
    }
    case 'SET_MONITORS': {
      return {
        ...state,
        tabs: state.tabs.map((t) =>
          t.sessionId === action.sessionId
            ? { ...t, monitors: action.monitors, status: 'active' as RemoteViewStatus }
            : t
        ),
      }
    }
    default:
      return state
  }
}

// ============================================================================
// PÁGINA PRINCIPAL
// ============================================================================

export default function RemoteViewPage() {
  const t = useTranslations('remoteView')
  const searchParams = useSearchParams()
  const [state, dispatch] = useReducer(remoteViewReducer, { tabs: [], activeTabId: null })
  const previousActiveRef = useRef<string | null>(null)
  const hydratedRef = useRef(false)
  const mountTimeRef = useRef(Date.now())
  const tabsRef = useRef(state.tabs)
  tabsRef.current = state.tabs

  // Estado de frames por sesión (useRef para evitar re-renders en cada frame)
  const frameDataRef = useRef<Record<string, { data: string; width: number; height: number }>>({})
  const deltaDataRef = useRef<Record<string, { tiles: DeltaTile[]; width: number; height: number }>>({})
  const [frameVersion, setFrameVersion] = useState(0)
  // Timestamp del último frame recibido (para retry automático)
  const lastFrameTimeRef = useRef<number>(0)

  // Conexión WebSocket para recibir mensajes del backend
  const { isConnected, addMessageHandler, send: wsSend } = useWebSocket({ autoConnect: true })

  // Hidratar tabs desde sessionStorage al montar (persistir estado al navegar)
  // Solo restaurar tabs de menos de 2 minutos (sesiones probablemente aún activas)
  useEffect(() => {
    if (hydratedRef.current) return
    hydratedRef.current = true

    if (typeof window === 'undefined') return
    try {
      const savedTabs = sessionStorage.getItem('rv_tabs')
      const savedActive = sessionStorage.getItem('rv_activeTab')
      if (savedTabs) {
        const tabs = JSON.parse(savedTabs) as RemoteViewTab[]
        // No filtrar por edad — el check periódico cada 15s cerrará tabs muertos
        const freshTabs = tabs
        freshTabs.forEach(tab => dispatch({ type: 'ADD_TAB', tab }))
        if (savedActive && freshTabs.some(t => t.sessionId === savedActive)) {
          dispatch({ type: 'SET_ACTIVE', sessionId: savedActive })
        }
      }
    } catch { /* ignorar errores de parse */ }
  }, [])

  // Persistir tabs en sessionStorage para no perder estado al navegar
  useEffect(() => {
    if (!hydratedRef.current) return
    if (state.tabs.length > 0) {
      sessionStorage.setItem('rv_tabs', JSON.stringify(state.tabs))
      sessionStorage.setItem('rv_activeTab', state.activeTabId || '')
    } else {
      sessionStorage.removeItem('rv_tabs')
      sessionStorage.removeItem('rv_activeTab')
    }
  }, [state.tabs, state.activeTabId])

  // Leer query params para abrir sesión inicial
  useEffect(() => {
    const sessionId = searchParams.get('session')
    const workstationId = searchParams.get('ws')
    const ip = searchParams.get('ip') || ''
    const hostname = searchParams.get('hostname') || ''
    const mode = (searchParams.get('mode') as RemoteViewMode) || 'screenshot'

    if (sessionId && workstationId) {
      dispatch({
        type: 'ADD_TAB',
        tab: {
          sessionId,
          workstationId,
          ip,
          hostname,
          mode,
          status: (searchParams.get('status') as RemoteViewStatus) || 'pending_consent',
          monitors: [],
          selectedMonitor: 0,
          startedAt: new Date().toISOString(),
        },
      })
    }
  }, [searchParams])

  // Manejar mensajes WebSocket entrantes (remote_view_accepted, remote_view_rejected, etc.)
  // Los tipos de mensajes de remote view aún no están en la unión OperatorMessage,
  // se agregan conforme se implementen los handlers en el backend.
  const handleWsMessage = useCallback(
    (message: OperatorMessage) => {
      // Cast genérico para manejar mensajes remote view que aún no están en la unión
      const msg = message as unknown as {
        type: string
        session_id?: string
        monitors?: RemoteViewMonitor[]
        reason?: string
      }

      if (msg.type === 'remote_view_accepted' && msg.session_id) {
        dispatch({
          type: 'SET_MONITORS',
          sessionId: msg.session_id,
          monitors: msg.monitors || [],
        })
      }

      if (msg.type === 'remote_view_rejected' && msg.session_id) {
        const rejectedMsg = msg as unknown as { type: string; session_id: string; reason?: string }
        // Mapear el motivo de rechazo al estado de display apropiado
        const rejectionStatus: RemoteViewStatus =
          rejectedMsg.reason === 'user_timeout' ? 'expired' : 'disconnected'
        dispatch({
          type: 'UPDATE_STATUS',
          sessionId: rejectedMsg.session_id,
          status: rejectionStatus,
        })
      }

      if (msg.type === 'rv_frame' && msg.session_id) {
        const frameMsg = msg as unknown as {
          type: string
          session_id: string
          frame_type?: string  // "keyframe" | "delta" | undefined (legacy)
          format?: string
          width: number
          height: number
          data?: string         // Presente en keyframe y legacy
          tiles?: DeltaTile[]   // Presente en delta frames
        }

        if (frameMsg.data) {
          // Keyframe o frame legacy — imagen JPEG completa
          frameDataRef.current[frameMsg.session_id] = {
            data: frameMsg.data,
            width: frameMsg.width,
            height: frameMsg.height,
          }
          // Limpiar delta cuando llega un keyframe (el canvas se redibuja completo)
          delete deltaDataRef.current[frameMsg.session_id]
          lastFrameTimeRef.current = Date.now()
          setFrameVersion(v => v + 1)
        } else if (frameMsg.tiles && Array.isArray(frameMsg.tiles)) {
          // Delta frame — array de tiles que cambiaron
          deltaDataRef.current[frameMsg.session_id] = {
            tiles: frameMsg.tiles,
            width: frameMsg.width,
            height: frameMsg.height,
          }
          lastFrameTimeRef.current = Date.now()
          setFrameVersion(v => v + 1)
        }
      }
    },
    []
  )

  useEffect(() => {
    const removeHandler = addMessageHandler(handleWsMessage)
    return removeHandler
  }, [addMessageHandler, handleWsMessage])

  // Verificar estado de sesiones al conectar WS y periódicamente:
  // - pending_consent: verificar si ya fue aceptada o rechazada
  // - active: verificar si la sesión sigue existiendo (pudo expirar o cerrarse en backend)
  // Usa tabsRef para leer tabs frescos sin re-disparar el effect en cada cambio de state.tabs
  useEffect(() => {
    if (!isConnected) return

    const checkSessions = async () => {
      const tabs = tabsRef.current
      for (const tab of tabs) {
        if (tab.status !== 'pending_consent' && tab.status !== 'active') continue
        try {
          const status = await remoteViewApi.getStatus(tab.workstationId)

          if (tab.status === 'pending_consent') {
            if (status.active && status.session_id === tab.sessionId) {
              // Sesión aceptada — transicionar a active
              dispatch({ type: 'UPDATE_STATUS', sessionId: tab.sessionId, status: 'active' })
            } else if (!status.active) {
              // Sesión ya no existe — fue rechazada o expiró
              const sessionAge = Date.now() - new Date(tab.startedAt).getTime()
              if (sessionAge > 35000) {
                dispatch({ type: 'REMOVE_TAB', sessionId: tab.sessionId })
              }
            }
          } else if (tab.status === 'active') {
            // Verificar si la sesión sigue activa en el backend
            if (!status.active || status.session_id !== tab.sessionId) {
              // Sesión muerta en el backend — cerrar tab automáticamente
              dispatch({ type: 'REMOVE_TAB', sessionId: tab.sessionId })
            }
          }
        } catch { /* Error de red — no cerrar el tab, reintentar después */ }
      }
    }

    // Verificar 2s después de conectar (catch-up inicial)
    const initialTimer = setTimeout(checkSessions, 2000)

    // Verificar periódicamente cada 15s (detectar sesiones que murieron)
    const periodicTimer = setInterval(checkSessions, 15000)

    return () => {
      clearTimeout(initialTimer)
      clearInterval(periodicTimer)
    }
  }, [isConnected])

  // Enviar rv_pause / rv_resume al cambiar de tab activo
  // No enviar señales en los primeros 2s después del mount para evitar
  // que tabs hidratados desde sessionStorage interfieran con sesiones nuevas
  // que se crean desde query params o WS connect
  useEffect(() => {
    const prevId = previousActiveRef.current
    const currentId = state.activeTabId

    if (Date.now() - mountTimeRef.current < 2000) {
      previousActiveRef.current = currentId
      return
    }

    if (prevId && prevId !== currentId) {
      // Pausar tab anterior
      sendPauseSignal(prevId)
    }

    if (currentId && currentId !== prevId) {
      // Reanudar tab nuevo (o primer frame si es primera vez)
      sendResumeSignal(currentId)
    }

    previousActiveRef.current = currentId
  }, [state.activeTabId])

  // Funciones de señalización vía WebSocket
  const sendPauseSignal = (sessionId: string) => {
    sendWsMessage({ type: 'remote_view_pause', session_id: sessionId })
  }

  const sendResumeSignal = (sessionId: string) => {
    sendWsMessage({ type: 'remote_view_resume', session_id: sessionId })
  }

  const sendStopSignal = (sessionId: string) => {
    sendWsMessage({ type: 'remote_view_stop', session_id: sessionId, reason: 'admin_closed' })
  }

  /** Enviar mensaje JSON al WebSocket del operador */
  const sendWsMessage = useCallback((payload: Record<string, unknown>) => {
    const sent = wsSend(payload)
    if (!sent) {
      console.warn('[RemoteView] No se pudo enviar mensaje WS (desconectado):', payload.type)
    }
  }, [wsSend])

  // Enviar primer rv_request_frame cuando WS conecta (no antes)
  // Esto reemplaza el request-on-mount del ScreenshotViewer que siempre se pierde
  // porque el WS tarda 100-500ms en conectar y el mount ocurre antes.
  useEffect(() => {
    if (!isConnected) return
    if (!state.activeTabId) return

    const activeTab = tabsRef.current.find(t => t.sessionId === state.activeTabId)
    if (!activeTab || activeTab.status !== 'active') return

    // Enviar request 500ms después de conectar (dar tiempo al backend para registrar el operator WS)
    const timer = setTimeout(() => {
      sendWsMessage({
        type: 'rv_request_frame',
        session_id: state.activeTabId!,
      })
    }, 500)

    return () => clearTimeout(timer)
  }, [isConnected, state.activeTabId, sendWsMessage])

  // Heartbeat "viewer_alive": indica al Tray que el frontend está activamente mostrando frames.
  // Si el Tray no recibe este heartbeat en 10s, pausa el streaming (ahorra CPU/bandwidth).
  // Si no recibe en 60s, cierra la sesión completamente.
  useEffect(() => {
    if (!isConnected || !state.activeTabId) return

    const activeTab = tabsRef.current.find(t => t.sessionId === state.activeTabId)
    if (!activeTab || activeTab.status !== 'active') return

    // Enviar heartbeat inmediatamente y cada 3s
    const sendHeartbeat = () => {
      sendWsMessage({
        type: 'rv_viewer_alive',
        session_id: state.activeTabId!,
      })
    }

    sendHeartbeat() // Inmediato al conectar/activar
    const interval = setInterval(sendHeartbeat, 3000)

    return () => clearInterval(interval)
  }, [isConnected, state.activeTabId, sendWsMessage])

  // Auto-retry: si no llegan frames en 5s después de conectar, re-solicitar
  // Esto fuerza el lazy-register en el worker correcto y restablece el flujo
  useEffect(() => {
    if (!isConnected || !state.activeTabId) return

    const activeTab = state.tabs.find(t => t.sessionId === state.activeTabId)
    if (!activeTab || activeTab.status !== 'active') return

    const retryTimer = setInterval(() => {
      const timeSinceLastFrame = Date.now() - lastFrameTimeRef.current
      // Si han pasado más de 5s sin recibir frame y hay una sesión activa, reintentar
      if (timeSinceLastFrame > 5000) {
        sendWsMessage({
          type: 'rv_request_frame',
          session_id: state.activeTabId!,
        })
      }
    }, 5000)

    return () => clearInterval(retryTimer)
  }, [isConnected, state.activeTabId, state.tabs, sendWsMessage])

  // Cerrar tab y enviar stop
  const handleCloseTab = (sessionId: string) => {
    // Enviar stop vía WS (best-effort, puede fallar por cross-worker)
    sendStopSignal(sessionId)

    // También cerrar vía REST directamente (garantiza cierre en BD)
    const tab = state.tabs.find(t => t.sessionId === sessionId)
    if (tab) {
      remoteViewApi.stop(tab.workstationId).catch(() => {
        // Ignorar error — la sesión podría ya estar cerrada
      })
    }

    dispatch({ type: 'REMOVE_TAB', sessionId })
  }

  // Cambiar tab activo
  const handleSelectTab = (sessionId: string) => {
    dispatch({ type: 'SET_ACTIVE', sessionId })
  }

  /**
   * Cambio de modo: envía remote_view_config con el nuevo mode al backend (Req 9.9, 11.4).
   * El Tray recibe el mensaje y transiciona seamless (sin recrear sesión).
   * El frontend actualiza el state para renderizar el viewer correcto.
   */
  const handleModeChange = useCallback(
    (sessionId: string, newMode: RemoteViewMode) => {
      sendWsMessage({
        type: 'remote_view_config',
        session_id: sessionId,
        mode: newMode,
      })
      dispatch({ type: 'UPDATE_MODE', sessionId, mode: newMode })
    },
    [sendWsMessage]
  )

  /** Cambio de monitor: envía remote_view_config con nuevo monitor index */
  const handleMonitorChange = useCallback(
    (sessionId: string, monitorIndex: number) => {
      sendWsMessage({
        type: 'remote_view_config',
        session_id: sessionId,
        monitor: monitorIndex,
      })
    },
    [sendWsMessage]
  )

  /** Cambio de resolución/calidad: envía remote_view_config */
  const handleResolutionChange = useCallback(
    (sessionId: string, resolution: string) => {
      sendWsMessage({
        type: 'remote_view_config',
        session_id: sessionId,
        resolution,
      })
    },
    [sendWsMessage]
  )

  /** Solicitar frame (Screenshot mode: rv_request_frame) */
  const handleRequestFrame = useCallback(
    (sessionId: string) => {
      sendWsMessage({
        type: 'rv_request_frame',
        session_id: sessionId,
      })
    },
    [sendWsMessage]
  )

  /** Enviar input event (Interactive mode: rv_input) */
  const handleSendInput = useCallback(
    (msg: RvInputMessage) => {
      sendWsMessage(msg as unknown as Record<string, unknown>)
    },
    [sendWsMessage]
  )

  /** Enviar clipboard a la workstation (rv_clipboard) */
  const handleSendClipboard = useCallback(
    (sessionId: string, text: string) => {
      sendWsMessage({
        type: 'rv_clipboard',
        session_id: sessionId,
        direction: 'to_ws',
        text,
      })
    },
    [sendWsMessage]
  )

  /** Reintentar sesión (después de rechazo de consent) */
  const handleRetry = useCallback(
    (sessionId: string) => {
      dispatch({ type: 'UPDATE_STATUS', sessionId, status: 'pending_consent' })
      sendWsMessage({
        type: 'remote_view_resume',
        session_id: sessionId,
      })
    },
    [sendWsMessage]
  )

  /** Keep-alive: resetear timer de inactividad */
  const handleKeepAlive = useCallback(
    (sessionId: string) => {
      sendWsMessage({
        type: 'remote_view_resume',
        session_id: sessionId,
      })
    },
    [sendWsMessage]
  )

  // Tab activo actual
  const activeTab = state.tabs.find((t) => t.sessionId === state.activeTabId) || null

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)]">
      {/* Barra de tabs horizontales */}
      {state.tabs.length > 0 && (
        <div className="flex items-center gap-1 border-b border-gray-200 bg-white px-2 pt-2 overflow-x-auto flex-shrink-0">
          {state.tabs.map((tab) => {
            const isActive = tab.sessionId === state.activeTabId
            const label = tab.ip && tab.hostname
              ? `${tab.ip} — ${tab.hostname}`
              : tab.ip || tab.hostname || tab.sessionId.slice(0, 8)

            return (
              <div
                key={tab.sessionId}
                className={`
                  group flex items-center gap-2 px-3 py-2 rounded-t-md text-sm font-medium
                  cursor-pointer select-none transition-colors min-w-0
                  ${isActive
                    ? 'bg-blue-50 text-blue-700 border border-b-0 border-gray-200'
                    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                  }
                `}
                onClick={() => handleSelectTab(tab.sessionId)}
                role="tab"
                aria-selected={isActive}
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    handleSelectTab(tab.sessionId)
                  }
                }}
              >
                {/* Indicador de estado */}
                <span
                  className={`w-2 h-2 rounded-full flex-shrink-0 ${
                    tab.status === 'active' ? 'bg-green-500' :
                    tab.status === 'pending_consent' ? 'bg-yellow-500 animate-pulse' :
                    tab.status === 'paused' ? 'bg-gray-400' :
                    'bg-red-500'
                  }`}
                  aria-label={t(`status_${tab.status}`)}
                />

                {/* Label: IP — Hostname */}
                <span className="truncate max-w-[200px]">{label}</span>

                {/* Botón cerrar */}
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-5 w-5 p-0 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
                  onClick={(e) => {
                    e.stopPropagation()
                    handleCloseTab(tab.sessionId)
                  }}
                  title={t('closeTab')}
                  aria-label={t('closeTab')}
                >
                  <X className="h-3 w-3" />
                </Button>
              </div>
            )
          })}
        </div>
      )}

      {/* Contenido del tab activo */}
      <div className="flex-1 bg-gray-900 relative overflow-hidden" data-frame-version={frameVersion}>
        {activeTab ? (
          <SessionTab
            tab={activeTab}
            isActive={true}
            modesAllowed={['screenshot', 'stream', 'interactive']}
            onClose={() => handleCloseTab(activeTab.sessionId)}
            onModeChange={(mode) => handleModeChange(activeTab.sessionId, mode)}
            onMonitorChange={(idx) => handleMonitorChange(activeTab.sessionId, idx)}
            onResolutionChange={(res) => handleResolutionChange(activeTab.sessionId, res)}
            latestFrame={null}
            frameData={frameDataRef.current[activeTab.sessionId]?.data ?? null}
            frameWidth={frameDataRef.current[activeTab.sessionId]?.width ?? 0}
            frameHeight={frameDataRef.current[activeTab.sessionId]?.height ?? 0}
            latestDelta={deltaDataRef.current[activeTab.sessionId] ?? null}
            onRequestFrame={() => handleRequestFrame(activeTab.sessionId)}
            onSendInput={handleSendInput}
            onSendClipboard={(text) => handleSendClipboard(activeTab.sessionId, text)}
            incomingClipboardText={null}
            clipboardEnabled={false}
            isConnected={isConnected}
            timeoutSecondsRemaining={null}
            isExpired={false}
            onKeepAlive={() => handleKeepAlive(activeTab.sessionId)}
            onRetry={() => handleRetry(activeTab.sessionId)}
          />
        ) : (
          <EmptyState t={t} />
        )}
      </div>
    </div>
  )
}

// ============================================================================
// COMPONENTE: Estado vacío (sin tabs)
// ============================================================================

function EmptyState({ t }: { t: ReturnType<typeof useTranslations> }) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-gray-400">
      <Monitor className="h-16 w-16 mb-4" />
      <p className="text-lg">{t('noActiveSessions')}</p>
      <p className="text-sm mt-2">{t('noActiveSessionsHint')}</p>
    </div>
  )
}
