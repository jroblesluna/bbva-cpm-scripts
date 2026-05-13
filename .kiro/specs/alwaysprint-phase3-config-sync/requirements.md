# Requirements Document

## Introduction

La **Fase 3 — Sincronización de Configuración por Hash** implementa el ciclo completo de sincronización de configuración entre el AlwaysPrintTray y APCM (AlwaysPrint Cloud Manager). Sobre la infraestructura de Fase 1 (configuración, credenciales HKCU, mensajes IPC) y Fase 2 (conexión WebSocket persistente, registro de workstation, CloudManager), esta fase agrega: clase `ConfigurationSync` para gestionar la descarga y aplicación de configuración, endpoint REST para obtener la configuración efectiva, cache offline en HKCU, cálculo de hash SHA-256 para detección de cambios, aplicación de configuración al Service vía Named Pipe (`CloudConfigurationReceived`), aplicación de locale override, y confirmación al servidor mediante `config_change_report`.

El mecanismo central es la comparación de hash: cuando APCM envía un mensaje `config_update` con un `config_hash`, el Tray compara ese hash con el almacenado localmente en HKCU. Solo si difieren se descarga la nueva configuración vía HTTP GET, se aplica al Service, y se confirma al servidor. La configuración descargada se persiste como cache offline para uso sin conexión.

Al finalizar esta fase, `dotnet build AlwaysPrint.sln -c Release --nologo` debe producir 0 errores y 0 advertencias, y el comportamiento existente del Client con `CloudEnabled=0` no debe verse alterado.

## Glossary

- **AlwaysPrintService**: Servicio Windows (LocalSystem) que gestiona la cola de impresión corporativa y expone el Named Pipe. No accede a Internet.
- **AlwaysPrintTray**: Aplicación WinForms de bandeja del sistema que se ejecuta en el contexto del usuario. Es el único componente que accede a Internet y a HKCU.
- **APCM**: AlwaysPrint Cloud Manager — plataforma SaaS (FastAPI + Next.js) a la que el Tray se conecta vía WebSocket.
- **AppConfiguration**: Clase de configuración compartida que se persiste en `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`. Contiene campos como `CorporateQueueName`, `SearchTargets`, `PendingTaskPollingMinutes`, `BootstrapDomains`, `ConnectivityChecks`, `CloudLocale`, `TelemetryEnabled`, `TelemetryIntervalSeconds`.
- **CloudCredentialsManager**: Clase en AlwaysPrint.Shared que gestiona credenciales y cache de workstation en `HKCU\SOFTWARE\Robles.AI\AlwaysPrint\Cloud`. Propiedades: `WorkstationId`, `ConfigHash`, `ConfigCachedAt`, `LastConnectedAt`, `ConfigJson`.
- **ConfigurationSync**: Nueva clase en `AlwaysPrintTray/Cloud/` que gestiona la descarga, validación por hash, persistencia en cache y aplicación de configuración desde APCM.
- **CloudManager**: Clase existente (Fase 2) en `AlwaysPrintTray/Cloud/` que orquesta la integración Cloud. En Fase 3 se extiende con el handler de `config_update`.
- **CloudWebSocketClient**: Clase existente (Fase 2) en `AlwaysPrintTray/Cloud/` que mantiene la conexión WSS persistente hacia APCM.
- **EffectiveConfig**: Objeto JSON que representa la configuración efectiva de una workstation, devuelto por el endpoint REST de APCM.
- **Config_Hash**: Hash SHA-256 calculado sobre el JSON crudo de la configuración descargada del servidor. Se usa para detectar cambios sin descargar el contenido completo.
- **Config_Update**: Mensaje WebSocket enviado por APCM al Tray cuando la configuración de la workstation ha cambiado. Contiene el campo `config_hash` con el nuevo hash.
- **Config_Change_Report**: Mensaje WebSocket enviado por el Tray a APCM para confirmar si la configuración fue aplicada exitosamente o reportar un error.
- **CloudConfigurationReceived**: Tipo de mensaje del Named Pipe que transporta la configuración descargada de la nube al AlwaysPrintService para su aplicación en el Registry.
- **SHA-256**: Algoritmo de hash criptográfico usado para calcular el fingerprint de la configuración JSON.
- **Cache_Offline**: Copia de la última configuración descargada almacenada en HKCU como JSON, disponible cuando no hay conexión a APCM.
- **Named_Pipe**: Canal IPC `\\.\pipe\AlwaysPrintService` entre el AlwaysPrintService y el AlwaysPrintTray.
- **PipeClient**: Clase en AlwaysPrintTray que mantiene la conexión al Named Pipe del Service.
- **MessageType**: Enumeración de tipos de mensajes del Named Pipe. Incluye `CloudConfigurationReceived` (nuevo en Fase 3).
- **MessageDispatcher**: Clase en AlwaysPrintService que despacha mensajes recibidos por el Named Pipe a sus handlers correspondientes.
- **LocalizationManager**: Clase que gestiona el idioma activo de la interfaz del Tray. Puede ser reinicializado con un locale diferente.
- **CloudLocale**: Campo de la configuración efectiva que permite al servidor forzar un idioma específico en el Tray.
- **AlwaysPrintLogger**: Clase de logging centralizada. Todos los logs deben pasar por ella con mensajes en español.
- **HKCU**: `HKEY_CURRENT_USER` — accesible sin privilegios de administrador.
- **HKLM**: `HKEY_LOCAL_MACHINE` — requiere privilegios de administrador para escritura.
- **AckPayload**: Payload de respuesta del Service que indica éxito o fallo de una operación solicitada por el Tray.
- **RegistryConfigManager**: Clase en AlwaysPrint.Shared que lee y escribe `AppConfiguration` en `HKLM`.

