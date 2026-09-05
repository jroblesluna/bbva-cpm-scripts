# Implementation Plan — Usage and Billing

El plan está ordenado por fases de riesgo creciente. Cada fase se valida (build + tests) antes
de avanzar. Las tasks de dinero (cierre, tarifas, liquidación) van después de que el modelo de
datos y `last_seen` estén sólidos. No se ejecuta ninguna migración contra PROD sin verificación
previa en solo-lectura.

---

## Fase 1 — Modelo de datos y migración

- [x] 1. Añadir columnas y tablas al modelo ORM
  - Añadir `last_seen` (DateTime) y `billing_status` (String(16)) a `app/models/workstation.py`.
  - Añadir `billing_mode` (String(16), server_default `monthly`) a `app/models/organization.py`.
  - Crear `app/models/billing.py` con `BillingRatePlan`, `BillingOrgPlan`, `BillingClosure`,
    `BillingClosureItem`, `BillingAnnualSubscription` (reusar `GUID` de `organization.py`).
  - Registrar los nuevos modelos en `app/models/__init__.py`.
  - _Requirements: 1.1, 2.1, 4.1, 5, 6, 8, 9_

- [x] 2. Crear la migración Alembic en 3 pasos (segura sobre PROD)
  - `last_seen`: add nullable → `UPDATE ... = COALESCE(last_connection, first_seen)` →
    server_default `CURRENT_TIMESTAMP` + NOT NULL.
  - `billing_status`: add nullable → `UPDATE ... = 'new'` → server_default `new` + NOT NULL +
    CHECK `IN ('new','billable','recycled','archived')`.
  - `billing_mode`: add NOT NULL server_default `monthly` + CHECK.
  - Crear las 5 tablas nuevas con sus FK, índices y `UniqueConstraint` de idempotencia
    (`uq_closure_org_period`).
  - Usar `batch_alter_table` para el path SQLite (tests).
  - _Requirements: 1.2, 1.3, 2.2, 2.3_

- [x] 3. Seed de planes tarifarios por defecto
  - Insertar en `billing_rate_plans` el plan `monthly` (T1–T5) y `annual` (5 tramos con
    `free_growth_to`) con los valores de la propuesta.
  - Hacerlo en la migración (data migration) o en un script idempotente de bootstrap.
  - _Requirements: 8.1_

- [x] 4. Verificación previa en PROD (solo lectura) y prueba de migración
  - Contar IPs por mes de `created_at` en PROD (BBVA) para dimensionar cierres retroactivos.
  - Ejecutar la migración en una BD de prueba/dev con datos representativos y verificar backfill
    (`last_seen` poblado, `billing_status='new'` en todas, NOT NULL efectivo).
  - _Requirements: 1.3, 2.3_

## Fase 2 — Actualización de `last_seen` en runtime (opción B)

- [x] 5. Implementar `LastSeenTracker` (buffer en memoria + helper de actividad)
  - Buffer `{workstation_id: last_telemetry_ts}` por worker.
  - Helper `mark_activity(db, ws, ts)` que setea `last_seen` y, si `billing_status` es
    `recycled`/`archived`, lo cambia a `billable` en la misma transacción.
  - _Requirements: 1.4, 1.5, 2.8_

- [x] 6. Cablear `last_seen` en registro y conexión
  - En `services/workstation.py`: setear `last_seen = first_seen` en la creación; setear
    `last_seen` en los puntos donde hoy se setea `last_connection` (registro/alta/update_status).
  - En `websocket/workstation.py`: en telemetría estando offline (offline→online), usar
    `last_telemetry_ts` como `last_seen`.
  - _Requirements: 1.4, 1.5_

- [x] 7. Ajustar marcado offline para persistir `last_seen`
  - En `websocket_manager._flush_disconnect_queue` (y equivalente en
    `redis_connection_manager`): al `is_online=False`, escribir `last_seen` = última actividad
    real conocida del tracker (no el momento del evento).
  - En el Death Ping: usar el timestamp de actividad que disparó la evaluación de inactividad.
  - _Requirements: 1.5, 1.6_

- [x] 8. Flush periódico de `last_seen` en el loop de ~60s
  - En `start_ping_loop`: batch UPDATE de `last_seen` de las workstations online cuyo
    `last_telemetry_ts` avanzó respecto al valor persistido.
  - No escribir en cada telemetría individual.
  - _Requirements: 1.7, 1.8_

