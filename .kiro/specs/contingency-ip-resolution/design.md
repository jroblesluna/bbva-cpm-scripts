# Contingency IP Resolution Bugfix Design

## Overview

El sistema de contingencia AlwaysPrint tiene tres bugs interrelacionados en la activación de contingencia forzada: (1) el backend envía `printer_ip: null` cuando no hay dispositivos activos y el cliente ejecuta el trigger con un template sin resolver `{{contingency_printer_ip}}`, (2) el frontend permite activar contingencia a nivel VLAN sin dispositivos activos, y (3) no se bloquea la desactivación individual cuando la VLAN tiene contingencia forzada activa.

La estrategia de fix es defensiva en múltiples capas: validación en backend (rechazar activación sin IP resoluble), protección en frontend (deshabilitar botones cuando no aplica), y defensa en cliente (rechazar mensajes con `printer_ip` nulo).

## Glossary

- **Bug_Condition (C)**: Condición que dispara el bug — activación de contingencia forzada cuando no se puede resolver una `printer_ip` válida, o interacción individual cuando la VLAN controla la contingencia
- **Property (P)**: Comportamiento deseado — rechazar activación sin IP válida, deshabilitar controles inaplicables, y bloquear desactivación individual bajo contingencia VLAN
- **Preservation**: Comportamiento existente que debe permanecer sin cambios — activación con IP válida, desactivación normal, toggle individual sin contingencia VLAN activa
- **`toggle_workstation_forced_contingency`**: Endpoint `PATCH /workstations/{id}/forced-contingency` en `workstations.py` que resuelve `printer_ip` y envía mensaje WebSocket
- **`toggle_vlan_forced_contingency`**: Endpoint `PATCH /vlans/{id}/forced-contingency` en `vlans.py` que activa contingencia para toda la VLAN
- **`HandleForcedContingency`**: Método en `CloudManager.cs` que recibe el mensaje WebSocket y lo reenvía al Service via Named Pipe
- **`OnForcedContingencyReceived`**: Callback en `AlwaysPrintWindowsService.cs` que establece `contingency_printer_ip` y ejecuta el trigger
- **`ActionEngine.ReplaceTemplates`**: Método que resuelve `{{variable}}` desde `_configVariables`

## Bug Details

### Bug Condition

El bug se manifiesta en tres escenarios: (1) cuando se activa contingencia forzada individual sin poder resolver una IP de impresora, el backend envía `printer_ip: null` y el cliente ejecuta el trigger con template sin resolver; (2) cuando el frontend muestra el botón de contingencia VLAN habilitado sin dispositivos activos; (3) cuando se permite desactivar contingencia individual estando la VLAN en contingencia forzada.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type ContingencyRequest
  OUTPUT: boolean
  
  // Bug 1 & 4: Activación individual sin IP resoluble
  CASE input.type == "workstation_activation":
    RETURN input.enabled == true
           AND resolveIP(input.workstation) == null
           
  // Bug 2: Botón VLAN habilitado sin dispositivos
  CASE input.type == "vlan_button_render":
    RETURN countActiveDevices(input.vlan) == 0
    
  // Bug 3: Desactivación individual bajo contingencia VLAN
  CASE input.type == "workstation_deactivation":
    RETURN input.enabled == false
           AND input.workstation.vlan.forced_contingency == true
           
  DEFAULT: RETURN false
END FUNCTION

FUNCTION resolveIP(workstation)
  IF workstation.default_printer_id != null:
    printer = getDevice(workstation.default_printer_id)
    IF printer != null: RETURN printer.ip_address
  IF workstation.vlan_id != null:
    device = getFirstActiveDevice(workstation.vlan_id, workstation.organization_id)
    IF device != null: RETURN device.ip_address
  RETURN null
