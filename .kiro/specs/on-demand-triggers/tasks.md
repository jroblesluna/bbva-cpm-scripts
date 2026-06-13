# Implementation Plan: On-Demand Triggers

## Overview

Implementación incremental de tres capacidades interconectadas para AlwaysPrint: (1) detección de segunda instancia con señalización Win32 broadcast para mostrar Status Form, (2) formulario WPF de estado del sistema con información general, servicios y triggers OnDemand, y (3) submenú de acciones a demanda en el menú contextual del Tray con ejecución delegada al Service vía Named Pipe.

Lenguaje: C# 9 / .NET Framework 4.8. Tests: FsCheck + xUnit.

## Tasks

- [x] 1. Definir tipos de mensaje, payloads y modelo de configuración
  - [x] 1.1 Agregar nuevos MessageType y payloads en AlwaysPrint.Shared
    - Agregar `ExecuteOnDemandTrigger`, `ServiceAction`, `ServiceActionResponse` al enum `MessageType` en `MessageType.cs`
    - Crear clases `ExecuteOnDemandTriggerPayload`, `ServiceActionPayload`, `ServiceActionResponsePayload` en `Payloads.cs`
    - Cada payload con atributos `[JsonProperty]` según diseño
    - _Requirements: 7.1, 7.2_
  - [x] 1.2 Agregar campo `Label` a `TriggerConfig` en ActionConfig.cs
    - Agregar propiedad `public string? Label { get; set; }` con `[JsonProperty("label")]`
    - Agregar constante `public const string OnDemand = "OnDemand"` en clase `TriggerEvents` (crear si no existe)
    - _Requirements: 5.1, 5.2_
  - [x] 1.3 Crear clase `OnDemandTriggerInfo` (DTO para UI)
    - Crear archivo `AlwaysPrintTray/OnDemand/OnDemandTriggerInfo.cs`
    - Propiedades: `Label` (string), `Description` (string)
    - _Requirements: 11.4_

- [x] 2. Implementar lectura de configuración OnDemand
  - [x] 2.1 Crear `OnDemandConfigReader` para leer triggers desde active.alwaysconfig
    - Crear archivo `AlwaysPrintTray/OnDemand/OnDemandConfigReader.cs`
    - Método `GetOnDemandTriggers()`: lee archivo, filtra `event == "OnDemand"` (case-insensitive) con `label` no vacío
    - Método `Reload()`: recarga y retorna lista actualizada
    - Retorna lista vacía si archivo no existe o JSON inválido, con log de advertencia
    - Preservar orden original del array de triggers
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 5.5_
  - [x] 2.2 Escribir property test para filtrado de triggers OnDemand
    - **Property 1: Filtrado de triggers OnDemand**
    - Generar `ActionConfiguration` arbitraria con mezcla de eventos y labels vacíos/válidos/nulos
    - Verificar que el resultado contiene exactamente los triggers con `event="OnDemand"` y `label` no vacío, en orden original
    - **Validates: Requirements 4.1, 5.2, 5.5, 6.3, 10.1, 11.4**
  - [x] 2.3 Escribir property test para serialización round-trip de ExecuteOnDemandTriggerPayload
    - **Property 3: Serialización round-trip de ExecuteOnDemandTriggerPayload**
    - Generar strings arbitrarios para label, serializar a JSON y deserializar
    - Verificar que el label resultante es idéntico al original
    - **Validates: Requirements 7.1, 7.2**
  - [x] 2.4 Escribir unit tests para OnDemandConfigReader
    - Test: archivo inexistente retorna lista vacía
    - Test: JSON inválido retorna lista vacía
    - Test: triggers sin label se omiten
    - Test: triggers con label vacío/whitespace se omiten
    - Test: solo triggers OnDemand se incluyen (no OnTrayLaunched, etc.)
    - _Requirements: 11.3, 11.4, 5.5_

