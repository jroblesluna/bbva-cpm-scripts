# Requirements Document

## Introduction

Esta feature agrega un componente de mini-terminal interactivo al panel de detalle de workstation en el Cloud Manager de AlwaysPrint. Permite a operadores y administradores ejecutar comandos arbitrarios del sistema operativo en una workstation remota conectada vía WebSocket, visualizar la salida (stdout) en tiempo real, y mantener un historial de comandos durante la sesión. El backend ya soporta el tipo de comando `execute_remote_command` vía `POST /api/v1/workstations/{id}/command`, que envía el comando por WebSocket a la workstation, la cual lo ejecuta con `cmd.exe /c <command>` como SYSTEM y retorna stdout.

## Glossary

- **Remote_Terminal**: Componente de interfaz de usuario que emula una terminal de comandos dentro del panel de detalle de workstation, permitiendo enviar comandos y ver la salida.
- **Operator**: Rol de usuario con permisos de gestión operativa sobre workstations de su organización.
- **Admin**: Rol de usuario con permisos globales de administración sobre todas las organizaciones y workstations.
- **ReadOnly**: Rol de usuario con permisos exclusivos de lectura, sin capacidad de ejecutar acciones.
- **Command_History**: Lista ordenada cronológicamente de los comandos ejecutados y sus respectivas salidas durante una sesión activa del panel de detalle.
- **Workstation_Detail_Modal**: Diálogo/modal que muestra información detallada de una workstation seleccionada, incluyendo secciones de estado, red, acciones OnDemand, comandos OS, y análisis de logs.
- **execute_remote_command**: Tipo de comando enviado al backend que instruye a la workstation a ejecutar un comando del sistema operativo vía `cmd.exe /c` como SYSTEM y retornar stdout.
- **Audit_Log**: Registro inmutable de acciones críticas del sistema, incluyendo usuario, workstation, organización y detalles de la operación.

## Requirements

### Requirement 1: Visualización del componente Remote Terminal

**User Story:** As an Admin or Operator, I want to see a mini-terminal section in the workstation detail modal, so that I can interact with the workstation's command line without leaving the dashboard.

#### Acceptance Criteria

1. WHEN the Workstation_Detail_Modal opens for an online workstation AND the current user has Admin or Operator role, THE Remote_Terminal SHALL display an input field and a command output area within the modal.
2. WHILE the workstation is offline, THE Remote_Terminal SHALL display a disabled state with a visual indicator explaining that the workstation must be online to execute commands.
3. WHEN the current user has ReadOnly role, THE Remote_Terminal SHALL NOT be rendered in the Workstation_Detail_Modal.
4. THE Remote_Terminal SHALL display all user-visible text via next-intl translation keys (namespace `workstations`), supporting both English and Spanish locales.

### Requirement 2: Ejecución de comandos remotos

**User Story:** As an Admin or Operator, I want to type and execute OS commands on the remote workstation, so that I can diagnose issues without needing direct access to the machine.

#### Acceptance Criteria

1. WHEN the user types a command in the input field and presses Enter or clicks the execute button, THE Remote_Terminal SHALL send the command to the backend via `POST /api/v1/workstations/{id}/command` with command_type `execute_remote_command`.
2. WHEN the user submits an empty or whitespace-only command, THE Remote_Terminal SHALL prevent submission and maintain the current state.
3. WHEN the command is submitted, THE Remote_Terminal SHALL clear the input field and set focus back to the input for the next command.
4. WHEN the command is submitted, THE Remote_Terminal SHALL display a loading indicator in the output area indicating that execution is in progress.
5. WHEN the backend returns a successful response with stdout, THE Remote_Terminal SHALL display the command and its output in the command output area using monospace font styling.
6. IF the backend returns an error (HTTP 500, 409, or 408), THEN THE Remote_Terminal SHALL display the error message in the output area with a distinct visual style differentiating it from successful output.
7. IF the backend returns HTTP 408 (timeout), THEN THE Remote_Terminal SHALL display a timeout message indicating that the 45-second limit was reached.

### Requirement 3: Historial de comandos de la sesión

**User Story:** As an Admin or Operator, I want to see the history of commands I have executed during this session, so that I can review previous outputs without re-executing commands.

#### Acceptance Criteria

1. THE Remote_Terminal SHALL maintain a scrollable Command_History displaying all commands executed and their outputs during the current modal session.
2. WHEN a new command result is received, THE Remote_Terminal SHALL append it to the Command_History and auto-scroll to the latest entry.
3. WHEN the Workstation_Detail_Modal is closed and reopened, THE Remote_Terminal SHALL start with an empty Command_History.
4. THE Command_History SHALL display each entry with the executed command text, a timestamp, and the resulting stdout or error message.
5. WHEN the Command_History contains content, THE Remote_Terminal SHALL provide a button to copy the full session history to the clipboard.

### Requirement 4: Estado de carga y timeout

**User Story:** As an Admin or Operator, I want clear feedback when a command is executing, so that I know the system is working and I can understand delays.

#### Acceptance Criteria

1. WHILE a command is being executed (awaiting backend response), THE Remote_Terminal SHALL display an animated loading indicator next to the pending command entry.
2. WHILE a command is being executed, THE Remote_Terminal SHALL disable the input field and execute button to prevent concurrent command submissions.
3. WHEN the response arrives (success or error), THE Remote_Terminal SHALL remove the loading indicator, re-enable the input field, and set focus to the input.

### Requirement 5: Control de acceso y seguridad

**User Story:** As a system administrator, I want the remote terminal to be restricted to authorized roles and audit all executions, so that command execution is traceable and secure.

#### Acceptance Criteria

1. THE Remote_Terminal SHALL only be accessible to users with Admin or Operator roles.
2. WHEN an Operator executes a command, THE backend SHALL verify that the target workstation belongs to the Operator's organization before executing.
3. WHEN a command is successfully sent to a workstation, THE backend SHALL create an Audit_Log entry with action_type `REMOTE_COMMAND_EXECUTED`, recording the user, workstation, command text, and execution result.
4. IF the workstation disconnects between the online check and command delivery, THEN THE Remote_Terminal SHALL display an appropriate error message indicating the workstation went offline.

### Requirement 6: Experiencia de usuario e interacción

**User Story:** As an Admin or Operator, I want the terminal to feel responsive and intuitive, so that I can efficiently diagnose workstation issues.

#### Acceptance Criteria

1. THE Remote_Terminal SHALL render the command output area with a dark background and light monospace font, visually differentiating it from the rest of the modal content.
2. WHEN the user presses the Up Arrow key in the input field, THE Remote_Terminal SHALL cycle backward through previously executed commands in the session.
3. WHEN the user presses the Down Arrow key in the input field, THE Remote_Terminal SHALL cycle forward through the command history, returning to an empty input after the most recent command.
4. THE Remote_Terminal input field SHALL display a prompt prefix (e.g., `>`) and placeholder text indicating the expected input.
5. WHEN the output of a single command exceeds the visible area, THE output section SHALL be independently scrollable within a bounded maximum height.
