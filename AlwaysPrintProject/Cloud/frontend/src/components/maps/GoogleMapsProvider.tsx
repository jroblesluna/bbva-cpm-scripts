'use client'

/**
 * Provider que carga el SDK de Google Maps con la API Key de la organización.
 * Obtiene la key vía GET /config/maps-key y envuelve a los hijos con el contexto de Google Maps.
 */

import { useState, useEffect, ReactNode } from 'react'
import { useJsApiLoader } from '@react-google-maps/api'
import { useTranslations } from 'next-intl'
import { apiClient } from '@/lib/api'

// Librerías requeridas para autocompletado de direcciones
const GOOGLE_MAPS_LIBRARIES: ('places')[] = ['places']

interface GoogleMapsProviderProps {
  children: ReactNode
  fallback?: ReactNode
}

interface MapsKeyState {
  apiKey: string | null
  isLoading: boolean
  error: 'no_key' | 'fetch_error' | null
}

/**
 * Componente que carga el SDK de Google Maps usando la API Key
 * de la organización del usuario autenticado.
 */
export function GoogleMapsProvider({ children, fallback }: GoogleMapsProviderProps) {
  const t = useTranslations('map')
  const [keyState, setKeyState] = useState<MapsKeyState>({
    apiKey: null,
    isLoading: true,
    error: null,
  })

  // Obtener la API Key desde el backend
  useEffect(() => {
    let cancelled = false

    async function fetchMapsKey() {
      try {
        const response = await apiClient.get<{ api_key: string }>('/config/maps-key')
        if (!cancelled) {
          setKeyState({
            apiKey: response.data.api_key,
            isLoading: false,
            error: null,
          })
        }
      } catch (err: unknown) {
        if (cancelled) return
        const apiErr = err as { status?: number }
        // 404 significa que la organización no tiene key configurada
        if (apiErr.status === 404) {
          setKeyState({ apiKey: null, isLoading: false, error: 'no_key' })
        } else {
          setKeyState({ apiKey: null, isLoading: false, error: 'fetch_error' })
        }
      }
    }

    fetchMapsKey()
    return () => { cancelled = true }
  }, [])

  // Estado: cargando la API key
  if (keyState.isLoading) {
    return fallback ?? <MapSkeleton message={t('loading')} />
  }

  // Estado: no hay key configurada
  if (keyState.error === 'no_key') {
    return <NoApiKeyMessage title={t('noApiKey')} description={t('noApiKeyDesc')} />
  }

  // Estado: error al obtener la key
  if (keyState.error === 'fetch_error' || !keyState.apiKey) {
    return <NoApiKeyMessage title={t('loadError')} description={t('noApiKeyDesc')} />
  }

  // API Key disponible → cargar el SDK de Google Maps
  return (
    <GoogleMapsLoader apiKey={keyState.apiKey} fallback={fallback}>
      {children}
    </GoogleMapsLoader>
  )
}

// ============================================================================
// Componente interno que carga el SDK con useJsApiLoader
// ============================================================================

interface GoogleMapsLoaderProps {
  apiKey: string
  children: ReactNode
  fallback?: ReactNode
}

function GoogleMapsLoader({ apiKey, children, fallback }: GoogleMapsLoaderProps) {
  const t = useTranslations('map')

  const { isLoaded, loadError } = useJsApiLoader({
    googleMapsApiKey: apiKey,
    libraries: GOOGLE_MAPS_LIBRARIES,
  })

  if (loadError) {
    return <NoApiKeyMessage title={t('loadError')} description={loadError.message} />
  }

  if (!isLoaded) {
    return fallback ?? <MapSkeleton message={t('loading')} />
  }

  return <>{children}</>
}

// ============================================================================
// Componentes de UI internos
// ============================================================================

interface MapSkeletonProps {
  message: string
}

/**
 * Skeleton que se muestra mientras se carga el SDK de Google Maps.
 */
function MapSkeleton({ message }: MapSkeletonProps) {
  return (
    <div className="flex items-center justify-center w-full h-64 bg-muted/50 rounded-lg border border-dashed animate-pulse">
      <div className="flex flex-col items-center gap-2 text-muted-foreground">
        <svg
          className="w-8 h-8 animate-spin"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
        >
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
        <p className="text-sm">{message}</p>
      </div>
    </div>
  )
}

interface NoApiKeyMessageProps {
  title: string
  description: string
}

/**
 * Mensaje informativo cuando no hay API Key de Google Maps configurada.
 */
function NoApiKeyMessage({ title, description }: NoApiKeyMessageProps) {
  return (
    <div className="flex items-center justify-center w-full h-64 bg-muted/30 rounded-lg border border-dashed">
      <div className="flex flex-col items-center gap-2 text-center px-4 max-w-md">
        <svg
          className="w-10 h-10 text-muted-foreground"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth="1.5"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M15 10.5a3 3 0 11-6 0 3 3 0 016 0z"
          />
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1115 0z"
          />
        </svg>
        <p className="text-sm font-medium text-muted-foreground">{title}</p>
        <p className="text-xs text-muted-foreground/80">{description}</p>
      </div>
    </div>
  )
}