- [x] 3. Checkpoint — Verificar compilación y tests de capa de datos
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implementar detección de segunda instancia y broadcast Win32
  - [x] 4.1 Modificar `Program.cs` para enviar broadcast en segunda instancia
    - Agregar P/Invoke: `RegisterWindowMessage`, `PostMessage`
    - Tras detectar mutex tomado: registrar mensaje, enviar broadcast `HWND_BROADCAST`, salir
    - Pasar `showStatusMsgId` al constructor de `TrayApplicationContext`
    - _Requirements: 1.1, 1.4_
  - [x] 4.2 Crear `BroadcastListener` en TrayApplicationContext para recibir broadcast
    - Crear clase interna `BroadcastListener : NativeWindow`
    - En `WndProc`: detectar mensaje registrado y llamar `ShowStatusForm()`
    - Registrar en log la recepción del broadcast
    - _Requirements: 1.2, 1.3, 1.4_
  - [x] 4.3 Escribir unit tests para lógica de decisión broadcast
    - Test: mutex libre → no enviar broadcast
    - Test: mutex tomado → enviar broadcast y salir
    - _Requirements: 1.1_

- [x] 5. Implementar Status Form (WPF) — Información General
  - [x] 5.1 Crear StatusForm.xaml y StatusForm.xaml.cs con layout base
    - Crear `AlwaysPrintTray/Forms/StatusForm.xaml` con secciones: Info General, Servicios, OnDemand Triggers
    - Formulario no modal, control de instancia única (singleton)
    - Implementar `ShowStatusForm()` en `TrayApplicationContext` con lógica de traer al frente si ya está abierto
    - _Requirements: 2.6, 2.7, 1.3_
  - [x] 5.2 Implementar sección de información general del Status Form
    - Campo "Estado": leer `ContingencyEnabled` del registro → "Normal" / "En Contingencia"
    - Campo "Versión": leer versión del ensamblado
    - Campo "Cola activa gestionada": modo CPM (solo nombre) vs modo LPM (nombre + ruta remota)
    - Campo "Configuración": formato `"{Name} v{Version}"` de la config activa
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_
  - [x] 5.3 Escribir property test para formato de display de configuración
    - **Property 4: Formato de display de configuración activa**
    - Generar pares (name, version) no vacíos arbitrarios
    - Verificar que el texto generado es exactamente `"{Name} v{Version}"`
    - **Validates: Requirements 2.5**
  - [x] 5.4 Escribir unit tests para información general del Status Form
    - Test: estado Normal vs En Contingencia
    - Test: cola activa modo CPM (solo nombre)
    - Test: cola activa modo LPM (nombre + ruta remota entre paréntesis)
    - _Requirements: 2.1, 2.3, 2.4_

- [x] 6. Implementar Status Form — Sección de Servicios
  - [x] 6.1 Implementar consulta y display de estado de servicios
    - Crear clase `ServiceStatusItem` con DataBinding (INotifyPropertyChanged)
    - Mostrar 5 servicios: AlwaysPrintService, lpmc_universal_service, LpdServiceMonitor, LPDSVC, Spooler
    - Botón "Reiniciar" si Running, "Iniciar" si Stopped
    - Si pipe no disponible: mostrar "Estado desconocido" y deshabilitar controles
    - _Requirements: 3.1, 3.2, 3.3, 3.7_
  - [x] 6.2 Implementar envío de ServiceAction vía Named Pipe
    - Al clic en Start/Restart: enviar `PipeMessage(ServiceAction, ServiceActionPayload)`
    - Deshabilitar control durante operación (`IsOperating = true`)
    - Al recibir `ServiceActionResponse`: actualizar estado visual y rehabilitar control
    - _Requirements: 3.4, 3.5, 3.6_
  - [x] 6.3 Escribir unit tests para sección de servicios
    - Test: mapeo estado Running → label "Reiniciar"
    - Test: mapeo estado Stopped → label "Iniciar"
    - Test: flag IsOperating deshabilita control
    - Test: pipe no disponible → "Estado desconocido"
    - _Requirements: 3.2, 3.3, 3.6, 3.7_

