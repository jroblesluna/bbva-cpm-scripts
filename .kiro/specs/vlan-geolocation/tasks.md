# Implementation Plan: vlan-geolocation

## Overview

Implementar georreferenciación de VLANs con Google Maps: API Key por organización, campos de geolocalización, autocompletado de direcciones, mapa interactivo en dashboard, y mini-mapa en la página de VLANs.

## Tasks

- [x] 1. Backend: Migración y modelos
  - [x] 1.1 Crear migración Alembic 020_add_vlan_geolocation
    - Añadir campos a `vlans`: address (VARCHAR 500), latitude (Float), longitude (Float), place_id (VARCHAR 100), location_image_url (VARCHAR 500)
    - Añadir campo a `organizations`: google_maps_api_key (VARCHAR 200)
    - Incluir downgrade que elimina todas las columnas
    - _Requirements: 2.1, 2.2, 2.3, 1.1_

  - [x] 1.2 Actualizar modelo VLAN con campos de geolocalización
    - Añadir columns: address, latitude, longitude, place_id, location_image_url
    - Importar Float de sqlalchemy
    - _Requirements: 2.1_

  - [x] 1.3 Actualizar modelo Organization con google_maps_api_key
    - Añadir column google_maps_api_key después de openai_api_key
    - _Requirements: 1.1_

  - [x] 1.4 Actualizar schemas Pydantic (VLANUpdate, VLANResponse, OrganizationUpdate, OrganizationResponse)
    - VLANUpdate: añadir campos opcionales (address, latitude, longitude, place_id, location_image_url)
    - VLANResponse: incluir nuevos campos en la respuesta
    - OrganizationUpdate: añadir google_maps_api_key opcional
    - OrganizationResponse: enmascarar google_maps_api_key (mostrar solo últimos 4 chars)
    - Crear VLANGeoResponse schema para el endpoint /geo
    - Validación: latitude y longitude deben venir juntos o ninguno
    - _Requirements: 2.3, 1.3, 1.4, 6.3_

- [x] 2. Backend: Endpoints
  - [x] 2.1 Crear endpoint GET /api/v1/vlans/geo
    - Retornar VLANs con lat/lng no-null + stats de WS (total, online, offline, contingency)
    - Query param organization_id (opcional para admin, obligatorio para operador via tenant isolation)
    - Incluir organization_name en la respuesta
    - Respetar tenant isolation
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 2.2 Crear endpoint GET /api/v1/config/maps-key
    - Retornar API Key de Google Maps de la organización del usuario autenticado
    - 404 si no hay key configurada
    - Solo usuarios autenticados
    - _Requirements: 7.3, 7.4_

  - [x] 2.3 Extender PATCH /api/v1/vlans/{id} para aceptar campos geo
    - Aceptar address, latitude, longitude, place_id, location_image_url
    - Validar que lat y lng vengan juntos
    - _Requirements: 2.3, 3.3_

  - [x] 2.4 Extender PATCH /api/v1/organizations/{id} para google_maps_api_key
    - Aceptar google_maps_api_key
    - Validar formato: empieza con "AIza", >= 39 chars (si no vacío)
    - GET retorna key mascarada
    - _Requirements: 1.1, 1.2, 1.3, 7.1, 7.2_

- [x] 3. Frontend: Dependencias e infraestructura
  - [x] 3.1 Instalar dependencias de Google Maps
    - npm install @react-google-maps/api @googlemaps/markerclusterer
    - Verificar que el build de Next.js funciona con las nuevas deps
    - _Requirements: 3.1, 4.2_

  - [x] 3.2 Crear GoogleMapsProvider component
    - Wrapper que carga el SDK de Google Maps con la API Key de la org
    - Fetch API Key via GET /config/maps-key
    - Mostrar skeleton mientras carga
    - Mostrar mensaje si no hay key configurada
    - Libraries: ['places']
    - _Requirements: 3.6, 7.3_

  - [x] 3.3 Añadir traducciones i18n (namespace map) en es.json y en.json
    - Keys: title, subtitle, filterAll, filterOrg, noApiKey, noApiKeyDesc, noLocations, noLocationsDesc, wsTotal, wsOnline, wsOffline, wsContingency, addressLabel, addressPlaceholder, imageLabel, imagePlaceholder, miniMapToggle, configureKey
    - _Requirements: 4.5, 5.4_

