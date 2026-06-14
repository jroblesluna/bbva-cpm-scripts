# Implementation Plan: Zero Query Updates

## Overview

Eliminar el thundering herd causado por el broadcast de `check_update` a N workstations (N > 30) enriqueciendo el mensaje WebSocket con una presigned URL de S3, versión y tamaño del archivo. Las workstations descargan directamente desde S3 sin queries al backend. El flujo legacy se preserva para clientes antiguos y como fallback ante errores S3.

## Tasks

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Broadcast check_update sin download_url genera N queries al backend
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists (broadcast sin presigned URL)
  - **Scoped PBT Approach**: Scope the property to the concrete failing case: broadcast `check_update` con `auto_update_enabled=true` y MSI disponible en S3 → params DEBE incluir `download_url`, `version`, `file_size`
  - **Backend test (pytest)**: Testear que `send_org_command` / `toggle_auto_update` con `command_type="check_update"` genera mensaje WebSocket con `params.download_url` presente
  - **Bug Condition from design**: `isBugCondition(X) = X.command_type = "check_update" AND X.params.download_url IS NULL AND X.target_count > pool_size`
  - **Expected Behavior from design**: `result.params.download_url IS NOT NULL AND result.params.version IS NOT NULL AND result.params.file_size > 0`
  - **Archivo test**: `AlwaysPrintProject/Cloud/backend/tests/test_zero_query_broadcast.py`
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (params actualmente es `{}` vacío, confirma que el bug existe)
  - Document counterexamples found: broadcast a N workstations genera params vacío → cada workstation debe llamar individualmente al backend
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Flujo legacy y timer 24h sin cambios
  - **IMPORTANT**: Follow observation-first methodology
  - **Client test (FsCheck+NUnit)**: Generar combinaciones de (presencia download_url, flag org, flag local) y verificar decisión correcta
  - **Archivo test client**: `AlwaysPrintProject/Client/AlwaysPrint.Tests/Updates/ZeroQueryPreservationTests.cs`
  - **Archivo test backend**: `AlwaysPrintProject/Cloud/backend/tests/test_zero_query_preservation.py`
  - Observe on UNFIXED code:
    - Workstation recibe `check_update` con `params: {}` → dispara flujo HTTP legacy (`CheckUpdateRequested` event)
    - Timer 24h ejecuta `CheckNowAsync()` → llama a `/api/v1/updates/check` via HTTP
    - Con `auto_update_enabled=false` → no se inicia descarga
    - Con flag local deshabilitado → se ignora el comando completamente
  - Write property-based tests:
    - **FsCheck**: Para todo comando `check_update` SIN campo `download_url` en params, el CloudManager DEBE disparar el evento `CheckUpdateRequested` (flujo legacy)
    - **FsCheck**: Para todo comando `check_update` con `auto_update_enabled=false` (org o local), NO se debe iniciar descarga independientemente de `download_url`
    - **pytest**: Verificar que endpoints `/api/v1/updates/check` y `/api/v1/updates/download` siguen funcionando sin cambios para requests individuales
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (confirma baseline de comportamiento a preservar)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3. Fix para zero-query updates (broadcast con presigned URL)

  - [x] 3.1 Implementar S3UpdateService para generación de presigned URL
    - Crear/modificar `app/services/s3_update_service.py`
    - Método `get_msi_metadata(target_version: str | None) -> dict` que retorna `{version, file_size, s3_key}`
    - Método `generate_download_url(s3_key: str, expires_in: int = 3600) -> str` que genera presigned URL via boto3
    - Respetar `target_version` de la organización si está configurada
    - Manejo de errores: si S3 falla, retornar `None` (permite fallback)
    - Comentarios en español
    - _Bug_Condition: isBugCondition(X) where X.params.download_url IS NULL_
    - _Expected_Behavior: generate presigned URL con expiración 3600s_
    - _Preservation: Si S3 falla, retornar None → fallback a params vacío (flujo legacy)_
    - _Requirements: 2.1, 2.4_

  - [x] 3.2 Enriquecer broadcast check_update en organizations.py
    - Modificar `toggle_auto_update` y `send_org_command` en `app/api/v1/endpoints/organizations.py`
    - Cuando `command_type == "check_update"` y `auto_update_enabled == True`:
      - Llamar a `S3UpdateService.get_msi_metadata(org.target_version)`
      - Generar presigned URL via `S3UpdateService.generate_download_url()`
      - Incluir `download_url`, `version`, `file_size` en params del mensaje WebSocket
    - Si S3 falla: enviar comando con params vacío (fallback a legacy) + log warning
    - Comentarios en español
    - _Bug_Condition: broadcast check_update a N workstations con params vacío_
    - _Expected_Behavior: params incluye download_url, version, file_size_
    - _Preservation: Si S3 falla → fallback a params vacío (comportamiento legacy)_
    - _Requirements: 2.1, 2.3, 2.4_

  - [x] 3.3 Enriquecer broadcast check_update en vlans.py
    - Modificar `send_vlan_command` en `app/api/v1/endpoints/vlans.py`
    - Misma lógica que 3.2: cuando `command_type == "check_update"`, generar presigned URL e incluir en params
    - Si S3 falla: enviar comando con params vacío (fallback) + log warning
    - Comentarios en español
    - _Bug_Condition: broadcast check_update por VLAN con params vacío_
    - _Expected_Behavior: params incluye download_url, version, file_size_
    - _Preservation: Si S3 falla → fallback a params vacío_
    - _Requirements: 2.1, 2.3, 2.4_

  - [x] 3.4 Manejar download_url en CloudManager.cs (Client)
    - Modificar `HandleCheckUpdateCommand` en `AlwaysPrintTray/Cloud/CloudManager.cs`
    - Parsear campo `params` del JSON del comando WebSocket
    - Si `download_url` está presente Y no vacío:
      - Verificar `auto_update_enabled` (organización) Y flag local (`LoadAutoUpdateEnabled()`)
      - Si ambos habilitados: invocar `UpdateDownloader.DownloadFromUrlAsync(downloadUrl, fileSize, version)`
      - Si alguno deshabilitado: loggear y no proceder
    - Si `download_url` ausente o vacío: mantener comportamiento actual (disparar `CheckUpdateRequested`)
    - Comentarios en español
    - _Bug_Condition: workstation recibe check_update sin download_url → llama a backend_
    - _Expected_Behavior: con download_url presente, descargar directamente de S3_
    - _Preservation: sin download_url, disparar CheckUpdateRequested (flujo legacy intacto)_
    - _Requirements: 2.2, 3.1, 3.3, 3.5_

  - [x] 3.5 Implementar DownloadFromUrlAsync en UpdateDownloader.cs (Client)
    - Agregar método `DownloadFromUrlAsync(string downloadUrl, long expectedSize, string version)` en `AlwaysPrintTray/Cloud/UpdateDownloader.cs`
    - Descargar MSI directamente desde la presigned URL de S3 (HttpClient GET)
    - Verificar tamaño descargado vs `expectedSize`
    - Si presigned URL expirada (HTTP 403 de S3): loggear warning y hacer fallback disparando `CheckUpdateRequested`
    - Si descarga exitosa: proceder con instalación (misma lógica que `DownloadAsync` existente)
    - Comentarios en español
    - _Bug_Condition: N workstations descargando vía backend → saturación_
    - _Expected_Behavior: descarga directa desde S3, cero queries a BD_
    - _Preservation: Si URL expirada → fallback a flujo legacy via CheckUpdateRequested_
    - _Requirements: 2.2, 2.3, 3.1_

  - [x] 3.6 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Broadcast check_update incluye presigned URL
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior (params debe incluir download_url, version, file_size)
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed - broadcast ahora incluye presigned URL)
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 3.7 Verify preservation tests still pass
    - **Property 2: Preservation** - Flujo legacy y flags sin regresiones
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all preservation tests still pass after fix:
      - Clientes sin download_url siguen usando flujo HTTP legacy
      - Timer 24h sigue funcionando sin cambios
      - Flags de auto-update siguen siendo respetados
      - Endpoints individuales siguen funcionando

- [x] 4. Checkpoint - Ensure all tests pass
  - Ejecutar suite completa de tests backend: `pytest tests/test_zero_query_*.py`
  - Ejecutar suite completa de tests client: `dotnet test` (FsCheck + NUnit)
  - Verificar que NO hay regresiones en tests existentes
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tests de bug condition (Property 1) deben ejecutarse ANTES del fix y FALLAR para confirmar el bug
- Tests de preservation (Property 2) deben ejecutarse ANTES del fix y PASAR para confirmar baseline
- Backend usa pytest para property tests; Client usa FsCheck+NUnit
- Fallback a flujo legacy es el mecanismo de seguridad: si S3 falla o URL expira, comportamiento legacy intacto
- Comentarios y logs en español según convención del proyecto
- Importar `Base` desde `app.core.database` (no `app.db`)
- La presigned URL tiene expiración de 3600 segundos (1 hora)
- El `target_version` de la organización se respeta al generar la URL

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "3.4"] },
    { "id": 4, "tasks": ["3.5"] },
    { "id": 5, "tasks": ["3.6", "3.7"] },
    { "id": 6, "tasks": ["4"] }
  ]
}
```
