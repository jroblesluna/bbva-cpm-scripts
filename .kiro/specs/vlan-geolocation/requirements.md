# Requirements Document

## Introduction

Georreferenciación de VLANs mediante Google Maps para visualizar la distribución geográfica de agencias/sucursales en un mapa interactivo. Cada VLAN representa una ubicación física (agencia) y se puede asociar a una dirección real verificada por Google Places, almacenando coordenadas (lat/lng) para renderizar marcadores en el dashboard con estadísticas de workstations en tiempo real.

## Glossary

- **VLAN**: Red local que agrupa workstations de una ubicación física (agencia/sucursal)
- **Google Places API**: Servicio de Google para autocompletado y geocodificación de direcciones
- **Google Maps JS API**: SDK JavaScript para renderizar mapas interactivos en el frontend
- **Place ID**: Identificador único de Google para una ubicación verificada
- **Geocoding**: Proceso de convertir una dirección textual en coordenadas lat/lng
- **Cluster**: Agrupación visual de marcadores cercanos en el mapa
- **Tenant Isolation**: Cada organización solo ve sus propios datos

## Requirements

### Requirement 1: Almacenamiento de API Key de Google Maps por organización

**User Story:** Como administrador de una organización, quiero configurar mi propia API Key de Google Maps para que el sistema pueda geocodificar las direcciones de mis VLANs sin depender de una key global.

#### Acceptance Criteria

1. THE Organization model SHALL include a field `google_maps_api_key` (encrypted at rest) that stores the Google Maps API key
2. WHEN an admin edits the organization settings, THE Frontend SHALL provide a field to input/update the Google Maps API key
3. THE Backend SHALL validate that the API key is a non-empty string of 39 characters starting with "AIza" before saving
4. THE Frontend SHALL mask the API key in the UI after being saved (show only last 4 characters)
5. IF the organization has no API key configured, THE Frontend SHALL disable the address autocomplete and show a message indicating configuration is required

### Requirement 2: Campos de geolocalización en el modelo VLAN

**User Story:** Como sistema, quiero almacenar la dirección verificada, coordenadas y metadatos de ubicación de cada VLAN para poder renderizar marcadores en el mapa.

#### Acceptance Criteria

1. THE VLAN model SHALL include fields: `address` (VARCHAR 500, nullable), `latitude` (Float, nullable), `longitude` (Float, nullable), `place_id` (VARCHAR 100, nullable), `location_image_url` (VARCHAR 500, nullable)
2. WHEN a VLAN is created, THE address fields SHALL be optional (nullable)
3. WHEN a VLAN is updated with address data, THE Backend SHALL require latitude, longitude and address to be provided together (all or none)
4. THE Backend SHALL store the place_id from Google Places for future reference/validation

### Requirement 3: Autocompletado de dirección al editar VLAN

**User Story:** Como operador/admin, quiero buscar y seleccionar una dirección real al editar una VLAN para que la ubicación sea precisa y verificada por Google.

#### Acceptance Criteria

1. WHEN editing a VLAN, THE Frontend SHALL show an autocomplete input that queries Google Places API as the user types
2. THE Autocomplete SHALL only suggest addresses (not establishments or regions) using type filter `address`
3. WHEN the user selects a suggestion, THE Frontend SHALL extract and store: formatted_address, latitude, longitude, place_id
4. THE Frontend SHALL show a mini-map preview with a marker at the selected location
5. THE Frontend SHALL allow the user to optionally provide a `location_image_url` (photo of the physical location/agency)
6. IF the organization has no Google Maps API key, THE autocomplete field SHALL be disabled with a tooltip explaining the requirement

### Requirement 4: Mapa interactivo en el Dashboard (Admin)

**User Story:** Como administrador, quiero ver un mapa con todas las VLANs geolocalizadas de todas las organizaciones (o filtradas por una) para tener visibilidad geográfica de la infraestructura.

#### Acceptance Criteria

1. THE Dashboard SHALL include a new page/section "Mapa" accessible from the sidebar navigation
2. THE Map page SHALL render a Google Maps instance with markers for each VLAN that has coordinates
3. THE Map SHALL support filtering by organization (dropdown: "Todas" or specific org)
4. WHEN multiple markers are close together, THE Map SHALL cluster them with a count badge
5. WHEN a user clicks a marker, THE Map SHALL show a popup/info window with: VLAN name, address, total workstations, online count, offline count, contingency count, and location image (if available)
6. THE Map SHALL only be accessible to users with admin role (can see all orgs) or operator role (sees only their org)

### Requirement 5: Mini-mapa en la vista de detalle de VLAN

**User Story:** Como operador, quiero ver un mini-mapa en la página de VLANs que muestre la ubicación de cada VLAN con coordenadas configuradas.

#### Acceptance Criteria

1. THE VLANs page SHALL show a small map (mini-map) above or alongside the VLAN list showing all geolocated VLANs of the current organization
2. WHEN clicking a marker on the mini-map, THE Frontend SHALL scroll to or highlight the corresponding VLAN in the list
3. THE mini-map SHALL update its bounds to fit all visible VLAN markers
4. IF no VLANs have coordinates, THE mini-map SHALL show a placeholder message

### Requirement 6: Endpoint API para datos geográficos

**User Story:** Como frontend, quiero un endpoint eficiente que retorne las VLANs con sus coordenadas y estadísticas de WS para renderizar el mapa sin múltiples requests.

#### Acceptance Criteria

1. THE Backend SHALL expose GET `/api/v1/vlans/geo` that returns VLANs with coordinates + workstation stats (total, online, offline, contingency)
2. THE Endpoint SHALL support query parameter `organization_id` (optional for admins, required for operators)
3. THE Response SHALL include: vlan_id, name, address, latitude, longitude, location_image_url, ws_total, ws_online, ws_offline, ws_contingency
4. THE Endpoint SHALL only return VLANs that have non-null latitude and longitude
5. THE Endpoint SHALL respect tenant isolation (operators only see their org's VLANs)

### Requirement 7: Seguridad de la API Key

**User Story:** Como sistema, quiero proteger las API Keys de Google Maps almacenadas para evitar filtración o uso no autorizado.

#### Acceptance Criteria

1. THE Backend SHALL encrypt the `google_maps_api_key` at rest using the same encryption mechanism used for other secrets (e.g., Fernet or AWS KMS)
2. THE Backend SHALL never return the full API key in any GET response (only last 4 chars for display)
3. THE Frontend SHALL load the Google Maps SDK using the API key via a backend proxy endpoint (`/api/v1/config/maps-key`) that returns the key only to authenticated users of the organization
4. THE Backend SHALL rate-limit the maps-key endpoint to prevent abuse
