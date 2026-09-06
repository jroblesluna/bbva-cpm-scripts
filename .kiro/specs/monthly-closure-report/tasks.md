# Implementation Plan

## Overview

Este plan implementa el **Reporte de Cierre Mensual** (PDF) del módulo *Usage and Billing* siguiendo un enfoque incremental y test-driven. Se construye desde la base de datos hacia arriba: dependencias y migración, luego el modelo y schemas, después el servicio (serie histórica → gráficos → análisis IA fail-safe → composición del PDF → caché S3), luego los endpoints REST con roles y tenant isolation, y finalmente el frontend (tipos, cliente API, UI y i18n). Cada tarea reutiliza patrones ya probados del repositorio (`debugging_analysis.py`, `llm_service.py`, `restore.py`) y referencia los criterios de aceptación de `requirements.md`.

## Tasks

- [x] 1. Agregar dependencias de gráficos y crear tabla `billing_closure_reports`
  - [x] 1.1 Pinnear dependencias de render de gráficos
    - En `AlwaysPrintProject/Cloud/backend/requirements.txt` agregar sección `# === CHARTS (server-side) ===` con `matplotlib>=3.8,<4.0` y `Pillow>=10.0,<12.0`
    - _Requisitos: 11.1, 11.2_

  - [x] 1.2 Definir modelo `BillingClosureReport`
    - En `app/models/billing.py` agregar la clase `BillingClosureReport` (tabla `billing_closure_reports`) con: `id` PK uuid4; `closure_id` FK → `billing_closures.id` `ON DELETE CASCADE`, `UNIQUE` (1:1); `organization_id` indexado (desnormalizado para tenant isolation); `ai_analysis` Text nullable; `ai_model` String(100) nullable; `ai_generated_at` DateTime nullable; `pdf_s3_key` String(512) nullable; `pdf_generated_at` DateTime nullable; `created_at`/`updated_at` con default utcnow y onupdate
    - No modificar la tabla `billing_closures` ni sus columnas
    - _Requisitos: 6.1, 11.4_

  - [x] 1.3 Crear migración Alembic para `billing_closure_reports`
    - Nuevo archivo en `app/db/migrations/versions/` que cree la tabla con la FK `ON DELETE CASCADE`, la restricción `UNIQUE` sobre `closure_id` y el índice sobre `organization_id`; incluir `downgrade` que borre la tabla
    - _Requisitos: 6.1, 11.4_

  - [x] 1.4 Test unitario del modelo y migración
    - Verificar que crear un `BillingClosureReport` con `closure_id` duplicado viola la restricción `UNIQUE`, y que borrar el `BillingClosure` padre elimina en cascada la fila del reporte
    - _Requisitos: 6.1, 11.4_

- [x] 2. Definir schemas Pydantic del reporte
  - [x] 2.1 Agregar schemas en `app/schemas/billing_closures.py`
    - `ClosureReportUrlResponse { report_url: str, expires_in_seconds: int = 3600, cached: bool, ai_analysis_available: bool }`
    - `ClosureReportMeta { closure_id, ai_model?, ai_generated_at?, pdf_generated_at?, ai_analysis_available }` con `from_attributes`
    - `HistoryPoint { cycle: int, period_year: int, period_month: int, total_billable: int, total_recycled: int, total_archived: int, amount: Decimal }`
    - `ClosureReportDataResponse { header, tiers_applied: list, history: List[HistoryPoint], ai_analysis: Optional[str], currency: str = "USD", taxes_included: bool = False }`
    - _Requisitos: 1.1, 7.4, 8.7_

  - [x] 2.2 Test unitario de serialización de schemas
    - Verificar defaults (`expires_in_seconds=3600`, `currency="USD"`, `taxes_included=False`) y `from_attributes` de `ClosureReportMeta`
    - _Requisitos: 1.3, 11.5_

