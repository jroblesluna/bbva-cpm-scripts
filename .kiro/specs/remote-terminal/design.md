# Design Document: Remote Terminal

## Overview

El componente Remote Terminal agrega una mini-terminal interactiva dentro del `WorkstationDetailModal` existente. Permite a usuarios con rol Admin u Operator ejecutar comandos OS arbitrarios en una workstation remota conectada vía WebSocket, visualizando la salida (stdout) en tiempo real con historial de sesión.

**Decisiones clave de diseño:**

1. **Componente independiente**: `RemoteTerminalSection` se implementa como componente separado en `src/components/workstations/` (mismo patrón que `OsCommandsSection`, `OnDemandActionsSection`).
2. **Reutilización del endpoint existente**: Se usa `POST /api/v1/workstations/{id}/command` con `command_type: "execute_remote_command"` — el backend ya soporta este tipo, valida permisos de organización, y tiene timeout de 45s.
3. **Estado local de sesión**: El historial de comandos vive en estado React local del componente (se pierde al cerrar/reabrir el modal, conforme a Req 3.3).
4. **Audit logging existente**: El endpoint ya registra `COMMAND_SENT` vía `AuditService.log_command`. Se agregará un `ActionType` específico `REMOTE_COMMAND_EXECUTED` para mayor trazabilidad.
5. **Control de acceso en frontend**: El componente se renderiza condicionalmente según rol (`isAdmin() || isOperator()`) y estado online de la workstation.

## Architecture

```mermaid
graph TD
    subgraph Frontend [Next.js Frontend]
        A[WorkstationDetailModal] --> B[RemoteTerminalSection]
        B --> C[useRemoteTerminal hook]
        C --> D[workstationsApi.sendCommand]
    end

    subgraph Backend [FastAPI Backend]
        D -->|POST /workstations/{id}/command| E[workstations.py endpoint]
        E -->|Valida permisos org| F{Operator?}
        F -->|Sí| G[Verifica organization_id]
        F -->|No Admin| H[Procede]
        G --> H
        H -->|WebSocket| I[Workstation Client]
        I -->|cmd.exe /c command| J[OS]
        J -->|stdout| I
        I -->|response| H
        H -->|AuditLog| K[(PostgreSQL)]
        H -->|JSONResponse stdout| D
    end
```

**Flujo de ejecución:**
1. Usuario escribe comando en el input y presiona Enter
2. `RemoteTerminalSection` llama a `workstationsApi.sendCommand(id, 'execute_remote_command', { command })`
3. Backend verifica: workstation existe → permisos org → workstation online
4. Backend envía vía WebSocket al cliente Windows: `{ type: "command", command_type: "execute_remote_command", params: { command } }`
5. Cliente ejecuta `cmd.exe /c <command>` como SYSTEM, captura stdout
6. Cliente responde vía WebSocket con `{ success: true, stdout: "..." }`
7. Backend registra audit log y retorna `{ stdout: "..." }` al frontend
8. Frontend muestra resultado en el historial

## Components and Interfaces

### Componente Principal: `RemoteTerminalSection`

```
Ubicación: src/components/workstations/RemoteTerminalSection.tsx
```

**Props:**
```typescript
interface RemoteTerminalSectionProps {
  workstationId: string;
  isOnline: boolean;
}
```

**Responsabilidades:**
- Renderizar la sección de terminal dentro del modal
- Controlar visibilidad según rol del usuario
- Mostrar estado disabled cuando workstation está offline
- Gestionar historial de comandos de la sesión
- Manejar navegación por historial con flechas arriba/abajo

### Hook Personalizado: `useRemoteTerminal`

```
Ubicación: src/hooks/useRemoteTerminal.ts
```

