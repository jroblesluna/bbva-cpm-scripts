# Implementation Plan: Auto-Update

## Overview

Implementación del sistema de actualizaciones automáticas para AlwaysPrint. Se organiza por capas: primero la capa compartida (Shared) que es fundación, luego backend y cliente en paralelo, y finalmente frontend e integración. Cada tarea construye sobre las anteriores de forma incremental.

## Tasks

- [x] 1. Capa Compartida (AlwaysPrint.Shared) - Fundación
  - [x] 1.1 Extender RegistryConfigManager con campo AutoUpdateEnabled
    - Agregar `SetIfMissing(key, "AutoUpdateEnabled", 0, RegistryValueKind.DWord)` en `EnsureDefaults()`
    - Implementar método `LoadAutoUpdateEnabled()` que lee DWORD del registro y retorna bool
    - Implementar método `SaveAutoUpdateEnabled(bool enabled)` que escribe al registro
    - El campo es independiente de `AppConfiguration` para evitar sobreescritura por sincronización Cloud
    - _Requirements: 1.2, 1.3, 1.4_

  - [x] 1.2 Agregar InstallUpdate/InstallUpdateResponse a MessageType y Payloads
    - Agregar valores `InstallUpdate` e `InstallUpdateResponse` al enum `MessageType` en `MessageType.cs`
    - Crear clase `InstallUpdatePayload` con propiedad `MsiFilePath` (string) en `Payloads.cs`
    - Crear clase `InstallUpdateResponsePayload` con propiedades `Success` (bool), `Message` (string), `ExitCode` (int) en `Payloads.cs`
    - Usar atributos `[JsonProperty(...)]` consistentes con el resto de payloads existentes
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 1.3 Write property test para serialización round-trip de payloads IPC (FsCheck)
    - **Property 8: IPC payload serialization round-trip**
    - Generar `InstallUpdatePayload` con strings arbitrarios no-nulos para MsiFilePath
    - Generar `InstallUpdateResponsePayload` con bool, string y int arbitrarios
    - Verificar que serializar a JSON y deserializar produce objeto igual al original
    - **Validates: Requirements 10.3, 10.4**

- [x] 2. Backend - Modelo de datos y migración
  - [x] 2.1 Agregar campo auto_update_enabled al modelo Account + migración Alembic
    - Agregar `auto_update_enabled = Column(Boolean, nullable=False, default=False, server_default='false')` al modelo Account en `app/models/account.py`
    - Importar Base desde `app.core.database` (NO desde `app.db`)
    - Crear migración Alembic con `op.add_column('accounts', ...)` y `op.drop_column` en downgrade
    - Verificar que la migración aplica correctamente con `alembic upgrade head`
    - _Requirements: 8.1_

- [x] 3. Backend - Servicio S3
  - [x] 3.1 Crear clase S3UpdateService
    - Crear archivo `app/services/s3_update_service.py`
    - Implementar método `get_msi_metadata()` que llama `head_object` en `alwaysprint-artifacts/latest/AlwaysPrint.msi`
    - Extraer metadata: version, build-date, commit-hash del response, y ContentLength para file_size
    - Implementar método `generate_download_url(expires_in=3600)` que genera presigned URL con boto3
    - Manejar excepciones de S3 (ClientError) con logging apropiado en español
    - _Requirements: 6.3, 7.2_

- [x] 4. Backend - Endpoints de actualización
  - [x] 4.1 Crear endpoint GET /api/v1/updates/check
    - Crear archivo `app/api/v1/endpoints/updates.py` con router
    - Implementar endpoint que identifica workstation, obtiene account_id, lee auto_update_enabled
    - Llamar `S3UpdateService.get_msi_metadata()` para obtener versión y tamaño
    - Retornar schema `UpdateCheckResponse` con version, auto_update_enabled, file_size, build_date, commit_hash
    - Retornar 503 si S3 no responde, 401 si workstation no autenticada
    - Loggear cada request con workstation identifier y response status
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 11.5_

  - [x] 4.2 Crear endpoint GET /api/v1/updates/download
    - En el mismo archivo `app/api/v1/endpoints/updates.py`
    - Identificar workstation y su organización
    - Verificar `account.auto_update_enabled == True`, retornar 403 si no
    - Generar presigned URL via `S3UpdateService.generate_download_url()`
    - Retornar `RedirectResponse(url, status_code=302)`
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 4.3 Crear endpoint PATCH /api/v1/organizations/{org_id}/auto-update
    - Crear archivo `app/api/v1/endpoints/organizations.py` (o agregar al existente si ya existe)
    - Requerir autenticación admin (JWT Bearer)
    - Aceptar body `{"enabled": bool}`, actualizar `auto_update_enabled` en Account
    - Retornar 404 si organización no encontrada, 403 si no es admin
    - Retornar `AutoUpdateToggleResponse` con auto_update_enabled, organization_id, updated_at
    - _Requirements: 8.2, 8.3, 8.4, 8.5_

  - [x] 4.4 Registrar router de updates en la aplicación FastAPI
    - Agregar el router de updates al `app/api/v1/api.py` o equivalente
    - Crear schemas Pydantic: `UpdateCheckResponse`, `AutoUpdateToggleRequest`, `AutoUpdateToggleResponse`
    - Verificar que los endpoints responden correctamente con `uvicorn` local
    - _Requirements: 6.1, 7.1, 8.2_