- [x] 3. Implementar serie histórica y ciclo de servicio
  - [x] 3.1 Crear `app/services/closure_report_service.py` con `build_history_series`
    - Crear el archivo del servicio con la clase `ClosureReportService` (sin estado) y el método `build_history_series(db, org)` que consulta `BillingClosure` filtrando por `organization_id`, ordena por `period_year` ASC y `period_month` ASC, y asigna `cycle` 1-based (el más antiguo = 1), devolviendo `List[HistoryPoint]` con ciclo, periodo, totales y monto
    - Fijar `matplotlib.use("Agg")` a nivel de módulo antes de cualquier import de `pyplot`
    - _Requisitos: 4.1, 7.1, 7.2, 7.3, 7.4, 11.2_

  - [x] 3.2 Test unitario de `build_history_series`
    - Verificar `cycle=1` para el cierre más antiguo, numeración creciente consecutiva, orden por `(period_year, period_month)` y filtrado exclusivo por `organization_id`
    - _Requisitos: 7.1, 7.2, 7.3, 8.6_

- [x] 4. Implementar render de gráficos server-side
  - [x] 4.1 Implementar `render_tiers_chart` y `render_history_chart`
    - En `closure_report_service.py` agregar funciones puras que devuelven `bytes` PNG en `io.BytesIO` con `dpi` fijo y `plt.close(fig)` tras exportar
    - `render_tiers_chart(tiers_applied)`: IPs por tramo; si no hay tramos con `ips_in_tier > 0` → placeholder "sin IPs facturables" sin excepción
    - `render_history_chart(history)`: evolución de `total_billable` (barras) y `amount` (línea); si hay 1 solo punto → render mínimo con marcador único y nota "primer ciclo de servicio" sin excepción
    - _Requisitos: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 4.2 Test unitario de render con degradación elegante
    - Verificar PNG no vacío (firma PNG) para caso normal, 1 solo cierre y tramos vacíos; confirmar que `plt.close(fig)` se invoca (sin fugas de figuras)
    - _Requisitos: 4.3, 4.5, 4.6_

- [x] 5. Implementar análisis IA cacheado con fail-safe
  - [x] 5.1 Implementar `build_ai_prompt` y `resolve_ai_analysis`
    - `build_ai_prompt(header, history, items)`: incluir serie histórica por ciclo, desglose de tramos del mes objetivo, modalidad (`header.mode`) y moneda USD; solicitar resumen ejecutivo, análisis de evolución por ciclo y observaciones (en español)
    - `resolve_ai_analysis(db, closure, org, header, items, history, regenerate)`: si `regenerate=false` y existe fila con `ai_analysis` → devolver cache sin invocar LLM; si no, invocar el LLM reutilizando el patrón `_invoke_llm` de `app/services/llm_service.py` (Bedrock default / OpenAI si `org.openai_api_key`, respetando `org.llm_model_id`, retry/backoff), persistir con `upsert` en `billing_closure_reports` (texto, modelo, `ai_generated_at`); en error tras reintentos → FAIL-SAFE: log warning, devolver `None`, no propagar
    - _Requisitos: 5.1, 5.2, 5.3, 5.4, 5.5, 6.1, 6.2_

  - [x] 5.2 Test unitario de caché IA y fail-safe
    - Con `ai_analysis` persistido y `regenerate=false` → mock del LLM verifica 0 invocaciones; con `regenerate=true` → se invoca y sobre-escribe
    - LLM que lanza error tras reintentos → `resolve_ai_analysis` devuelve `None` sin propagar
    - _Requisitos: 5.4, 5.5, 6.2_

- [x] 6. Implementar composición del PDF con reconciliación
  - [x] 6.1 Implementar `compose_pdf` con las 9 secciones
    - En `closure_report_service.py`, reutilizando el patrón `_generate_pdf`/`sanitize` (Latin-1) y `footer` de `app/services/debugging_analysis.py`, componer el PDF con: (1) portada con logos AlwaysPrint + Robles.AI, título, organización, periodo `YYYY-MM`, modalidad y fecha; (2) resumen del cierre (facturables/reciclados/archivados, monto USD, tipo de cierre); (3) conceptos/tarifas/modalidad/tabla de tramos; (4) gráfico de composición de tramos; (5) gráfico de evolución histórica; (6) tabla resumen del desglose por tramo (from, to, rate, `ips_in_tier`, subtotal); (7) análisis IA o nota fail-safe si `ai_analysis=None`; (8) nota explícita USD sin impuestos; (9) footer de copyright de Inversiones On Line S.A.C. en cada página
    - _Requisitos: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 5.4, 11.5_

  - [x] 6.2 Implementar validación de reconciliación de montos
    - Antes de componer, validar que `sum(items.amount)` y el total del desglose reconcilien con `header.amount` con tolerancia `< 0.01` (redondeo half-up; cabecera 2 decimales, items 4); si excede → log warning y anotar la discrepancia en el PDF preservando `header.amount` como fuente de verdad
    - _Requisitos: 10.1, 10.2, 10.3_

  - [x] 6.3 Test unitario de composición y reconciliación
    - Verificar que `compose_pdf` produce bytes PDF válidos e incluye la nota USD sin impuestos y el footer; con `ai_analysis=None` incluye la nota fail-safe
    - Verificar que un cierre con varios tramos reconcilia dentro de `< 0.01` y que una discrepancia forzada genera warning + anotación sin alterar `header.amount`
    - _Requisitos: 3.7, 3.8, 5.4, 10.1, 10.2, 10.3_