END FUNCTION
```

### Examples

- **Bug 1**: Workstation `ws-001` (sin `default_printer_id`) en VLAN sin dispositivos activos → `PATCH /workstations/ws-001/forced-contingency?enabled=true` → backend envía `{"printer_ip": null}` → cliente ejecuta `OnContingencyActivated` → `SetTcpPort` recibe `"host_address": "{{contingency_printer_ip}}"` literal
- **Bug 2**: VLAN "Piso 3" sin dispositivos activos → frontend muestra botón ShieldAlert habilitado → usuario hace click → se activa contingencia sin efecto útil (no hay IP para enviar)
- **Bug 3**: VLAN "Piso 3" con `forced_contingency=true` → usuario va a workstations → desactiva contingencia individual de `ws-001` → se envía `enabled=false` → rompe la intención de contingencia a nivel VLAN
- **Bug 4 (variante de 1)**: Backend marca `forced_contingency=true` en la workstation ANTES de verificar si hay IP resoluble → estado inconsistente en BD

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Activación de contingencia forzada con `printer_ip` válida (desde `default_printer_id` o primer dispositivo activo en VLAN) debe seguir funcionando normalmente
- Desactivación de contingencia (`enabled=false`) debe seguir enviando mensaje y ejecutando `OnContingencyDeactivated` sin importar disponibilidad de dispositivos
- Toggle individual de contingencia cuando la VLAN NO tiene `forced_contingency` activa debe seguir permitido
- Botón de contingencia VLAN con dispositivos activos debe seguir habilitado y funcional
- Cliente que recibe `printer_ip` válido (no nulo, no vacío) debe seguir estableciendo `contingency_printer_ip` y ejecutando `OnContingencyActivated`

**Scope:**
Todos los inputs que NO involucren las condiciones de bug deben ser completamente no afectados por este fix. Esto incluye:
- Activaciones con IP resoluble (happy path)
- Todas las desactivaciones (siempre permitidas excepto individual bajo VLAN forzada)
- Renderizado de VLANs con dispositivos activos
- Mensajes WebSocket con `printer_ip` válido
- Operaciones de contingencia automática (no forzada)

## Hypothesized Root Cause

Basado en el análisis del código fuente, las causas raíz son:

1. **Falta de validación pre-commit en backend (Bug 1 & 4)**: En `workstations.py`, el endpoint `toggle_workstation_forced_contingency` ejecuta `workstation.forced_contingency = enabled` y `db.commit()` ANTES de resolver `printer_ip`. Si la resolución falla (retorna `null`), el estado ya está persistido y el mensaje se envía con `printer_ip: null`. No hay validación que rechace la request.

2. **Falta de validación en frontend VLAN (Bug 2)**: En `vlans/page.tsx`, el botón `ShieldAlert` se renderiza siempre habilitado (`onClick={() => setContingencyTarget(vlan)}`) sin verificar si la VLAN tiene dispositivos activos. No hay lógica condicional de `disabled`.

3. **Falta de bloqueo por jerarquía VLAN→Workstation (Bug 3)**: El frontend de workstations no consulta el estado `forced_contingency` de la VLAN padre. El toggle individual no tiene lógica para deshabilitarse cuando la VLAN controla la contingencia.

4. **Falta de defensa en cliente (Bug 1 complemento)**: En `AlwaysPrintWindowsService.cs`, `OnForcedContingencyReceived` solo verifica `!string.IsNullOrEmpty(printerIp)` para decidir si establece la variable, pero SIEMPRE ejecuta `ExecuteActionTrigger(TriggerEvents.OnContingencyActivated)` cuando `enabled=true`, incluso si `printerIp` es null.

## Correctness Properties

Property 1: Bug Condition - Rechazo de activación sin IP resoluble

_For any_ request de activación de contingencia forzada individual (`enabled=true`) donde `resolveIP(workstation)` retorna null (no hay `default_printer_id` válido ni dispositivos activos en la VLAN), el endpoint corregido SHALL retornar HTTP 400 sin modificar el estado `forced_contingency` de la workstation ni enviar mensaje WebSocket.

**Validates: Requirements 2.1, 2.4**

Property 2: Preservation - Activación con IP válida sin cambios

_For any_ request de activación de contingencia forzada (`enabled=true`) donde `resolveIP(workstation)` retorna una IP válida (no nula, no vacía), el endpoint corregido SHALL producir exactamente el mismo resultado que el código original: marcar `forced_contingency=true`, enviar mensaje WebSocket con la IP resuelta, y el cliente SHALL ejecutar `OnContingencyActivated` normalmente.

**Validates: Requirements 3.1, 3.5**

Property 3: Preservation - Desactivación siempre permitida

_For any_ request de desactivación de contingencia forzada (`enabled=false`) para cualquier workstation o VLAN, el sistema corregido SHALL producir exactamente el mismo resultado que el código original: enviar mensaje de desactivación y ejecutar `OnContingencyDeactivated`, independientemente de la disponibilidad de dispositivos.

**Validates: Requirements 3.2**

Property 4: Bug Condition - Botón VLAN deshabilitado sin dispositivos

_For any_ VLAN que no tiene dispositivos activos (`devices.filter(is_active=true).count() == 0`), el frontend corregido SHALL renderizar el botón de contingencia como deshabilitado (visualmente gris) con tooltip explicativo.

**Validates: Requirements 2.2**

Property 5: Bug Condition - Bloqueo de toggle individual bajo contingencia VLAN

_For any_ workstation cuya VLAN tiene `forced_contingency=true`, el frontend corregido SHALL deshabilitar el toggle de contingencia individual, impidiendo la desactivación individual (solo se permite a nivel VLAN).

**Validates: Requirements 2.3**

Property 6: Preservation - Toggle individual sin contingencia VLAN

_For any_ workstation cuya VLAN NO tiene `forced_contingency=true`, el sistema corregido SHALL permitir el toggle individual de contingencia exactamente como antes del fix.

**Validates: Requirements 3.3, 3.4**

## Fix Implementation

### Changes Required

Asumiendo que nuestro análisis de causa raíz es correcto:

**File**: `AlwaysPrintProject/Cloud/backend/app/api/v1/endpoints/workstations.py`

**Function**: `toggle_workstation_forced_contingency`

**Specific Changes**:
1. **Validación pre-commit de IP**: Mover la resolución de `printer_ip` ANTES del `db.commit()`. Si `enabled=true` y `printer_ip` es `None`, retornar HTTP 400 con mensaje descriptivo sin modificar la BD.
2. **Bloqueo por contingencia VLAN**: Si `enabled=false` y la VLAN de la workstation tiene `forced_contingency=true`, retornar HTTP 409 (Conflict) indicando que la contingencia está controlada a nivel VLAN.

---

**File**: `AlwaysPrintProject/Cloud/backend/app/api/v1/endpoints/vlans.py`

**Function**: `toggle_vlan_forced_contingency`

**Specific Changes**:
3. **Incluir `printer_ip` en mensaje VLAN**: Al enviar el mensaje WebSocket a cada workstation, resolver la IP de contingencia (desde `default_printer_id` de cada workstation o primer dispositivo activo de la VLAN) e incluirla en el mensaje. Si `enabled=true` y no hay dispositivos activos en la VLAN, retornar HTTP 400.

---

**File**: `AlwaysPrintProject/Cloud/frontend/src/app/dashboard/vlans/page.tsx`

**Specific Changes**:
4. **Deshabilitar botón sin dispositivos**: Agregar prop `disabled` al botón `ShieldAlert` cuando la VLAN no tiene dispositivos activos. Agregar tooltip con texto internacionalizado explicando la razón.
5. **Obtener conteo de dispositivos**: Incluir información de dispositivos activos en la query de VLANs o hacer query adicional para determinar disponibilidad.

---

**File**: `AlwaysPrintProject/Cloud/frontend/src/app/dashboard/workstations/page.tsx` (o componente equivalente)

**Specific Changes**:
6. **Deshabilitar toggle bajo contingencia VLAN**: Cuando la VLAN de la workstation tiene `forced_contingency=true`, deshabilitar el toggle de contingencia individual con tooltip explicativo internacionalizado.

---

**File**: `AlwaysPrintProject/Client/AlwaysPrintService/AlwaysPrintWindowsService.cs`

**Function**: `OnForcedContingencyReceived`

**Specific Changes**:
7. **Defensa en cliente**: Cuando `enabled=true` y `printerIp` es null o vacío, loguear warning y NO ejecutar `ExecuteActionTrigger(TriggerEvents.OnContingencyActivated)`. Retornar temprano sin entrar en modo contingencia.

---

**File**: `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/CloudManager.cs`

**Function**: `HandleForcedContingency`

**Specific Changes**:
8. **Validación en Tray**: Antes de enviar `ForcedContingencyPayload` al Service, verificar que si `enabled=true`, `printerIp` no sea null/vacío. Si lo es, loguear warning y no enviar el payload al Service.

## Testing Strategy

### Validation Approach

La estrategia de testing sigue un enfoque de dos fases: primero, generar contraejemplos que demuestren el bug en código sin corregir, luego verificar que el fix funciona correctamente y preserva el comportamiento existente.

### Exploratory Bug Condition Checking

**Goal**: Generar contraejemplos que demuestren el bug ANTES de implementar el fix. Confirmar o refutar el análisis de causa raíz. Si refutamos, necesitaremos re-hipotetizar.

**Test Plan**: Escribir tests que simulen requests de activación de contingencia sin IP resoluble, renderizado de botones VLAN sin dispositivos, y desactivación individual bajo contingencia VLAN. Ejecutar estos tests en código SIN CORREGIR para observar fallos y entender la causa raíz.

**Test Cases**:
1. **Backend Activation Without IP**: Llamar `PATCH /workstations/{id}/forced-contingency?enabled=true` con workstation sin `default_printer_id` y VLAN sin dispositivos activos → verificar que retorna 200 (bug: debería ser 400) (fallará en código sin corregir)
2. **Backend State Persistence**: Verificar que `forced_contingency=true` se persiste en BD incluso cuando `printer_ip` es null (fallará en código sin corregir)
3. **WebSocket Message With Null IP**: Verificar que el mensaje WebSocket contiene `printer_ip: null` cuando no hay dispositivos (fallará en código sin corregir)
4. **Client Trigger Without IP**: Simular recepción de mensaje con `printer_ip: null` y `enabled: true` → verificar que `OnContingencyActivated` se ejecuta sin variable establecida (fallará en código sin corregir)

**Expected Counterexamples**:
- El endpoint retorna 200 y persiste estado incluso sin IP resoluble
- El mensaje WebSocket se envía con `printer_ip: null`
- El cliente ejecuta el trigger sin haber establecido la variable de configuración
- Posibles causas: falta de validación pre-commit, falta de early return en cliente

### Fix Checking

**Goal**: Verificar que para todos los inputs donde la condición de bug se cumple, la función corregida produce el comportamiento esperado.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  CASE input.type == "workstation_activation":
    result := toggle_workstation_forced_contingency_fixed(input)
    ASSERT result.status_code == 400
    ASSERT workstation.forced_contingency == false  // no cambió
    ASSERT no_websocket_message_sent()
    
  CASE input.type == "vlan_button_render":
    rendered := renderVlanButton_fixed(input.vlan)
    ASSERT rendered.disabled == true
    ASSERT rendered.tooltip != null
    
  CASE input.type == "workstation_deactivation":
    result := toggle_workstation_forced_contingency_fixed(input)
    ASSERT result.status_code == 409
    ASSERT workstation.forced_contingency unchanged
END FOR
```

