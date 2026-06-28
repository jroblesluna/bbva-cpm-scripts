# Documento de Requisitos — Capturas de Debugging a Nivel de Organización

## Introducción

Esta funcionalidad agrega al sistema AlwaysPrint un mecanismo de **capturas de debugging orientadas a diagnóstico** que se definen a nivel de organización y se ejecutan sobre workstations individuales bajo demanda del administrador/operador.

El flujo completo es:
```
1. Admin define perfil de debugging (pestaña Debugging en config org, requiere LLM habilitado)
2. LLM sugiere nombre y mensaje de confirmación para el perfil
3. Perfil queda disponible en "Detalles" de cada workstation activa
4. Admin/Oper selecciona perfil → confirma ejecución (puede añadir motivo e instrucciones)
5. Backend crea debugging ID → envía instrucción vía WebSocket al cliente Windows
6. Cliente Windows inicia captura: snapshot inicial + monitoreo por duración configurada (15-300s)
7. Al finalizar (timeout o detención manual): snapshot final + extracción de logs/eventos
8. Cliente empaqueta todo en carpeta temporal con índice → notifica "listo para recolección"
9. Admin/Oper decide: Analizar (ZIP → upload → LLM → PDF) o Eliminar (borrar del cliente)
```

**Prerequisito**: La organización debe tener LLM habilitado (campo `llm_model_id` o `openai_api_key` configurado) para acceder a la pestaña de Debugging.

**Restricción**: Solo un debugging activo por workstation a la vez.

## Glosario

- **Debugging_Profile**: Definición de qué monitorear durante una sesión de debugging. Se configura a nivel de organización.
- **Debugging_Session**: Instancia de ejecución de un Debugging_Profile sobre una workstation específica, con ID único.
- **Debugging_ID**: Identificador UUID único generado por el backend para cada sesión de debugging.
- **External_Log**: Archivo de log externo a AlwaysPrint que se desea monitorear (ruta absoluta o patrón glob).
- **EventLog_Group**: Grupo de eventos Windows a monitorear: System, Application, o Security.
- **Registry_Key**: Llave de registro Windows cuyas claves (values) se capturan al inicio y fin del debugging.
- **Monitored_Service**: Nombre de servicio Windows cuyo estado se captura al inicio y fin del debugging.
- **Capture_Duration**: Tiempo en segundos que dura la captura (15-300s, recomendado 60s).
- **Snapshot_Inicial**: Captura del estado de servicios y valores de registro al momento de iniciar el debugging.
- **Snapshot_Final**: Captura del estado de servicios y valores de registro al momento de finalizar el debugging.
- **Index_File**: Archivo JSON dentro de la carpeta de debugging que describe el contenido total y cada archivo incluido.
- **LLM_Enablement**: Condición de que la organización tenga configurado un modelo LLM (Bedrock o OpenAI) para poder usar debugging.

## Requisitos

### Requisito 1: Pestaña de Debugging en configuración de organización (con gate de LLM)

**User Story:** Como administrador, quiero definir perfiles de debugging en la configuración de mi organización, para poder diagnosticar problemas en workstations de forma estructurada y repetible.

#### Criterios de Aceptación

1. THE frontend SHALL display a "Debugging" tab in the organization configuration page ONLY WHEN the organization has LLM enabled (field `llm_model_id` is not null OR `openai_api_key` is not null).
2. WHEN the organization does not have LLM enabled, THE frontend SHALL NOT show the "Debugging" tab and SHALL display a message indicating that LLM enablement is required.
3. THE "Debugging" tab SHALL allow creating multiple Debugging_Profiles, each containing: a list of External_Logs, selected EventLog_Groups, a list of Registry_Keys, a list of Monitored_Services, and a description of what is being monitored and the objective.
4. EACH External_Log entry SHALL accept an absolute path (e.g., `C:\Logs\app.log`) or a glob pattern (e.g., `C:\Logs\*.log`).
5. EACH EventLog_Group entry SHALL be selectable from the options: System, Application, Security. The admin may select one or more.
6. EACH Registry_Key entry SHALL accept a full registry path (e.g., `HKLM\SOFTWARE\Lexmark\CPM`) and the system will capture all values (claves) at that single level (non-recursive).
7. EACH Monitored_Service entry SHALL accept a Windows service name (e.g., `Spooler`, `LPDSVC`, `lpmc_universal_service`).
8. THE description field SHALL be a free-text area where the admin describes what is being monitored and the objective of this debugging profile.
9. THE backend SHALL store Debugging_Profiles associated with the organization (tenant-isolated via `organization_id`).
10. THE backend SHALL validate that at least one monitoring target is defined (at least one External_Log, one EventLog_Group, one Registry_Key, or one Monitored_Service).

