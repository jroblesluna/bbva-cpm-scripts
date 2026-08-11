# Implementation Plan: Reconnection Reliability Fixes

## Overview

Implementación de 4 fixes independientes de fiabilidad que afectan la reconexión WebSocket, auto-actualización MSI, soporte de proxy en health checks, y manejo tolerante de servicios inexistentes. Cada fix es mínimo y modifica solo las líneas necesarias en su componente respectivo.

**Lenguajes**: C# (.NET 4.8) para cliente Windows, Python 3.12 para backend FastAPI.

## Tasks

- [x] 1. Fix MSI version check in PushMessageHandler.SyncFromStateAsync
  - [x] 1.1 Implementar comparación semántica de versiones MSI en SyncFromStateAsync
    - Modificar `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/PushMessageHandler.cs`
    - Reemplazar comparación string de `MsiVersion` por comparación semántica con `Version.TryParse`
    - Usar `localVer >= remoteVer` para evitar downgrades involuntarios
    - Si `Version.TryParse` falla en cualquier lado, caer a comparación string (fallback)
    - Si `MsiVersion` es más nueva pero `MsiUrl` es null, loguear warning sin intentar descarga
    - Todos los comentarios en español
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [x] 1.2 Escribir tests unitarios para comparación de versiones MSI
    - Verificar que "1.2.3" vs local "1.2.3.0" se compara semánticamente (match)
    - Verificar que "1.3.0" vs local "1.2.3.0" dispara descarga
    - Verificar que "1.1.0" vs local "1.2.3.0" NO dispara descarga (no downgrade)
    - Verificar que MsiVersion más nueva con MsiUrl null genera warning log
    - Verificar que MsiVersion igual a la local no dispara descarga
    - _Requirements: 1.1, 1.2, 1.4, 1.5_

- [x] 2. Fix proxy support in DomainHealthChecker HttpClient
  - [x] 2.1 Inicializar HttpClient con ProxyHelper.CreateHandler() en DomainHealthChecker
    - Modificar `AlwaysPrintProject/Client/AlwaysPrintTray/Bootstrap/DomainHealthChecker.cs`
    - Cambiar inicialización de `_http` para usar `new HttpClient(ProxyHelper.CreateHandler(), disposeHandler: false)`
    - Agregar `using AlwaysPrintTray.Cloud;` si no existe (ProxyHelper está en ese namespace)
    - Mantener `Timeout = TimeSpan.FromSeconds(TimeoutSecs)` sin cambios
    - Todos los comentarios en español
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 2.2 Verificar que DomainHealthChecker.Http tiene proxy configurado
    - Test: `DomainHealthChecker.Http` no es null después de inicialización
    - Smoke test: `CheckAll()` funciona correctamente con dominio alcanzable
    - _Requirements: 2.1, 2.2_

- [x] 3. Fix WebSocket register race condition (Backend + Cliente)
  - [x] 3.1 Agregar asyncio.wait_for con timeout 10s en endpoint WebSocket del backend
    - Modificar `AlwaysPrintProject/Cloud/backend/app/api/v1/websocket/workstation.py`
    - Envolver `await websocket.receive_json()` con `asyncio.wait_for(..., timeout=10.0)`
    - En caso de `asyncio.TimeoutError`, cerrar conexión con código 1008 y reason "Timeout esperando mensaje de registro"
    - Agregar `import asyncio` si no existe
    - Todos los comentarios en español
    - _Requirements: 3.1, 3.2, 3.5_

  - [x] 3.2 Agregar delay post-registro en CloudWebSocketClient.ConnectInternalAsync
    - Modificar `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/CloudWebSocketClient.cs`
    - Después de `Connected?.Invoke()` y antes de `ReceiveLoopAsync`, agregar `await Task.Delay(100, token).ConfigureAwait(false)`
    - Esto garantiza que el SendAsync del register se complete antes de entrar al receive loop
    - Todos los comentarios en español
    - _Requirements: 3.3, 3.4_

  - [x] 3.3 Escribir test del timeout de registro en el backend
    - Test: Conectar WebSocket sin enviar nada → verificar close con código 1008 tras ~10s
    - Test: Conectar WebSocket y enviar register dentro de 10s → flujo normal
    - Test: Enviar mensaje no-register como primer mensaje → close 1008
    - _Requirements: 3.1, 3.2, 3.5_

- [x] 4. Handle non-existent services gracefully in AdminActions
  - [x] 4.1 Agregar método helper IsServiceNotFound y catch en StopService
    - Modificar `AlwaysPrintProject/Client/AlwaysPrintService/Actions/AdminActions.cs`
    - Agregar método privado estático `IsServiceNotFound(InvalidOperationException ex)` que verifica `Win32Exception.NativeErrorCode == 1060`
    - Agregar fallback por string matching para edge cases de localización
    - Agregar `catch (InvalidOperationException ex) when (IsServiceNotFound(ex))` en `StopService`
    - Loguear warning con `AlwaysPrintLogger.WriteWarning` y retornar `true` (nada que detener)
    - Todos los comentarios en español
    - _Requirements: 4.1, 4.3, 4.4_

  - [x] 4.2 Agregar catch análogo en StartService para servicios inexistentes
    - Modificar `AlwaysPrintProject/Client/AlwaysPrintService/Actions/AdminActions.cs`
    - Mismo patrón de `catch (InvalidOperationException ex) when (IsServiceNotFound(ex))`
    - Loguear warning y retornar `true` (el estado deseado "servicio iniciado" no aplica si no existe)
    - Todos los comentarios en español
    - _Requirements: 4.2, 4.3, 4.4_

  - [x] 4.3 Escribir tests unitarios para manejo de servicios inexistentes
    - Test: `StopService("ServicioInexistente")` retorna `true`
    - Test: `StartService("ServicioInexistente")` retorna `true`
    - Test: `IsServiceNotFound` con `Win32Exception(1060)` retorna `true`
    - Test: `IsServiceNotFound` con `Win32Exception(5)` (access denied) retorna `false`
    - Test: Verificar que ActionEngine continúa ejecución después de servicio no encontrado
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 5. Checkpoint — Verificar compilación y tests
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marcados con `*` son opcionales y pueden ser omitidos para un MVP rápido
- Cada fix es independiente — pueden implementarse en paralelo sin conflictos
- El código C# está en `AlwaysPrintProject/Client/` (proyectos AlwaysPrintTray y AlwaysPrintService)
- El código Python está en `AlwaysPrintProject/Cloud/backend/`
- PBT (Property-Based Testing) NO es apropiado para estos fixes (error handling, timing, infra config)
- Todos los comentarios y mensajes de log deben estar en español
- Se preservan todas las verificaciones y protecciones existentes (impact-analysis)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "3.1", "3.2", "4.1"] },
    { "id": 1, "tasks": ["1.2", "2.2", "3.3", "4.2"] },
    { "id": 2, "tasks": ["4.3"] }
  ]
}
```
