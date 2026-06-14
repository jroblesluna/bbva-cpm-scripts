# Requirements Document

## Introduction

Cuando una workstation intenta verificar actualizaciones (`GET /api/v1/updates/check`) desde una IP pública no registrada, el backend actualmente solo registra un warning y retorna HTTP 401. Esta feature agrega el registro automático de esas IPs desconocidas como "pendientes de aprobación" en la tabla `public_ips`, permitiendo que un administrador las visualice en el dashboard y las autorice posteriormente. El flujo existente para IPs ya conocidas y autorizadas permanece sin cambios.

## Glossary

- **Backend**: Aplicación FastAPI que sirve la API REST de AlwaysPrint Cloud Manager
- **Workstation**: Equipo Windows con el cliente AlwaysPrint instalado que solicita actualizaciones al Backend
- **PublicIP**: Modelo de base de datos en la tabla `public_ips` que representa una dirección IP pública con su estado de autorización
- **IP_Desconocida**: Dirección IP pública desde la cual se recibe una solicitud y que no existe en la tabla `public_ips`
- **IP_Pendiente**: Registro en la tabla `public_ips` con `is_authorized=False` y `organization_id=NULL`
- **Admin**: Usuario con rol administrador que puede autorizar IPs pendientes desde el dashboard
- **Registro_Pendiente**: Acción de crear una entrada en `public_ips` con `is_authorized=False` para una IP no conocida
- **Endpoint_Check**: Endpoint `GET /api/v1/updates/check` que las workstations invocan para verificar actualizaciones disponibles

## Requirements

### Requirement 1: Registro automático de IP desconocida como pendiente

**User Story:** Como administrador, quiero que las IPs públicas desconocidas que intentan verificar actualizaciones se registren automáticamente como pendientes, para poder revisarlas y autorizarlas desde el dashboard sin perder visibilidad de nuevas ubicaciones.

#### Acceptance Criteria

1. WHEN a request arrives at Endpoint_Check from an IP_Desconocida AND the Workstation cannot be authenticated by any method (token, X-Workstation-ID, or IP pública autorizada), THE Backend SHALL create a Registro_Pendiente in the PublicIP table with `is_authorized=False` and `organization_id=NULL`
2. WHEN the Backend creates a Registro_Pendiente, THE Backend SHALL set the `first_seen` field to the current UTC timestamp and set `ip_address` to the client public IP address extracted from the request (max 45 characters, supporting IPv4 and IPv6 formats)
3. WHEN a request triggers a Registro_Pendiente AND the request includes the `X-Workstation-ID` header with a non-empty value, THE Backend SHALL populate the `last_hostname` field of the Registro_Pendiente with the value of that header, regardless of whether the identifier matches an existing Workstation in the database
4. WHEN a request triggers a Registro_Pendiente AND the request includes the `X-Workstation-Local-IP` header with a non-empty value, THE Backend SHALL populate the `last_user` field of the Registro_Pendiente with the value of that header
5. WHEN a request triggers a Registro_Pendiente AND the request does NOT include the `X-Workstation-ID` header or the `X-Workstation-Local-IP` header, THE Backend SHALL leave the corresponding fields (`last_hostname`, `last_user`) as NULL

### Requirement 2: Prevención de registros duplicados

**User Story:** Como administrador, quiero que la tabla de IPs pendientes no se llene de entradas duplicadas por la misma IP, para poder gestionar las autorizaciones de forma limpia y sin ruido.

#### Acceptance Criteria

1. WHEN a request arrives from an IP that already exists in the PublicIP table (regardless of authorization status), THE Backend SHALL NOT create a new Registro_Pendiente for that IP address
2. WHEN a request arrives from an IP that already exists as IP_Pendiente AND the request includes a non-null `X-Workstation-ID` header value, THE Backend SHALL update only the `last_hostname` field of that existing record with the new value, leaving `last_user` unchanged if its corresponding header is absent
3. WHEN a request arrives from an IP that already exists as IP_Pendiente AND the request includes a non-null `X-Workstation-Local-IP` header value, THE Backend SHALL update only the `last_user` field of that existing record with the new value, leaving `last_hostname` unchanged if its corresponding header is absent
4. WHEN a request arrives from an IP that exists in the PublicIP table with `is_authorized=True`, THE Backend SHALL NOT modify the `last_hostname` or `last_user` fields of that record
5. THE Backend SHALL use the existing `ip_address` unique constraint in the PublicIP table to guarantee no duplicate IP entries are created