**Interface:**
```typescript
interface CommandHistoryEntry {
  id: string;              // UUID generado en frontend para key de React
  command: string;         // Comando ejecutado
  output: string | null;   // stdout o mensaje de error
  isError: boolean;        // Distinguir error de éxito
  timestamp: Date;         // Momento de ejecución
  isLoading: boolean;      // En espera de respuesta
}

interface UseRemoteTerminalReturn {
  history: CommandHistoryEntry[];
  isExecuting: boolean;
  executeCommand: (command: string) => Promise<void>;
  clearHistory: () => void;
  copyHistory: () => Promise<void>;
}
```

**Lógica interna:**
- Usa `useMutation` de `@tanstack/react-query` para la llamada API
- Mantiene `history` como `useState<CommandHistoryEntry[]>([])` 
- `executeCommand` agrega entrada con `isLoading: true`, llama al API, actualiza con resultado
- `copyHistory` formatea el historial y usa `navigator.clipboard.writeText`

### Integración en WorkstationDetailModal

El componente se agrega entre la sección `OsCommandsSection` y `LogAnalysisButton` existentes:

```tsx
{/* Sección de Remote Terminal — solo Admin/Operator con WS online */}
<RemoteTerminalSection
  workstationId={workstation.id}
  isOnline={workstation.is_online}
/>
```

### API Layer (sin cambios en `workstationsApi`)

Se reutiliza el método existente:
```typescript
workstationsApi.sendCommand(
  workstationId,
  'execute_remote_command' as 'execute_on_demand',  // type assertion (patrón existente)
  { command: commandText }
)
```

La respuesta del backend para `execute_remote_command` es `JSONResponse` con el contenido completo del response de la workstation: `{ success: boolean, stdout?: string, output?: string }`.

### Backend: Audit Log Enhancement

Agregar nuevo `ActionType`:
```python
# En app/models/audit.py
REMOTE_COMMAND_EXECUTED = "remote_command_executed"
```

Registrar en el endpoint después de recibir respuesta:
```python
audit_service.log_action(
    db=db,
    action_type=ActionType.REMOTE_COMMAND_EXECUTED,
    entity_type="workstation",
    entity_id=str(workstation_id),
    user_id=str(current_user.id),
    organization_id=str(workstation.organization_id),
    new_values={
        "command": command_data.params.get("command"),
        "command_id": command_id,
        "success": success,
        "stdout_preview": stdout[:200] if stdout else None,
    }
)
```

## Data Models

### Frontend State

```typescript
// Estado del componente RemoteTerminalSection
interface RemoteTerminalState {
  history: CommandHistoryEntry[];        // Historial de la sesión actual
  historyIndex: number;                  // Índice para navegación con flechas (-1 = input actual)
  currentInput: string;                  // Valor actual del input (guardado al navegar historial)
  isExecuting: boolean;                  // Comando en ejecución
}
```

### Respuesta del API (ya existente)

```typescript
// Respuesta de workstationsApi.sendCommand para execute_remote_command
interface RemoteCommandResponse {
  success: boolean;
  stdout?: string;       // Output del comando (cuando success=true)
  output?: string;       // Mensaje de error (cuando success=false)
}
```

### Backend AuditLog Entry (registro nuevo)

| Campo | Valor |
|-------|-------|
| `action_type` | `REMOTE_COMMAND_EXECUTED` |
| `entity_type` | `"workstation"` |
| `entity_id` | ID de la workstation |
| `user_id` | ID del usuario que ejecutó |
| `organization_id` | Organización de la workstation |
| `new_values` | `{ command, command_id, success, stdout_preview }` |

### i18n Keys (namespace: `workstations`)

```json
{
  "remoteTerminal": "Terminal Remota",
  "remoteTerminalPlaceholder": "Escribe un comando...",
  "remoteTerminalOffline": "La workstation debe estar online para ejecutar comandos",
  "remoteTerminalExecute": "Ejecutar",
  "remoteTerminalExecuting": "Ejecutando...",
  "remoteTerminalTimeout": "Timeout — el comando no respondió en 45 segundos",
  "remoteTerminalError": "Error al ejecutar el comando",
  "remoteTerminalWsDisconnected": "La workstation se desconectó durante la ejecución",
  "remoteTerminalCopyHistory": "Copiar historial",
  "remoteTerminalCopied": "Historial copiado al portapapeles",
  "remoteTerminalNoOutput": "(sin salida)",
  "remoteTerminalClearHistory": "Limpiar"
}
```

