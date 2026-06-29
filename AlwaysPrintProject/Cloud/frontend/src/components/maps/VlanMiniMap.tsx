'use client'

/**
 * Mini-mapa de VLANs geolocalizadas.
 * Se muestra en la página de VLANs como un mapa colapsable (300px height).
 * Asume que el SDK de Google Maps ya está cargado vía GoogleMapsProvider.
 */

import { useCallback, useEffect, useRef } from 'react'
import { GoogleMap, Marker } from '@react-google-maps/api'
import { useTranslations } from 'next-intl'

// ============================================================================
// Interfaces
// ============================================================================

export interface VlanMarkerData {
  id: string
  name: string
  latitude: number
  longitude: number
}

export interface VlanMiniMapProps {
  vlans: VlanMarkerData[]
  onMarkerClick?: (vlanId: string) => void
  collapsed?: boolean
  onToggleCollapse?: () => void
}

// ============================================================================
// Constantes
// ============================================================================

const MAP_CONTAINER_STYLE: React.CSSProperties = {
  width: '100%',
  height: '300px',
}

const DEFAULT_CENTER = { lat: 0, lng: 0 }
const SINGLE_MARKER_ZOOM = 15

// ============================================================================
// Componente principal
// ============================================================================

export function VlanMiniMap({
  vlans,
  onMarkerClick,
  collapsed = false,
  onToggleCollapse,
}: VlanMiniMapProps) {
  const t = useTranslations('map')
  const mapRef = useRef<google.maps.Map | null>(null)

  // Guardar referencia al mapa cuando se carga y ajustar bounds inmediatamente
  const onMapLoad = useCallback((map: google.maps.Map) => {
    mapRef.current = map

    // fitBounds inmediato (las VLANs ya están disponibles cuando el mapa se monta)
    if (vlans.length === 1) {
      map.setCenter({ lat: vlans[0].latitude, lng: vlans[0].longitude })
      map.setZoom(SINGLE_MARKER_ZOOM)
    } else if (vlans.length > 1) {
      const bounds = new google.maps.LatLngBounds()
      vlans.forEach((vlan) => {
        bounds.extend({ lat: vlan.latitude, lng: vlan.longitude })
      })
      map.fitBounds(bounds, { top: 30, right: 30, bottom: 30, left: 30 })
    }
  }, [vlans])

  // Auto-fit bounds cuando cambian las VLANs
  useEffect(() => {
    if (!mapRef.current || vlans.length === 0) return

    if (vlans.length === 1) {
      // Un solo marker: centrar con zoom fijo
      mapRef.current.setCenter({
        lat: vlans[0].latitude,
        lng: vlans[0].longitude,
      })
      mapRef.current.setZoom(SINGLE_MARKER_ZOOM)
    } else {
      // Múltiples markers: fitBounds para encajar todos
      const bounds = new google.maps.LatLngBounds()
      vlans.forEach((vlan) => {
        bounds.extend({ lat: vlan.latitude, lng: vlan.longitude })
      })
      mapRef.current.fitBounds(bounds, { top: 30, right: 30, bottom: 30, left: 30 })
    }
  }, [vlans])

  // Determinar si hay VLANs con coordenadas
  const hasGeoVlans = vlans.length > 0

  return (
    <div className="rounded-lg border bg-card">
      {/* Toggle header */}
      <button
        type="button"
        onClick={onToggleCollapse}
        className="flex w-full items-center justify-between px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors rounded-t-lg"
      >
        <span>{t('miniMapToggle')}</span>
        <svg
          className={`h-4 w-4 transition-transform ${collapsed ? '' : 'rotate-180'}`}
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth="2"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
        </svg>
      </button>

      {/* Contenido del mapa (visible solo si no está colapsado) */}
      {!collapsed && (
        <div className="border-t">
          {hasGeoVlans ? (
            <GoogleMap
              mapContainerStyle={MAP_CONTAINER_STYLE}
              center={
                vlans.length === 1
                  ? { lat: vlans[0].latitude, lng: vlans[0].longitude }
                  : DEFAULT_CENTER
              }
              zoom={vlans.length === 1 ? SINGLE_MARKER_ZOOM : 2}
              onLoad={onMapLoad}
              options={{
                disableDefaultUI: true,
                zoomControl: true,
                mapTypeControl: false,
                streetViewControl: false,
                fullscreenControl: false,
              }}
            >
              {vlans.map((vlan) => (
                <Marker
                  key={vlan.id}
                  position={{ lat: vlan.latitude, lng: vlan.longitude }}
                  title={vlan.name}
                  onClick={() => onMarkerClick?.(vlan.id)}
                />
              ))}
            </GoogleMap>
          ) : (
            <NoLocationsPlaceholder
              title={t('noLocations')}
              description={t('noLocationsDesc')}
            />
          )}
        </div>
      )}
    </div>
  )
}

// ============================================================================
// Placeholder sin ubicaciones
// ============================================================================

interface NoLocationsPlaceholderProps {
  title: string
  description: string
}

function NoLocationsPlaceholder({ title, description }: NoLocationsPlaceholderProps) {
  return (
    <div className="flex items-center justify-center w-full h-[300px] bg-muted/30">
      <div className="flex flex-col items-center gap-2 text-center px-4 max-w-sm">
        <svg
          className="w-8 h-8 text-muted-foreground"
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