- [x] 7. Implementar caché S3 y orquestación `generate_or_get`
  - [x] 7.1 Implementar storage/caché S3 y presigned URL
    - En `closure_report_service.py`: `build_s3_key(closure)` → `billing-reports/{organization_id}/{closure_id}/report.pdf`; `s3_exists` vía `head_object`; `upload_to_s3` reutilizando el patrón `_upload_to_s3` de `debugging_analysis.py` (sobre-escribe en regenerate); cliente S3 con SigV4 y endpoint regional explícito (`https://s3.{AWS_REGION}.amazonaws.com`, `Config(signature_version="s3v4")`) replicando `restore.py::_get_s3_client`; presigned URL con `ResponseContentDisposition` y expiración 3600s
    - _Requisitos: 1.2, 1.3, 2.1, 2.5_

  - [x] 7.2 Implementar `generate_or_get`
    - Orquestar: `build_s3_key` → si `regenerate=false` y `s3_exists` → cache-hit `(s3_key, analysis_exists, True)`; cache-miss/regenerate → cargar items, `build_history_series`, `resolve_ai_analysis`, `render_tiers_chart`, `render_history_chart`, `compose_pdf`, `upload_to_s3`; devolver `(s3_key, analysis_is_not_none, False)`; tratar el `BillingClosure` como solo lectura
    - _Requisitos: 1.1, 1.6, 2.2, 2.3, 2.4, 6.3, 11.3_

  - [x] 7.3 Test unitario de caché S3 hit/miss
    - Con S3 mockeado: artefacto existente + `regenerate=false` → `cached=true` sin recomputar; sin artefacto → pipeline completo → `cached=false`; `regenerate=true` → sobre-escribe aunque exista
    - Verificar que el cliente S3 se construye con SigV4 y endpoint regional (assert sobre `Config` y `endpoint_url`)
    - _Requisitos: 1.2, 2.2, 2.3, 2.4_

- [x] 8. Implementar endpoints REST con roles y tenant isolation
  - [x] 8.1 Agregar endpoints en `app/api/v1/endpoints/billing_closures.py`
    - `GET /billing/closures/{closure_id}/report`: `require_operator_or_admin` + resolver cierre + `_assert_org_scope`; 404 si no existe; 502/500 si falla S3; devolver `ClosureReportUrlResponse`
    - `POST /billing/closures/{closure_id}/report/regenerate`: restringido a Superadmin o admin de la org dueña; llama `generate_or_get(regenerate=true)`; 403 si no autorizado; `cached=false`
    - `GET /billing/closures/{closure_id}/report-data`: `require_operator_or_admin` + `_assert_org_scope`; devolver `ClosureReportDataResponse` (header, tiers_applied, history, ai_analysis si existe, currency, taxes_included)
    - _Requisitos: 1.1, 1.4, 1.5, 6.3, 6.4, 6.5, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [x] 8.2 Tests de integración de endpoints
    - `GET .../report` end-to-end con fixture (cabecera + items, S3 mock/localstack) → `report_url`; segunda llamada → `cached=true`
    - Tenant isolation: operador de org A pidiendo cierre de org B → 403; superadmin → 200
    - `regenerate` con admin/superadmin → `cached=false` y `ai_generated_at` actualizado; operador de otra org → 403
    - Fail-safe end-to-end: proveedor LLM forzado a fallar → PDF generado con `ai_analysis_available=false`
    - _Requisitos: 1.4, 1.5, 5.4, 6.4, 6.5, 8.2, 8.3, 8.4, 8.5_

