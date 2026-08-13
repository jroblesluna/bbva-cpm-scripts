# Implementation Plan: Remote Terminal

## Overview

Implementar el componente RemoteTerminalSection que permite a Admin/Operator ejecutar comandos OS en workstations remotas desde el WorkstationDetailModal. El backend ya soporta `execute_remote_command` — el trabajo es mayoritariamente frontend (componente + hook + i18n) con un cambio menor en backend (audit ActionType + migración).

## Tasks

- [x] 1. Backend: Agregar ActionType y migración
  - [x] 1.1 Agregar `REMOTE_COMMAND_EXECUTED` al enum ActionType en `app/models/audit.py`
    - Agregar nuevo valor al enum `ActionType` en `app/models/audit.py`
    - Crear migración alembic `035_add_remote_command_audit_action.py` que agrega el valor al enum PostgreSQL
    - Seguir el patrón de migración 031 (ADD VALUE IF NOT EXISTS en MAYÚSCULA directamente)
    - _Requirements: 5.3_

  - [x] 1.2 Escribir test unitario para el nuevo ActionType
    - Verificar que `ActionType.REMOTE_COMMAND_EXECUTED` existe y tiene valor correcto
    - Verificar que el audit log se crea con los campos correctos (command, command_id, success, stdout_preview)
    - Verificar que stdout_preview se trunca a 200 caracteres
    - _Requirements: 5.3_

- [x] 2. Frontend: Crear hook `useRemoteTerminal`
  - [x] 2.1 Crear `src/hooks/useRemoteTerminal.ts`
    - Definir interfaces `CommandHistoryEntry` y `UseRemoteTerminalReturn`
    - Implementar estado local con `useState<CommandHistoryEntry[]>([])`
    - Implementar `executeCommand`: genera UUID, agrega entrada con `isLoading: true`, llama `workstationsApi.sendCommand`, actualiza con resultado/error
    - Implementar `clearHistory`: vacía el array
    - Implementar `copyHistory`: formatea historial como texto y copia al clipboard con `navigator.clipboard.writeText`
    - Manejar errores HTTP (408 timeout, 409 desconexión, 500 genérico) con mensajes i18n
    - Prevenir ejecución concurrente (no ejecutar si `isExecuting === true`)
    - _Requirements: 2.1, 2.5, 2.6, 2.7, 3.1, 3.5, 4.1, 4.2, 4.3_

  - [x] 2.2 Escribir tests unitarios para `useRemoteTerminal`
    - Test: `executeCommand` agrega entrada al historial y llama API
    - Test: Historial se actualiza con stdout al recibir respuesta exitosa
    - Test: Historial se actualiza con error al recibir error HTTP 408/409/500
    - Test: `clearHistory` vacía el array
    - Test: `copyHistory` formatea y copia al clipboard
    - Test: No permite ejecutar si ya hay comando en progreso
    - _Requirements: 2.1, 2.5, 2.6, 2.7, 3.5, 4.2_

- [x] 3. Frontend: Actualizar API layer para soportar `execute_remote_command`
  - [x] 3.1 Agregar `'execute_remote_command'` al type union de `sendCommand` en `src/lib/api.ts`
    - Agregar `'execute_remote_command'` al union type del parámetro `commandType`
    - Agregar timeout de 60000ms para `execute_remote_command` (backend usa 45s, frontend necesita margen)
    - Ajustar la condición de timeout: `execute_on_demand` 90s, `execute_remote_command` 60s, resto 30s
    - _Requirements: 2.1, 4.3_

