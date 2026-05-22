# Implementation Plan: Contingency IP Resolution Bugfix

## Overview

Fix para tres bugs interrelacionados en la activación de contingencia forzada: (1) backend envía `printer_ip: null` cuando no hay IP resoluble, (2) frontend permite activar contingencia VLAN sin dispositivos, y (3) no se bloquea desactivación individual bajo contingencia VLAN. La estrategia sigue el workflow exploratorio: primero escribir tests que demuestren el bug, luego tests de preservación, implementar el fix, y verificar.

## Tasks

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Activación de contingencia sin IP resoluble
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: Scope the property to concrete failing cases:
    - Workstation sin `default_printer_id` en VLAN sin dispositivos activos → `PATCH /workstations/{id}/forced-contingency?enabled=true`
    - Verificar que `forced_contingency` NO se persiste en BD cuando IP es null
    - Desactivación individual (`enabled=false`) cuando VLAN tiene `forced_contingency=true`
  - Test assertions (Expected Behavior):
    - Para activación sin IP: endpoint retorna HTTP 400, `workstation.forced_contingency` permanece `false`, no se envía mensaje WebSocket
    - Para desactivación bajo VLAN forzada: endpoint retorna HTTP 409, estado no cambia
    - Para cliente con `printer_ip=null` y `enabled=true`: NO ejecuta `OnContingencyActivated`
  - Bug Condition from design: `isBugCondition(input)` where `resolveIP(workstation) == null` AND `enabled == true`, OR `enabled == false` AND `workstation.vlan.forced_contingency == true`
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists: endpoint returns 200 instead of 400, state persists, message sent with null IP)
  - Document counterexamples found:
    - `toggle_workstation_forced_contingency(ws_sin_ip, enabled=true)` → returns 200, persists `forced_contingency=true`, sends `printer_ip: null`
    - `OnForcedContingencyReceived(enabled=true, printerIp=null)` → executes `OnContingencyActivated` without setting variable
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.4, 2.1, 2.4_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Comportamiento sin cambios para inputs no-buggy
  - **IMPORTANT**: Follow observation-first methodology
  - Observe behavior on UNFIXED code for non-buggy inputs:
    - Observe: `toggle_workstation_forced_contingency(ws_con_ip, enabled=true)` returns 200 with valid `printer_ip`
    - Observe: `toggle_workstation_forced_contingency(ws, enabled=false)` returns 200 and sends deactivation message
    - Observe: `OnForcedContingencyReceived(enabled=true, printerIp="10.0.1.50")` sets variable and executes `OnContingencyActivated`
    - Observe: `toggle_vlan_forced_contingency(vlan_con_devices, enabled=true)` returns 200
  - Write property-based tests capturing observed behavior patterns:
    - For all workstations with valid `resolveIP()` (non-null): activation returns 200, persists state, sends WebSocket with resolved IP
    - For all deactivation requests (`enabled=false`): always returns 200 and sends deactivation message regardless of device availability
    - For all client messages with valid non-empty `printer_ip`: sets `contingency_printer_ip` variable and executes `OnContingencyActivated`
    - For all VLANs with active devices: contingency activation returns 200
    - For all workstations whose VLAN does NOT have `forced_contingency=true`: individual toggle remains permitted
  - Preservation Requirements from design: activación con IP válida, desactivación siempre permitida, toggle individual sin contingencia VLAN, botón VLAN con dispositivos, cliente con IP válida
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3. Fix for contingency IP resolution bugs

  - [x] 3.1 Backend: Validar IP antes de commit en `workstations.py`
    - Mover resolución de `printer_ip` ANTES de `db.commit()`
    - Si `enabled=true` y `printer_ip` es `None`, retornar HTTP 400 con mensaje: "No se puede activar contingencia: no hay dispositivo de impresión disponible"
    - No modificar `workstation.forced_contingency` ni hacer commit si la validación falla
    - _Bug_Condition: isBugCondition(input) where input.type == "workstation_activation" AND resolveIP(workstation) == null_
    - _Expected_Behavior: HTTP 400, no state change, no WebSocket message_
    - _Preservation: Activación con IP válida sigue retornando 200 con printer_ip correcto_
    - _Requirements: 1.1, 1.4, 2.1, 3.1_

  - [x] 3.2 Backend: Bloquear desactivación individual bajo contingencia VLAN en `workstations.py`
    - Si `enabled=false` y la VLAN de la workstation tiene `forced_contingency=true`, retornar HTTP 409 (Conflict)
    - Mensaje: "No se puede desactivar contingencia individual: la VLAN tiene contingencia forzada activa"
    - Consultar estado de la VLAN: `db.query(VLAN).filter(VLAN.id == workstation.vlan_id).first()`
    - _Bug_Condition: isBugCondition(input) where input.type == "workstation_deactivation" AND workstation.vlan.forced_contingency == true_
    - _Expected_Behavior: HTTP 409, no state change_
    - _Preservation: Desactivación sin VLAN forzada sigue permitida_
    - _Requirements: 1.3, 2.3, 3.2, 3.3_

  - [x] 3.3 Backend: Incluir `printer_ip` en mensaje VLAN y rechazar sin dispositivos en `vlans.py`
    - Si `enabled=true`, verificar que hay al menos un dispositivo activo en la VLAN antes de commit
    - Si no hay dispositivos activos, retornar HTTP 400: "No se puede activar contingencia VLAN: no hay dispositivos activos configurados"
    - Al enviar mensaje WebSocket a cada workstation, resolver `printer_ip` (desde `default_printer_id` de cada ws o primer dispositivo activo de la VLAN) e incluirla en el mensaje
    - _Bug_Condition: countActiveDevices(vlan) == 0 AND enabled == true_
    - _Expected_Behavior: HTTP 400 when no devices, message includes printer_ip when devices exist_
    - _Preservation: Activación VLAN con dispositivos sigue funcionando normalmente_
    - _Requirements: 2.2, 3.4_

  - [x] 3.4 Frontend: Deshabilitar botón contingencia VLAN sin dispositivos en `vlans/page.tsx`
    - Obtener conteo de dispositivos activos por VLAN (query adicional o incluir en datos existentes)
    - Agregar prop `disabled` al botón `ShieldAlert` cuando `activeDeviceCount === 0`
    - Agregar tooltip internacionalizado con key `vlans.contingencyNoDevices`
    - Estilo visual: botón gris cuando deshabilitado, cursor `not-allowed`
    - Agregar keys en `messages/es.json`: `"contingencyNoDevices": "No hay dispositivos activos configurados para contingencia"`
    - Agregar keys en `messages/en.json`: `"contingencyNoDevices": "No active devices configured for contingency"`
    - _Bug_Condition: VLAN sin dispositivos activos muestra botón habilitado_
    - _Expected_Behavior: Botón deshabilitado con tooltip explicativo_
    - _Preservation: Botón VLAN con dispositivos activos sigue habilitado_
    - _Requirements: 2.2, 3.4_

  - [x] 3.5 Frontend: Deshabilitar toggle individual bajo contingencia VLAN en `workstations/page.tsx`
    - Cuando `workstation.vlan.forced_contingency === true`, deshabilitar toggle de contingencia individual
    - Agregar tooltip internacionalizado con key `workstations.contingencyControlledByVlan`
    - Agregar keys en `messages/es.json`: `"contingencyControlledByVlan": "La contingencia está controlada a nivel de VLAN"`
    - Agregar keys en `messages/en.json`: `"contingencyControlledByVlan": "Contingency is controlled at VLAN level"`
    - _Bug_Condition: VLAN con forced_contingency=true permite toggle individual_
    - _Expected_Behavior: Toggle deshabilitado con tooltip_
    - _Preservation: Toggle individual sin contingencia VLAN sigue habilitado_
    - _Requirements: 2.3, 3.3_

  - [x] 3.6 Client: Defensa en `AlwaysPrintWindowsService.cs` - no ejecutar trigger sin IP
    - En `OnForcedContingencyReceived`: cuando `enabled=true` y `string.IsNullOrEmpty(printerIp)`, loguear warning y retornar temprano
    - NO ejecutar `ExecuteActionTrigger(TriggerEvents.OnContingencyActivated)` si no se estableció `contingency_printer_ip`
    - Mantener comportamiento de desactivación sin cambios (siempre ejecutar `OnContingencyDeactivated`)
    - _Bug_Condition: enabled=true AND string.IsNullOrEmpty(printerIp) → ejecuta trigger sin variable_
    - _Expected_Behavior: Log warning, early return, no trigger execution_
    - _Preservation: Con printerIp válido sigue ejecutando OnContingencyActivated normalmente_
    - _Requirements: 2.4, 3.5_

  - [x] 3.7 Client: Validación en `CloudManager.cs` - no enviar payload sin IP
    - En `HandleForcedContingency`: si `enabled=true` y `string.IsNullOrEmpty(printerIp)`, loguear warning y NO enviar `ForcedContingencyPayload` al Service via Named Pipe
    - Mantener envío de notificación balloon tip (informar al usuario que se intentó pero falló)
    - Mantener comportamiento de desactivación sin cambios
    - _Bug_Condition: enabled=true AND string.IsNullOrEmpty(printerIp) → envía payload sin IP al Service_
    - _Expected_Behavior: Log warning, no pipe send, balloon tip informativo_
    - _Preservation: Con printerIp válido sigue enviando payload normalmente_
    - _Requirements: 2.4, 3.5_

  - [x] 3.8 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Activación de contingencia sin IP resoluble
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.3, 2.4_

  - [x] 3.9 Verify preservation tests still pass
    - **Property 2: Preservation** - Comportamiento sin cambios para inputs no-buggy
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix (no regressions)

- [x] 4. Checkpoint - Ensure all tests pass
  - Ejecutar suite completa de tests (backend pytest, client dotnet test)
  - Verificar que exploration test (Property 1) pasa después del fix
  - Verificar que preservation tests (Property 2) siguen pasando
  - Verificar que no hay regresiones en tests existentes
  - Ensure all tests pass, ask the user if questions arise.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3", "3.6", "3.7"] },
    { "id": 3, "tasks": ["3.4", "3.5"] },
    { "id": 4, "tasks": ["3.8", "3.9"] },
    { "id": 5, "tasks": ["4"] }
  ]
}
```

## Notes

- Los tasks 1 y 2 (exploration y preservation tests) DEBEN ejecutarse ANTES de cualquier implementación
- Wave 2 agrupa cambios backend (3.1, 3.2, 3.3) y client (3.6, 3.7) que son independientes entre sí
- Wave 3 agrupa cambios frontend (3.4, 3.5) que dependen de los cambios backend para la API
- Wave 4 verifica que los tests pasan después del fix
- Filtrar siempre por `organization_id` en queries del backend (tenant isolation)
- Usar `next-intl` para todos los textos de UI nuevos (tooltips de disabled)
- No usar `any` en TypeScript — tipar correctamente las respuestas de API