- [x] 7. Implementar Status Form — Sección de Triggers OnDemand
  - [x] 7.1 Implementar lista de triggers OnDemand en Status Form
    - Usar `ObservableCollection<OnDemandTriggerItem>` con DataBinding
    - Mostrar campo `label` de cada trigger
    - Si no hay triggers: mostrar mensaje "No hay acciones disponibles"
    - _Requirements: 4.1, 4.7_
  - [x] 7.2 Implementar ejecución con diálogo de confirmación
    - Al clic en trigger: mostrar diálogo con `description` y botones "Confirmar Ejecución" / "Cancelar"
    - Si confirma: enviar `PipeMessage(ExecuteOnDemandTrigger, { label })` al Service
    - Si cancela: cerrar diálogo sin acción
    - Deshabilitar ítem durante ejecución (`IsExecuting = true`)
    - Rehabilitar y mostrar feedback visual al recibir respuesta (éxito/fallo)
    - _Requirements: 4.2, 4.3, 4.4, 4.5, 4.6_
  - [x] 7.3 Escribir unit tests para ejecución OnDemand desde Status Form
    - Test: confirmar ejecuta envío de pipe message
    - Test: cancelar no envía nada
    - Test: IsExecuting deshabilita ítem
    - Test: sin triggers muestra mensaje vacío
    - _Requirements: 4.3, 4.4, 4.5, 4.7_

- [x] 8. Checkpoint — Verificar Status Form completo
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implementar submenú OnDemand en menú contextual del Tray
  - [x] 9.1 Implementar construcción dinámica del submenú OnDemand
    - Crear método `RebuildOnDemandSubmenu()` en `TrayApplicationContext`
    - Llamar en bootstrap y ante `ActionConfigChanged`
    - Crear `ToolStripMenuItem("Acciones A Demanda")` con ítems por trigger
    - Posicionar después de "Buscar Actualizaciones", antes del separador de "Salir"
    - Insertar separador visual antes del submenú
    - Si no hay triggers: no mostrar submenú
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.6_
  - [x] 9.2 Implementar ejecución desde submenú y feedback
    - Al clic en ítem: enviar `PipeMessage(ExecuteOnDemandTrigger, { label })` al Service
    - Deshabilitar ítem (grayed out) durante ejecución
    - Al recibir Ack success=true: balloon tip con mensaje de éxito incluyendo label
    - Al recibir Ack success=false o Error: balloon tip con mensaje de error
    - Rehabilitar ítem tras respuesta
    - Si pipe no disponible: balloon tip de error y log
    - _Requirements: 6.5, 7.1, 7.3, 9.1, 9.2, 9.3, 9.4_
  - [x] 9.3 Escribir unit tests para submenú OnDemand
    - Test: con triggers → submenú presente con ítems correctos
    - Test: sin triggers → submenú ausente
    - Test: ítem deshabilitado durante ejecución
    - Test: balloon success con label correcto
    - Test: balloon error con mensaje
    - _Requirements: 6.1, 6.4, 9.1, 9.2, 9.3_

