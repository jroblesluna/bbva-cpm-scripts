# Zero Query Updates - Bugfix Design

## Overview

El bug actual causa un "thundering herd" cuando un admin envía `check_update` a N workstations (N > 30): todas llaman simultáneamente a `/api/v1/updates/check` y `/api/v1/updates/download`, saturando el pool de conexiones a BD (30 max) y provocando que NINGUNA workstation se actualice.

El fix consiste en enriquecer el mensaje WebSocket `check_update` con una presigned URL de S3, versión y tamaño del archivo, permitiendo a las workstations descargar directamente desde S3 sin hacer queries al backend. El backend genera UNA sola presigned URL y la incluye en el broadcast, eliminando completamente la carga sobre la BD durante actualizaciones masivas.

## Glossary

- **Bug_Condition (C)**: Comando `check_update` enviado a N workstations (N > pool_size) sin incluir `download_url` en los params, forzando a cada workstation a llamar al backend individualmente
- **Property (P)**: El mensaje WebSocket `check_update` incluye `download_url`, `version` y `file_size`, permitiendo descarga directa desde S3 sin queries al backend
- **Preservation**: El flujo legacy (timer 24h, clientes sin soporte de `download_url`, descarga individual vía `/updates/download`) debe seguir funcionando sin cambios
- **S3UpdateService**: Servicio en `app/services/s3_update_service.py` que interactúa con el bucket S3 para metadata y generación de presigned URLs
- **CloudManager**: Clase en `AlwaysPrintTray/Cloud/CloudManager.cs` que gestiona la conexión WebSocket y despacha comandos remotos
- **UpdateChecker**: Clase en `AlwaysPrintTray/Cloud/UpdateChecker.cs` que verifica actualizaciones vía HTTP GET a `/updates/check`
- **UpdateDownloader**: Clase en `AlwaysPrintTray/Cloud/UpdateDownloader.cs` que descarga el MSI desde `/updates/download`
- **connection_manager**: Instancia de `WebSocketManager` que gestiona las conexiones WebSocket activas y permite broadcast por organización

## Bug Details

### Bug Condition

El bug se manifiesta cuando un administrador envía el comando `check_update` a múltiples workstations simultáneamente (típicamente 303 en producción). El mensaje WebSocket actual solo contiene `{"type": "command", "command_type": "check_update", "params": {}}`, lo que obliga a cada workstation a:
1. Llamar a `GET /api/v1/updates/check` (1 query BD por workstation)
2. Llamar a `GET /api/v1/updates/download` (1 query BD + streaming S3 por workstation)

Con 303 workstations simultáneas, se generan ~606 queries a BD contra un pool de 30 conexiones.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type BroadcastCheckUpdateCommand
  OUTPUT: boolean
  
  RETURN input.command_type = "check_update"
         AND input.params.download_url IS NULL
         AND input.target_workstation_count > 30
         AND input.auto_update_enabled = TRUE
