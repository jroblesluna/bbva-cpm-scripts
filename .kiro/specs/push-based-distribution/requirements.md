# Requirements Document

## Introduction

Rediseño del flujo de actualización de configuraciones de acciones, certificados ECDSA y MSI para que sea 100% push-based vía WebSocket. Las workstations dejan de consultar endpoints HTTP del backend para obtener su configuración, certificado o MSI — toda la información necesaria (hashes, URLs de descarga S3) se envía proactivamente vía WebSocket cuando un admin realiza un cambio. Esto elimina el pool exhaustion causado por polling de ~300 workstations simultáneas cada 30 segundos.

## Glossary

- **Backend**: Servidor FastAPI con 2 workers uvicorn que gestiona WebSocket, API REST y coordinación vía Redis pub/sub.
- **Workstation**: Cliente C# .NET 4.8 (AlwaysPrintTray + AlwaysPrintService) instalado en PCs Windows corporativos.
- **In_Memory_State_Map**: Estructura de datos en memoria por worker que mantiene `workstation_id → {config_hash, config_s3_url, cert_url, cert_version, msi_url, msi_version}` sincronizado con la base de datos.
- **Config_Push_Message**: Mensaje WebSocket de tipo `action_config_changed` que incluye `config_hash` y `download_url` (URL pública de S3 del archivo firmado).
- **MSI_Push_Message**: Mensaje WebSocket de tipo `check_update` enriquecido con `download_url` (presigned URL de S3), `version` y `file_size`.
- **Cert_Push_Message**: Mensaje WebSocket de tipo `cert_rotated` que incluye `cert_url` (URL pública de S3) y `cert_version`.
- **S3_Direct_Download**: Descarga directa desde S3 sin pasar por el backend, usando URL pública (configs firmadas, certificados) o presigned URL (MSI).
- **Registration_Enrichment**: Datos completos de estado (config_hash, config_s3_url, cert_version, cert_url, msi_version, msi_url) incluidos en la respuesta de registro WebSocket.
- **Manual_Check**: Acción del usuario desde el Tray ("Buscar actualizaciones") que solicita su estado actual al backend vía una sola request HTTP o desde los datos del WebSocket registration.

## Requirements

### Requirement 1: Mapa de estado en memoria por worker

**User Story:** Como operador del sistema, quiero que el backend mantenga un mapa de estado en memoria por cada worker, para que la distribución de configs/updates no genere queries a BD por workstation.

#### Acceptance Criteria

1. WHEN el Backend inicia un worker, THE In_Memory_State_Map SHALL cargarse con los datos actuales de todas las organizaciones activas desde la base de datos (config activa con storage_path, cert_version, cert_url, msi_version/target_version).
2. WHEN un admin activa o modifica una configuración, THE In_Memory_State_Map SHALL actualizarse inmediatamente en el worker que procesa la request.
3. WHEN un admin rota un certificado ECDSA, THE In_Memory_State_Map SHALL actualizarse con el nuevo cert_version y cert_url.
4. WHEN un admin sube un nuevo MSI o cambia target_version, THE In_Memory_State_Map SHALL actualizarse con la nueva msi_version y msi_url.
5. THE In_Memory_State_Map SHALL sincronizarse entre workers vía Redis pub/sub cuando un cambio ocurre en un worker diferente.
6. THE In_Memory_State_Map SHALL organizarse por organization_id como clave primaria, con la config activa por scope (org, vlan, workstation) como sub-estructura.

### Requirement 2: Push de configuración de acciones vía WebSocket

**User Story:** Como workstation, quiero recibir la URL de descarga directa de S3 cuando mi configuración cambia, para no tener que consultar endpoints HTTP del backend.

#### Acceptance Criteria

1. WHEN un admin activa una configuración, THE Backend SHALL enviar un Config_Push_Message a todas las workstations online de la organización afectada con el `config_hash` y la `download_url` (URL pública del archivo firmado en S3).
2. WHEN la Workstation recibe un Config_Push_Message, THE Workstation SHALL comparar el `config_hash` recibido con el hash local.
3. WHEN el hash recibido difiere del hash local, THE Workstation SHALL descargar el archivo firmado directamente desde la `download_url` de S3 sin contactar al backend.
4. WHEN el hash recibido coincide con el hash local, THE Workstation SHALL ignorar el mensaje sin realizar ninguna descarga.
5. IF la descarga directa desde S3 falla, THEN THE Workstation SHALL reintentar con backoff exponencial (1s, 2s, 4s) hasta un máximo de 3 intentos.
6. THE Workstation SHALL verificar la firma ECDSA del archivo descargado desde S3 antes de aplicar la configuración (mismo flujo que actualmente).

### Requirement 3: Push de actualización MSI vía WebSocket

**User Story:** Como workstation, quiero recibir la URL de descarga de MSI cuando hay una nueva versión disponible, para descargar directamente desde S3 sin consultar al backend.

#### Acceptance Criteria

1. WHEN un admin habilita auto-updates o cambia target_version de la organización, THE Backend SHALL enviar un MSI_Push_Message a todas las workstations online de la organización con `download_url` (presigned URL S3), `version` y `file_size`.
2. WHEN la Workstation recibe un MSI_Push_Message, THE Workstation SHALL comparar el campo `version` con su versión instalada actual.
3. WHEN la versión recibida es diferente a la instalada, THE Workstation SHALL descargar el MSI directamente desde la `download_url` presigned de S3.
4. WHEN la versión recibida coincide con la instalada, THE Workstation SHALL ignorar el mensaje.
5. IF la presigned URL de S3 expira o falla la descarga, THEN THE Workstation SHALL solicitar una nueva URL al backend mediante un solo request HTTP de fallback.

