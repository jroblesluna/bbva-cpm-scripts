'use client'

/**
 * Componente de autocompletado de dirección con Google Places API.
 * Incluye un mini-mapa preview (200px) con marker en la ubicación seleccionada.
 * Debe usarse dentro de GoogleMapsProvider (SDK ya cargado).
 */

import { useCallback, useRef, useState } from 'react'
import { Autocomplete, GoogleMap, Marker } from '@react-google-maps/api'
import { useTranslations } from 'next-intl'

// ============================================================================
// Interfaces
// ============================================================================

export interface AddressSelection {
  address: string      // formatted_address de Google Places
  latitude: number
  longitude: number
  place_id: string
}

export interface AddressAutocompleteProps {
  onSelect: (selection: AddressSelection) => void
  defaultValue?: string          // Texto de dirección pre-llenado
  defaultLatitude?: number       // Latitud para preview map inicial
  defaultLongitude?: number      // Longitud para preview map inicial
  disabled?: boolean
}

// ============================================================================
// Constantes
// ============================================================================

const MAP_CONTAINER_STYLE = {
  width: '100%',
  height: '200px',
  borderRadius: '0.5rem',
}

const MAP_OPTIONS: google.maps.MapOptions = {
  disableDefaultUI: true,
  zoomControl: false,
  scrollwheel: false,
  draggable: false,
  disableDoubleClickZoom: true,
  gestureHandling: 'none',
}

// ============================================================================
// Componente
// ============================================================================

export function AddressAutocomplete({
  onSelect,
  defaultValue = '',
  defaultLatitude,
  defaultLongitude,
  disabled = false,
}: AddressAutocompleteProps) {
  const t = useTranslations('map')
  const autocompleteRef = useRef<google.maps.places.Autocomplete | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  // Estado para las coordenadas del marker/mapa
  const [coordinates, setCoordinates] = useState<{ lat: number; lng: number } | null>(
    defaultLatitude != null && defaultLongitude != null
      ? { lat: defaultLatitude, lng: defaultLongitude }
      : null
  )

  // Callback cuando se carga el Autocomplete
  const onAutocompleteLoad = useCallback((autocomplete: google.maps.places.Autocomplete) => {
    autocompleteRef.current = autocomplete
  }, [])

  // Callback cuando el usuario selecciona una sugerencia
  const onPlaceChanged = useCallback(() => {
    const autocomplete = autocompleteRef.current
    if (!autocomplete) return

    const place = autocomplete.getPlace()

    if (!place.geometry?.location || !place.place_id) return

    const lat = place.geometry.location.lat()
    const lng = place.geometry.location.lng()
    const address = place.formatted_address ?? ''
    const place_id = place.place_id

    setCoordinates({ lat, lng })

    onSelect({
      address,
      latitude: lat,
      longitude: lng,
      place_id,
    })
  }, [onSelect])

  // Determinar si hay coordenadas para mostrar el mapa
  const showMap = !disabled && coordinates !== null

  return (
    <div className="flex flex-col gap-2">
      {/* Label */}
      <label
        htmlFor="address-autocomplete-input"
        className="text-sm font-medium text-foreground"
      >
        {t('addressLabel')}
      </label>

      {/* Input con Autocomplete de Google Places */}
      <Autocomplete
        onLoad={onAutocompleteLoad}
        onPlaceChanged={onPlaceChanged}
        options={{ types: ['address'] }}
      >
        <input
          id="address-autocomplete-input"
          ref={inputRef}
          type="text"
          defaultValue={defaultValue}
          disabled={disabled}
          placeholder={t('addressPlaceholder')}
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        />
      </Autocomplete>

      {/* Mini-mapa preview */}
      {showMap && (
        <GoogleMap
          mapContainerStyle={MAP_CONTAINER_STYLE}
          center={coordinates}
          zoom={15}
          options={MAP_OPTIONS}
        >
          <Marker position={coordinates} />
        </GoogleMap>
      )}
    </div>
  )
}
