'use client'

/**
 * Página /dashboard/map — Mapa interactivo de VLANs geolocalizadas.
 * Muestra markers coloreados por salud (% online) con clustering y filtro por organización.
 * Acceso: admin (ve todas las orgs) y operador (solo su org).
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { GoogleMap } from '@react-google-maps/api'
import { MarkerClusterer } from '@googlemaps/markerclusterer'
import { useTranslations } from 'next-intl'
import { useAuth } from '@/hooks/useAuth'
import { GoogleMapsProvider } from '@/components/maps/GoogleMapsProvider'
import { MarkerInfoWindow } from '@/components/maps/MarkerInfoWindow'
import { apiClient } from '@/lib/api'

// ============================================================================
// Tipos
// ============================================================================

interface VlanGeoData {
  id: string
  name: string
  organization_id: string
  organization_name: string
  address: string
  latitude: number
  longitude: number
  location_image_url?: string | null
  ws_total: number
  ws_online: number
  ws_offline: number
  ws_contingency: number
}

interface OrganizationOption {
  id: string
  name: string
}

// ============================================================================
// Constantes
// ============================================================================

const MAP_CONTAINER_STYLE: React.CSSProperties = {
  width: '100%',
  height: 'calc(100vh - 220px)',
  minHeight: '400px',
}

const DEFAULT_CENTER = { lat: -12.046374, lng: -77.042793 } // Lima, Perú
const DEFAULT_ZOOM = 5

// Colores de markers según porcentaje de WS online
const MARKER_COLOR_GREEN = '#22c55e'  // >80% online
const MARKER_COLOR_YELLOW = '#eab308' // 50-80% online
const MARKER_COLOR_RED = '#ef4444'    // <50% online

// ============================================================================
// Helpers
// ============================================================================

/**
 * Determina el color del marker según el porcentaje de workstations online.
 */
function getMarkerColor(wsOnline: number, wsTotal: number): string {
  if (wsTotal === 0) return MARKER_COLOR_RED
  const ratio = wsOnline / wsTotal
  if (ratio > 0.8) return MARKER_COLOR_GREEN
  if (ratio >= 0.5) return MARKER_COLOR_YELLOW
  return MARKER_COLOR_RED
}

/**
 * Genera un ícono SVG circular con el color indicado para usar como marker.
 */
function createMarkerIcon(color: string): string {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
      <circle cx="16" cy="16" r="12" fill="${color}" stroke="white" stroke-width="3"/>
      <circle cx="16" cy="16" r="5" fill="white" opacity="0.8"/>
    </svg>
  `
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg.trim())}`
}

// ============================================================================
// Componente principal de la página
// ============================================================================

export default function MapPage() {
  return (
    <GoogleMapsProvider>
      <MapContent />
    </GoogleMapsProvider>
  )
}

// ============================================================================
// Contenido del mapa (se renderiza cuando el SDK está cargado)
// ============================================================================

