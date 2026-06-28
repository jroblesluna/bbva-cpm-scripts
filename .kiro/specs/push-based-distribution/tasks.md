# Implementation Plan: Push-Based Distribution

## Overview

Implementación del flujo push-based para distribución de configuraciones, certificados ECDSA y MSI vía WebSocket. El plan sigue un enfoque incremental: primero el StateMapService (cimiento), luego el PushDistributionService, después las modificaciones al flujo de registro WebSocket, y finalmente las modificaciones al cliente C#. Los property-based tests se integran junto a cada componente.

## Tasks

- [x] 1. StateMapService - Mapa de estado en memoria
  - [x] 1.1 Crear data models y StateMapService base
    - Crear `app/services/state_map_service.py` con las dataclasses `VlanConfigState`, `WsConfigState`, `OrgDistributionState`, `StateMapUpdate`
    - Implementar `StateMapService.__init__()` con el dict `_state: dict[str, OrgDistributionState]`
    - Implementar `get_state(org_id)` y `resolve_workstation_state(org_id, vlan_id, ws_id)` con resolución jerárquica de scope (org < vlan < workstation)
    - _Requirements: 1.6_

  - [x] 1.2 Implementar carga inicial desde BD
    - Implementar `initialize(db_session_factory)` que ejecuta la query SQL de carga (JOIN organizations + action_configs)
    - Implementar `_load_org_state(db, org_id)` para carga individual de una org (fallback en cache miss)
    - Construir URLs S3 a partir de `storage_path` y `ecdsa_cert_s3_key` existentes en BD
    - _Requirements: 1.1, 9.3_

  - [x] 1.3 Implementar métodos de actualización local del state map
    - Implementar `update_config(org_id, config_hash, config_s3_url, scope, scope_id)` que actualiza org/vlan/ws según scope
    - Implementar `update_cert(org_id, cert_version, cert_url)`
    - Implementar `update_msi(org_id, msi_version, msi_url)` con `msi_url_expires_at`
    - _Requirements: 1.2, 1.3, 1.4_

  - [x] 1.4 Implementar sincronización Redis pub/sub
    - Implementar `_publish_update(org_id, update_type, data)` que publica en canal `state_map:update`
    - Implementar `_on_redis_message(message)` que actualiza el state map local al recibir mensajes de otros workers
    - Incluir `origin_worker_id` en el payload para evitar procesar mensajes propios
    - Implementar suscripción al canal en `initialize()` y background listener task
    - _Requirements: 1.5, 8.1, 8.2_

  - [x] 1.5 Implementar manejo de errores y resiliencia Redis
    - Si Redis no está disponible al publicar, loguear warning y continuar (state map local queda correcto)
    - Si se detecta inconsistencia entre workers, loguear ERROR con org_id y valores divergentes
    - Regenerar presigned URL de MSI cuando `msi_url_expires_at` está por expirar (threshold 5 min)
    - _Requirements: 8.3, 8.4_

  - [x] 1.6 Property test: State map initialization completeness (Property 1)
    - **Property 1: State map initialization completeness**
    - Generar conjuntos aleatorios de organizaciones con configs/certs/MSI, verificar que `initialize()` produce un mapa con entrada para cada org activa con valores correctos
    - **Validates: Requirements 1.1**

  - [x] 1.7 Property test: State map local update consistency (Property 2)
    - **Property 2: State map local update consistency**
    - Generar secuencias aleatorias de cambios (config, cert, MSI), aplicar cada uno, verificar que el mapa refleja solo el último estado
    - **Validates: Requirements 1.2, 1.3, 1.4**

  - [x] 1.8 Property test: Cross-worker state synchronization round-trip (Property 3)
    - **Property 3: Cross-worker state synchronization round-trip**
    - Generar updates aleatorios, serializar/deserializar vía JSON (simula Redis), verificar que el receptor reconstruye el mismo estado
    - **Validates: Requirements 1.5, 8.1, 8.2**

  - [x] 1.9 Property test: State map scope structure (Property 4)
    - **Property 4: State map scope structure**
    - Generar orgs con múltiples configs a diferentes scopes, verificar que `resolve_workstation_state()` retorna la config del scope más específico
    - **Validates: Requirements 1.6**