---

## Requirements

### Requirement 1: ConfigurationSync — Clase principal de sincronización

**User Story:** Como AlwaysPrintTray conectado a APCM, quiero una clase que gestione el ciclo completo de sincronización de configuración (comparación de hash, descarga, persistencia, aplicación), para que la configuración de la workstation se mantenga actualizada de forma eficiente y automática.

#### Acceptance Criteria

1. THE `ConfigurationSync` SHALL be a new `sealed` class in `AlwaysPrintTray/Cloud/ConfigurationSync.cs` within the namespace `AlwaysPrintTray.Cloud`.
2. THE `ConfigurationSync` SHALL accept the following dependencies in its constructor: `string cloudApiUrl`, `string workstationId`, `CloudCredentialsManager credentials`, `PipeClient pipe`, and `CloudWebSocketClient wsClient`.
3. THE `ConfigurationSync` SHALL expose a public `bool SyncIfNeeded(string serverConfigHash)` method that compares the server hash with the local hash stored in `CloudCredentialsManager.ConfigHash`.
4. WHEN `SyncIfNeeded(serverConfigHash)` is called and `serverConfigHash` equals the local hash from `CloudCredentialsManager.ConfigHash`, THE `ConfigurationSync` SHALL return `true` without making any HTTP request.
5. WHEN `SyncIfNeeded(serverConfigHash)` is called and `serverConfigHash` differs from the local hash, THE `ConfigurationSync` SHALL perform the following sequence: (a) send an HTTP GET to `{cloudApiUrl}/api/v1/workstations/{workstationId}/config` with a timeout of 10 seconds, (b) verify the response status is HTTP 200, (c) persist the raw JSON response body and its SHA-256 hash via `CloudCredentialsManager.SaveConfigCache()`, (d) deserialize the JSON into an `AppConfiguration` object, (e) send a `CloudConfigurationReceived` pipe message to the Service via `PipeClient`, and (f) return `true` only if all steps succeed, or `false` if any step fails.
6. THE `ConfigurationSync` SHALL expose a public `bool ForceSync()` method that downloads and applies the configuration using the same sequence as criterion 5 regardless of the current hash value.
7. THE `ConfigurationSync` SHALL expose a public `AppConfiguration? LoadFromCache()` method that reads the cached JSON string via `CloudCredentialsManager.LoadConfigCache()` and returns the deserialized `AppConfiguration`, or returns `null` if no cache exists.
8. IF `LoadFromCache()` is called and the cached JSON string cannot be deserialized into a valid `AppConfiguration` object, THEN THE `ConfigurationSync` SHALL log the error using `AlwaysPrintLogger.WriteTrayError()` and return `null`.
9. IF an exception occurs during `SyncIfNeeded` or `ForceSync`, THEN THE `ConfigurationSync` SHALL log the error using `AlwaysPrintLogger.WriteTrayError()` with a descriptive message in Spanish and return `false` without propagating the exception.
10. THE `ConfigurationSync` SHALL use the same static `HttpClient` instance from `DomainHealthChecker` for HTTP requests — no new `HttpClient` SHALL be created.
11. WHEN `SyncIfNeeded` or `ForceSync` completes the apply sequence successfully, THE `ConfigurationSync` SHALL send a `config_change_report` message via `wsClient` with `applied = true` and the new config hash.
12. IF the pipe send to the Service fails during `SyncIfNeeded` or `ForceSync`, THEN THE `ConfigurationSync` SHALL send a `config_change_report` message via `wsClient` with `applied = false` and an error description, and return `false`.