- [x] 5. Checkpoint - Verificar que backend compila y migración aplica
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Property tests para backend (Python/Hypothesis)
  - [x] 6.1 Write property test para completitud de respuesta de /updates/check
    - **Property 5: Update check response completeness**
    - Generar metadata S3 aleatoria (version string, file_size int positivo, build_date, commit_hash)
    - Generar estado auto_update_enabled aleatorio (bool)
    - Verificar que la respuesta siempre contiene todos los campos requeridos: version, auto_update_enabled, file_size
    - **Validates: Requirements 6.2**

  - [x] 6.2 Write property test para autorización de /updates/download
    - **Property 6: Download endpoint authorization**
    - Generar escenarios con org flag true/false
    - Verificar que retorna 302 si y solo si auto_update_enabled es true; 403 en caso contrario
    - **Validates: Requirements 7.3, 7.4**

  - [x] 6.3 Write property test para consistencia del toggle de organización
    - **Property 7: Organization flag toggle consistency**
    - Generar secuencias aleatorias de operaciones PATCH con valores bool
    - Verificar que el valor final en BD siempre es igual al último PATCH de la secuencia
    - **Validates: Requirements 8.3, 8.4**

- [x] 7. Cliente Service - Handler de instalación
  - [x] 7.1 Crear clase UpdateInstallHandler en AlwaysPrintService
    - Crear archivo `AlwaysPrintService/Tasks/UpdateInstallHandler.cs`
    - Implementar método `Execute(string msiFilePath)` que retorna `InstallUpdateResponsePayload`
    - Verificar existencia del archivo con `File.Exists()`
    - Ejecutar `Process.Start("msiexec", "/i \"<path>\" /quiet /norestart")` con `WaitForExit()`
    - Timeout de 10 minutos; si excede, matar proceso y retornar error
    - Si ExitCode == 0: eliminar MSI temporal, reiniciar Tray, retornar éxito
    - Si ExitCode != 0: loggear error con código, retornar fallo
    - Todos los logs en español via `AlwaysPrintLogger`
    - _Requirements: 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 11.3_

  - [x] 7.2 Integrar InstallUpdate en MessageDispatcher
    - Agregar case `MessageType.InstallUpdate` en el método `Dispatch()` de `MessageDispatcher.cs`
    - Implementar `HandleInstallUpdate(PipeMessage req)` que deserializa payload, valida, y llama a `UpdateInstallHandler.Execute()`
    - Retornar `PipeMessage.Reply` con `MessageType.InstallUpdateResponse` y el resultado
    - Retornar error si payload es inválido (MsiFilePath vacío o nulo)
    - _Requirements: 10.5, 5.1_

  - [x] 7.3 Write property test para validación de file path del install handler (FsCheck)
    - **Property 3: Install handler file path validation**
    - Generar paths aleatorios (existentes y no existentes)
    - Verificar que retorna failure si y solo si el archivo no existe en el path
    - **Validates: Requirements 5.2, 5.4**

  - [x] 7.4 Write property test para reporte de exit code (FsCheck)
    - **Property 4: Install handler exit code reporting**
    - Generar exit codes aleatorios no-cero
    - Verificar que InstallUpdateResponse tiene Success=false y ExitCode igual al código real del proceso
    - **Validates: Requirements 5.5**