### Preservation Checking

**Goal**: Verificar que para todos los inputs donde la condición de bug NO se cumple, la función corregida produce el mismo resultado que la función original.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT toggle_workstation_forced_contingency_original(input) 
         == toggle_workstation_forced_contingency_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing es recomendado para preservation checking porque:
- Genera muchos casos de prueba automáticamente a través del dominio de inputs
- Captura edge cases que tests manuales podrían perder
- Provee garantías fuertes de que el comportamiento no cambia para inputs no-buggy

**Test Plan**: Observar comportamiento en código SIN CORREGIR primero para activaciones con IP válida, desactivaciones, y toggles individuales sin contingencia VLAN, luego escribir property-based tests capturando ese comportamiento.

**Test Cases**:
1. **Activation With Valid IP Preservation**: Verificar que activar contingencia con `default_printer_id` válido sigue retornando 200 con `printer_ip` correcto
2. **Deactivation Preservation**: Verificar que desactivar contingencia sigue funcionando sin importar disponibilidad de dispositivos
3. **Individual Toggle Without VLAN Contingency**: Verificar que toggle individual sigue habilitado cuando VLAN no tiene `forced_contingency`
4. **VLAN Button With Devices**: Verificar que botón VLAN sigue habilitado cuando hay dispositivos activos
5. **Client Valid IP Preservation**: Verificar que cliente con `printer_ip` válido sigue ejecutando trigger normalmente