- [x] 10. Implementar ejecución OnDemand en el Service (ActionEngine)
  - [x] 10.1 Implementar método `ExecuteOnDemandTrigger` en ActionEngine
    - Buscar primer trigger con `event="OnDemand"` y `label` exacto
    - Si no se encuentra: retornar `(false, "Trigger no encontrado")`
    - Si hay duplicados: advertir en log, ejecutar el primero
    - Ejecutar acciones del trigger secuencialmente
    - Log de inicio y fin con label y duración
    - Retornar `(success, message)` al pipe
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
  - [x] 10.2 Integrar manejo de `ExecuteOnDemandTrigger` en PipeServer
    - Agregar case para `MessageType.ExecuteOnDemandTrigger` en handler del PipeServer
    - Deserializar `ExecuteOnDemandTriggerPayload`
    - Llamar `ActionEngine.ExecuteOnDemandTrigger(payload.Label)`
    - Responder con `Ack` (success/fail) o `Error` según resultado
    - _Requirements: 8.1, 8.3_
  - [x] 10.3 Integrar manejo de `ServiceAction` en PipeServer
    - Agregar case para `MessageType.ServiceAction`
    - Deserializar `ServiceActionPayload`
    - Ejecutar Start o Restart del servicio indicado
    - Responder con `ServiceActionResponse` indicando resultado y nuevo estado
    - _Requirements: 3.4, 3.5_
  - [x] 10.4 Escribir property test para resolución de trigger por label
    - **Property 2: Resolución de trigger por label (búsqueda exacta)**
    - Generar configs arbitrarias con triggers OnDemand y labels variados
    - Verificar que buscar un label existente encuentra el trigger correcto; buscar uno inexistente retorna error
    - **Validates: Requirements 8.1, 8.2, 5.6, 8.5**
  - [x] 10.5 Escribir property test para deduplicación (primero encontrado gana)
    - **Property 5: Deduplicación preserva orden (primero encontrado gana)**
    - Generar configs con múltiples triggers que comparten el mismo label
    - Verificar que se ejecutan las acciones del primer trigger en el array
    - **Validates: Requirements 5.6, 8.5**
  - [x] 10.6 Escribir unit tests para ExecuteOnDemandTrigger
    - Test: label existente ejecuta acciones correctas
    - Test: label inexistente retorna error
    - Test: labels duplicados ejecuta primero y loguea warning
    - Test: config no cargada retorna error
    - _Requirements: 8.1, 8.2, 8.4, 8.5_

- [x] 11. Implementar actualización dinámica ante cambios de configuración
  - [x] 11.1 Conectar evento ActionConfigChanged con reconstrucción del menú y Status Form
    - Al recibir `ActionConfigChanged` vía pipe: llamar `OnDemandConfigReader.Reload()`
    - Llamar `RebuildOnDemandSubmenu()` para actualizar menú contextual
    - Si `StatusForm` está abierto: llamar `RefreshOnDemandTriggers()` y actualizar campo "Configuración"
    - Si hay trigger en ejecución que fue eliminado: esperar respuesta antes de actualizar UI
    - _Requirements: 10.1, 10.2, 10.3, 10.4_
  - [x] 11.2 Escribir unit tests para actualización dinámica
    - Test: cambio de config reconstruye submenú
    - Test: cambio de config actualiza Status Form si está abierto
    - Test: trigger en ejecución no se elimina hasta respuesta
    - _Requirements: 10.1, 10.2, 10.4_

- [x] 12. Checkpoint final — Verificar integración completa
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Las tareas marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido
- Cada tarea referencia requisitos específicos para trazabilidad
- Los checkpoints aseguran validación incremental
- Property tests validan propiedades universales de correctitud definidas en el diseño
- Unit tests validan ejemplos específicos y edge cases
- El proyecto usa FsCheck.Xunit para property-based testing (ya configurado en `AlwaysPrint.Tests`)
- Los tests de propiedad deben ejecutarse con mínimo 100 iteraciones

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1", "4.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "4.2", "4.3"] },
    { "id": 3, "tasks": ["5.1", "9.1", "10.1"] },
    { "id": 4, "tasks": ["5.2", "5.3", "5.4", "9.2", "9.3", "10.2", "10.3", "10.4", "10.5", "10.6"] },
    { "id": 5, "tasks": ["6.1", "7.1"] },
    { "id": 6, "tasks": ["6.2", "6.3", "7.2", "7.3"] },
    { "id": 7, "tasks": ["11.1", "11.2"] }
  ]
}
```
