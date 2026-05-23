# Implementation Plan: Workstation Log Analyzer

## Overview

Implementación del servicio de análisis de logs de workstations AlwaysPrint, integrado en el backend FastAPI existente. El plan sigue un enfoque incremental: primero la infraestructura (modelo BD, configuración), luego las funciones puras de procesamiento estructural (testables de forma aislada), después la integración con LLM y el servicio orquestador, los endpoints REST, la integración WebSocket, el frontend y finalmente el handler del cliente C#.

## Tasks

- [x] 1. Configuración y modelo de base de datos
  - [x] 1.1 Agregar settings de log analyzer a la configuración del backend
    - Añadir las variables `LOG_ANALYZER_*` a la clase `Settings` en `app/core/config.py`
    - Incluir validación de rangos con fallback a defaults y logging de warnings
    - Variables: `COMPRESSION_THRESHOLD`, `PROCESSING_THRESHOLD`, `CONTEXT_WINDOW_SIZE`, `MAX_CONTEXT_BLOCKS`, `TOP_PATTERNS`, `LLM_MAX_TOKENS`, `MAX_UPLOAD_SIZE`, `EXTRA_KEYWORDS`, `COMMAND_TIMEOUT`
    - _Requirements: 13.1, 13.2, 13.3_

  - [x] 1.2 Crear modelo SQLAlchemy LogAnalysis
    - Crear `app/models/log_analysis.py` con el modelo `LogAnalysis`
    - Campos: id, workstation_id, organization_id, analysis_date, analysis_text, processing_path, log_size_bytes, processing_duration_ms, original_filename, created_at, updated_at
    - Relaciones con Workstation y Organization
    - Importar Base desde `app.core.database`
    - _Requirements: 12.1, 12.8_

  - [x] 1.3 Crear migración Alembic para tabla log_analyses
    - Generar migración con `alembic revision --autogenerate`
    - Incluir índices: `ix_log_analyses_workstation_date` y `ix_log_analyses_organization`
    - _Requirements: 12.1_

  - [x] 1.4 Crear schemas Pydantic para log analysis
    - Crear `app/schemas/log_analysis.py` con: `LogAnalysisResponse`, `LogAnalysisTodayCheckResponse`, `LogAnalysisListResponse`
    - _Requirements: 12.5, 12.6, 12.7_

- [x] 2. Módulo de procesamiento estructural de logs (funciones puras)
  - [x] 2.1 Implementar funciones de descompresión y routing
    - Crear `app/services/log_processor.py` con dataclasses: `MatchInfo`, `ContextBlock`, `RecurringPattern`, `TimelineEntry`, `StructuralAnalysisResult`
    - Implementar `decompress_if_needed`: descompresión ZIP, validación de extensiones, concatenación alfabética con headers
    - Implementar `route_by_size`: decisión basada en tamaño UTF-8 del contenido
    - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2_

  - [x] 2.2 Write property tests for decompression and routing
    - **Property 1: ZIP decompression round-trip**
    - **Property 2: ZIP file extension validation**
    - **Property 3: Multi-file concatenation preserves alphabetical order**
    - **Property 4: Routing decision correctness**
    - **Validates: Requirements 2.2, 2.3, 2.5, 2.6, 3.1, 3.2**

  - [x] 2.3 Implementar funciones de detección y normalización
    - Implementar `detect_keywords`: substring matching case-insensitive con lista de keywords
    - Implementar `parse_timestamp`: extracción de timestamps formato `YYYY-MM-DD HH:MM:SS`
    - Implementar `normalize_line`: reemplazos en orden fijo (timestamps → UUIDs → IPv4 → temp paths → números)
    - _Requirements: 5.2, 5.3, 5.4, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [x] 2.4 Write property tests for detection and normalization
    - **Property 5: Keyword detection correctness**
    - **Property 6: Normalization order preserves specific patterns**
    - **Validates: Requirements 5.2, 5.3, 7.1-7.6**

  - [x] 2.5 Implementar funciones de ventanas de contexto
    - Implementar `extract_context_windows`: extracción de N líneas antes/después de cada match
    - Implementar `merge_windows`: fusión de ventanas solapantes o adyacentes
    - Implementar `select_blocks`: selección con priorización de primeras ocurrencias
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [x] 2.6 Write property tests for context windows
    - **Property 8: Context window merge produces no overlaps**
    - **Property 9: Block selection respects limit and prioritizes first occurrences**
    - **Validates: Requirements 6.4, 6.5, 6.6**

  - [x] 2.7 Implementar funciones de agrupación y timeline
    - Implementar `group_patterns`: agrupación por forma normalizada con conteo
    - Implementar `identify_first_occurrences`: primera ocurrencia de cada patrón, ordenada
    - Implementar `build_condensed_timeline`: agrupación por minuto (≤1h) o por hora (>1h)
    - _Requirements: 7.7, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9_

  - [x] 2.8 Write property tests for grouping and timeline
    - **Property 7: Pattern grouping count consistency**
    - **Property 10: First occurrence has minimum line number**
    - **Property 11: Critical occurrences sorting**
    - **Property 12: Timeline granularity matches time span**
    - **Property 13: Timeline count consistency**
    - **Validates: Requirements 7.7, 8.1, 8.3, 8.4, 8.6, 8.7, 8.8**

  - [x] 2.9 Implementar generación de output estructurado y funciones de ensamblaje
    - Implementar `generate_structured_output`: Markdown con secciones en orden fijo (Metadata, Patrones, Ocurrencias, Bloques, Timeline)
    - Implementar `run_structural_analysis`: orquestación del pipeline completo
    - Implementar `assemble_direct_payload` y `assemble_structural_payload`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 4.1, 4.2, 4.3_

  - [x] 2.10 Write property tests for structured output and payload assembly
    - **Property 14: Structured output sections in fixed order**
    - **Property 15: Context block formatting marks only match lines**
    - **Property 17: Direct path payload assembly**
    - **Validates: Requirements 9.1, 9.5, 4.1, 4.2, 4.3**

