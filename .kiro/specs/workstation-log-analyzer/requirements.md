# Requirements Document

## Introduction

Servicio backend de análisis de logs de estaciones de trabajo AlwaysPrint, integrado en el backend FastAPI existente (`AlwaysPrintProject/Cloud/backend/`). El análisis se ejecuta **bajo demanda** cuando un administrador u operador solicita el diagnóstico de una workstation específica desde el dashboard frontend.

El flujo completo es:
```
Admin solicita análisis → Backend envía comando vía WebSocket a Workstation →
Workstation lee log → (comprime a ZIP si <50KB) → Envía al Backend →
Backend descomprime si ZIP →
  SI <100KB: log crudo + prompt → LLM → respuesta de análisis
  SI ≥100KB: análisis estructural → datos estructurados + prompt → LLM → respuesta de análisis
→ Respuesta mostrada al Admin en el dashboard
```

- **Logs pequeños (<100KB)**: Se envían completos directamente al LLM (AWS Bedrock Claude) junto con el prompt de análisis, sin procesamiento estructural previo.
- **Logs grandes (≥100KB)**: Se realiza análisis estructural completo (detección de keywords, normalización, ventanas de contexto, agrupación de patrones, línea de tiempo) y se envía el resultado estructurado al LLM con el prompt de análisis.

Los umbrales de compresión (50KB) y de procesamiento (100KB) son parámetros configurables. La respuesta del LLM se presenta al administrador en el dashboard frontend.

## Glossary

- **Log_Analyzer_Service**: Servicio backend (módulo dentro de FastAPI en `AlwaysPrintProject/Cloud/backend/`) que recibe, procesa y analiza logs de workstations.
- **Workstation_Client**: Cliente AlwaysPrint instalado en la workstation Windows que envía logs automáticamente al backend.
- **Compression_Threshold**: Umbral configurable (default 50KB) por debajo del cual el Workstation_Client comprime el log a ZIP antes de enviarlo.
- **Processing_Threshold**: Umbral configurable (default 100KB) que determina si el log se envía crudo al LLM o se procesa estructuralmente antes.
- **Context_Window**: Conjunto de líneas antes y después de un hallazgo relevante que proporcionan contexto para el análisis.
- **Keyword_Pattern**: Patrón regex utilizado para detectar líneas relevantes en los logs (error, exception, failed, timeout, etc.).
- **Normalized_Line**: Línea de log donde timestamps, números, UUIDs, IPs y rutas temporales han sido reemplazados por placeholders genéricos para agrupar errores repetidos.
- **Context_Block**: Bloque de líneas numeradas alrededor de un hallazgo, con la línea del hallazgo marcada con `>>`.
- **Structured_Analysis**: Resultado del análisis estructural de logs grandes, conteniendo metadata, patrones recurrentes, primeras ocurrencias críticas, bloques de contexto, línea de tiempo condensada y prompt para LLM.
- **Condensed_Timeline**: Representación cronológica de eventos agrupados por timestamp/minuto/hora.
- **Recurring_Pattern**: Patrón normalizado que aparece múltiples veces en los logs, con conteo de ocurrencias.
- **Critical_Occurrence**: Primera aparición de un error importante, identificada por número de línea y timestamp.
- **LLM_Prompt**: Prompt pre-construido enviado al LLM junto con el log (crudo o estructurado) para análisis de causa raíz.
- **LLM_Response**: Respuesta generada por el modelo LLM con el análisis de causa raíz, entregada al administrador vía frontend.

## Requirements

### Requirement 1: Solicitud de análisis bajo demanda por el administrador

**User Story:** Como administrador u operador, quiero solicitar el análisis de logs del día en curso de una workstation específica desde la sección Workstations del dashboard, para diagnosticar problemas cuando lo necesite.

#### Acceptance Criteria