---

### Requirement 2: Endpoint REST para descarga de configuración

**User Story:** Como ConfigurationSync necesitando descargar la configuración efectiva de una workstation, quiero un endpoint REST bien definido en APCM, para que el Tray pueda obtener la configuración completa cuando el hash indica un cambio.

#### Acceptance Criteria

1. WHEN `ConfigurationSync` determines that the server config hash differs from the local hash stored in HKCU, THE `ConfigurationSync` SHALL send an HTTP GET request to `{CloudApiUrl}/api/v1/workstations/{workstation_id}/config`.
2. THE HTTP GET request SHALL NOT include authentication headers — the server authenticates by public IP address.
3. WHEN the server responds with HTTP 200 and a JSON body that deserializes successfully into an `EffectiveConfig` object containing all required fields (`corporate_queue_name`, `search_targets`, `pending_task_polling_minutes`, `bootstrap_domains`, `connectivity_checks`, `locale`, `telemetry_enabled`, `telemetry_interval_seconds`), THE `ConfigurationSync` SHALL parse the response as an `EffectiveConfig` object and call `AppConfiguration.Validate()` on the resulting configuration before returning it.
4. THE `EffectiveConfig` JSON response SHALL contain the following fields mapped to `AppConfiguration` properties: `corporate_queue_name` → `CorporateQueueName`, `search_targets.ips` → `SearchTargets.Ips`, `search_targets.ranges` → `SearchTargets.Ranges`, `pending_task_polling_minutes` → `PendingTaskPollingMinutes`, `bootstrap_domains` → `BootstrapDomains`, `connectivity_checks` → `ConnectivityChecks`, `locale` → `CloudLocale`, `telemetry_enabled` → `TelemetryEnabled`, `telemetry_interval_seconds` → `TelemetryIntervalSeconds`.
5. IF the server responds with an HTTP error status (4xx or 5xx), THEN THE `ConfigurationSync` SHALL log the error code and up to the first 2048 characters of the response body using `AlwaysPrintLogger.WriteTrayError()` with a message in Spanish and return `false`.
6. IF the HTTP request does not receive a response within 30 seconds or a network error occurs, THEN THE `ConfigurationSync` SHALL log the error using `AlwaysPrintLogger.WriteTrayError()` with a message in Spanish and return `false`.
7. THE `ConfigurationSync` SHALL use `ProxyHelper.CreateHandler()` for the `HttpClient` configuration to support corporate proxy environments.
8. IF the server responds with HTTP 200 but the response body cannot be deserialized as valid JSON or fails `AppConfiguration.Validate()`, THEN THE `ConfigurationSync` SHALL log the parsing or validation error using `AlwaysPrintLogger.WriteTrayError()` with a message in Spanish and return `false`.