### Unit Tests

- Test de endpoint backend: activación rechazada sin IP (HTTP 400)
- Test de endpoint backend: activación exitosa con IP válida (HTTP 200)
- Test de endpoint backend: desactivación individual bloqueada bajo VLAN (HTTP 409)
- Test de endpoint backend: desactivación siempre permitida sin VLAN forzada
- Test de cliente: `OnForcedContingencyReceived` con `printerIp=null` no ejecuta trigger
- Test de cliente: `OnForcedContingencyReceived` con `printerIp` válido ejecuta trigger
- Test de frontend: botón VLAN deshabilitado sin dispositivos activos
- Test de frontend: toggle workstation deshabilitado bajo contingencia VLAN

### Property-Based Tests

- Generar workstations aleatorias con/sin `default_printer_id` y VLANs con/sin dispositivos activos → verificar que activación solo procede cuando hay IP resoluble
- Generar estados aleatorios de VLAN (`forced_contingency` true/false) y verificar que toggle individual se habilita/deshabilita correctamente
- Generar mensajes WebSocket aleatorios con `printer_ip` válido/null → verificar que cliente solo ejecuta trigger con IP válida
- Generar combinaciones de desactivación → verificar que siempre se permite (preservation)

### Integration Tests

- Test end-to-end: activar contingencia individual sin dispositivos → verificar rechazo completo (backend → no mensaje → no trigger)
- Test end-to-end: activar contingencia VLAN con dispositivos → verificar que todas las workstations reciben mensaje con IP
- Test end-to-end: intentar desactivar individual bajo VLAN forzada → verificar bloqueo en frontend y backend
- Test end-to-end: flujo completo de activación exitosa → verificar que `{{contingency_printer_ip}}` se resuelve correctamente en `SetTcpPort`