1. THE frontend dashboard SHALL display an "Analizar Log" action button in the workstation actions menu (alongside existing actions like enter/exit contingency, restart service, get logs, restart tray, request check for updates) for each individual workstation
2. WHEN the admin clicks "Analizar Log" on a specific workstation, THE frontend SHALL send a request to the backend API indicating the target workstation identifier
3. THE backend SHALL send a command to the target Workstation_Client via the existing WebSocket connection, requesting that it upload its log file for the current day only
4. THE Workstation_Client SHALL respond to the log analysis command by reading only the current day's log file (the log file corresponding to today's date)
5. WHEN the current day's log file size is less than the Compression_Threshold (default 50KB), THE Workstation_Client SHALL compress the log file to ZIP format before sending it to the backend
6. WHEN the current day's log file size is equal to or greater than the Compression_Threshold, THE Workstation_Client SHALL send the log file without compression
7. THE Workstation_Client SHALL include in the upload: workstation identifier, organization identifier, original file name, original file size in bytes, and a flag indicating whether the payload is compressed
8. IF the Workstation_Client is offline (WebSocket disconnected), THEN THE backend SHALL return an error to the frontend indicating the workstation is not reachable
9. IF the Workstation_Client does not respond within 30 seconds, THEN THE backend SHALL return a timeout error to the frontend
10. THE Compression_Threshold SHALL be configurable via the workstation configuration without requiring a client update
11. THE frontend SHALL show a loading/progress indicator while waiting for the analysis result, and display the LLM analysis response once available

### Requirement 2: Recepción y descompresión de logs en el backend

**User Story:** Como servicio backend, quiero recibir logs de las workstations y descomprimirlos si vienen en formato ZIP, para tener el contenido del log disponible para procesamiento.

#### Acceptance Criteria

1. THE Log_Analyzer_Service SHALL expose an API endpoint that accepts log file uploads via HTTP POST with multipart/form-data encoding
2. WHEN the received payload has the compression flag set to true, THE Log_Analyzer_Service SHALL decompress the ZIP payload and extract the log file content
3. WHEN the received payload has the compression flag set to false, THE Log_Analyzer_Service SHALL use the raw payload directly as the log content
4. IF the ZIP payload cannot be decompressed (corrupted archive or invalid format), THEN THE Log_Analyzer_Service SHALL return an HTTP 422 response with an error message indicating the decompression failure
5. THE Log_Analyzer_Service SHALL validate that the extracted content contains at least one file with a supported extension (`.log` or `.txt`)
6. IF the extracted ZIP contains multiple log files, THEN THE Log_Analyzer_Service SHALL concatenate them in alphabetical order by filename, separated by a header line indicating the source file name
7. THE Log_Analyzer_Service SHALL validate the request includes valid workstation identifier and organization identifier, returning HTTP 401 if authentication fails
8. THE Log_Analyzer_Service SHALL enforce a maximum upload size of 50MB, returning HTTP 413 if exceeded

### Requirement 3: Enrutamiento por tamaño de log

**User Story:** Como servicio backend, quiero determinar automáticamente si un log necesita análisis estructural previo o puede enviarse directamente al LLM, para optimizar el procesamiento según la complejidad del log.

#### Acceptance Criteria

1. WHEN the decompressed log content size is less than the Processing_Threshold (default 100KB), THE Log_Analyzer_Service SHALL route the log to the direct LLM path (send raw content with prompt, without structural analysis)
2. WHEN the decompressed log content size is equal to or greater than the Processing_Threshold, THE Log_Analyzer_Service SHALL route the log to the structural analysis path before sending to the LLM
3. THE Processing_Threshold SHALL be configurable via environment variable or backend configuration without requiring a code deployment
4. THE Log_Analyzer_Service SHALL log the routing decision (direct or structural) along with the log size and workstation identifier for observability

### Requirement 4: Procesamiento directo de logs pequeños (ruta directa al LLM)