---

### Requirement 3: Cache Offline en HKCU

**User Story:** Como AlwaysPrintTray operando sin conexión a APCM, quiero que la última configuración descargada esté disponible como cache en HKCU, para que la workstation pueda aplicar la configuración más reciente incluso en modo offline.

#### Acceptance Criteria

1. THE `CloudCredentialsManager` SHALL expose a new `void SaveConfigCache(string configJson, string configHash)` method that persists the configuration JSON, hash, and timestamp in HKCU.
2. WHEN `SaveConfigCache(configJson, configHash)` is called, THE `CloudCredentialsManager` SHALL write the following values to `HKCU\SOFTWARE\Robles.AI\AlwaysPrint\Cloud`: `ConfigJson` (REG_SZ — the raw JSON, maximum 1 MB), `ConfigHash` (REG_SZ — the SHA-256 hash, 64 hexadecimal characters lowercase), and `ConfigCachedAt` (REG_SZ — current UTC time in ISO-8601 round-trip format specifier "O").
3. THE `CloudCredentialsManager` SHALL expose a new `string? LoadConfigCache()` method that returns the stored `ConfigJson` value from HKCU, or `null` if no cache exists.
4. WHEN `LoadConfigCache()` is called and the registry value `ConfigJson` does not exist, is empty, or consists only of whitespace, THE `CloudCredentialsManager` SHALL return `null`.
5. WHEN configuration is successfully downloaded from the server, THE `ConfigurationSync` SHALL persist the JSON response exactly as received (without re-serialization or reformatting) to ensure hash reproducibility.
6. WHEN configuration is successfully downloaded and applied via Named Pipe (Service responds with `AckPayload.Success = true`), THE `ConfigurationSync` SHALL call `CloudCredentialsManager.SaveConfigCache(rawJson, computedHash)` to persist the cache.
7. IF writing to HKCU fails due to a registry access error, THEN THE `CloudCredentialsManager` SHALL log the error using `AlwaysPrintLogger.WriteTrayWarning()` with a descriptive message in Spanish, leave in-memory properties (`ConfigHash`, `ConfigCachedAt`) unchanged, and return without throwing an exception.
8. IF `SaveConfigCache` is called with a `configJson` parameter that is null or empty, THEN THE `CloudCredentialsManager` SHALL not write to the registry and SHALL return without throwing an exception.

---

### Requirement 4: Cálculo de Hash SHA-256

**User Story:** Como ConfigurationSync comparando configuraciones, quiero calcular un hash SHA-256 del JSON de configuración recibido, para que pueda detectar cambios de forma eficiente sin comparar el contenido completo campo por campo.

#### Acceptance Criteria

1. THE `ConfigurationSync` SHALL compute the SHA-256 hash of the raw JSON string received from the server using `System.Security.Cryptography.SHA256`.
2. WHEN computing the hash, THE `ConfigurationSync` SHALL encode the JSON string as UTF-8 bytes before hashing.
3. THE hash output SHALL be formatted as a lowercase hexadecimal string of exactly 64 characters, without separators (e.g., `"a1b2c3d4..."`).
4. THE hash SHALL be computed over the raw JSON response from the server, not over a re-serialized version of the deserialized object, to ensure deterministic results.
5. WHEN the computed hash matches the `serverConfigHash` provided in the `config_update` message using a case-insensitive ordinal comparison, THE `ConfigurationSync` SHALL consider the download valid and proceed with persisting the configuration in HKCU and sending it to the Service via Named Pipe.
6. IF the computed hash does not match the `serverConfigHash`, THEN THE `ConfigurationSync` SHALL log a warning using `AlwaysPrintLogger.WriteTrayWarning()` with a message in Spanish indicating hash mismatch, and SHALL still apply the configuration, storing the locally computed hash in HKCU.ConfigHash for future comparisons.
7. IF the raw JSON string received from the server is null or empty, THEN THE `ConfigurationSync` SHALL log a warning using `AlwaysPrintLogger.WriteTrayWarning()` with a message in Spanish indicating that the configuration body is empty, and SHALL NOT compute the hash nor proceed with application.

