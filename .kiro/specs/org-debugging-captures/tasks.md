# Tareas de Implementación — Capturas de Debugging a Nivel de Organización

## Fase 1: Backend — Modelos y Migración

- [x] 1. Crear modelo `DebuggingProfile` en `app/models/debugging.py` con todos los campos (id, organization_id, name, description, confirmation_message, external_logs, eventlog_groups, registry_keys, monitored_services, is_active, created_by, timestamps)
- [x] 2. Crear modelo `DebuggingSession` en `app/models/debugging.py` con campos (id, organization_id, profile_id, workstation_id, status enum, duration_seconds, start_time, end_time, motivo, additional_instructions, total_data_size_bytes, s3_report_key, initiated_by, created_at)
- [x] 3. Crear migración Alembic para tablas `debugging_profiles` y `debugging_sessions`
- [x] 4. Registrar modelos en `app/models/__init__.py` y verificar import desde `app.core.database`

## Fase 2: Backend — Schemas y Validación

- [x] 5. Crear schemas Pydantic en `app/schemas/debugging.py`: DebuggingProfileCreate, DebuggingProfileUpdate, DebuggingProfileResponse, DebuggingSessionCreate, DebuggingSessionResponse
- [x] 6. Implementar validadores: eventlog_groups solo permite System/Application/Security, al menos un target de monitoreo requerido, duration_seconds entre 15-300

## Fase 3: Backend — API Endpoints de Perfiles

- [x] 7. Crear endpoint `POST /api/v1/debugging/profiles` — Crear perfil (con invocación LLM para sugerencia de nombre/mensaje)
- [x] 8. Crear endpoint `GET /api/v1/debugging/profiles` — Listar perfiles de la organización (filtro tenant isolation)
- [x] 9. Crear endpoint `GET /api/v1/debugging/profiles/{id}` — Detalle de perfil
- [x] 10. Crear endpoint `PUT /api/v1/debugging/profiles/{id}` — Editar perfil
- [x] 11. Crear endpoint `DELETE /api/v1/debugging/profiles/{id}` — Desactivar perfil (soft delete)
- [x] 12. Implementar gate de LLM: verificar que organización tiene `llm_model_id` o `openai_api_key` antes de permitir operaciones

## Fase 4: Backend — API Endpoints de Sesiones

- [x] 13. Crear endpoint `POST /api/v1/debugging/sessions` — Iniciar sesión (genera debugging_id, valida un solo debugging activo por workstation, envía comando WebSocket StartDebugging)
- [x] 14. Crear endpoint `GET /api/v1/debugging/sessions` — Listar sesiones (filtro por workstation_id, status, organización)
- [x] 15. Crear endpoint `GET /api/v1/debugging/sessions/{id}` — Detalle de sesión
- [x] 16. Crear endpoint `POST /api/v1/debugging/sessions/{id}/stop` — Detener sesión (envía StopDebugging vía WebSocket)
- [x] 17. Crear endpoint `POST /api/v1/debugging/sessions/{id}/analyze` — Solicitar análisis (envía RequestDebugUpload vía WebSocket)
- [x] 18. Crear endpoint `POST /api/v1/debugging/sessions/{id}/delete` — Solicitar eliminación (envía DeleteDebugData vía WebSocket)
- [x] 19. Crear endpoint `GET /api/v1/debugging/sessions/{id}/report` — Generar presigned S3 URL para descarga del PDF

## Fase 5: Backend — Upload Endpoint y Pipeline de Análisis

- [x] 20. Crear endpoint `POST /api/v1/debugging/{debugging_id}/upload` — Recibir ZIP multipart desde workstation (validar auth, session status, max 100MB)
- [x] 21. Implementar `DebuggingAnalysisService` en `app/services/debugging_analysis.py`: descomprimir ZIP, leer index.json, generar diffs entre snapshots inicial/final
- [x] 22. Implementar construcción de prompt LLM: incluir objetivo, motivo, instrucciones adicionales, índice, diffs, extractos de logs y eventos
- [x] 23. Implementar invocación al LLM usando el patrón existente de `log_analysis.py` (respetar openai_api_key o bedrock por org)
- [x] 24. Implementar generación de PDF con el resultado del LLM (header con metadata, body con análisis, appendices)
- [x] 25. Implementar upload del PDF a S3 (key: `debugging/{org_id}/{debugging_id}/report.pdf`) y actualización de session