**User Story:** Como servicio backend, quiero enviar logs pequeños directamente al LLM sin procesamiento previo, para obtener análisis rápidos sin la sobrecarga del análisis estructural.

#### Acceptance Criteria

1. WHEN a log is routed to the direct LLM path, THE Log_Analyzer_Service SHALL send the complete raw log content together with the LLM_Prompt to the LLM model without performing keyword detection, normalization, context extraction, or pattern grouping
2. THE Log_Analyzer_Service SHALL prepend the LLM_Prompt before the raw log content, separated by a clear delimiter indicating where the prompt ends and the log begins
3. THE Log_Analyzer_Service SHALL include basic metadata (workstation identifier, original file name, file size, timestamp of upload) in the prompt context sent to the LLM
4. IF the LLM returns an error response, THEN THE Log_Analyzer_Service SHALL retry the request up to 2 times with a 3-second delay between attempts before returning an error to the caller

### Requirement 5: Análisis estructural de logs grandes - Detección de líneas relevantes

**User Story:** Como servicio backend, quiero detectar automáticamente líneas con errores, advertencias y eventos críticos en logs grandes, para extraer solo la información relevante antes de enviarla al LLM.

#### Acceptance Criteria

1. WHEN a log is routed to the structural analysis path, THE Log_Analyzer_Service SHALL read the log content line by line using a streaming approach without loading the entire file into memory, such that peak memory usage attributable to file reading does not exceed 100 MB regardless of log size
2. THE Log_Analyzer_Service SHALL detect relevant lines by performing substring matching against the following default Keyword_Patterns: `error`, `exception`, `failed`, `failure`, `timeout`, `denied`, `refused`, `unreachable`, `fatal`, `warn`, `warning`, `access denied`, `connection refused`, `SSL`, `TLS`, `certificate`, `proxy`, `authentication`, `unauthorized`, `forbidden`, `service stopped`, `service started`, `crash`, `retry`, `reconnect`
3. THE Log_Analyzer_Service SHALL perform case-insensitive matching by default
4. THE Log_Analyzer_Service SHALL record the line number (1-based), timestamp (if present in "YYYY-MM-DD HH:MM:SS" format), and full content (up to 10,000 characters per line) of each matching line
5. THE Log_Analyzer_Service SHALL handle file encoding with tolerance using `errors="replace"` to avoid crashes on malformed characters
6. IF no lines match any pattern in the log, THEN THE Log_Analyzer_Service SHALL include the first 50 lines and last 50 lines as a sample in the structured output, with a note indicating no obvious errors were detected

### Requirement 6: Análisis estructural - Extracción de ventanas de contexto

**User Story:** Como servicio backend, quiero extraer las líneas antes y después de cada hallazgo, para proporcionar contexto al LLM sobre el entorno en que ocurrió cada error.

#### Acceptance Criteria

1. WHEN a matching line is found during structural analysis, THE Log_Analyzer_Service SHALL extract a Context_Window of configurable size (default 20 lines before and 20 lines after the match)
2. THE Context_Window size SHALL be configurable via backend configuration (valid range 0 to 500 lines)
3. WHEN a matching line is located fewer than N lines from the beginning or end of the log, THE Log_Analyzer_Service SHALL extract all available lines up to the boundary without producing an error
4. WHEN two or more Context_Windows overlap or are adjacent (separated by zero lines), THE Log_Analyzer_Service SHALL merge them into a single contiguous Context_Block without repeating lines
5. THE Log_Analyzer_Service SHALL limit the total number of Context_Blocks to a configurable maximum (default 30, valid range 1 to 1000)
6. WHEN the number of candidate Context_Blocks exceeds the maximum limit, THE Log_Analyzer_Service SHALL retain blocks containing the first occurrence of each distinct error pattern and discard remaining blocks in reverse chronological order
7. WHEN one or more Context_Blocks are discarded due to the limit, THE Log_Analyzer_Service SHALL append a summary note indicating the number of additional blocks omitted

