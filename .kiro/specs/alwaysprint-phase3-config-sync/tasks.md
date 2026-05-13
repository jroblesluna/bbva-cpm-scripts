# Implementation Plan: Phase 3 — Configuration Sync by Hash

## Overview

Implementación del ciclo completo de sincronización de configuración entre AlwaysPrintTray y APCM. El mecanismo central es la comparación de hash SHA-256: cuando APCM envía un `config_update` con un `config_hash`, el Tray compara con el hash local en HKCU, y solo si difieren descarga la nueva configuración vía HTTP GET, la aplica al Service vía Named Pipe, la persiste como cache offline, y confirma al servidor.

La implementación abarca: C# (.NET 4.8) para el Client (Tray + Service + Shared) y Python 3.12 (FastAPI) para el Backend.

## Tasks

- [x] 1. Modelos y schemas del backend — Nuevos campos de configuración
  - [x] 1.1 Agregar campos al modelo de base de datos y crear migración Alembic
    - Agregar columnas `connectivity_checks` (JSON, default `[]`), `locale` (VARCHAR(10), default `""`), `telemetry_enabled` (BOOLEAN, default `True`), `telemetry_interval_seconds` (INTEGER, default `300`) a los modelos `GlobalConfig`, `VLANConfig`, y `WorkstationConfig` en `AlwaysPrintProject/Cloud/backend/app/models/config.py`
    - En `VLANConfig` y `WorkstationConfig` las columnas deben ser nullable para permitir override selectivo
    - Crear migración Alembic con `alembic revision --autogenerate -m "add_phase3_config_fields"`
    - _Requirements: 8.9_

  - [x] 1.2 Actualizar schemas Pydantic con los nuevos campos
    - Agregar campos `connectivity_checks`, `locale`, `telemetry_enabled`, `telemetry_interval_seconds` al schema `EffectiveConfigResponse` en `AlwaysPrintProject/Cloud/backend/app/schemas/config.py`
    - Definir validaciones: `connectivity_checks` como lista de objetos con `id` (max 64 chars), `type` (http|tcp), `url` (max 2048 chars), `timeout_ms` (100-30000); máximo 50 elementos
    - Definir `locale` (max 10 chars), `telemetry_enabled` (bool, default True), `telemetry_interval_seconds` (int 10-86400, default 300)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

- [x] 2. Endpoint REST — GET /api/v1/workstations/{id}/config
  - [x] 2.1 Implementar endpoint de configuración efectiva
    - Crear archivo `AlwaysPrintProject/Cloud/backend/app/api/v1/endpoints/config.py` con el endpoint `GET /api/v1/workstations/{workstation_id}/config`
    - Implementar resolución de configuración efectiva: WorkstationConfig override → VLANConfig override → GlobalConfig defaults
    - Serializar respuesta JSON con claves en orden alfabético fijo usando `json.dumps(sort_keys=True)` para garantizar hash estable
    - Retornar HTTP 404 si la workstation no existe o no pertenece a la cuenta autenticada
    - Autenticación por IP pública (sin headers de auth)
    - Registrar el router en el archivo principal de rutas
    - _Requirements: 2.1, 2.2, 8.1, 8.7, 8.8_

  - [ ]* 2.2 Write property test for deterministic JSON serialization
    - **Property 6: Backend JSON deterministic serialization**
    - **Validates: Requirements 8.8**
    - Verificar que serializar la misma configuración múltiples veces produce bytes idénticos con claves en orden alfabético

  - [ ]* 2.3 Write unit tests for endpoint config
    - Test HTTP 200 con todos los campos presentes
    - Test HTTP 404 para workstation inexistente
    - Test valores por defecto cuando campos no están configurados (`connectivity_checks` → `[]`, `locale` → `""`, `telemetry_enabled` → `true`, `telemetry_interval_seconds` → `300`, `search_targets` → `null`)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