---

### Requirement 5: Aplicar configuración al Service vía Named Pipe

**User Story:** Como AlwaysPrintTray que ha descargado una nueva configuración de APCM, quiero enviarla al AlwaysPrintService a través del Named Pipe, para que el Service la persista en HKLM y la aplique al comportamiento operativo del sistema.

#### Acceptance Criteria

1. WHEN configuration is successfully downloaded and parsed, THE `ConfigurationSync` SHALL send a `PipeMessage` of type `MessageType.CloudConfigurationReceived` to the AlwaysPrintService via `PipeClient`, with a `CloudConfigurationReceivedPayload` containing the parsed `AppConfiguration` object in the `Configuration` field, the SHA-256 hash string in the `ConfigHash` field, and the string `"cloud"` in the `Source` field.
2. WHEN the `ConfigurationSync` sends a `CloudConfigurationReceived` message, THE `ConfigurationSync` SHALL wait for an `AckPayload` response for a maximum of 10 seconds before treating the operation as failed.
3. WHEN the AlwaysPrintService receives a `CloudConfigurationReceived` message, THE `MessageDispatcher` SHALL call `RegistryConfigManager.Save(payload.Configuration)` to persist the configuration in HKLM.
4. WHEN the AlwaysPrintService successfully saves the configuration, THE `MessageDispatcher` SHALL respond with `AckPayload { Success = true }` and log the event using `AlwaysPrintLogger.WriteServiceInfo()` with a message in Spanish indicating the configuration source and hash.
5. IF the AlwaysPrintService fails to save the configuration due to validation error or registry access failure, THEN THE `MessageDispatcher` SHALL respond with `AckPayload { Success = false, Message = <description of the failure> }` and log the error using `AlwaysPrintLogger.WriteServiceError()` with a message in Spanish.
6. THE `MessageDispatcher` SHALL include a case for `MessageType.CloudConfigurationReceived` in its dispatch logic that routes to the `HandleCloudConfigurationReceived` handler method.
7. IF the Named Pipe is not connected when the configuration needs to be applied, THEN THE `ConfigurationSync` SHALL log a warning using `AlwaysPrintLogger.WriteTrayWarning()` with a message in Spanish indicating the pipe is disconnected, and return `false` to the caller without retrying.
8. IF the `ConfigurationSync` receives an `AckPayload` with `Success = false` or the response times out, THEN THE `ConfigurationSync` SHALL log a warning using `AlwaysPrintLogger.WriteTrayWarning()` with a message in Spanish indicating the failure reason, and return `false` to the caller.

---

### Requirement 6: Aplicar Locale Override

**User Story:** Como administrador de APCM configurando workstations remotamente, quiero poder forzar un idioma específico en el Tray a través de la configuración cloud, para que las workstations en diferentes regiones muestren la interfaz en el idioma correcto sin intervención local.

#### Acceptance Criteria

1. WHEN configuration is successfully applied (the Service has responded with `AckPayload { Success = true }`) and the `CloudLocale` field of the parsed configuration is not null or empty, THE `ConfigurationSync` SHALL call `LocalizationManager.Initialize(parsedConfig.CloudLocale)` to apply the locale override.
2. WHEN configuration is successfully applied (the Service has responded with `AckPayload { Success = true }`) and the `CloudLocale` field is null or empty, THE `ConfigurationSync` SHALL NOT call `LocalizationManager.Initialize()` — the existing locale SHALL remain unchanged.
3. THE `ConfigurationSync` SHALL invoke the locale override only after the configuration has been successfully sent to the Service via Named Pipe and an `AckPayload { Success = true }` has been received, and before sending the `config_change_report` to the server.
4. IF `LocalizationManager.Initialize()` throws an exception during resource loading, THEN THE `ConfigurationSync` SHALL log the error using `AlwaysPrintLogger.WriteTrayWarning()` with a message indicating the locale value that failed and SHALL continue operation without propagating the exception — the locale SHALL fall back to "en".
5. THE `LocalizationManager.Initialize()` SHALL accept locale values in ISO 639-1 two-letter format (e.g., "es", "en") or BCP 47 variants (e.g., "es-PE", "es-MX"), normalizing any value starting with "es" to "es" and all other values to "en".