END FUNCTION
```

### Examples

- Admin activa auto-update para organización con 303 workstations → 303 llamadas simultáneas a `/updates/check` → pool saturado → timeouts → 0 workstations actualizadas
- Admin envía `check_update` via endpoint `/organizations/{id}/command?command_type=check_update` → mismo resultado
- Admin envía `check_update` via endpoint `/vlans/{id}/command?command_type=check_update` a VLAN con 50 workstations → 50 llamadas simultáneas → pool parcialmente saturado → algunas workstations fallan
- Caso edge: organización con 5 workstations → 5 llamadas simultáneas → funciona correctamente pero ineficiente

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Verificación periódica (timer 24h) de `UpdateChecker` debe seguir llamando a `/api/v1/updates/check` normalmente
- Workstations que reciben `check_update` SIN campo `download_url` (clientes antiguos) deben seguir usando el flujo HTTP legacy
- El flag `auto_update_enabled` de la organización debe seguir respetándose
- El flag local de auto-actualización (`LoadAutoUpdateEnabled()`) debe seguir respetándose
- El endpoint `/api/v1/updates/download` debe seguir funcionando para descargas individuales
- El endpoint `/api/v1/updates/check` debe seguir funcionando para verificaciones individuales
- Descarga directa vía `/updates/download/{version}` (admin) sigue sin cambios

**Scope:**
Todos los inputs que NO involucren un broadcast masivo de `check_update` con `download_url` deben ser completamente no afectados:
- Timer 24h del UpdateChecker
- Comandos `restart_service` y `restart_tray`
- Verificaciones manuales de actualización desde el frontend
- Descarga individual desde el panel de admin

## Hypothesized Root Cause

Based on the bug description, the most likely issues are:

1. **Diseño original sin consideración de escala**: El flujo fue diseñado para verificación individual (timer 24h por workstation), no para broadcast masivo simultáneo. El `check_update` command simplemente dispara `UpdateChecker.CheckNowAsync()` que llama a HTTP endpoints.

2. **Ausencia de información en el mensaje WebSocket**: El mensaje `check_update` actual tiene `"params": {}` vacío. No hay razón técnica para no incluir la metadata de la actualización directamente en el mensaje, evitando el round-trip HTTP.

3. **Patrón thundering herd no mitigado**: Los endpoints `send_org_command` y `toggle_auto_update` disparan el comando a TODAS las workstations online sin rate limiting, jitter, o pre-cómputo de la URL.

4. **Streaming directo del MSI**: El endpoint `/updates/download` hace streaming del MSI a través del backend (proxy de S3), retiene una conexión de BD durante el setup y una conexión HTTP durante toda la descarga. Con N descargas simultáneas, el backend se convierte en bottleneck.

## Correctness Properties

Property 1: Bug Condition - Presigned URL incluida en broadcast check_update

_For any_ broadcast de `check_update` a una organización donde `auto_update_enabled` es true y existe un MSI en S3, el backend SHALL incluir `download_url`, `version` y `file_size` en los params del mensaje WebSocket, y la `download_url` SHALL ser una presigned URL de S3 válida con expiración de 3600 segundos.

**Validates: Requirements 2.1, 2.4**

Property 2: Bug Condition - Descarga directa sin queries al backend

_For any_ workstation que recibe un comando `check_update` con campo `download_url` presente y válido, Y cuyo flag local y de organización de auto-update están habilitados, la workstation SHALL descargar el MSI directamente desde la presigned URL sin llamar a `/api/v1/updates/check` ni `/api/v1/updates/download`.

**Validates: Requirements 2.2, 2.3**

Property 3: Preservation - Backward compatibility para clientes sin soporte download_url

_For any_ workstation que recibe un comando `check_update` SIN campo `download_url` (clientes antiguos), la workstation SHALL ejecutar el flujo HTTP legacy completo (llamar a `/updates/check` y luego `/updates/download`), preservando el comportamiento idéntico al código sin fix.

**Validates: Requirements 3.1**

Property 4: Preservation - Timer periódico de 24 horas sin cambios

_For any_ ejecución del timer periódico de `UpdateChecker` (cada 24 horas), el comportamiento SHALL ser idéntico al código original: llamar a `/api/v1/updates/check` vía HTTP y proceder con el flujo estándar.

**Validates: Requirements 3.2**

Property 5: Preservation - Flags de auto-update respetados

_For any_ workstation que recibe `check_update` con `download_url`, si el flag `auto_update_enabled` de la organización es false O el flag local está deshabilitado, la workstation SHALL NOT iniciar la descarga.

**Validates: Requirements 3.3, 3.5**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `AlwaysPrintProject/Cloud/backend/app/api/v1/endpoints/organizations.py`

**Functions**: `toggle_auto_update`, `send_org_command`

**Specific Changes**:
1. **Generar presigned URL antes del broadcast**: Cuando `command_type == "check_update"`, obtener metadata del MSI via `S3UpdateService.get_msi_metadata()` y generar presigned URL via `S3UpdateService.generate_download_url(expires_in=3600)`. Respetar `target_version` de la organización si está configurada.
2. **Enriquecer params del mensaje WebSocket**: Incluir `download_url`, `version` y `file_size` en el campo `params` del comando:
   ```python
   "params": {
       "download_url": presigned_url,
       "version": msi_metadata['version'],
       "file_size": msi_metadata['file_size'],
   }
   ```
3. **Manejo de errores S3**: Si falla la generación de presigned URL (S3 no disponible), enviar el comando sin `download_url` (fallback al flujo legacy) y loggear warning.

**File**: `AlwaysPrintProject/Cloud/backend/app/api/v1/endpoints/vlans.py`

**Function**: `send_vlan_command`

**Specific Changes**:
4. **Mismo enriquecimiento de params para commands por VLAN**: Aplicar la misma lógica de generación de presigned URL cuando `command_type == "check_update"`.

**File**: `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/CloudManager.cs`

**Function**: `HandleCheckUpdateCommand`

**Specific Changes**:
5. **Extraer params del comando**: Parsear el campo `params` del JSON del comando para buscar `download_url`, `version` y `file_size`.
6. **Bifurcar flujo según presencia de download_url**:
   - Si `download_url` está presente: verificar flags de auto-update, y si habilitados, invocar descarga directa via `UpdateDownloader` modificado.
   - Si `download_url` está ausente: mantener comportamiento actual (disparar `CheckUpdateRequested` event).

**File**: `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/UpdateDownloader.cs`

**Function**: Nuevo overload `DownloadFromUrlAsync`

**Specific Changes**:
7. **Nuevo método de descarga directa**: Agregar método `DownloadFromUrlAsync(string downloadUrl, long expectedSize, string version)` que descarga directamente desde una URL arbitraria (presigned URL de S3) sin pasar por el backend.
8. **Reusar lógica de verificación de integridad**: Comparar tamaño descargado vs `expectedSize` (mismo patrón que `DownloadAsync`).
9. **Manejo de errores específicos**: Si la presigned URL ha expirado (HTTP 403 de S3), loggear y hacer fallback al flujo legacy via `CheckUpdateRequested`.

## Testing Strategy

### Validation Approach

La estrategia de testing sigue un enfoque de dos fases: primero, demostrar el bug con counterexamples en código sin fix, luego verificar que el fix funciona y preserva el comportamiento existente.

### Exploratory Bug Condition Checking

**Goal**: Demostrar que el broadcast actual de `check_update` genera N queries al backend cuando N > 30.

**Test Plan**: Simular el envío de `check_update` a múltiples workstations y medir las llamadas HTTP generadas contra el backend. Ejecutar en código sin fix para confirmar el thundering herd.

**Test Cases**:
1. **Broadcast a 50 workstations**: Verificar que se generan 50 llamadas simultáneas a `/updates/check` (fallará en código sin fix porque el pool se satura)
2. **Verificar saturación de pool**: Con 50+ workstations, confirmar que el backend retorna timeouts de BD
3. **Broadcast sin download_url**: Verificar que el mensaje actual tiene `"params": {}` vacío (confirmado en código fuente)
4. **Medición de queries por broadcast**: Contar queries a BD generadas por un broadcast a N workstations

**Expected Counterexamples**:
- N queries a BD por broadcast de N workstations (en vez de 0)
- Timeouts de conexión cuando N > 30
- Posible causa confirmada: `params` vacío en mensaje WebSocket

### Fix Checking

**Goal**: Verificar que para todos los broadcasts de `check_update`, el mensaje incluye `download_url` y las workstations descargan directamente desde S3.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := broadcast_check_update_fixed(input)
  ASSERT result.params.download_url IS NOT NULL
  ASSERT result.params.download_url STARTS WITH "https://"
  ASSERT result.params.version IS NOT NULL
  ASSERT result.params.file_size > 0
  ASSERT backend_db_queries_during_download(result) = 0
END FOR
```