- [x] 8. Cliente Tray - Componentes de actualización
  - [x] 8.1 Crear clase UpdateChecker en AlwaysPrintTray/Cloud/
    - Crear archivo `AlwaysPrintTray/Cloud/UpdateChecker.cs`
    - Implementar Timer con intervalo de 24 horas (86_400_000 ms)
    - Método `Start()` que inicia timer y ejecuta check inmediato si Local_Flag habilitado
    - Método `CheckNowAsync()`: leer flag local → llamar API /updates/check → comparar versiones → disparar evento
    - Evento `UpdateAvailable` con `UpdateInfo` (Version, FileSize, OrganizationAutoUpdateEnabled)
    - Si backend inalcanzable: loggear warning en español, no interrumpir operación
    - Si org flag deshabilitado: loggear y salir sin descargar
    - Si versiones iguales: loggear "sin actualización disponible"
    - Implementar `IDisposable` para cleanup del timer
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 11.1_

  - [x] 8.2 Crear clase UpdateDownloader en AlwaysPrintTray/Cloud/
    - Crear archivo `AlwaysPrintTray/Cloud/UpdateDownloader.cs`
    - Directorio de descarga: `Path.Combine(Path.GetTempPath(), "AlwaysPrint", "Updates")`
    - Método `DownloadAsync(long expectedSize)`: llamar /updates/download, seguir redirect, guardar archivo
    - Verificar integridad: `FileInfo.Length == expectedSize`
    - Si falla: eliminar archivo parcial, loggear error en español, retornar null
    - Descarga asíncrona y no bloqueante (Task-based)
    - Método `Cleanup()` para eliminar archivos antiguos
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 11.2_

  - [x] 8.3 Write property test para lógica de decisión de actualización (FsCheck)
    - **Property 1: Update decision logic**
    - Generar combinaciones aleatorias de (local_flag: bool, org_flag: bool, available_version: string, installed_version: string)
    - Verificar que procede a descarga si y solo si: local_flag=true AND org_flag=true AND available_version != installed_version
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4**

  - [x] 8.4 Write property test para verificación de integridad por tamaño (FsCheck)
    - **Property 2: File size integrity verification**
    - Generar pares (actual_size, expected_size) con valores long aleatorios
    - Verificar que la verificación pasa si y solo si actual_size == expected_size
    - **Validates: Requirements 4.3**

- [x] 9. Cliente Tray - UI y wiring
  - [x] 9.1 Agregar toggle de auto-update en la pantalla de configuración del Tray
    - Agregar CheckBox "Habilitar Actualizaciones Automáticas" en la UI de settings (XAML)
    - Binding bidireccional que lee/escribe via `RegistryConfigManager.LoadAutoUpdateEnabled()` / `SaveAutoUpdateEnabled()`
    - _Requirements: 1.1, 1.2_

  - [x] 9.2 Integrar UpdateChecker + UpdateDownloader + Named Pipe en startup del Tray
    - En el flujo de inicio del Tray, instanciar `UpdateChecker` con la configuración actual
    - Suscribirse al evento `UpdateAvailable` para iniciar descarga con `UpdateDownloader`
    - Al completar descarga exitosa, enviar mensaje `InstallUpdate` via Named Pipe al Service
    - Loggear inicio y fin de descarga con tamaño y duración
    - _Requirements: 3.4, 4.1, 5.1, 11.2_

- [x] 10. Checkpoint - Verificar que cliente C# compila correctamente
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Frontend - Panel de administración de actualizaciones
  - [x] 11.1 Crear página de admin updates en /dashboard/admin/updates
    - Crear archivo `src/app/dashboard/admin/updates/page.tsx`
    - Definir interface `UpdateInfo` con version, buildDate, commitHash, fileSize, autoUpdateEnabled
    - Llamar GET /api/v1/updates/check para obtener información del MSI actual
    - Mostrar card con versión, fecha de build, commit hash
    - Implementar toggle para habilitar/deshabilitar auto-updates de la organización
    - Al toggle, llamar PATCH /api/v1/organizations/{org_id}/auto-update
    - Mostrar diálogo de confirmación antes de habilitar auto-updates
    - Usar TypeScript estricto (no `any`), componentes de `components/ui/`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

- [x] 12. Final checkpoint - Verificar integración completa
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Las tareas marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido
- Cada tarea referencia requisitos específicos para trazabilidad
- Los checkpoints aseguran validación incremental entre capas
- Los property tests validan propiedades universales de correctitud definidas en el diseño
- Los unit tests validan ejemplos específicos y edge cases
- Todos los comentarios y mensajes de log deben estar en español (AGENTS.md)
- Importar Base siempre desde `app.core.database` (no `app.db`)
- Usar `AlwaysPrintLogger` para todos los logs del cliente (no `Console.WriteLine`)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "2.1"] },
    { "id": 1, "tasks": ["1.3", "3.1", "7.1"] },
    { "id": 2, "tasks": ["4.1", "4.2", "4.3", "7.2", "8.1"] },
    { "id": 3, "tasks": ["4.4", "7.3", "7.4", "8.2"] },
    { "id": 4, "tasks": ["6.1", "6.2", "6.3", "8.3", "8.4", "9.1"] },
    { "id": 5, "tasks": ["9.2", "11.1"] }
  ]
}
```