- [x] 2. Checkpoint - Verificar StateMapService
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. PushDistributionService - Envío de push messages
  - [x] 3.1 Crear PushDistributionService base
    - Crear `app/services/push_distribution_service.py` con `PushDistributionService`
    - Implementar `_get_target_workstations(org_id, scope, scope_id)` que obtiene workstations online del `connection_manager` filtradas por org/vlan/workstation scope
    - Implementar `push_config_change(org_id, config_hash, download_url, scope, scope_id)` que envía `Config_Push_Message` a workstations afectadas (zero BD queries)
    - _Requirements: 2.1, 9.1_

  - [x] 3.2 Implementar push de MSI y certificado
    - Implementar `push_msi_update(org_id, msi_version, download_url, file_size)` que envía `MSI_Push_Message` a todas las workstations online de la org
    - Implementar `push_cert_rotation(org_id, cert_version, cert_url)` que envía `Cert_Push_Message` a todas las workstations online de la org
    - _Requirements: 3.1, 4.1_

  - [x] 3.3 Integrar StateMapService y PushDistributionService en endpoints de admin
    - Modificar endpoint de activación de config para: actualizar state map → publicar Redis → push a workstations
    - Modificar endpoint de rotación de certificado para: actualizar state map → publicar Redis → push a workstations
    - Modificar endpoint de cambio de MSI/target_version para: actualizar state map → publicar Redis → push a workstations
    - _Requirements: 2.1, 3.1, 4.1, 1.2, 1.3, 1.4_

  - [x] 3.4 Property test: Zero database queries in distribution hot path (Property 8)
    - **Property 8: Zero database queries in distribution hot path**
    - Generar N workstations, mockear DB con contador, ejecutar push/enrichment, verificar contador = 0
    - **Validates: Requirements 9.1, 9.2**

  - [x] 3.5 Property test: Load efficiency per organization (Property 9)
    - **Property 9: Load efficiency per organization**
    - Generar N workstations de la misma org, simular cache misses secuenciales, verificar que solo el primero hace query a BD
    - **Validates: Requirements 9.3**

- [x] 4. Registration Enrichment - Enriquecimiento del registro WebSocket
  - [x] 4.1 Modificar flujo de registro WebSocket para incluir estado
    - Modificar `register_workstation` en el WebSocket handler para consultar `StateMapService.resolve_workstation_state()` después del registro
    - Si state map tiene datos de la org, incluir `state: {config_hash, config_s3_url, cert_version, cert_url, msi_version, msi_url}` en la respuesta `registered`
    - Si state map no tiene datos (cold start), cargar desde BD una sola vez con `_load_org_state()` y luego responder
    - _Requirements: 5.1, 5.3, 9.2_

  - [x] 4.2 Property test: Registration enrichment completeness (Property 7)
    - **Property 7: Registration enrichment completeness**
    - Para cualquier registro exitoso con state map poblado, verificar que la respuesta incluye los 6 campos con valores correctos del state map resuelto por scope
    - **Validates: Requirements 5.1**

- [x] 5. Checkpoint - Verificar backend completo
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Cliente C# - PushMessageHandler
  - [x] 6.1 Crear modelo DistributionState y PushMessageHandler
    - Crear `AlwaysPrintTray/Cloud/DistributionState.cs` con propiedades ConfigHash, ConfigS3Url, CertVersion, CertUrl, MsiVersion, MsiUrl, LastUpdated
    - Crear `AlwaysPrintTray/Cloud/PushMessageHandler.cs` con métodos para procesar mensajes push
    - Implementar cache del último estado recibido (`_lastKnownState`)
    - _Requirements: 5.2, 6.1_

  - [x] 6.2 Implementar procesamiento de Config_Push_Message
    - Implementar handler para mensaje `action_config_changed`: comparar `config_hash` recibido vs hash local
    - Si hash difiere: descargar archivo firmado desde `download_url` de S3 directamente
    - Si hash coincide: ignorar mensaje
    - Mantener verificación de firma ECDSA del archivo descargado antes de aplicar
    - _Requirements: 2.2, 2.3, 2.4, 2.6_

  - [x] 6.3 Implementar procesamiento de MSI_Push_Message y Cert_Push_Message
    - Implementar handler para `check_update`: comparar `version` vs versión instalada, descargar desde presigned URL si difiere
    - Implementar handler para `cert_rotated`: comparar `cert_version` vs local, descargar si mayor
    - Implementar fallback HTTP para MSI cuando presigned URL expira (403) — un solo request a `/updates/download`
    - _Requirements: 3.2, 3.3, 3.4, 4.2, 4.3_

  - [x] 6.4 Implementar retry con backoff exponencial para descargas S3
    - Implementar método `DownloadWithRetry(url, maxAttempts=3)` con delays [1s, 2s, 4s]
    - Aplicar a descargas de config y certificado (no MSI, que tiene fallback HTTP)
    - Si 3 intentos fallan, loguear error y esperar próximo push
    - _Requirements: 2.5, 4.4_

  - [x] 6.5 Property test: Diff-based download decision (Property 5)
    - **Property 5: Diff-based download decision**
    - Generar pares (local_state, push_message), verificar que la decisión de descarga es correcta (descarga sii difiere)
    - Nota: Este test se implementa en Python con Hypothesis simulando la lógica del cliente
    - **Validates: Requirements 2.2, 2.3, 2.4, 3.2, 3.3, 3.4, 4.2, 4.3, 5.2, 6.1**

  - [x] 6.6 Property test: Exponential backoff retry on S3 failure (Property 6)
    - **Property 6: Exponential backoff retry on S3 failure**
    - Verificar que los delays siguen [1s, 2s, 4s] y el total de intentos nunca excede 3
    - Nota: Este test se implementa en Python con Hypothesis simulando la lógica de retry
    - **Validates: Requirements 2.5, 4.4**