- [x] 4. Frontend: Crear componente `RemoteTerminalSection`
  - [x] 4.1 Crear `src/components/workstations/RemoteTerminalSection.tsx`
    - Props: `workstationId: string`, `isOnline: boolean`
    - Renderizar condicionalmente según rol (solo Admin/Operator usando `useAuth`)
    - Mostrar estado disabled con mensaje cuando workstation está offline
    - Input con prompt prefix `>`, placeholder text i18n, y estilo monospace
    - Área de output con fondo oscuro, fuente monospace clara, altura máxima con scroll independiente
    - Botón ejecutar (deshabilitado con input vacío/whitespace o durante ejecución)
    - Submit con Enter además del botón
    - Loading indicator animado junto a la entrada pendiente
    - Deshabilitar input y botón durante ejecución
    - Al recibir respuesta: re-habilitar input, set focus, limpiar input
    - Mostrar historial de comandos con timestamp, comando, y stdout/error
    - Estilo diferenciado para errores (texto rojo/naranja)
    - Auto-scroll al agregar nueva entrada
    - Botones de "Copiar historial" y "Limpiar" (visibles cuando hay contenido)
    - _Requirements: 1.1, 1.2, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.4, 4.1, 4.2, 4.3, 5.1, 6.1, 6.4, 6.5_

  - [x] 4.2 Implementar navegación por historial de comandos con teclado
    - Up Arrow: ciclar hacia atrás por comandos ejecutados previamente
    - Down Arrow: ciclar hacia adelante, volver a input vacío después del último comando
    - Guardar input actual al comenzar navegación, restaurar al volver
    - No hacer nada si historial está vacío
    - _Requirements: 6.2, 6.3_

  - [x] 4.3 Escribir tests unitarios para `RemoteTerminalSection`
    - Test: Se renderiza cuando workstation online y usuario Admin/Operator
    - Test: No se renderiza cuando usuario ReadOnly
    - Test: Estado disabled con mensaje cuando workstation offline
    - Test: Input deshabilitado durante ejecución
    - Test: Botón deshabilitado con input vacío/whitespace
    - Test: Submit con Enter ejecuta comando
    - Test: Up/Down arrow navega por historial
    - Test: Auto-scroll al agregar entrada
    - _Requirements: 1.1, 1.2, 1.3, 2.2, 4.2, 6.2, 6.3_

- [x] 5. Frontend: Agregar traducciones i18n
  - [x] 5.1 Agregar keys de traducción en `messages/en.json` y `messages/es.json`
    - Namespace `workstations`: agregar todas las keys definidas en el diseño (remoteTerminal, remoteTerminalPlaceholder, remoteTerminalOffline, remoteTerminalExecute, remoteTerminalExecuting, remoteTerminalTimeout, remoteTerminalError, remoteTerminalWsDisconnected, remoteTerminalCopyHistory, remoteTerminalCopied, remoteTerminalNoOutput, remoteTerminalClearHistory)
    - Textos en español para `es.json`, textos en inglés para `en.json`
    - _Requirements: 1.4_

- [x] 6. Integración: Montar componente en WorkstationDetailModal
  - [x] 6.1 Agregar `RemoteTerminalSection` en `src/app/dashboard/workstations/page.tsx`
    - Importar `RemoteTerminalSection` desde `@/components/workstations/RemoteTerminalSection`
    - Insertar entre `OsCommandsSection` y la sección de Log Analysis
    - Pasar props `workstationId={workstation.id}` y `isOnline={workstation.is_online}`
    - Verificar que el componente se monta/desmonta correctamente al abrir/cerrar modal (historial se resetea)
    - _Requirements: 1.1, 3.3_

- [x] 7. Checkpoint - Verificar implementación completa
  - Ensure all tests pass, ask the user if questions arise.
  - Verificar: componente se renderiza correctamente, comandos se ejecutan, historial funciona, i18n en ambos idiomas, audit log se registra

## Notes

- Tasks marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido
- El backend ya soporta `execute_remote_command` — solo falta el audit ActionType específico
- El timeout del frontend (60s) da margen sobre los 45s del backend para evitar race conditions
- No hay PBT — la feature es primordialmente UI sin invariantes complejas de datos
- El componente sigue el patrón existente de `OsCommandsSection` y `OnDemandActionsSection`
- El historial vive en estado local React (se pierde al cerrar modal, por diseño)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "3.1", "5.1"] },
    { "id": 1, "tasks": ["1.2", "2.2", "4.1"] },
    { "id": 2, "tasks": ["4.2"] },
    { "id": 3, "tasks": ["4.3", "6.1"] }
  ]
}
```