- [x] 3. Checkpoint — Backend completo
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. CloudCredentialsManager — Cache offline en HKCU
  - [x] 4.1 Implementar métodos SaveConfigCache y LoadConfigCache
    - Agregar método `void SaveConfigCache(string configJson, string configHash)` a `CloudCredentialsManager` en `AlwaysPrintProject/Client/AlwaysPrint.Shared/Configuration/CloudCredentialsManager.cs`
    - Escribir `ConfigJson` (REG_SZ, max 1 MB), `ConfigHash` (REG_SZ, 64 hex chars lowercase), `ConfigCachedAt` (REG_SZ, UTC ISO-8601 formato "O") en `HKCU\SOFTWARE\Robles.AI\AlwaysPrint\Cloud`
    - Agregar método `string? LoadConfigCache()` que retorna el valor `ConfigJson` almacenado, o `null` si no existe, está vacío, o es solo whitespace
    - Si `configJson` es null o vacío, no escribir al registro y retornar sin excepción
    - Si falla la escritura al registro, loggear con `AlwaysPrintLogger.WriteTrayWarning()` en español, dejar propiedades in-memory sin cambios, y retornar sin excepción
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.7, 3.8_

  - [ ]* 4.2 Write property test for cache round-trip preservation
    - **Property 2: Cache round-trip preservation**
    - **Validates: Requirements 3.2, 3.3, 3.5**
    - Para cualquier JSON string válido almacenado vía `SaveConfigCache`, `LoadConfigCache()` debe retornar un string byte-for-byte idéntico al input original

- [x] 5. Mensajes IPC — CloudConfigurationReceived
  - [x] 5.1 Agregar MessageType y Payload para CloudConfigurationReceived
    - Agregar `CloudConfigurationReceived` al enum `MessageType` en `AlwaysPrintProject/Client/AlwaysPrint.Shared/Messages/MessageType.cs`
    - Crear clase `CloudConfigurationReceivedPayload` en `AlwaysPrintProject/Client/AlwaysPrint.Shared/Messages/Payloads.cs` con propiedades: `AppConfiguration Configuration`, `string ConfigHash`, `string Source` (valor fijo `"cloud"`)
    - _Requirements: 5.1_

  - [x] 5.2 Implementar handler en MessageDispatcher del Service
    - Agregar case `MessageType.CloudConfigurationReceived` en el dispatch logic de `MessageDispatcher` en `AlwaysPrintProject/Client/AlwaysPrintService/`
    - Implementar método `HandleCloudConfigurationReceived` que: deserializa el payload, llama `RegistryConfigManager.Save(payload.Configuration)`, responde con `AckPayload { Success = true }` y loggea con `AlwaysPrintLogger.WriteServiceInfo()` en español indicando fuente y hash
    - Si falla la validación o escritura al registro, responder con `AckPayload { Success = false, Message = <descripción> }` y loggear con `AlwaysPrintLogger.WriteServiceError()` en español
    - _Requirements: 5.3, 5.4, 5.5, 5.6_