- [x] 7. Cliente C# - Modificaciones a CloudManager y ConfigManager
  - [x] 7.1 Modificar CloudManager para almacenar estado del registro enriquecido
    - Almacenar `DistributionState` recibido en la respuesta de registro WebSocket (`lastKnownState`)
    - Exponer método `GetCachedState()` para verificación manual
    - Procesar el campo `state` del mensaje `registered` y pasarlo al PushMessageHandler
    - _Requirements: 5.2, 6.1_

  - [x] 7.2 Modificar ConfigManager para eliminar polling HTTP
    - Eliminar polling periódico a `/workstations/{id}/config/info`
    - Eliminar llamadas HTTP a `/workstations/{id}/config/download`
    - Agregar método `DownloadFromS3(url)` para descarga directa desde URLs provistas por push
    - Mantener verificación ECDSA del archivo descargado (fail-closed)
    - _Requirements: 7.1, 7.4_

  - [x] 7.3 Implementar verificación manual desde el Tray
    - Modificar botón "Buscar actualizaciones" para usar `GetCachedState()` como fuente primaria
    - Si no hay estado cacheado (primer inicio o reconexión pendiente), hacer un solo request HTTP fallback al backend
    - Comparar estado local vs cacheado/recibido y descargar desde S3 lo que difiera
    - _Requirements: 6.1, 6.2, 6.3_

  - [x] 7.4 Eliminar dependencia de endpoints de descarga de certificado y MSI
    - Eliminar polling/llamadas HTTP para obtener certificados (usar solo URL del push/registration)
    - Eliminar polling/llamadas HTTP para check updates de MSI (usar solo URL del push/registration)
    - Mantener endpoints legacy funcionales en backend (transición), pero el cliente no los usa en operación normal
    - _Requirements: 7.2, 7.3, 7.4_
- [x] 8. Checkpoint - Verificar cliente completo
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Integración y wiring final
  - [x] 9.1 Inicializar StateMapService en el startup de la aplicación
    - Registrar `StateMapService` como singleton en el lifespan de FastAPI
    - Llamar `initialize()` durante startup del worker (cargar estado desde BD)
    - Inyectar `StateMapService` en `PushDistributionService` y en el WebSocket handler
    - _Requirements: 1.1, 9.3_

  - [x] 9.2 Wiring completo: conectar todos los componentes
    - Verificar que el flujo completo funciona: admin activa config → state map update → Redis publish → push to WS
    - Verificar que registro enriquecido funciona: WS conecta → registration enrichment con datos del state map
    - Verificar que endpoints legacy siguen funcionando (período de transición)
    - _Requirements: 2.1, 3.1, 4.1, 5.1, 7.4_

  - [x] 9.3 Unit tests del backend
    - Registration enrichment con state map vacío (fallback a BD)
    - Registration enrichment con state map poblado (zero queries)
    - Redis desconectado durante publish (graceful fallback)
    - Presigned URL refresh cuando está por expirar
    - Scope resolution: org < vlan < workstation priority
    - _Requirements: 5.3, 8.3, 1.6_

  - [x] 9.4 Integration tests del backend
    - Flujo completo: admin activa config → state map update → Redis publish → push to WS
    - Flujo de registro: WS conecta → registration enrichment con datos correctos
    - Multi-worker: cambio en worker 1 visible en worker 2 vía Redis
    - Fallback: legacy endpoints siguen funcionando durante transición
    - _Requirements: 2.1, 5.1, 8.1, 7.4_

- [x] 10. Final checkpoint - Verificar integración completa
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido
- Cada task referencia requirements específicos para trazabilidad
- Los checkpoints aseguran validación incremental
- Property tests validan propiedades universales de correctness (Hypothesis, mín. 100 iteraciones)
- Unit tests validan ejemplos específicos y edge cases
- El backend usa Python 3.12 con FastAPI; el cliente usa C# .NET 4.8
- La BD es source of truth; el state map es un caché en memoria
- Redis pub/sub se usa para sincronización inter-worker (2 uvicorn workers)
- Los property tests 5 y 6 se implementan en Python simulando la lógica del cliente C# (ya que Hypothesis no corre en .NET)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["1.4", "1.5"] },
    { "id": 3, "tasks": ["1.6", "1.7", "1.8", "1.9"] },
    { "id": 4, "tasks": ["3.1", "6.1"] },
    { "id": 5, "tasks": ["3.2", "6.2"] },
    { "id": 6, "tasks": ["3.3", "6.3", "6.4"] },
    { "id": 7, "tasks": ["3.4", "3.5", "6.5", "6.6"] },
    { "id": 8, "tasks": ["4.1"] },
    { "id": 9, "tasks": ["4.2", "7.1"] },
    { "id": 10, "tasks": ["7.2", "7.3"] },
    { "id": 11, "tasks": ["7.4"] },
    { "id": 12, "tasks": ["9.1"] },
    { "id": 13, "tasks": ["9.2"] },
    { "id": 14, "tasks": ["9.3", "9.4"] }
  ]
}
```
