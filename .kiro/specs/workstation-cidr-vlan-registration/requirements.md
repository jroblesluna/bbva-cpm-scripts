# Requirements Document

## Introduction

Esta feature extiende el sistema de registro de workstations en AlwaysPrint para incluir información de red (CIDR) y versión del Tray. El backend auto-asigna VLANs basándose en el segmento de red reportado por cada workstation, eliminando la necesidad de asignación manual. Adicionalmente, se mejora la UI con filtros por VLAN, columna de versión del Tray, y badges de salud CIDR en la página de VLANs.

## Glossary

- **Workstation**: Equipo Windows que ejecuta AlwaysPrintTray y se registra en el Cloud Manager
- **CIDR**: Classless Inter-Domain Routing — notación de red en formato `x.x.x.x/prefix` (ej: `192.168.1.0/24`)
- **VLAN**: Agrupación lógica de workstations por segmento de red dentro de una organización
- **Tray**: Aplicación AlwaysPrintTray que corre en la workstation Windows
- **Backend**: Servidor FastAPI que gestiona el registro y la lógica de negocio
- **NetworkHelper**: Clase C# que calcula información de red de la workstation
- **Organization**: Entidad multi-tenant que agrupa workstations y VLANs
- **CIDR_Health_Badge**: Indicador visual del número de CIDRs asignados a una VLAN (verde=1, amarillo=2, rojo=3+)

## Requirements

### Requirement 1: Cálculo de CIDR en la Workstation

**User Story:** Como administrador de red, quiero que cada workstation calcule y reporte su CIDR automáticamente, para que el sistema pueda agruparlas por segmento de red sin intervención manual.

#### Acceptance Criteria

1. WHEN the Tray application starts, THE NetworkHelper SHALL calculate the CIDR by applying the subnet mask to the IP address of the network interface with a default gateway
2. WHEN the NetworkHelper calculates the CIDR, THE NetworkHelper SHALL return the result in the format `network_address/prefix_length` (e.g., `192.168.1.0/24`)
3. IF no network interface with a default gateway is found, THEN THE NetworkHelper SHALL return null
4. WHEN multiple network interfaces with gateways exist, THE NetworkHelper SHALL select the interface with highest priority (Ethernet over WiFi over others)

### Requirement 2: Registro de Workstation con CIDR

**User Story:** Como workstation, quiero enviar mi CIDR y versión del Tray durante el registro, para que el backend pueda asignarme a la VLAN correcta y mantener un inventario actualizado.

#### Acceptance Criteria

1. WHEN a workstation registers via HTTP or WebSocket, THE Tray SHALL send the fields `cidr` (mandatory) and `tray_version` (optional) along with the existing registration data
2. WHEN the Backend receives a registration request without a `cidr` field, THE Backend SHALL reject the request with HTTP 422 Unprocessable Entity
3. WHEN the Backend receives a registration request with an invalid CIDR format, THE Backend SHALL reject the request with HTTP 422 and a descriptive error message
4. WHEN the Backend receives a valid registration request, THE Backend SHALL normalize the CIDR using `ipaddress.ip_network(cidr, strict=False)` before storing it
5. WHEN a workstation re-registers with a different CIDR, THE Backend SHALL update the workstation's CIDR and re-evaluate its VLAN assignment

### Requirement 3: Auto-asignación de VLAN por CIDR

**User Story:** Como administrador, quiero que las workstations se asignen automáticamente a VLANs basándose en su CIDR, para eliminar la configuración manual de agrupaciones de red.

#### Acceptance Criteria

1. WHEN a workstation registers with a CIDR that matches an existing VLAN's `cidr_ranges`, THE Backend SHALL assign the workstation to that existing VLAN
2. WHEN a workstation registers with a CIDR that does not match any existing VLAN in the organization, THE Backend SHALL create a new VLAN named `VLAN_{CIDR}` with `cidr_ranges=[CIDR]` and assign the workstation to it
3. THE Backend SHALL ensure that every successfully registered workstation has a non-null `vlan_id`
4. WHEN two workstations with the same CIDR register simultaneously, THE Backend SHALL assign both to the same VLAN without creating duplicates

### Requirement 4: Unicidad de CIDR por Organización