- [x] 9. Tests de `last_seen`
  - Unit: `mark_activity` reactiva estado; no-actualización en cada telemetría; flush solo de
    los que avanzaron.
  - Integración: transición offline→online y offline persisten el ts correcto.
  - _Requirements: 1.4–1.8, 2.8_

## Fase 3 — Máquina de estados y reactivación

- [x] 10. Implementar `BillingStateMachine`
  - `can_transition(old, new)` con la matriz de transiciones válidas.
  - `assert_archivable(ws)` que exige `is_online == False`.
  - Prohibir `archived → recycled` automático y cualquier retorno a `new`.
  - _Requirements: 2.5, 2.6, 2.7_

- [x] 11. Tests property-based de invariantes de estado
  - Nadie vuelve a `new`; `archived` no pasa a `recycled` por cierre; solo offline se archiva.
  - _Requirements: 2.5, 2.6, 2.7_

## Fase 4 — Motor de cierre mensual y snapshot

- [x] 12. Utilidades de tiempo por organización
  - `compute_cuts(timezone, year, month)` → `cutoff` (M+1), `cut1` (M−2), `cut2` (M−3) usando
    `zoneinfo`, devueltos en UTC. Cubrir cruces de mes/año y DST.
  - _Requirements: 5.1, 5.4, 5.5_

- [x] 13. Implementar `BillingCloseService.close_month`
  - Validar idempotencia (no re-cerrar) y secuencialidad (no saltar meses).
  - Scope: `created_at < cutoff`, excluir `archived` del recálculo.
  - Paso 1: `new → billable`. Paso 2: reglas de reciclaje con `last_seen` **crudo** (caso 1 y 2).
  - Persistir cabecera + ítems (snapshot con `last_seen` **capado** a cutoff) en transacción única.
  - Estado vivo = el del cierre de mayor `(year, month)`; retroactivos anteriores no revierten
    la columna viva (solo registran histórico en el snapshot).
  - _Requirements: 5.1–5.8, 6.1–6.5, 7.6_

- [x] 14. Tests del motor de cierre
  - Reglas de reciclaje caso 1/2 con datos límite; capping en snapshot; idempotencia;
    secuencialidad; escenario BBVA mayo–agosto (mayo/junio/julio sin recycled, agosto primeros
    recycled).
  - _Requirements: 5, 6, 7.4, 7.6_

## Fase 5 — Tarifas y facturación mensual

- [x] 15. Implementar `BillingService` (resolución de plan + cálculo)
  - Resolver plan: `billing_org_plans` de la org si existe, si no el default vigente.
  - `compute_amount_monthly(count, tiers)` incremental por tramos; redondeo half-up 2 decimales.
  - _Requirements: 8.2, 8.3, 8.4, 8.7_

- [x] 16. Integrar cálculo de monto en el cierre mensual
  - Base = `billable` tras el cierre; poblar `amount` y `tiers_applied` en la cabecera y el
    aporte por IP en los ítems.
  - _Requirements: 8.3, 8.4_

- [x] 17. Endpoints y permisos de tarifas
  - GET/PUT `rate-plans` (superadmin), PUT `organizations/{id}/plan` (superadmin); mensual
    editable, cambios de defaults no sobrescriben planes de org.
  - _Requirements: 8.1, 8.2, 8.5, 8.8, 11.1_

- [x] 18. Tests de facturación mensual
  - Casos de la propuesta (13, 585, 3136, 6276 IPs); planes de org vs default; edición de tarifas.
  - _Requirements: 8.3, 8.4, 8.7, 8.8_

## Fase 6 — Suscripción y liquidación anual (informativa)

- [x] 19. Implementar suscripción anual
  - Endpoint de creación (superadmin): inicio = primer `created_at`, fin = aniversario−1 día,
    volumen declarado, tarifa/tramo/tope congelados.
  - Cierres mensuales durante la vigencia con `amount = 0.00`.
  - _Requirements: 9.1, 9.2, 8.6_

- [x] 20. Cálculo de liquidación en aniversario (informativo)
  - `real = min(billable, tier_cap)`; diff; crédito/cargo; guardar en `settlement`.
  - Endpoint GET (informativo) + endpoint de confirmación manual (aplica `status='settled'`).
  - Indicador informativo de "crecimiento libre"/reclasificación (sin reclasificar auto).
  - _Requirements: 9.3, 9.4, 9.5, 9.6_