function MapContent() {
  const t = useTranslations('map')
  const { isAdmin } = useAuth()

  // Estado
  const [vlans, setVlans] = useState<VlanGeoData[]>([])
  const [organizations, setOrganizations] = useState<OrganizationOption[]>([])
  const [selectedOrgId, setSelectedOrgId] = useState<string>('')
  const [selectedVlan, setSelectedVlan] = useState<VlanGeoData | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Referencia al mapa y al clusterer
  const mapRef = useRef<google.maps.Map | null>(null)
  const clustererRef = useRef<MarkerClusterer | null>(null)
  const markersRef = useRef<google.maps.Marker[]>([])

  // Cargar lista de organizaciones (solo admin)
  useEffect(() => {
    if (!isAdmin()) return

    async function fetchOrgs() {
      try {
        const response = await apiClient.get<{ items: OrganizationOption[] }>('/organizations/')
        setOrganizations(response.data.items.map((org) => ({ id: org.id, name: org.name })))
      } catch {
        // Error silencioso — el filtro simplemente no estará disponible
      }
    }

    fetchOrgs()
  }, [isAdmin])

  // Cargar datos geográficos de VLANs
  useEffect(() => {
    async function fetchGeoData() {
      setIsLoading(true)
      try {
        const params: Record<string, string> = {}
        if (selectedOrgId) {
          params.organization_id = selectedOrgId
        }
        const response = await apiClient.get<VlanGeoData[]>('/vlans/geo', { params })
        setVlans(response.data)
      } catch {
        setVlans([])
      } finally {
        setIsLoading(false)
      }
    }

    fetchGeoData()
  }, [selectedOrgId])

  // Callback cuando el mapa se carga
  const onMapLoad = useCallback((map: google.maps.Map) => {
    mapRef.current = map

    // Si las VLANs ya están disponibles, ajustar bounds inmediatamente
    if (vlans.length === 1) {
      map.setCenter({ lat: vlans[0].latitude, lng: vlans[0].longitude })
      map.setZoom(15)
    } else if (vlans.length > 1) {
      const bounds = new google.maps.LatLngBounds()
      vlans.forEach((vlan) => {
        bounds.extend({ lat: vlan.latitude, lng: vlan.longitude })
      })
      map.fitBounds(bounds, { top: 50, right: 50, bottom: 50, left: 50 })
    }
  }, [vlans])

  // Gestionar markers y clusterer cuando cambian las VLANs
  useEffect(() => {
    if (!mapRef.current) return

    // Limpiar markers y clusterer anteriores
    markersRef.current.forEach((marker) => marker.setMap(null))
    markersRef.current = []
    if (clustererRef.current) {
      clustererRef.current.clearMarkers()
      clustererRef.current = null
    }

    if (vlans.length === 0) return

    // Crear nuevos markers
    const newMarkers = vlans.map((vlan) => {
      const color = getMarkerColor(vlan.ws_online, vlan.ws_total)
      const marker = new google.maps.Marker({
        position: { lat: vlan.latitude, lng: vlan.longitude },
        title: vlan.name,
        icon: {
          url: createMarkerIcon(color),
          scaledSize: new google.maps.Size(32, 32),
          anchor: new google.maps.Point(16, 16),
        },
      })

      // Click en marker → mostrar InfoWindow
      marker.addListener('click', () => {
        setSelectedVlan(vlan)
      })

      return marker
    })

    markersRef.current = newMarkers

    // Crear clusterer con los markers
    clustererRef.current = new MarkerClusterer({
      map: mapRef.current,
      markers: newMarkers,
    })

    // Ajustar bounds para encajar todos los markers
    if (vlans.length === 1) {
      mapRef.current.setCenter({ lat: vlans[0].latitude, lng: vlans[0].longitude })
      mapRef.current.setZoom(15)
    } else {
      const bounds = new google.maps.LatLngBounds()
      vlans.forEach((vlan) => {
        bounds.extend({ lat: vlan.latitude, lng: vlan.longitude })
      })
      mapRef.current.fitBounds(bounds, { top: 50, right: 50, bottom: 50, left: 50 })
    }
  }, [vlans])

  // Handler del filtro de organización
  const handleOrgFilterChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedOrgId(event.target.value)
    setSelectedVlan(null)
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{t('title')}</h1>
          <p className="text-sm text-gray-500 mt-1">{t('subtitle')}</p>
        </div>

        {/* Filtro de organización (solo admin) */}
        {isAdmin() && (
          <div className="flex-shrink-0">
            <select
              value={selectedOrgId}
              onChange={handleOrgFilterChange}
              className="block w-full sm:w-64 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="">{t('filterAll')}</option>
              {organizations.map((org) => (
                <option key={org.id} value={org.id}>
                  {org.name}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* Mapa */}
      <div className="rounded-lg border bg-card overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center" style={{ height: MAP_CONTAINER_STYLE.height, minHeight: MAP_CONTAINER_STYLE.minHeight }}>
            <div className="flex flex-col items-center gap-2 text-muted-foreground">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
              <p className="text-sm">{t('loading')}</p>
            </div>
          </div>
        ) : vlans.length === 0 ? (
          <div className="flex items-center justify-center" style={{ height: MAP_CONTAINER_STYLE.height, minHeight: MAP_CONTAINER_STYLE.minHeight }}>
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
              <p className="text-sm font-medium text-muted-foreground">{t('noLocations')}</p>
              <p className="text-xs text-muted-foreground/80">{t('noLocationsDesc')}</p>
            </div>
          </div>
        ) : (
          <GoogleMap
            mapContainerStyle={MAP_CONTAINER_STYLE}
            center={DEFAULT_CENTER}
            zoom={DEFAULT_ZOOM}
            onLoad={onMapLoad}
            options={{
              disableDefaultUI: false,
              zoomControl: true,
              mapTypeControl: true,
              streetViewControl: false,
              fullscreenControl: true,
            }}
          >
            {/* InfoWindow al hacer click en un marker */}
            {selectedVlan && (
              <MarkerInfoWindow
                vlan={selectedVlan}
                onClose={() => setSelectedVlan(null)}
              />
            )}
          </GoogleMap>
        )}
      </div>

      {/* Leyenda de colores */}
      {vlans.length > 0 && (
        <div className="flex flex-wrap items-center gap-4 text-xs text-gray-600">
          <div className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 rounded-full" style={{ backgroundColor: MARKER_COLOR_GREEN }} />
            <span>&gt;80% {t('wsOnline')}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 rounded-full" style={{ backgroundColor: MARKER_COLOR_YELLOW }} />
            <span>50-80% {t('wsOnline')}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-3 rounded-full" style={{ backgroundColor: MARKER_COLOR_RED }} />
            <span>&lt;50% {t('wsOnline')}</span>
          </div>
        </div>
      )}
    </div>
  )
}