---

### Requirement 7: Confirmar al servidor (config_change_report)

**User Story:** Como APCM gestionando la configuración de workstations, quiero recibir confirmación de que la configuración fue aplicada exitosamente (o un reporte de error), para que pueda auditar el estado de despliegue y reintentar si es necesario.

#### Acceptance Criteria

1. WHEN configuration is successfully downloaded, applied to the Service via Named Pipe, and the Service responds with `AckPayload { Success = true }`, THE `ConfigurationSync` SHALL send a `config_change_report` message via `CloudWebSocketClient.Send("config_change_report", payload)` with payload `{ applied: true, config_hash: "<hash>" }` within 5 seconds of receiving the acknowledgment.
2. IF the Service responds with `AckPayload { Success = false }`, THEN THE `ConfigurationSync` SHALL send a `config_change_report` message via `CloudWebSocketClient.Send("config_change_report", payload)` with payload `{ applied: false, config_hash: "<hash>", error_message: "<description from AckPayload.Message>" }`.
3. IF configuration download fails (HTTP non-2xx response or network timeout) or Named Pipe communication with the Service fails, THEN THE `ConfigurationSync` SHALL send a `config_change_report` message via `CloudWebSocketClient.Send("config_change_report", payload)` with payload `{ applied: false, config_hash: "<hash>", error_message: "<description>" }`.
4. THE `config_hash` field in the report SHALL contain the `serverConfigHash` value from the `config_update` message that triggered the synchronization.
5. IF the WebSocket is not in `Open` state when `config_change_report` is to be sent, THEN THE `ConfigurationSync` SHALL log the failure using `AlwaysPrintLogger.WriteTrayWarning()` with a message in Spanish — the failure to report SHALL NOT affect the already-applied configuration nor trigger a retry of the configuration application.

---

### Requirement 8: Backend — Verificar y agregar campos al endpoint

**User Story:** Como backend de APCM sirviendo configuración a workstations, quiero que el endpoint `GET /api/v1/workstations/{id}/config` incluya todos los campos necesarios para la Fase 3, para que el Tray pueda recibir la configuración completa incluyendo connectivity checks, locale y telemetría.

#### Acceptance Criteria

1. THE backend endpoint `GET /api/v1/workstations/{id}/config` SHALL return an HTTP 200 response with a JSON body containing all the following fields: `corporate_queue_name` (string, max 255 characters), `search_targets` (object with `ips` and `ranges` string fields), `pending_task_polling_minutes` (integer, 1–1440), `bootstrap_domains` (string, max 1000 characters), `connectivity_checks` (array of up to 50 objects, each with `id` string max 64 characters, `type` string being one of `http` or `tcp`, `url` string max 2048 characters, and `timeout_ms` integer 100–30000), `locale` (string, max 10 characters), `telemetry_enabled` (boolean), and `telemetry_interval_seconds` (integer, 10–86400).
2. WHEN the `connectivity_checks` field is not configured for a workstation, THE endpoint SHALL return an empty array `[]`.
3. WHEN the `locale` field is not configured for a workstation, THE endpoint SHALL return an empty string `""`.
4. WHEN the `telemetry_enabled` field is not configured for a workstation, THE endpoint SHALL return `true` as the default value.
5. WHEN the `telemetry_interval_seconds` field is not configured for a workstation, THE endpoint SHALL return `300` as the default value.
6. WHEN the `search_targets` field is not configured for a workstation, THE endpoint SHALL return `null` for that field.
7. IF the requested workstation `{id}` does not exist or does not belong to the authenticated account, THEN THE endpoint SHALL return an HTTP 404 response with an error message indicating the workstation was not found.
8. THE backend SHALL serialize the JSON response with fields in a fixed alphabetical order so that identical configuration values produce identical byte-level output across requests, enabling stable SHA-256 hash comparison by the client.
9. IF the fields `connectivity_checks`, `locale`, `telemetry_enabled`, or `telemetry_interval_seconds` do not exist in the backend models, THEN the developer SHALL add them to `AlwaysPrintProject/Cloud/backend/app/models/config.py` and `AlwaysPrintProject/Cloud/backend/app/schemas/config.py` and create the corresponding Alembic migration to update the database schema.