### Requirement 4: Push de rotación de certificado vía WebSocket

**User Story:** Como workstation, quiero recibir la URL del nuevo certificado cuando se rota, para descargar directamente desde S3 sin consultar al backend.

#### Acceptance Criteria

1. WHEN un admin rota el certificado ECDSA de la organización, THE Backend SHALL enviar un Cert_Push_Message a todas las workstations online de la organización con `cert_url` y `cert_version`.
2. WHEN la Workstation recibe un Cert_Push_Message con cert_version mayor al local, THE Workstation SHALL descargar el nuevo certificado desde la `cert_url` de S3.
3. WHEN la Workstation recibe un Cert_Push_Message con cert_version igual o menor al local, THE Workstation SHALL ignorar el mensaje.
4. IF la descarga del certificado falla, THEN THE Workstation SHALL reintentar con backoff exponencial (1s, 2s, 4s) hasta un máximo de 3 intentos.

### Requirement 5: Enriquecimiento del registro WebSocket

**User Story:** Como workstation que se reconecta, quiero recibir mi estado completo (config, cert, MSI) al registrarme por WebSocket, para sincronizarme sin consultar endpoints HTTP.

#### Acceptance Criteria

1. WHEN una Workstation completa el registro WebSocket exitosamente, THE Backend SHALL incluir en la respuesta de registro: config_hash, config_s3_url, cert_version, cert_url, msi_version y msi_url obtenidos desde el In_Memory_State_Map.
2. WHEN la Workstation procesa la respuesta de registro enriquecida, THE Workstation SHALL comparar cada campo contra su estado local y descargar desde S3 lo que difiera.
3. IF el In_Memory_State_Map no tiene datos para la organización de la workstation al momento del registro, THEN THE Backend SHALL consultar la BD una sola vez para poblar el mapa y luego responder.

### Requirement 6: Verificación manual desde el Tray

**User Story:** Como usuario, quiero poder verificar manualmente si hay actualizaciones pendientes desde el botón del Tray, para tener una forma de sincronización on-demand.

#### Acceptance Criteria

1. WHEN el usuario presiona "Buscar actualizaciones" en el Tray, THE Workstation SHALL verificar config, certificado y MSI comparando su estado local contra los datos recibidos en el último Registration_Enrichment o el último push message recibido.
2. IF la Workstation no tiene datos de estado recientes (primer inicio o reconexión pendiente), THEN THE Workstation SHALL hacer una sola request HTTP al Backend para obtener su estado completo (config_hash, config_s3_url, cert_version, cert_url, msi_version, msi_url).
3. WHEN la verificación manual detecta diferencias, THE Workstation SHALL descargar directamente desde S3 los recursos que difieran.

### Requirement 7: Eliminación de dependencia de endpoints de workstation

**User Story:** Como equipo de desarrollo, quiero eliminar la dependencia de las workstations en los endpoints `/config/info` y `/config/download`, para que el pool de conexiones BD no se sature por operaciones de distribución.

#### Acceptance Criteria

1. THE Workstation SHALL obtener configuraciones exclusivamente vía S3_Direct_Download usando URLs provistas por WebSocket push o Registration_Enrichment.
2. THE Workstation SHALL obtener certificados exclusivamente vía S3_Direct_Download usando la cert_url provista por WebSocket push o Registration_Enrichment.
3. THE Workstation SHALL obtener MSI exclusivamente vía S3_Direct_Download usando presigned URLs provistas por WebSocket push o Registration_Enrichment.
4. THE Backend SHALL mantener los endpoints `/workstations/{id}/config/info` y `/workstations/{id}/config/download` funcionales como fallback durante un periodo de transición, pero las workstations actualizadas no los consultarán en operación normal.

### Requirement 8: Sincronización multi-worker del estado en memoria

**User Story:** Como sistema distribuido con 2 workers, quiero que los cambios de estado se propaguen entre workers, para que cualquier worker pueda enviar push messages con datos actualizados.

#### Acceptance Criteria

1. WHEN un cambio de configuración, certificado o MSI ocurre en un worker, THE Backend SHALL publicar el cambio en un canal Redis dedicado (`state_map:update`).
2. WHEN un worker recibe una actualización vía Redis pub/sub del canal `state_map:update`, THE In_Memory_State_Map de ese worker SHALL actualizarse inmediatamente.
3. IF Redis no está disponible temporalmente, THEN THE Backend SHALL seguir operando con el In_Memory_State_Map del worker local (eventual consistency) y re-sincronizar cuando Redis se recupere.
4. THE Backend SHALL loguear cuando detecta inconsistencia entre workers (config_hash diferente para la misma organización).

### Requirement 9: Zero queries a BD en la ruta de distribución

**User Story:** Como equipo de operaciones, quiero que la distribución de configs/updates no genere queries a BD por workstation, para que el pool de conexiones nunca se sature por esta operación.

#### Acceptance Criteria

1. WHEN el Backend envía Config_Push_Message, MSI_Push_Message o Cert_Push_Message a N workstations, THE Backend SHALL realizar 0 queries a BD (los datos provienen del In_Memory_State_Map).
2. WHEN una Workstation se registra y el In_Memory_State_Map ya tiene datos de su organización, THE Backend SHALL responder con Registration_Enrichment sin queries a BD.
3. THE Backend SHALL realizar como máximo 1 query a BD por organización al cargar datos en el In_Memory_State_Map (no 1 por workstation).