### Preservation Checking

**Goal**: Verificar que para todos los inputs que NO son broadcast masivo de `check_update`, el comportamiento es idéntico al código original.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT F(input) = F'(input)
  // Timer 24h sigue llamando a /updates/check via HTTP
  // Clientes sin download_url siguen usando flujo legacy
  // Flags de auto-update siguen siendo respetados
END FOR
```

**Testing Approach**: Property-based testing recomendado para preservation checking porque:
- Genera muchas combinaciones de inputs (con/sin download_url, flags on/off, versiones diversas)
- Detecta edge cases que unit tests manuales pueden omitir (URL expirada, S3 error, campo parcial)
- Garantiza fuertemente que el comportamiento legacy no cambia

**Test Plan**: Observar comportamiento en código sin fix para timer 24h y comandos individuales, luego escribir tests que verifiquen que ese comportamiento se preserva.

**Test Cases**:
1. **Preservación timer 24h**: Verificar que UpdateChecker.CheckNowAsync() sigue llamando a HTTP `/updates/check` sin cambios
2. **Preservación flag organización**: Verificar que con `auto_update_enabled=false`, no se inicia descarga aunque `download_url` esté presente
3. **Preservación flag local**: Verificar que con flag local deshabilitado, se ignora el comando completamente
4. **Preservación clientes legacy**: Verificar que sin `download_url` en params, el flujo HTTP legacy se ejecuta completo
5. **Preservación endpoint /updates/download individual**: Verificar que descargas individuales (no broadcast) siguen funcionando

### Unit Tests

- Test generación de presigned URL en backend al hacer broadcast `check_update`
- Test que params contiene `download_url`, `version`, `file_size` cuando auto_update habilitado
- Test que params está vacío (fallback) si S3 falla al generar URL
- Test que `target_version` de la organización se respeta al generar la URL
- Test parseo de `download_url` en CloudManager.HandleCheckUpdateCommand
- Test descarga directa desde URL en UpdateDownloader.DownloadFromUrlAsync
- Test fallback a flujo legacy cuando presigned URL ha expirado (HTTP 403)
- Test que flags de auto-update se verifican antes de descargar

### Property-Based Tests

- Generar combinaciones aleatorias de (N workstations, auto_update flag, target_version, S3 disponible) y verificar que el broadcast siempre incluye download_url cuando S3 está disponible
- Generar combinaciones de (presencia download_url, flag org, flag local, versión instalada) y verificar que la workstation toma la decisión correcta (descargar, ignorar, o flujo legacy)
- Generar URLs con distintos estados (válida, expirada, malformada) y verificar manejo correcto de errores

### Integration Tests

- Test end-to-end: admin toggle auto-update → backend genera presigned URL → WebSocket broadcast con download_url → workstation descarga de S3 sin queries a BD
- Test end-to-end con clientes legacy: broadcast con download_url pero cliente antiguo sin soporte → cliente usa flujo HTTP legacy sin errores
- Test de expiración: generar URL, esperar expiración, verificar que workstation hace fallback a flujo legacy
- Test de concurrencia: 50 workstations descargando simultáneamente desde la misma presigned URL de S3 → todas completan exitosamente sin impactar al backend