### Requirement 7: Análisis estructural - Normalización y agrupación de patrones

**User Story:** Como servicio backend, quiero que errores repetidos se agrupen automáticamente, para que el LLM reciba información consolidada sobre los problemas más frecuentes.

#### Acceptance Criteria

1. THE Log_Analyzer_Service SHALL apply normalization replacements in the following fixed order: timestamps, UUIDs, IPv4 addresses, Windows temporary paths, and numeric sequences, so that specific patterns are captured before the general numeric replacement
2. THE Log_Analyzer_Service SHALL normalize matching lines by replacing timestamps in "YYYY-MM-DD HH:MM:SS" format with `[TIMESTAMP]`
3. THE Log_Analyzer_Service SHALL normalize matching lines by replacing UUID patterns matching the format `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` (where x is a case-insensitive hexadecimal digit) with `[UUID]`
4. THE Log_Analyzer_Service SHALL normalize matching lines by replacing IPv4 addresses matching the format `N.N.N.N` (where each N is a number from 0 to 255) with `[IP]`
5. THE Log_Analyzer_Service SHALL normalize matching lines by replacing the full file path segment that contains `\Temp\` or `\tmp\` (case-insensitive, from the drive letter or UNC prefix through the end of the path token) with `[TEMP_PATH]`
6. THE Log_Analyzer_Service SHALL normalize matching lines by replacing numeric sequences of 2 or more consecutive digits with `[NUMBER]`, applied after all other normalization rules
7. THE Log_Analyzer_Service SHALL group matching lines by their Normalized_Line and count occurrences of each unique Normalized_Line, classifying those with 2 or more occurrences as a Recurring_Pattern

### Requirement 8: Análisis estructural - Primeras ocurrencias y línea de tiempo

**User Story:** Como servicio backend, quiero identificar cuándo apareció por primera vez cada tipo de error y generar una línea de tiempo condensada, para que el LLM pueda establecer la secuencia temporal de la degradación.

#### Acceptance Criteria

1. THE Log_Analyzer_Service SHALL identify the first occurrence of each unique Recurring_Pattern, including the pattern identifier, line number, and timestamp (if available)
2. THE Log_Analyzer_Service SHALL record the line number and timestamp of each Critical_Occurrence, using the value "N/A" for the timestamp field when the log entry does not contain a parseable timestamp
3. IF all Critical_Occurrences contain parseable timestamps, THEN THE Log_Analyzer_Service SHALL sort Critical_Occurrences in ascending chronological order by timestamp
4. IF no log entries contain parseable timestamps, THEN THE Log_Analyzer_Service SHALL sort Critical_Occurrences in ascending order by line number
5. THE Log_Analyzer_Service SHALL parse timestamps from log lines using the format `yyyy-MM-dd HH:mm:ss`
6. IF the time span between the first and last parsed timestamp is less than or equal to 1 hour, THEN THE Log_Analyzer_Service SHALL group events by minute in the Condensed_Timeline
7. IF the time span between the first and last parsed timestamp is greater than 1 hour, THEN THE Log_Analyzer_Service SHALL group events by hour in the Condensed_Timeline
8. THE Log_Analyzer_Service SHALL include, for each time group in the Condensed_Timeline, the total count of events and a list of distinct event types with their respective counts, ordered chronologically by time group
9. WHEN no parseable timestamps are found, THE Log_Analyzer_Service SHALL omit the Condensed_Timeline section and include a note indicating timestamps were not detected

### Requirement 9: Generación de datos estructurados para el LLM

**User Story:** Como servicio backend, quiero generar un bloque de texto estructurado en Markdown con toda la evidencia extraída del análisis estructural, para enviarlo al LLM como contexto de análisis.

#### Acceptance Criteria

1. THE Log_Analyzer_Service SHALL generate the Structured_Analysis as a text block in Markdown format containing sections in the following fixed order: Metadata, Top Recurring Patterns, First Critical Occurrences, Context Blocks, and Condensed Timeline
2. THE Structured_Analysis SHALL include a Metadata section with: workstation identifier, original file name, original file size in bytes, total lines, timestamp range (earliest and latest timestamps found), total matches, and count of unique patterns
3. THE Structured_Analysis SHALL include a Top Recurring Patterns section showing the top N patterns (configurable, default 50) with normalized pattern, occurrence count, and one raw example truncated to 500 characters with ellipsis if exceeded
4. THE Structured_Analysis SHALL include a First Critical Occurrences section listing the first occurrence of each unique pattern, showing line number, timestamp, and raw content truncated to 500 characters with ellipsis if exceeded
5. THE Structured_Analysis SHALL include a Context Blocks section with numbered lines and the matching line prefixed with `>>`
6. THE Structured_Analysis SHALL include a Condensed Timeline section with events grouped by time period
7. WHEN the log contained multiple source files (from a ZIP), THE Structured_Analysis SHALL separate results by source file using a Markdown level-2 heading containing the source file name

### Requirement 10: Integración con LLM (AWS Bedrock Claude)

**User Story:** Como servicio backend, quiero enviar los datos de análisis al modelo Claude en AWS Bedrock, para obtener un análisis de causa raíz automatizado sin intervención manual.

#### Acceptance Criteria

1. THE Log_Analyzer_Service SHALL invoke the AWS Bedrock API using the `anthropic.claude-3-5-sonnet` model in the `us-west-2` region
2. THE Log_Analyzer_Service SHALL use the AWS profile corresponding to the deployment environment (account 040982755196 for DEV, account 425642439683 for PROD)
3. WHEN processing via the direct path (small logs), THE Log_Analyzer_Service SHALL send the LLM_Prompt concatenated with the raw log content to the LLM
4. WHEN processing via the structural analysis path (large logs), THE Log_Analyzer_Service SHALL send the LLM_Prompt concatenated with the Structured_Analysis to the LLM
5. THE Log_Analyzer_Service SHALL set a maximum token limit of 4096 for the LLM response
6. IF the AWS Bedrock API returns a throttling error (429), THEN THE Log_Analyzer_Service SHALL retry with exponential backoff up to 3 times (1s, 2s, 4s delay)
7. IF the AWS Bedrock API returns an error after all retries, THEN THE Log_Analyzer_Service SHALL return an HTTP 502 response to the caller with an error message indicating the LLM service is temporarily unavailable
8. THE Log_Analyzer_Service SHALL log the LLM invocation duration, input token count, and output token count for cost monitoring

### Requirement 11: Prompt LLM contextualizado para AlwaysPrint

**User Story:** Como servicio backend, quiero que el prompt enviado al LLM incluya contexto específico del sistema AlwaysPrint, para que el modelo pueda interpretar los logs con conocimiento del dominio.

#### Acceptance Criteria

1. THE LLM_Prompt SHALL instruct the LLM to analyze the evidence as logs from a Windows workstation running AlwaysPrint (contingency printing system for BBVA), specifying that AlwaysPrint coexists with Lexmark CPM and activates when CPM fails to redirect print traffic directly to printer IP bypassing the Linux server
2. THE LLM_Prompt SHALL request analysis of: service operational state, service configuration validity, contingency entry/exit events, user session changes, network connectivity to Cloud Manager and printers, and error root causes based on Event IDs
3. THE LLM_Prompt SHALL request the LLM to provide the response structured in: (a) summary of findings, (b) chronological narrative of events with timestamps, (c) identified root causes mapped to Event IDs, (d) impact assessment on print service availability, and (e) recommended corrective actions
4. THE LLM_Prompt SHALL specify that the log format is `[yyyy-MM-dd HH:mm:ss] [SVC/APP] Event NNNN: message` where SVC indicates AlwaysPrintService, APP indicates AlwaysPrintTray, and NNNN is a numeric Event ID in the range 1000-1091
5. THE LLM_Prompt SHALL be written in Spanish to match the project language conventions
6. THE LLM_Prompt SHALL include a reference table of key Event IDs with their meaning: 1000 (service started), 1001 (service stopped), 1003 (tray monitoring), 1004 (task queue), 1005 (pipe server), 1007 (user detected), 1008 (tray launched), 1009 (tray initialized), 1020 (task dispatched), 1021 (task completed), 1030 (config saved), 1090 (info/debug), 1091 (error)

### Requirement 12: Almacenamiento y entrega de respuesta al frontend

**User Story:** Como administrador, quiero que el resultado del análisis de IA se almacene en el historial de la workstation y se muestre en el dashboard, para poder consultarlo posteriormente y tomar decisiones informadas.

#### Acceptance Criteria

1. THE Log_Analyzer_Service SHALL store the LLM_Response in the database as an "Análisis de IA" record associated with the workstation identifier, organization identifier, date of the analysis, and timestamp of creation
2. THE Log_Analyzer_Service SHALL enforce a maximum of one analysis per workstation per day: IF an analysis already exists for the same workstation on the current day, THEN THE backend SHALL inform the frontend that a previous analysis exists for today
3. WHEN the frontend receives notification that a previous analysis exists for today, THE frontend SHALL display a confirmation dialog to the admin indicating that a new analysis will overwrite the previous one, and SHALL only proceed if the admin confirms
4. IF the admin confirms overwriting, THEN THE Log_Analyzer_Service SHALL replace the existing analysis record for that workstation and date with the new LLM_Response
5. THE Log_Analyzer_Service SHALL return the LLM_Response in the HTTP response to the analysis request with HTTP status 200
6. THE Log_Analyzer_Service SHALL expose a GET endpoint that returns the analysis history for a given workstation, paginated with a default page size of 20 results ordered by date descending
7. THE Log_Analyzer_Service SHALL expose a GET endpoint that returns a single analysis result by its unique identifier
8. WHEN the analysis is complete, THE Log_Analyzer_Service SHALL include in the stored record: the LLM analysis text, the processing path used (direct or structural), the log size in bytes, the processing duration in milliseconds, and the date
9. THE Log_Analyzer_Service SHALL filter all query results by organization_id to maintain tenant isolation
10. THE frontend SHALL display the analysis history in the workstation detail view, allowing the admin to view past analyses by date

### Requirement 13: Configuración y parámetros del servicio

**User Story:** Como desarrollador, quiero que los parámetros del servicio de análisis sean configurables, para adaptar el comportamiento a diferentes entornos y necesidades sin modificar código.

#### Acceptance Criteria

1. THE Log_Analyzer_Service SHALL accept the following configurable parameters via environment variables or backend configuration: Compression_Threshold (default 50KB), Processing_Threshold (default 100KB), context window size (default 20), maximum context blocks (default 30), top patterns count (default 50), LLM max tokens (default 4096), and maximum upload size (default 50MB)
2. THE Log_Analyzer_Service SHALL validate all configuration values at startup and log a warning for any value outside its valid range, falling back to the default value
3. THE Log_Analyzer_Service SHALL allow additional keyword patterns to be configured via a comma-separated environment variable, which are appended to the default keyword list
4. THE Log_Analyzer_Service SHALL use Python 3.12 and integrate with the existing FastAPI application structure in `AlwaysPrintProject/Cloud/backend/`
5. THE Log_Analyzer_Service SHALL implement the structural analysis logic as a distinct module with individually callable functions: keyword detection, line normalization, context extraction, pattern grouping, timeline generation, and structured output generation
6. THE Log_Analyzer_Service SHALL include type hints for all function parameters and return values
7. THE Log_Analyzer_Service SHALL include docstrings in Spanish for every module-level and top-level function