- [x] 9. Checkpoint backend
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Implementar frontend (tipos, cliente API, UI e i18n)
  - [x] 10.1 Agregar tipos TS en `src/types/billing.ts`
    - `ClosureReportUrlResponse { report_url, expires_in_seconds, cached, ai_analysis_available }`, `HistoryPoint { cycle, period_year, period_month, total_billable, total_recycled, total_archived, amount: number | string }`, `ClosureReportData { header, tiers_applied: unknown[], history: HistoryPoint[], ai_analysis: string | null, currency, taxes_included }` (sin `any`, snake_case)
    - _Requisitos: 9.1, 9.4_

  - [x] 10.2 Agregar funciones de cliente API en `src/lib/api/billing.ts`
    - `getClosureReport(closureId)` → `GET /billing/closures/{closureId}/report`; `regenerateClosureReport(closureId)` → `POST .../report/regenerate`; `getClosureReportData(closureId)` → `GET .../report-data`
    - _Requisitos: 9.1, 9.2, 9.4_

  - [x] 10.3 Implementar UI en la página de cierres del dashboard de billing
    - Botón "Descargar reporte" → `getClosureReport` y abre `report_url` en nueva pestaña; botón "Regenerar análisis" visible solo a admin/superadmin → `regenerateClosureReport` con confirmación previa (oculto para no-admin); vista previa opcional que consume `getClosureReportData` y renderiza composición de tramos y evolución histórica con `recharts`
    - _Requisitos: 9.1, 9.2, 9.3, 9.4_

  - [x] 10.4 Agregar claves i18n del namespace `billingReport`
    - Añadir el namespace `billingReport` con todas las claves de textos visibles en `messages/en.json` y `messages/es.json`; usar `next-intl` en la UI
    - _Requisitos: 9.5_

  - [x] 10.5 Tests de frontend
    - Verificar que "Regenerar análisis" se oculta para no-admin y se muestra para admin/superadmin; que "Descargar reporte" invoca `getClosureReport` y abre la URL; que la vista previa renderiza gráficos con `recharts`
    - _Requisitos: 9.1, 9.2, 9.3, 9.4_

- [x] 11. Property-based tests (opcional, hypothesis)
  - [x] 11.1 Propiedades de composición de tramos y reconciliación
    - Con `hypothesis`: para cualquier `count >= 0` y tramos válidos, la suma de `ips_in_tier` del gráfico de composición nunca excede `count`, y el subtotal del desglose reconcilia con el `amount` de `billing_service.compute_amount_monthly` dentro de la tolerancia de redondeo
    - _Requisitos: 4.2, 10.1_

- [x] 12. Checkpoint final
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Las tareas marcadas con `*` son opcionales (tests) y pueden omitirse para un MVP más rápido, pero se recomienda implementarlas para mantener la integridad del sustento de facturación.
- Cada tarea referencia criterios de aceptación específicos de `requirements.md` para trazabilidad.
- El servicio es de solo lectura sobre `BillingClosure`; nunca modifica el motor de cierre ni la resolución de tarifas.
- El fail-safe de IA es obligatorio: un fallo del LLM nunca bloquea la generación del reporte ni la factura.
- Se reutilizan patrones existentes de `debugging_analysis.py` (PDF/logos/footer/upload/sanitize), `llm_service.py` (invocación LLM multi-proveedor) y `restore.py` (cliente S3 SigV4 regional).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "2.1", "10.1"] },
    { "id": 1, "tasks": ["1.3", "2.2", "3.1", "10.2", "10.4"] },
    { "id": 2, "tasks": ["1.4", "3.2", "4.1", "5.1"] },
    { "id": 3, "tasks": ["4.2", "5.2", "6.1", "6.2"] },
    { "id": 4, "tasks": ["6.3", "7.1"] },
    { "id": 5, "tasks": ["7.2"] },
    { "id": 6, "tasks": ["7.3", "8.1"] },
    { "id": 7, "tasks": ["8.2", "10.3"] },
    { "id": 8, "tasks": ["10.5", "11.1"] }
  ]
}
```