### Requirement 3: Preservar respuesta HTTP 401 para IPs no autorizadas

**User Story:** Como desarrollador del cliente, quiero que las workstations con IP no autorizada sigan recibiendo HTTP 401, para que el cliente maneje el rechazo correctamente sin cambios en su lógica.

#### Acceptance Criteria

1. WHEN a request arrives from an IP_Desconocida AND a Registro_Pendiente is created, THE Backend SHALL return HTTP 401 with a JSON body containing the field "detail" set to "Workstation no autenticada"
2. WHEN a request arrives from an IP that exists as IP_Pendiente (is_authorized=False), THE Backend SHALL return HTTP 401 with a JSON body containing the field "detail" set to "Workstation no autenticada"
3. IF a Workstation cannot be authenticated by any method (token, X-Workstation-ID, or IP pública autorizada), THEN THE Backend SHALL emit a log warning including the fields: ip_publica, x_workstation_id, and x_workstation_local_ip of the request
4. THE Backend SHALL return an identical HTTP response (status code, headers, and body structure) for an IP_Desconocida and an IP_Pendiente, such that the client cannot distinguish between the two cases

### Requirement 4: Flujo existente sin alteraciones para IPs autorizadas

**User Story:** Como workstation con IP autorizada, quiero que mi flujo de verificación de actualizaciones siga funcionando exactamente igual, para que esta nueva funcionalidad no impacte el servicio en producción.

#### Acceptance Criteria

1. WHEN a request arrives at Endpoint_Check from an IP that exists in the PublicIP table with `is_authorized=True`, THE Backend SHALL skip Registro_Pendiente logic entirely and return HTTP 200 with the UpdateCheckResponse containing the version, auto_update_enabled flag, file_size, build_date, and commit_hash fields
2. WHEN a request arrives at Endpoint_Check authenticated via Bearer token (with admin or operator role) or via a valid X-Workstation-ID header matching an existing Workstation, THE Backend SHALL process the request through the standard authentication path without executing any Registro_Pendiente lookup or insert
3. THE Backend SHALL preserve the existing authentication priority order (Bearer token evaluated first, then X-Workstation-ID header, then IP pública autorizada) and SHALL NOT introduce additional database queries in the authorized request path compared to the flow prior to the Registro_Pendiente feature
4. THE Backend SHALL NOT modify the response status codes (HTTP 200 for successful checks, HTTP 503 for S3 unavailability) nor the UpdateCheckResponse schema fields for requests that are successfully authenticated by any method

### Requirement 5: Registro atómico sin afectar rendimiento del endpoint

**User Story:** Como operador del sistema, quiero que el registro de IPs pendientes no degrade el tiempo de respuesta del endpoint ni cause errores si la base de datos tiene problemas al insertar, para mantener la estabilidad del servicio.

#### Acceptance Criteria

1. IF the database insert or update for a Registro_Pendiente fails (constraint violation, connection error, or any other exception), THEN THE Backend SHALL rollback the failed operation, log the error at WARNING level, and continue returning HTTP 401 without returning an HTTP 5xx response to the client
2. THE Backend SHALL perform the Registro_Pendiente insert within the same database session as the authentication check to avoid additional connection overhead
3. WHEN creating or updating a Registro_Pendiente, THE Backend SHALL execute and commit the operation before raising the HTTPException 401, so that the pending record is persisted prior to the response being sent
4. THE Backend SHALL complete the Registro_Pendiente operation (insert or update) in no more than 500 milliseconds; IF the operation exceeds this threshold, THEN THE Backend SHALL abort the operation, log a timeout warning, and continue returning HTTP 401