- [x] 6. ConfigurationSync — Clase principal de sincronización
  - [x] 6.1 Crear clase ConfigurationSync con estructura base
    - Crear archivo `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/ConfigurationSync.cs` con namespace `AlwaysPrintTray.Cloud`
    - Declarar como `public sealed class ConfigurationSync`
    - Implementar constructor con dependencias: `string cloudApiUrl`, `string workstationId`, `CloudCredentialsManager credentials`, `PipeClient pipe`, `CloudWebSocketClient wsClient`
    - Implementar método privado `static string ComputeSha256(string input)` — codificar como UTF-8, calcular SHA-256 con `System.Security.Cryptography.SHA256`, formatear como hex lowercase 64 chars
    - Implementar método privado `void SendChangeReport(bool applied, string configHash, string? errorMessage)` — enviar `config_change_report` vía `wsClient.Send()`, si WebSocket no está Open loggear warning en español
    - Reutilizar `HttpClient` estático de `DomainHealthChecker` — NO crear nuevas instancias
    - _Requirements: 1.1, 1.2, 1.10, 4.1, 4.2, 4.3, 10.1, 10.5_

  - [ ]* 6.2 Write property test for SHA-256 computation correctness
    - **Property 4: SHA-256 computation correctness**
    - **Validates: Requirements 4.1, 4.2, 4.3**
    - Para cualquier string no-null no-vacío, `ComputeSha256(input)` produce un hex lowercase de exactamente 64 caracteres igual al SHA-256 digest de la representación UTF-8 del input

  - [ ]* 6.3 Write property test for hash comparison case-insensitivity
    - **Property 5: Hash comparison case-insensitivity**
    - **Validates: Requirements 4.5**
    - Para dos hash strings que difieren solo en casing, la comparación en `SyncIfNeeded` los trata como iguales (no dispara descarga)

  - [x] 6.4 Implementar método SyncIfNeeded
    - Implementar `public bool SyncIfNeeded(string serverConfigHash)` que:
      - Compara `serverConfigHash` con `credentials.ConfigHash` usando `StringComparison.OrdinalIgnoreCase`
      - Si son iguales: retorna `true` sin HTTP request
      - Si difieren: llama `DownloadConfig()` → `ApplyConfig(rawJson, serverConfigHash)` → retorna resultado
    - Toda excepción se captura, se loggea con `AlwaysPrintLogger.WriteTrayError()` en español, y retorna `false`
    - _Requirements: 1.3, 1.4, 1.5, 1.9_

  - [ ]* 6.5 Write property test for hash-based sync decision
    - **Property 1: Hash-based sync decision**
    - **Validates: Requirements 1.4, 1.5**
    - Para cualquier `serverConfigHash` y hash local, `SyncIfNeeded` dispara descarga HTTP si y solo si los hashes difieren (comparación case-insensitive ordinal)

  - [x] 6.6 Implementar método privado DownloadConfig
    - Implementar `private string? DownloadConfig()` que:
      - Envía HTTP GET a `{cloudApiUrl}/api/v1/workstations/{workstationId}/config` usando el HttpClient estático de `DomainHealthChecker` con `ProxyHelper.CreateHandler()`
      - Timeout de 30 segundos
      - Si HTTP 200: retorna el body como string crudo
      - Si HTTP 4xx/5xx: loggea código + primeros 2048 chars del body con `WriteTrayError` en español, retorna `null`
      - Si timeout o error de red: loggea con `WriteTrayError` en español, retorna `null`
      - Si body es null o vacío: loggea warning en español, retorna `null`
    - _Requirements: 2.1, 2.2, 2.5, 2.6, 2.7, 4.7_

  - [x] 6.7 Implementar método privado ApplyConfig
    - Implementar `private bool ApplyConfig(string rawJson, string serverConfigHash)` que ejecuta la secuencia:
      1. Calcular SHA-256 del rawJson → `computedHash`
      2. Si `computedHash` ≠ `serverConfigHash` (case-insensitive): loggear warning de hash mismatch, continuar con `computedHash`
      3. Deserializar JSON → `AppConfiguration` usando mapeo de campos (snake_case → PascalCase)
      4. Llamar `AppConfiguration.Validate()` — si falla, loggear error y retornar `false`
      5. Verificar que PipeClient está conectado — si no, loggear warning y retornar `false`
      6. Enviar `PipeMessage(CloudConfigurationReceived, payload)` con `Configuration`, `ConfigHash = computedHash`, `Source = "cloud"`
      7. Esperar `AckPayload` del Service con timeout de 10 segundos
      8. Si `AckPayload.Success = false` o timeout: loggear warning, enviar `config_change_report(applied: false)`, retornar `false`
      9. Llamar `credentials.SaveConfigCache(rawJson, computedHash)` — capturar excepciones de CCM
      10. Si `config.CloudLocale` no es null/vacío: llamar `LocalizationManager.Initialize(config.CloudLocale)` — capturar excepciones, loggear warning
      11. Enviar `config_change_report(applied: true, configHash: serverConfigHash)`
      12. Retornar `true`
    - _Requirements: 1.5, 1.11, 1.12, 3.5, 3.6, 4.4, 4.5, 4.6, 5.1, 5.2, 5.7, 5.8, 6.1, 6.2, 6.3, 6.4, 7.1, 7.2, 7.3, 7.4, 7.5, 10.6, 10.8, 10.10_

  - [ ]* 6.8 Write property test for EffectiveConfig → AppConfiguration field mapping
    - **Property 3: EffectiveConfig → AppConfiguration field mapping**
    - **Validates: Requirements 2.3, 2.4**
    - Para cualquier JSON válido con todos los campos requeridos, deserializar y mapear a `AppConfiguration` produce una configuración donde cada campo coincide con el mapeo definido

  - [x] 6.9 Implementar métodos ForceSync y LoadFromCache
    - Implementar `public bool ForceSync()` — misma secuencia que `SyncIfNeeded` cuando hashes difieren, sin comparar hash previo
    - Implementar `public AppConfiguration? LoadFromCache()` — lee JSON vía `credentials.LoadConfigCache()`, deserializa a `AppConfiguration`, retorna `null` si no hay cache o si falla la deserialización (loggeando error con `WriteTrayError` en español)
    - _Requirements: 1.6, 1.7, 1.8_