- [x] 4. Frontend: Componentes de mapa
  - [x] 4.1 Crear AddressAutocomplete component
    - Input con Google Places Autocomplete (type filter: 'address')
    - Al seleccionar: extraer formatted_address, lat, lng, place_id
    - Mini-mapa preview (200px height) con marker en la ubicación seleccionada
    - Props: onSelect callback, defaultValue, disabled
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 4.2 Crear MarkerInfoWindow component
    - Popup que muestra: nombre VLAN, dirección, imagen (si existe), stats WS
    - Stats con badges de color: total, online (verde), offline (gris), contingency (naranja)
    - _Requirements: 4.5_

  - [x] 4.3 Crear VlanMiniMap component
    - Mapa pequeño (300px height, colapsable)
    - Renderiza markers de VLANs con coordenadas
    - Auto-fit bounds para encajar todos los markers
    - Click en marker → emite evento onMarkerClick(vlanId)
    - Placeholder si no hay VLANs geolocalizadas
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [x] 5. Frontend: Páginas
  - [x] 5.1 Crear página /dashboard/map
    - Añadir entrada "Mapa" en sidebar bajo MONITORING/OPERATIONS
    - Google Map a pantalla completa con markers por VLAN
    - Filtro dropdown: "Todas las organizaciones" (admin) o fixed (operador)
    - MarkerClusterer cuando markers se solapan
    - Click marker → InfoWindow con stats
    - Markers con color según % online: verde (>80%), amarillo (50-80%), rojo (<50%)
    - Acceso: admin (ve todas) y operador (ve solo su org)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 5.2 Extender modal de editar VLAN con campos de geolocalización
    - Añadir sección "Ubicación" con AddressAutocomplete
    - Campo "URL de imagen" (input text, opcional)
    - Si org no tiene API key: mostrar mensaje y link a configuración
    - Guardar address, lat, lng, place_id, location_image_url via PATCH
    - _Requirements: 3.1, 3.4, 3.5, 3.6_

  - [x] 5.3 Integrar VlanMiniMap en la página de VLANs
    - Añadir mini-mapa arriba de la lista de VLANs (colapsable con toggle)
    - Solo visible si >=1 VLAN tiene coordenadas
    - Click marker → scroll a la VLAN en la lista y highlight
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 5.4 Extender Organization Edit con campo Google Maps API Key
    - Añadir campo en tab "General" después de OpenAI API Key
    - Input type=password
    - Mostrar solo últimos 4 chars después de guardar (mascarado)
    - Helper text con link a Google Cloud Console
    - _Requirements: 1.2, 1.4_

- [x] 6. Checkpoint — Verificación completa
  - Verificar migración aplica correctamente
  - Verificar endpoint /vlans/geo retorna datos correctos
  - Verificar tenant isolation en todos los endpoints
  - Verificar mapa renderiza con markers
  - Verificar autocompletado funciona con Places API
  - Verificar API key se enmascara en respuestas

## Notes

- Google Maps API Key debe configurarse por organización (patrón existente de openai_api_key)
- El frontend carga la API key via /config/maps-key — NO se hardcodea en env vars
- La dirección SOLO se guarda si viene de Google Places (evita coordenadas incorrectas de texto libre)
- Sin API Key configurada: mapa muestra placeholder, autocomplete disabled
- MarkerClusterer se activa automáticamente cuando hay >100 VLANs cercanas
- Las traducciones deben estar en namespace `map` separado de `vlans`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3", "2.4"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3"] },
    { "id": 3, "tasks": ["4.1", "4.2", "4.3"] },
    { "id": 4, "tasks": ["5.1", "5.2", "5.3", "5.4"] },
    { "id": 5, "tasks": ["6"] }
  ]
}
```