---

### Requirement 9: Integración con CloudManager — Handler de config_update

**User Story:** Como CloudManager recibiendo mensajes WebSocket de APCM, quiero despachar los mensajes de tipo `config_update` al ConfigurationSync, para que la sincronización de configuración se active automáticamente cuando el servidor notifica un cambio.

#### Acceptance Criteria

1. WHEN the `CloudWebSocketClient` raises the `MessageReceived` event with type `"config_update"`, THE `CloudManager` SHALL parse the JSON payload and extract the `config_hash` field.
2. WHEN a `config_update` message is received with a `config_hash` that is a non-empty string, THE `CloudManager` SHALL call `ConfigurationSync.SyncIfNeeded(configHash)` to trigger the synchronization process.
3. THE `CloudManager` SHALL instantiate `ConfigurationSync` during `Start()` after the `CloudWebSocketClient` is created, passing the required dependencies (`cloudApiUrl`, `workstationId`, `credentials`, `pipe`, `wsClient`).
4. WHEN the server sends a `config_update` message as part of the registration response flow, THE `CloudManager` SHALL handle it identically to any other `config_update` message received at a later time.
5. IF the `config_hash` field is missing, null, or an empty string in the `config_update` message, THEN THE `CloudManager` SHALL log a warning using `AlwaysPrintLogger.WriteTrayWarning()` with a message in Spanish indicating the invalid hash and SHALL NOT call `ConfigurationSync.SyncIfNeeded()`.
6. IF `ConfigurationSync.SyncIfNeeded()` returns `false`, THEN THE `CloudManager` SHALL log a warning using `AlwaysPrintLogger.WriteTrayWarning()` with a message in Spanish indicating that configuration synchronization could not be completed.
7. THE `CloudManager` SHALL add the `"config_update"` case to its existing `OnMessageReceived` switch statement alongside the existing `"ping"` and `"registered"` handlers.
8. IF the JSON payload of a `config_update` message cannot be parsed (malformed JSON), THEN THE `CloudManager` SHALL log a warning using `AlwaysPrintLogger.WriteTrayWarning()` with a message in Spanish indicating the parse failure and SHALL NOT call `ConfigurationSync.SyncIfNeeded()`.
9. IF `ConfigurationSync.SyncIfNeeded()` throws an exception, THEN THE `CloudManager` SHALL catch the exception, log an error using `AlwaysPrintLogger.WriteTrayError()` with a message in Spanish including the exception message, and SHALL NOT propagate the exception to the WebSocket message loop.

---

### Requirement 10: Reglas de arquitectura y logging

**User Story:** Como arquitecto del sistema AlwaysPrint, quiero que todos los cambios de la Fase 3 respeten las reglas de arquitectura establecidas, para que la separación de responsabilidades se mantenga y el sistema sea auditable.

#### Acceptance Criteria