### Requisito 2: Sugerencia de nombre y mensaje por LLM al guardar perfil

**User Story:** Como administrador, quiero que el sistema sugiera automáticamente un nombre descriptivo y un mensaje de confirmación para el perfil de debugging, para agilizar la creación y asegurar claridad al ejecutarlo.

#### Criterios de Aceptación

1. WHEN the admin clicks "Guardar" on a new or edited Debugging_Profile, THE backend SHALL invoke the organization's configured LLM with the profile definition (targets + description) to generate a suggested name and a confirmation message.
2. THE LLM suggestion SHALL include: a short descriptive name (max 60 characters) and a confirmation message (max 200 characters) explaining what the debugging will capture.
3. THE frontend SHALL present the LLM suggestions to the admin in an editable form, allowing the admin to accept, modify, or override both the name and confirmation message before saving.
4. WHEN the admin confirms the name and message, THE backend SHALL persist the Debugging_Profile with the final name and confirmation message.
5. IF the LLM invocation fails, THE frontend SHALL allow the admin to manually enter the name and confirmation message with a warning that auto-suggestion failed.
6. THE saved Debugging_Profile SHALL appear as "Debugging disponible" in the workstation detail view for all active workstations.

### Requisito 3: Disponibilidad del debugging en vista de detalle de workstation

**User Story:** Como administrador/operador, quiero ver los perfiles de debugging disponibles en la ventana de detalles de cada workstation activa, para poder iniciar una captura de diagnóstico cuando lo necesite.

#### Criterios de Aceptación

1. THE workstation detail view SHALL display a section "Debugging disponible" listing all active Debugging_Profiles defined for the workstation's organization.
2. EACH listed profile SHALL show its name (as suggested/confirmed by LLM) and a brief description.
3. THE section SHALL only be visible when the organization has LLM enabled AND at least one Debugging_Profile exists.
4. WHEN the workstation is offline (WebSocket disconnected), THE debugging profiles SHALL be shown as disabled with a tooltip indicating the workstation must be online.
5. WHEN a debugging session is already active on the workstation, THE frontend SHALL disable all other debugging profiles and show the active session's status (elapsed time, remaining time).

### Requisito 4: Inicio de sesión de debugging (confirmación y parámetros)

**User Story:** Como administrador/operador, quiero confirmar la ejecución de un debugging con opción de añadir motivo e instrucciones adicionales, para documentar el contexto del diagnóstico y guiar el análisis posterior.

#### Criterios de Aceptación

1. WHEN the admin/oper clicks "Iniciar Debugging" on a profile, THE frontend SHALL show a confirmation dialog containing: the profile name, the profile description (confirmation message from LLM), a duration selector (15-300 seconds, default 60), an optional "Motivo" text field, and an optional "Instrucciones adicionales para el debugging" text area.
2. THE confirmation dialog SHALL display all monitoring targets (logs, events, registry, services) as a read-only summary so the admin knows exactly what will be captured.
3. WHEN the admin confirms, THE frontend SHALL send to the backend: the profile ID, the target workstation ID, the selected duration, and optionally the motivo and additional instructions.
4. THE backend SHALL generate a unique Debugging_ID (UUID) and create a Debugging_Session record with status "active", start timestamp, expected end timestamp, profile reference, workstation reference, motivo, and additional instructions.
5. THE backend SHALL send a WebSocket command to the target workstation with the Debugging_ID, the full profile definition (all monitoring targets), and the capture duration in seconds.
6. IF the workstation does not acknowledge the debugging start within 10 seconds, THE backend SHALL mark the session as "failed" and notify the frontend.
7. THE backend SHALL enforce that only one Debugging_Session can be active per workstation at any time.

### Requisito 5: Inicio de captura en el cliente Windows

**User Story:** Como cliente Windows, quiero recibir la instrucción de debugging y comenzar la captura de datos según el perfil definido, para recopilar la información de diagnóstico requerida.

#### Criterios de Aceptación

