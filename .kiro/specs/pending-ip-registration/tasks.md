# Implementation Plan: Pending IP Registration

## Overview

Implementar el registro automático de IPs públicas desconocidas como pendientes de aprobación dentro del flujo `check_update`. Se añade la función helper `_register_pending_ip` con patrón upsert PostgreSQL y se integra en el bloque `else` antes del `raise HTTPException 401`. Los tests property-based (Hypothesis) validan las 7 propiedades de correctness definidas en el diseño.

## Tasks

- [x] 1. Implementar función `_register_pending_ip` y su integración
  - [x] 1.1 Crear la función helper `_register_pending_ip(db, request)` en `app/api/v1/endpoints/updates.py`
    - Implementar el patrón upsert con `sqlalchemy.dialects.postgresql.insert`
    - INSERT con `ip_address`, `is_authorized=False`, `organization_id=None`, `first_seen=utcnow`, `last_hostname` (del header `X-Workstation-ID`), `last_user` (del header `X-Workstation-Local-IP`)
    - ON CONFLICT DO UPDATE solo cuando `is_authorized=False`: actualizar `last_hostname` y `last_user` con los valores del header (si presentes)
    - Envolver en try/except amplio: rollback + log warning si falla, nunca propagar la excepción
    - Importar `insert as pg_insert` desde `sqlalchemy.dialects.postgresql`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 5.1, 5.2, 5.3_

  - [x] 1.2 Integrar `_register_pending_ip` en `check_update`
    - En el bloque `else` (donde actualmente solo se lanza HTTPException 401), insertar la llamada a `_register_pending_ip(db, request)` antes del `raise`
    - Agregar log warning con `ip_publica`, `x_workstation_id` y `x_workstation_local_ip` antes de la llamada
    - Verificar que el flujo para IPs autorizadas y workstations identificadas no se altera
    - _Requirements: 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 5.3_

- [x] 2. Checkpoint - Verificar implementación base
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. Tests property-based con Hypothesis
  - [x] 3.1 Escribir property test: Registro pendiente para IP desconocida
    - **Property 1: Registro pendiente para IP desconocida**
    - Generar IPs válidas (IPv4/IPv6) no existentes en DB, simular request sin auth
    - Verificar que se crea registro con `is_authorized=False`, `organization_id=None`, `ip_address` correcta, `first_seen` dentro de ±5s UTC
    - **Validates: Requirements 1.1, 1.2, 5.3**

  - [x] 3.2 Escribir property test: Captura de metadata desde headers
    - **Property 2: Captura de metadata desde headers**
    - Generar combinaciones de headers `X-Workstation-ID` y `X-Workstation-Local-IP` (presentes/ausentes, valores aleatorios)
    - Verificar que `last_hostname` y `last_user` coinciden con headers o son NULL si ausentes
    - **Validates: Requirements 1.3, 1.4, 1.5**

  - [x] 3.3 Escribir property test: Idempotencia — sin registros duplicados
    - **Property 3: Idempotencia — sin registros duplicados**
    - Generar IP + repetir N veces (N ∈ [2, 20]), verificar que siempre existe exactamente 1 registro
    - **Validates: Requirements 2.1, 2.5**

  - [x] 3.4 Escribir property test: Actualización selectiva de metadata en IP pendiente
    - **Property 4: Actualización selectiva de metadata en IP pendiente**
    - Crear registro pendiente, enviar request con solo uno de los headers, verificar que solo ese campo se actualiza y el otro permanece sin cambios
    - **Validates: Requirements 2.2, 2.3**

  - [x] 3.5 Escribir property test: IPs autorizadas son inmutables al registro pendiente
    - **Property 5: IPs autorizadas son inmutables al registro pendiente**
    - Crear registro autorizado (`is_authorized=True`), enviar request desde esa IP, verificar que ningún campo del registro cambia
    - **Validates: Requirements 2.4, 4.2**

  - [x] 3.6 Escribir property test: Respuesta HTTP 401 invariante para IPs no autorizadas
    - **Property 6: Respuesta HTTP 401 invariante para IPs no autorizadas**
    - Generar IPs desconocidas vs. pendientes, comparar responses — deben ser HTTP 401 con body idéntico `{"detail": "Workstation no autenticada"}`
    - **Validates: Requirements 3.1, 3.2, 3.4**

  - [x] 3.7 Escribir property test: Resiliencia ante fallos de BD en el registro
    - **Property 7: Resiliencia ante fallos de BD en el registro**
    - Inyectar excepciones aleatorias en sesión DB (mock), verificar que endpoint retorna 401 (nunca 5xx) y la sesión queda en estado limpio
    - **Validates: Requirements 5.1**

- [x] 4. Tests unitarios (ejemplo-based)
  - [x] 4.1 Escribir tests unitarios para `_register_pending_ip` y la integración en `check_update`
    - `test_register_pending_ip_basic`: IP nueva → registro creado con campos correctos
    - `test_register_pending_ip_with_all_headers`: ambos headers presentes → metadata capturada
    - `test_register_pending_ip_no_headers`: sin headers → `last_hostname` y `last_user` NULL
    - `test_authorized_ip_not_modified`: IP autorizada → sin cambios en registro
    - `test_register_pending_ip_db_failure`: simular fallo DB → response sigue siendo 401
    - `test_log_warning_on_unauthorized`: verificar que se emite log WARNING con campos correctos
    - `test_check_update_authorized_ip_unchanged`: flujo completo para IP autorizada → HTTP 200 sin pasar por lógica pendiente
    - _Requirements: 1.1–1.5, 2.1–2.5, 3.1–3.4, 4.1, 5.1_

- [x] 5. Checkpoint final - Ejecutar suite completa de tests
  - Ejecutar `pytest` completo para confirmar que no hay regresiones en tests existentes
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido
- La implementación usa SQLAlchemy Core (`pg_insert`) para el patrón upsert, no el ORM
- No se requiere nueva migración: los campos `first_seen`, `last_hostname` y `last_user` ya existen
- El modelo `PublicIP` ya tiene la constraint UNIQUE en `ip_address`
- Los property tests usan Hypothesis con mínimo 100 iteraciones por propiedad
- Para tests unitarios usar SQLite in-memory (fixture `db` en `conftest.py`); para PBT con upsert real usar PostgreSQL

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3", "3.4", "3.5", "3.6", "3.7", "4.1"] }
  ]
}
```