1. THE `ConfigurationSync` class SHALL reside in `AlwaysPrintTray/Cloud/` and SHALL NOT be placed in `AlwaysPrint.Shared` or `AlwaysPrintService`.
2. THE classes added or modified in Phase 3 within `AlwaysPrintTray/Cloud/` SHALL NOT write to `HKLM` under any circumstance — all cache persistence SHALL use `CloudCredentialsManager` which writes exclusively to `HKCU`. Only the `AlwaysPrintService` writes to `HKLM` via `RegistryConfigManager`.
3. THE new code SHALL NOT use `Console.WriteLine` anywhere — all diagnostic output SHALL use `AlwaysPrintLogger` with messages in Spanish.
4. THE `AlwaysPrintService` project SHALL NOT reference any class under `AlwaysPrintTray/Cloud/` — the Service only receives configuration via the Named Pipe.
5. THE `ConfigurationSync` SHALL NOT create new `HttpClient` instances — it SHALL reuse the existing static `HttpClient` from `DomainHealthChecker` to avoid socket exhaustion.
6. IF a `CloudCredentialsManager` method invoked from `ConfigurationSync` throws an exception, THEN THE `ConfigurationSync` SHALL catch the exception, log the error message and exception type using `AlwaysPrintLogger.WriteTrayError`, and continue executing subsequent operations without propagating the exception to the caller.
7. WHILE `CloudEnabled` is `false`, THE AlwaysPrintTray SHALL NOT instantiate `ConfigurationSync`, SHALL NOT make HTTP requests to APCM endpoints, and SHALL NOT send or receive WebSocket messages — all Tray features present before Phase 3 (Named Pipe communication, local configuration display, system tray icon and menu) SHALL remain functional without modification.
8. THE JSON response from the server SHALL be stored as-is (without re-serialization) to guarantee that the hash computed locally matches the hash computed by the server over the same bytes.
9. ALL log messages generated by Phase 3 code SHALL be in Spanish and SHALL use `WriteTrayInfo`, `WriteTrayWarning`, or `WriteTrayError` for code executing in the Tray process, and `WriteServiceInfo` or `WriteServiceError` for code executing in the Service process.
10. IF `ConfigurationSync` catches an exception during the config download HTTP request or during Named Pipe communication with the Service, THEN THE `ConfigurationSync` SHALL log the failure using `AlwaysPrintLogger.WriteTrayError` with the exception details and SHALL send a `config_change_report` with `applied: false` to the server via WebSocket within 5 seconds of the failure.

---

### Requirement 11: Compilación sin errores ni advertencias

**User Story:** Como desarrollador de AlwaysPrint, quiero que la solución compile sin errores ni advertencias después de implementar la Fase 3, para que el pipeline de CI/CD no se vea afectado y el instalador MSI pueda generarse correctamente.

#### Acceptance Criteria

1. WHEN `dotnet build AlwaysPrint.sln -c Release --nologo` is executed from the `AlwaysPrintProject/Client/` directory after all Phase 3 changes, THE `AlwaysPrint.Shared` project SHALL compile with 0 errors and 0 warnings reported in the build output.
2. WHEN `dotnet build AlwaysPrint.sln -c Release --nologo` is executed from the `AlwaysPrintProject/Client/` directory after all Phase 3 changes, THE `AlwaysPrintService` project SHALL compile with 0 errors and 0 warnings reported in the build output.
3. WHEN `dotnet build AlwaysPrint.sln -c Release --nologo` is executed from the `AlwaysPrintProject/Client/` directory after all Phase 3 changes, THE `AlwaysPrintTray` project SHALL compile with 0 errors and 0 warnings reported in the build output.
4. WHEN `build.ps1` is executed from the `AlwaysPrintProject/Client/` directory after all Phase 3 changes, THE `build.ps1` script SHALL terminate with exit code 0 and produce the file `AlwaysPrint.msi` in the `AlwaysPrintProject/Client/` directory.
5. THE Phase 3 changes SHALL NOT add any new `PackageReference` entries to any `.csproj` file in the solution — all required libraries (`Newtonsoft.Json 13.0.3`, `WebSocket4Net 0.15.2`) and framework assemblies (`System.Security.Cryptography`) are already available from previous phases.
6. WHEN `build.ps1` completes successfully, THE `dist/` directory SHALL contain at minimum the files `AlwaysPrintService.exe`, `AlwaysPrintTray.exe`, `AlwaysPrint.Shared.dll`, and `Newtonsoft.Json.dll`.