- [x] 7. Checkpoint — ConfigurationSync completo
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Integración con CloudManager — Handler de config_update
  - [x] 8.1 Integrar ConfigurationSync en CloudManager
    - Agregar campo `private ConfigurationSync? _configSync` en `CloudManager`
    - Instanciar `ConfigurationSync` en `Start()` después de crear `CloudWebSocketClient`, pasando `_config.CloudApiUrl`, `_credentials.WorkstationId`, `_credentials`, `_pipe`, `_wsClient`
    - Agregar case `"config_update"` en el switch de `OnMessageReceived` que llama a `HandleConfigUpdate(json)`
    - Implementar `HandleConfigUpdate`: parsear JSON, extraer `config_hash`, validar que no sea null/vacío, llamar `_configSync.SyncIfNeeded(configHash)`
    - Si `config_hash` es missing/null/vacío: loggear warning en español, no llamar SyncIfNeeded
    - Si JSON malformado: loggear warning en español, no llamar SyncIfNeeded
    - Si `SyncIfNeeded` retorna `false`: loggear warning en español
    - Si `SyncIfNeeded` lanza excepción: capturar, loggear error en español con mensaje de excepción, no propagar
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9_

  - [ ]* 8.2 Write property test for config_update message dispatch
    - **Property 7: config_update message dispatch**
    - **Validates: Requirements 9.1, 9.2**
    - Para cualquier mensaje WebSocket con `type = "config_update"` y `config_hash` no vacío, `CloudManager.OnMessageReceived` extrae el hash e invoca `ConfigurationSync.SyncIfNeeded()` con ese string exacto

- [x] 9. Locale override — Integración con LocalizationManager
  - [x] 9.1 Verificar y ajustar LocalizationManager.Initialize para locale normalization
    - Verificar que `LocalizationManager.Initialize()` acepta valores ISO 639-1 (e.g., "es", "en") y BCP 47 (e.g., "es-PE", "es-MX")
    - Implementar normalización: cualquier valor que empiece con "es" → "es", todos los demás → "en"
    - Si `Initialize()` lanza excepción durante carga de recursos, el caller (`ConfigurationSync`) ya la captura y loggea warning
    - _Requirements: 6.5_

- [x] 10. Reglas de arquitectura y validación final
  - [x] 10.1 Verificar reglas de arquitectura
    - Confirmar que `ConfigurationSync` está en `AlwaysPrintTray/Cloud/` y NO en `AlwaysPrint.Shared` ni `AlwaysPrintService`
    - Confirmar que ningún código en `AlwaysPrintTray/Cloud/` escribe a HKLM
    - Confirmar que no hay `Console.WriteLine` en el código nuevo — solo `AlwaysPrintLogger`
    - Confirmar que `AlwaysPrintService` no referencia clases de `AlwaysPrintTray/Cloud/`
    - Confirmar que no se crean nuevas instancias de `HttpClient`
    - Confirmar que no se agregan nuevos `PackageReference` a ningún `.csproj`
    - Confirmar que `CloudEnabled=false` no instancia `ConfigurationSync` ni hace requests HTTP/WebSocket
    - Confirmar que todos los logs están en español
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.7, 10.8, 10.9, 11.5_

  - [x] 10.2 Compilar solución sin errores ni advertencias
    - Ejecutar `dotnet build AlwaysPrint.sln -c Release --nologo` desde `AlwaysPrintProject/Client/`
    - Verificar 0 errores y 0 advertencias en AlwaysPrint.Shared, AlwaysPrintService, y AlwaysPrintTray
    - _Requirements: 11.1, 11.2, 11.3_

- [x] 11. Final checkpoint — Compilación y validación completa
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- El código C# usa .NET Framework 4.8 — no usar features de .NET 5+
- El backend usa Python 3.12 con FastAPI y SQLAlchemy
- Todos los mensajes de log deben estar en español según AGENTS.md
- No agregar nuevos PackageReference — usar librerías ya disponibles (Newtonsoft.Json 13.0.3, WebSocket4Net 0.15.2, System.Security.Cryptography)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "5.1"] },
    { "id": 1, "tasks": ["1.2", "5.2"] },
    { "id": 2, "tasks": ["2.1", "4.1"] },
    { "id": 3, "tasks": ["2.2", "2.3", "4.2"] },
    { "id": 4, "tasks": ["6.1"] },
    { "id": 5, "tasks": ["6.2", "6.3", "6.4"] },
    { "id": 6, "tasks": ["6.5", "6.6"] },
    { "id": 7, "tasks": ["6.7"] },
    { "id": 8, "tasks": ["6.8", "6.9"] },
    { "id": 9, "tasks": ["8.1", "9.1"] },
    { "id": 10, "tasks": ["8.2"] },
    { "id": 11, "tasks": ["10.1", "10.2"] }
  ]
}
```