- [x] 21. Tests de anual
  - Liquidación crédito/cargo; tope de tramo (10,500→10,000); invoice mensual $0 durante vigencia.
  - _Requirements: 9.2, 9.3, 9.4_

## Fase 7 — Restricción de eliminación

- [x] 22. `BillingDeletionService.delete_or_archive`
  - `new` → delete físico; no-`new` offline → `archived`; no-`new` online → rechazo.
  - _Requirements: 3.1, 3.2, 3.3_

- [x] 23. Interceptar borrado individual y añadir borrado masivo
  - Modificar `DELETE /workstations/{id}` para usar el servicio.
  - Añadir `POST /workstations/bulk-delete` con reporte de desglose (deleted/archived/rejected).
  - _Requirements: 3.4, 3.5, 3.6_

- [x] 24. Tests de eliminación
  - Individual (3 casos) y masivo mixto con reporte.
  - _Requirements: 3.1–3.6_

## Fase 8 — Modalidad, timezone lock y scheduler

- [x] 25. Timezone lock y modalidad en organización
  - En `update_organization` y `update_my_organization`: rechazar cambio de `timezone` si la org
    tiene ≥1 cierre.
  - Endpoint `PUT /billing/organizations/{id}/mode` (superadmin).
  - _Requirements: 4.2, 4.3, 4.4, 4.6_

- [x] 26. `BillingCloseScheduler` (cron de medianoche)
  - Clase con `AsyncIOScheduler` (patrón `status_scheduler`); cron horario que detecta orgs que
    cruzaron `00:00 del día 1` en su tz y aún no cerraron el mes anterior.
  - Arrancar/detener en el `lifespan` de `main.py`. Lock de concurrencia.
  - _Requirements: 7.1_

- [x] 27. Cierres retroactivos (endpoint superadmin)
  - `POST /billing/organizations/{id}/closures/retroactive`: cierra el mes pendiente más antiguo,
    uno por uno, respetando secuencialidad; aplica capping.
  - _Requirements: 7.2, 7.3, 7.4, 7.5_

- [x] 28. Configurar timezone de BBVA
  - Task operativa: setear `America/Lima` en la org BBVA antes de su primer cierre (verificar que
    no tenga cierres previos).
  - _Requirements: 4.5_

## Fase 9 — Frontend (sección Usage and Billing)

- [x] 29. Tipos y cliente API
  - `src/types/billing.ts`; funciones de fetch (sin `any`).
  - _Requirements: 10_

- [x] 30. Página y componentes de configuración/tarifas
  - `usage-and-billing/page.tsx`, `BillingModeCard`, `RatePlanEditor` (solo superadmin),
    timezone bloqueada tras el primer cierre.
  - _Requirements: 10.1, 10.2, 10.4, 10.8, 11.1_

- [x] 31. Listado de cierres y detalle
  - `ClosuresTable` + `ClosureDetailDrawer` (detalle por IP paginado); `RetroactiveCloseButton`.
  - _Requirements: 10.3, 10.5_

- [x] 32. Liquidación anual y ajustes de listado de workstations
  - `AnnualSettlementCard` (informativa + confirmar); filtro "ocultar archived" (default ON);
    diálogo de borrado que indica delete físico vs archive y la razón.
  - _Requirements: 10.6, 10.7, 9.5_

## Fase 10 — Integración, auditoría y cierre

- [x] 33. Auditoría de acciones sensibles
  - Registrar: cambio de modalidad, bloqueo de timezone, archivado manual, edición de tarifas,
    ejecución de cierres (auto/retroactivo), liquidaciones.
  - _Requirements: 11.4_

- [x] 34. Backup/restore de las tablas nuevas
  - Añadir las 5 tablas al listado del backup service; verificar orden FK en restore
    (`billing_closures` antes de `billing_closure_items`).
  - _Requirements: 6.4_

- [x] 35. Verificación end-to-end en dev y build final
  - Ejecutar suite completa (unit + integración + property-based) y build backend/frontend.
  - Ensayar la secuencia de cierres retroactivos de BBVA (mayo→agosto) en dev.
  - _Requirements: todos_