1. WHEN the client receives a StartDebugging WebSocket command, THE client SHALL create a temporary folder named with the Debugging_ID (e.g., `%TEMP%\AlwaysPrint\Debug\{debugging_id}\`).
2. THE client SHALL record the exact start timestamp (fecha y hora) of the debugging session.
3. THE client SHALL capture the Snapshot_Inicial: the current state (Running/Stopped/etc.) of each Monitored_Service specified in the profile, saved to a file `services_initial.json`.
4. THE client SHALL capture the Snapshot_Inicial: the current values of all claves within each Registry_Key specified in the profile (single level, non-recursive), saved to a file `registry_initial.json`.
5. THE client SHALL record the current total line count of each External_Log file (to know from which line to extract at the end of debugging). If a glob pattern is specified, resolve it to actual file paths at this moment.
6. THE client SHALL record the current line count of the AlwaysPrint log file for the current day.
7. THE client SHALL start a timer for the specified Capture_Duration (15-300 seconds, max enforced at 300s client-side).
8. THE client SHALL create an Index_File (`index.json`) in the temporary folder describing the debugging session metadata (debugging_id, profile_name, start_time, duration, targets) and will be updated with file references as they are added.
9. THE client SHALL acknowledge the debugging start to the backend via WebSocket with the Debugging_ID and status "capturing".
10. IF any monitored target is inaccessible (file not found, registry key doesn't exist, service not found), THE client SHALL log the error in the index file under an "errors" array but continue with the remaining targets.

### Requisito 6: Finalización de la captura (timeout o detención manual)

**User Story:** Como cliente Windows, quiero finalizar la captura al cumplirse el plazo o al recibir orden del backend, para recopilar los datos del período de monitoreo y preparar la entrega.

#### Criterios de Aceptación

1. THE client SHALL stop the debugging capture when ANY of these conditions is met: (a) the Capture_Duration timer expires, (b) the client receives a StopDebugging WebSocket command from the backend, (c) the elapsed time reaches 300 seconds (hard max enforced client-side regardless of configured duration).
2. THE client SHALL record the exact end timestamp of the debugging session.
3. THE client SHALL extract from the AlwaysPrint log: all lines from the line count recorded at start to the current end of file, saving them to a file `alwaysprint_log.txt` in the temporary folder.
4. THE client SHALL extract from each External_Log: all lines from the line count recorded at start to the current end of file, saving each to a separate file named `ext_log_{sanitized_filename}.txt` in the temporary folder. If the file has grown, extract only the new lines.
5. THE client SHALL extract Windows Event Log entries for each selected EventLog_Group (System, Application, Security): all entries with TimeGenerated between the start and end timestamps of the debugging session, saving each group to a separate file `events_{group_name}.txt` in the temporary folder.
6. THE client SHALL capture the Snapshot_Final: the current state of each Monitored_Service, saved to `services_final.json`.
7. THE client SHALL capture the Snapshot_Final: the current values of all claves within each Registry_Key, saved to `registry_final.json`.
8. THE client SHALL update the Index_File with: end_time, all file references (filename, description, size_bytes), total file count, and any errors encountered during extraction.
9. EACH deliverable (log extract, event extract, service snapshot, registry snapshot) SHALL be a separate file referenced by the Index_File.
10. THE client SHALL notify the backend via WebSocket that the debugging data is "ready_for_collection" with the Debugging_ID and total data size.

### Requisito 7: Visualización de estado del debugging en el frontend

**User Story:** Como administrador/operador, quiero ver en tiempo real el estado de la sesión de debugging activa, para saber cuándo puedo proceder con el análisis o decidir detenerla anticipadamente.

#### Criterios de Aceptación

1. WHILE a debugging session is active, THE frontend SHALL display in the workstation detail: the profile name, elapsed time, remaining time (countdown), and a "Detener Debugging" button.
2. WHEN the admin/oper clicks "Detener Debugging", THE frontend SHALL send a stop request to the backend, which forwards StopDebugging via WebSocket to the client.
3. WHEN the backend receives the "ready_for_collection" notification from the client, THE backend SHALL update the session status to "ready" and notify the frontend.
4. THE frontend SHALL display the session as "Datos disponibles" with two action buttons: "Analizar" and "Eliminar".
5. THE frontend SHALL show the total data size reported by the client alongside the "Datos disponibles" status.

### Requisito 8: Recolección y análisis con LLM (flujo "Analizar")

**User Story:** Como administrador/operador, quiero que al seleccionar "Analizar", el sistema recopile los datos del cliente, los envíe al LLM junto con el contexto del debugging, y genere un reporte PDF descargable.

#### Criterios de Aceptación

1. WHEN the admin/oper clicks "Analizar", THE backend SHALL send a WebSocket command to the client requesting the ZIP upload.
2. THE client SHALL compress the entire temporary folder (all files including index.json) into a single ZIP file named `debug_{debugging_id}.zip`.
3. AFTER creating the ZIP, THE client SHALL delete the original uncompressed files from the temporary folder, keeping only the ZIP.
4. THE client SHALL upload the ZIP to the backend via a dedicated HTTP endpoint (POST `/api/v1/debugging/{debugging_id}/upload`).
5. THE backend SHALL receive the ZIP, decompress it, read the Index_File, and organize all deliverables.
6. THE backend SHALL construct an LLM prompt containing: (a) the debugging objective/description from the profile, (b) the motivo provided by the admin/oper (if any), (c) the additional instructions (if any), (d) the index file content for context, (e) relevant extracts from each deliverable file (service diffs, registry diffs, log extracts, event extracts).
7. THE backend SHALL invoke the organization's configured LLM (respecting `llm_model_id` or `openai_api_key` per existing log_analysis pattern) with the constructed prompt.
8. THE backend SHALL generate a PDF report from the LLM response, including: header with debugging metadata (ID, profile, workstation, timestamps, duration), the LLM analysis/conclusions, and appendices with key data summaries.
9. THE backend SHALL upload the PDF to S3 (key: `debugging/{org_id}/{debugging_id}/report.pdf`) and store the S3 reference in the Debugging_Session record.
10. THE backend SHALL delete the local ZIP file after processing (the PDF in S3 is the permanent artifact).
11. THE frontend SHALL show a download link for the PDF once generation is complete.
12. IF the LLM invocation fails, THE backend SHALL retry up to 2 times with 5-second delay. If all retries fail, mark session as "analysis_failed" and notify frontend with error details.

### Requisito 9: Eliminación de datos (flujo "Eliminar")

**User Story:** Como administrador/operador, quiero poder eliminar los datos de debugging del cliente sin analizarlos, para casos donde la captura no fue útil o se hizo por error.

#### Criterios de Aceptación

1. WHEN the admin/oper clicks "Eliminar", THE frontend SHALL show a brief confirmation dialog.
2. WHEN confirmed, THE backend SHALL send a WebSocket command to the client requesting deletion of the debugging folder (ZIP and any remaining files) for the given Debugging_ID.
3. THE client SHALL delete the entire temporary folder for that Debugging_ID (including ZIP if it exists).
4. THE client SHALL acknowledge deletion to the backend via WebSocket.
5. THE backend SHALL update the Debugging_Session status to "deleted".
6. THE frontend SHALL remove the session from the active view and show a confirmation toast.

### Requisito 10: Descarga del ZIP desde la workstation

**User Story:** Como administrador/operador, quiero poder descargar el ZIP crudo directamente desde la workstation si aún existe, para casos donde necesito los datos originales sin procesamiento LLM.

#### Criterios de Aceptación

1. WHEN the debugging session status is "ready" or "analyzed" AND the ZIP still exists on the workstation, THE frontend SHALL offer a "Descargar ZIP" action.
2. THE backend SHALL send a WebSocket command to the client requesting the ZIP upload to the same dedicated endpoint.
3. THE backend SHALL stream the ZIP directly to the admin/oper's browser as a download (without storing it permanently on the backend).
4. IF the ZIP no longer exists on the workstation (client deleted it or workstation was reimaged), THE client SHALL respond with an error and THE frontend SHALL inform the admin that the raw data is no longer available.

### Requisito 11: Endpoint dedicado para upload de ZIP

**User Story:** Como sistema backend, quiero un endpoint HTTP dedicado para recibir el ZIP de debugging desde el cliente Windows, separado del flujo WebSocket para manejar uploads grandes de forma eficiente.

#### Criterios de Aceptación

1. THE backend SHALL expose `POST /api/v1/debugging/{debugging_id}/upload` accepting multipart/form-data with the ZIP file.
2. THE endpoint SHALL validate that the Debugging_ID exists and belongs to the requesting workstation's organization.
3. THE endpoint SHALL validate that the session status is "ready" (not already analyzed or deleted).
4. THE endpoint SHALL accept files up to 100MB maximum size, returning HTTP 413 if exceeded.
5. THE endpoint SHALL authenticate the request using the workstation's existing authentication mechanism (workstation_id header or token).
6. AFTER successful upload, THE backend SHALL update the session status to "uploading_complete" and begin the analysis pipeline.

### Requisito 12: Modelo de datos para Debugging_Profile y Debugging_Session

**User Story:** Como sistema backend, quiero modelos de datos persistentes para perfiles y sesiones de debugging, con tenant isolation y trazabilidad completa.

#### Criterios de Aceptación

1. THE Debugging_Profile model SHALL include: id (UUID), organization_id (FK), name (string, max 60), description (text), confirmation_message (string, max 200), external_logs (JSON array of paths/patterns), eventlog_groups (JSON array of selected groups), registry_keys (JSON array of registry paths), monitored_services (JSON array of service names), is_active (boolean), created_at, updated_at, created_by (FK to user).
2. THE Debugging_Session model SHALL include: id/debugging_id (UUID), organization_id (FK), profile_id (FK to Debugging_Profile), workstation_id (FK), status (enum: active, ready, uploading, analyzing, analyzed, analysis_failed, deleted, failed), duration_seconds (int), start_time (datetime), end_time (datetime, nullable), motivo (text, nullable), additional_instructions (text, nullable), total_data_size_bytes (bigint, nullable), s3_report_key (string, nullable), initiated_by (FK to user), created_at.
3. ALL queries on both models SHALL filter by organization_id (tenant isolation).
4. THE Debugging_Session status transitions SHALL be: active → ready → uploading → analyzing → analyzed; active → ready → deleted; active → failed.

### Requisito 13: Comunicación WebSocket para debugging

**User Story:** Como sistema, quiero comandos WebSocket bien definidos para orquestar el flujo de debugging entre backend y cliente Windows.

#### Criterios de Aceptación

1. THE backend SHALL define a WebSocket command `StartDebugging` with payload: debugging_id, profile (full definition with all monitoring targets), duration_seconds.
2. THE backend SHALL define a WebSocket command `StopDebugging` with payload: debugging_id.
3. THE backend SHALL define a WebSocket command `RequestDebugUpload` with payload: debugging_id.
4. THE backend SHALL define a WebSocket command `DeleteDebugData` with payload: debugging_id.
5. THE client SHALL send WebSocket messages for: `DebuggingStarted` (debugging_id, status="capturing"), `DebuggingReady` (debugging_id, status="ready_for_collection", total_size_bytes), `DebuggingDeleted` (debugging_id), `DebuggingError` (debugging_id, error_message).
6. ALL debugging WebSocket messages SHALL include the debugging_id for correlation.

### Requisito 14: Seguridad y control de acceso

**User Story:** Como sistema, quiero asegurar que solo usuarios autorizados puedan crear perfiles y ejecutar sesiones de debugging, con trazabilidad completa.

#### Criterios de Aceptación

1. ONLY users with admin role SHALL be able to create, edit, or delete Debugging_Profiles.
2. BOTH admin and operator roles SHALL be able to initiate debugging sessions, stop them, request analysis, or delete data.
3. THE backend SHALL record which user initiated each Debugging_Session (initiated_by field).
4. THE backend SHALL record which user created each Debugging_Profile (created_by field).
5. THE client SHALL only accept StartDebugging/StopDebugging/RequestDebugUpload/DeleteDebugData commands from its authenticated WebSocket connection (backend-originated).
6. THE upload endpoint SHALL validate workstation identity to prevent unauthorized uploads.

### Requisito 15: Manejo de errores y edge cases

**User Story:** Como sistema, quiero manejar gracefully los escenarios de error durante el debugging, para evitar datos huérfanos y estados inconsistentes.

#### Criterios de Aceptación

1. IF the workstation disconnects during an active debugging session, THE backend SHALL mark the session as "failed" after 30 seconds without reconnection.
2. IF the workstation reconnects after a disconnection during active debugging, THE client SHALL check if it has an active debugging timer running and continue normally (the session is local to the client).
3. IF the client encounters an error during capture (cannot read a log, registry access denied, etc.), THE client SHALL log the error in the index file but continue capturing other targets.
4. IF the ZIP upload fails (network error, timeout), THE client SHALL retain the ZIP locally and THE backend SHALL allow retrying the upload via a new RequestDebugUpload command.
5. IF the analysis LLM call exceeds the context window (too much data), THE backend SHALL truncate the deliverables intelligently (prioritize errors, recent events, and diffs over full logs) and retry.
6. THE client SHALL enforce a maximum total capture folder size of 50MB. If exceeded during capture, stop early and note the truncation in the index file.
7. WHEN a debugging session has been in "ready" status for more than 24 hours without action (no analysis or deletion requested), THE backend SHALL send a reminder notification to the frontend but SHALL NOT auto-delete.