**User Story:** Como administrador, quiero que cada CIDR pertenezca a exactamente una VLAN dentro de mi organización, para evitar ambigüedades en la asignación de workstations.

#### Acceptance Criteria

1. THE Backend SHALL ensure that a given CIDR appears in the `cidr_ranges` of at most one VLAN within the same organization
2. WHEN an administrator attempts to add a CIDR to a VLAN that already exists in another VLAN of the same organization, THE Backend SHALL reject the operation with HTTP 409 Conflict
3. WHEN auto-creating a VLAN, THE Backend SHALL verify that the CIDR does not already exist in another VLAN of the organization before creating

### Requirement 5: Aislamiento Multi-Tenant

**User Story:** Como operador de la plataforma, quiero que las VLANs auto-creadas respeten el aislamiento por organización, para que los datos de una organización no sean visibles ni afecten a otra.

#### Acceptance Criteria

1. THE Backend SHALL associate auto-created VLANs exclusively with the `organization_id` of the registering workstation
2. WHEN querying VLANs, THE Backend SHALL filter results by `organization_id` to prevent cross-tenant data leakage
3. THE Backend SHALL allow the same CIDR to exist in different organizations without conflict

### Requirement 6: Filtro por VLAN en Listado de Workstations

**User Story:** Como administrador, quiero filtrar workstations por VLAN en el listado, para poder ver rápidamente qué equipos pertenecen a cada segmento de red.

#### Acceptance Criteria

1. WHEN an organization is selected in the workstations list page, THE Frontend SHALL display a VLAN filter dropdown populated with the VLANs of that organization
2. WHEN a VLAN filter is selected, THE Frontend SHALL display only workstations assigned to that VLAN
3. WHEN no VLAN filter is selected, THE Frontend SHALL display all workstations of the selected organization

### Requirement 7: Columna de Versión del Tray

**User Story:** Como administrador, quiero ver la versión del Tray de cada workstation en el listado, para identificar equipos desactualizados que necesiten actualización.

#### Acceptance Criteria

1. THE Frontend SHALL display a `tray_version` column in the workstations list table
2. WHEN a workstation has no `tray_version` value, THE Frontend SHALL display a placeholder indicator (e.g., "—") in the column

### Requirement 8: Badges de Salud CIDR en Página de VLANs

**User Story:** Como administrador de red, quiero ver indicadores visuales de cuántos CIDRs tiene cada VLAN, para identificar rápidamente VLANs con configuración anómala.

#### Acceptance Criteria

1. THE Frontend SHALL display a CIDR health badge next to each VLAN in the VLANs page
2. WHEN a VLAN has exactly 1 CIDR in its `cidr_ranges`, THE Frontend SHALL display a green badge
3. WHEN a VLAN has exactly 2 CIDRs in its `cidr_ranges`, THE Frontend SHALL display a yellow badge
4. WHEN a VLAN has 3 or more CIDRs in its `cidr_ranges`, THE Frontend SHALL display a red badge

### Requirement 9: Validación de Formato CIDR

**User Story:** Como desarrollador del backend, quiero validar rigurosamente el formato CIDR recibido, para prevenir datos malformados en la base de datos.

#### Acceptance Criteria

1. THE Backend SHALL validate that the CIDR field conforms to IPv4 network notation using Python's `ipaddress.ip_network()` function
2. WHEN the CIDR prefix length is outside the range 8-30, THE Backend SHALL reject the registration with a descriptive error
3. THE Backend SHALL normalize CIDRs to their canonical network form (e.g., `192.168.1.50/24` becomes `192.168.1.0/24`)

### Requirement 10: Manejo de Errores en Detección de CIDR

**User Story:** Como usuario de la workstation, quiero recibir feedback claro cuando el sistema no puede detectar mi CIDR, para saber que debo verificar mi conexión de red.

#### Acceptance Criteria

1. IF the NetworkHelper cannot detect a CIDR (returns null), THEN THE Tray SHALL display an error message indicating network configuration issues
2. IF the NetworkHelper cannot detect a CIDR, THEN THE Tray SHALL NOT attempt to register with the Backend
3. WHEN the Tray cannot register due to missing CIDR, THE Tray SHALL retry CIDR detection periodically until a valid CIDR is obtained