## Error Handling

| Escenario | HTTP Status | Comportamiento Frontend |
|-----------|-------------|------------------------|
| Workstation offline al enviar | 409 | Mostrar error "La workstation está offline" en historial con estilo de error |
| Timeout (45s) | 408 | Mostrar mensaje de timeout en historial |
| Error interno backend | 500 | Mostrar mensaje genérico de error en historial |
| Workstation se desconecta mid-execution | 409 | Mostrar error "La workstation se desconectó" |
| Network error (sin conexión) | — | Mostrar error de conexión en historial |
| Comando vacío/whitespace | — | Prevenir submit (disabled button + no action on Enter) |
| Input mientras hay comando ejecutándose | — | Input y botón disabled, no se puede enviar |

**Estrategia de error en el componente:**

Todos los errores se muestran **inline en el historial** (no como toast), con un estilo visual distinto (texto rojo/naranja, fondo diferenciado). Esto permite al usuario ver el contexto del error junto al comando que lo causó.

```typescript
// En el hook, catch del mutation
onError: (error) => {
  const status = error?.status;
  let errorMessage: string;
  
  if (status === 408) {
    errorMessage = t('remoteTerminalTimeout');
  } else if (status === 409) {
    errorMessage = t('remoteTerminalWsDisconnected');
  } else {
    errorMessage = error?.detail || t('remoteTerminalError');
  }
  
  // Actualizar la entrada en historial con el error
  updateHistoryEntry(entryId, { output: errorMessage, isError: true, isLoading: false });
}
```

## Testing Strategy

### Justificación: PBT No Aplica

Property-based testing **no es apropiado** para esta feature porque:
1. Es primordialmente UI rendering e interacción (componentes React)
2. La operación central es una llamada REST (side-effect) sin lógica de transformación de datos
3. El historial de comandos es gestión básica de array sin invariantes complejas
4. La navegación por teclado es comportamiento UI que se prueba mejor con ejemplos concretos

### Unit Tests (Frontend)

**Componente `RemoteTerminalSection`:**
- Renderiza input y área de output cuando workstation está online y usuario es Admin/Operator
- No se renderiza cuando usuario es ReadOnly
- Muestra estado disabled con mensaje cuando workstation está offline
- Input deshabilitado mientras hay comando ejecutándose
- Botón ejecutar deshabilitado con input vacío o solo whitespace
- Auto-scroll al agregar nueva entrada al historial

**Hook `useRemoteTerminal`:**
- `executeCommand` agrega entrada al historial y llama API
- Historial se actualiza con stdout al recibir respuesta exitosa
- Historial se actualiza con error al recibir error HTTP
- `clearHistory` vacía el array de historial
- `copyHistory` formatea y copia al clipboard
- No permite ejecutar si ya hay comando en progreso

**Navegación por teclado:**
- Up arrow con historial vacío no hace nada
- Up arrow cicla hacia atrás por comandos ejecutados
- Down arrow cicla hacia adelante
- Down arrow desde último comando restaura input vacío

### Integration Tests (Frontend)

- Flujo completo: escribir comando → Enter → loading → output aparece
- Flujo de error: comando → timeout → mensaje de error en historial
- Sesión se limpia al cerrar/reabrir modal (mock de mount/unmount)

### Backend Tests

- Verificar que `REMOTE_COMMAND_EXECUTED` audit log se crea correctamente
- Verificar que el stdout_preview se trunca a 200 chars en el audit log

### Test Tools

- **Frontend**: Jest + React Testing Library (existente en el proyecto)
- **Backend**: pytest + httpx (existente en el proyecto)