## Fase 6: Backend — WebSocket Commands

- [x] 26. Definir comandos WebSocket salientes: `start_debugging`, `stop_debugging`, `request_debug_upload`, `delete_debug_data` con sus payloads
- [x] 27. Implementar handlers para mensajes entrantes del cliente: `debugging_started`, `debugging_ready`, `debugging_deleted`, `debugging_error` — actualizar estado de session y notificar frontend
- [x] 28. Implementar timeout de 10s para acknowledgment de StartDebugging (marcar session como "failed" si no responde)

## Fase 7: Cliente Windows — Motor de Debugging

- [x] 29. Crear clase `DebuggingEngine` en `AlwaysPrintService/Debugging/DebuggingEngine.cs`: orquestación del ciclo de vida (start, timer, stop, package, delete), enforce single session
- [x] 30. Crear clase `SnapshotManager` en `AlwaysPrintService/Debugging/SnapshotManager.cs`: captura estado de servicios Windows (ServiceController) y valores de registro (RegistryKey, single level)
- [x] 31. Crear clase `LogExtractor` en `AlwaysPrintService/Debugging/LogExtractor.cs`: conteo de líneas al inicio, extracción de líneas nuevas al final, soporte glob patterns, extracción log AlwaysPrint
- [x] 32. Crear clase `EventLogExtractor` en `AlwaysPrintService/Debugging/EventLogExtractor.cs`: extracción de eventos por grupo y rango de tiempo con formato texto
- [x] 33. Crear clase `IndexBuilder` en `AlwaysPrintService/Debugging/IndexBuilder.cs`: creación y actualización del index.json con metadata, files, errors
- [x] 34. Crear clase `ZipPacker` en `AlwaysPrintService/Debugging/ZipPacker.cs`: compresión de carpeta completa a ZIP, eliminación de originales post-zip

## Fase 8: Cliente Windows — Integración WebSocket

- [x] 35. Implementar handler para comando `start_debugging`: parsear payload, invocar DebuggingEngine.StartSession, enviar ack `debugging_started`
- [x] 36. Implementar handler para comando `stop_debugging`: invocar DebuggingEngine.StopSession
- [x] 37. Implementar handler para comando `request_debug_upload`: invocar ZipPacker, hacer HTTP POST del ZIP al endpoint de upload
- [x] 38. Implementar handler para comando `delete_debug_data`: invocar DebuggingEngine.DeleteSession, enviar ack `debugging_deleted`
- [x] 39. Implementar notificación `debugging_ready` al finalizar captura (timeout o stop): enviar debugging_id y total_size_bytes

## Fase 9: Frontend — Pestaña Debugging en Config de Organización

- [x] 40. Crear componente de pestaña "Debugging" en configuración de organización con gate de LLM (mostrar solo si org tiene llm_model_id o openai_api_key)
- [x] 41. Implementar formulario de creación de perfil: campos para external_logs (lista dinámica), eventlog_groups (checkboxes), registry_keys (lista dinámica), monitored_services (lista dinámica), description (textarea)
- [x] 42. Implementar flujo de guardado con sugerencia LLM: mostrar nombre y mensaje sugeridos editables antes de confirmar
- [x] 43. Implementar listado de perfiles existentes con acciones: editar, desactivar/activar, eliminar

## Fase 10: Frontend — UI de Debugging en Detalle de Workstation

- [x] 44. Crear sección "Debugging disponible" en vista de detalle de workstation: lista de perfiles activos con nombre y descripción
- [x] 45. Implementar diálogo de confirmación para iniciar debugging: nombre, descripción, selector de duración (15-300s), campos opcionales motivo e instrucciones
- [x] 46. Implementar vista de sesión activa: timer countdown, tiempo restante, botón "Detener Debugging"
- [x] 47. Implementar vista de datos disponibles (status "ready"): botones "Analizar" y "Eliminar", tamaño total reportado
- [x] 48. Implementar vista de análisis completado: link de descarga del PDF, opción "Descargar ZIP" (si disponible)
- [x] 49. Implementar feedback de estados: loading durante captura, progress durante análisis, error states con mensajes descriptivos