- [x] 3. Checkpoint - Verificar funciones puras
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Servicio LLM parametrizable (AWS Bedrock + providers alternativos)
  - [x] 4.1 Implementar abstracción LLMProvider y providers concretos
    - Crear `app/services/llm_service.py` con clase abstracta `LLMProvider` y clase `LLMService`
    - Implementar `BedrockProvider`: lazy init de boto3 client, modelo y región configurables via env vars
    - Implementar `OpenAIProvider`: invocación via httpx a OpenAI API, API key configurable
    - Implementar `AnthropicProvider`: invocación via httpx a Anthropic Messages API, API key configurable
    - `LLMService` selecciona provider según `LOG_ANALYZER_LLM_PROVIDER` env var (default: "bedrock")
    - Implementar retry con exponential backoff (3 reintentos: 1s, 2s, 4s) para todos los providers
    - Logging de duración, input tokens y output tokens
    - Clase `LLMServiceError` para errores después de agotar reintentos
    - Agregar settings: `LLM_PROVIDER`, `LLM_MODEL_ID`, `LLM_REGION`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`
    - _Requirements: 10.1, 10.2, 10.5, 10.6, 10.7, 10.8_

  - [x] 4.2 Write unit tests for LLM service
    - Test retry en throttling (429) con mock de boto3 (Bedrock)
    - Test error después de retries → LLMServiceError
    - Test respuesta exitosa con métricas loggeadas
    - Test selección de provider según env var
    - Test OpenAI provider con mock de httpx
    - Test Anthropic provider con mock de httpx
    - _Requirements: 10.6, 10.7, 10.8_

- [x] 4.5 Infraestructura Terraform para AWS Bedrock
  - Crear archivo Terraform (o añadir a existente) con:
    - IAM policy `bedrock-invoke-model` con permiso `bedrock:InvokeModel` para el modelo `anthropic.claude-3-5-sonnet*` en us-west-2
    - Attach de la policy al IAM role del ECS task (o EC2 instance profile) del backend
    - Variables para environment (dev/prod) usando los account IDs correspondientes (040982755196 DEV, 425642439683 PROD)
    - Documentar en comentarios que el acceso al modelo debe habilitarse manualmente en AWS Console → Bedrock → Model access
  - _Requirements: 10.1, 10.2_

- [ ] 5. Servicio orquestador de análisis de logs
  - [x] 5.1 Implementar LogAnalysisService
    - Crear `app/services/log_analysis.py` con clase `LogAnalysisService`
    - Implementar `process_log`: descompresión → routing → procesamiento → LLM → guardado en BD
    - Implementar `get_today_analysis`: búsqueda por workstation_id + fecha actual + organization_id
    - Implementar `get_analysis_history`: paginación con filtro por organization_id
    - Implementar `get_analysis_by_id`: búsqueda por ID con filtro de tenant
    - Incluir constante `LLM_PROMPT` con el prompt contextualizado para AlwaysPrint (en español, con tabla de Event IDs)
    - Manejo de overwrite: eliminar registro existente antes de crear nuevo
    - _Requirements: 4.1, 10.3, 10.4, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 12.1, 12.2, 12.4, 12.6, 12.7, 12.8, 12.9_

  - [x] 5.2 Write property test for tenant isolation
    - **Property 16: Tenant isolation in queries**
    - **Validates: Requirements 12.9**

  - [x] 5.3 Write unit tests for LogAnalysisService
    - Test process_log ruta directa (log < 100KB)
    - Test process_log ruta estructural (log ≥ 100KB)
    - Test get_today_analysis retorna None si no existe
    - Test overwrite elimina registro previo
    - Test historial paginado con orden descendente
    - _Requirements: 12.2, 12.4, 12.6_

- [ ] 6. Endpoints REST
  - [x] 6.1 Implementar endpoints de log analysis
    - Crear `app/api/v1/endpoints/log_analysis.py` con router
    - Implementar `POST /{workstation_id}/analyze-log`: validación de workstation, permisos, envío de comando WebSocket, procesamiento, respuesta
    - Implementar `GET /{workstation_id}/log-analyses/today`: verificación de análisis existente
    - Implementar `GET /{workstation_id}/log-analyses`: historial paginado
    - Implementar `GET /log-analyses/{analysis_id}`: análisis individual
    - Registrar router en la aplicación FastAPI principal
    - _Requirements: 1.2, 1.8, 1.9, 2.1, 2.7, 2.8, 12.5, 12.6, 12.7_

  - [x] 6.2 Write unit tests for endpoints
    - Test workstation no encontrada (404)
    - Test workstation offline (409)
    - Test timeout WebSocket (408)
    - Test análisis existente sin overwrite (409)
    - Test overwrite exitoso (200)
    - Test permisos: operador solo su organización (403)
    - Test ZIP corrupto (422)
    - Test upload > 50MB (413)
    - Test LLM error → 502
    - _Requirements: 1.8, 1.9, 2.4, 2.7, 2.8, 10.7_

- [x] 7. Checkpoint - Verificar backend completo
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Integración WebSocket (comando analyze_log)
  - [x] 8.1 Implementar envío de comando analyze_log en el backend
    - Integrar con `connection_manager.register_command_waiter` y `wait_for_command_response`
    - Enviar mensaje `{"type": "command", "command_id": "...", "command_type": "analyze_log", "params": {}}`
    - Parsear respuesta: extraer `filename`, `content` (base64), `original_size`, `is_compressed`
    - Manejar timeout configurable (default 30s) y workstation offline
    - _Requirements: 1.3, 1.8, 1.9_

- [ ] 9. Frontend - Componentes de análisis de logs
  - [x] 9.1 Crear componente LogAnalysisButton
    - Crear `LogAnalysisButton.tsx` con botón "Analizar Log" e icono (Brain/FileSearch de lucide-react)
    - Implementar flujo: verificar análisis existente (GET today) → diálogo de confirmación si existe → POST analyze-log
    - Mostrar loading spinner durante el análisis
    - Manejar errores (offline, timeout, LLM error) con mensajes descriptivos
    - _Requirements: 1.1, 1.2, 1.11, 12.3_

  - [x] 9.2 Crear componente LogAnalysisResult
    - Crear `LogAnalysisResult.tsx` para visualización del resultado
    - Renderizar Markdown del análisis LLM con formato adecuado
    - Mostrar metadata: fecha, ruta de procesamiento, tamaño del log, duración
    - _Requirements: 1.11, 12.5_

  - [x] 9.3 Crear componente LogAnalysisHistory
    - Crear `LogAnalysisHistory.tsx` con lista paginada de análisis previos
    - Integrar en la vista detalle de workstation
    - Paginación con page_size=20, orden descendente por fecha
    - Permitir ver análisis individuales al hacer clic
    - _Requirements: 12.6, 12.10_

- [ ] 10. Cliente C# - Handler del comando analyze_log
  - [x] 10.1 Implementar handler de comando analyze_log en el Workstation Client
    - Agregar handler para `command_type: "analyze_log"` en el sistema de comandos WebSocket existente
    - Leer log del día actual (formato `AlwaysPrint_YYYY-MM-DD.log`)
    - Si tamaño < 50KB (configurable): comprimir a ZIP antes de enviar
    - Si tamaño ≥ 50KB: enviar sin compresión
    - Codificar contenido en base64
    - Responder con `command_result`: `{"filename", "content", "original_size", "is_compressed"}`
    - Manejar caso de archivo no encontrado (responder con success=false)
    - _Requirements: 1.3, 1.4, 1.5, 1.6, 1.7, 1.10_

- [ ] 11. Configuración y property test de validación
  - [x] 11.1 Write property test for configuration validation
    - **Property 18: Configuration validation fallback**
    - **Validates: Requirements 13.2**

- [x] 12. Final checkpoint - Verificar integración completa
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- El módulo `log_processor.py` contiene funciones puras sin I/O, facilitando testing aislado
- La integración WebSocket reutiliza la infraestructura existente (`connection_manager`)
- Todos los queries deben filtrar por `organization_id` para tenant isolation
- Importar Base siempre desde `app.core.database`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.4"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["1.3", "2.2", "2.3"] },
    { "id": 3, "tasks": ["2.4", "2.5"] },
    { "id": 4, "tasks": ["2.6", "2.7"] },
    { "id": 5, "tasks": ["2.8", "2.9"] },
    { "id": 6, "tasks": ["2.10", "4.1", "4.5"] },
    { "id": 7, "tasks": ["4.2", "5.1"] },
    { "id": 8, "tasks": ["5.2", "5.3", "6.1"] },
    { "id": 9, "tasks": ["6.2", "8.1"] },
    { "id": 10, "tasks": ["9.1", "9.2", "9.3", "10.1", "11.1"] }
  ]
}
```
