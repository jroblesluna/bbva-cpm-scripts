# Design Document

## Overview

Esta feature agrega un **Reporte de Cierre Mensual** (PDF) al módulo *Usage and Billing* de AlwaysPrint Cloud, pensado como **sustento formal de la factura** de una organización. El reporte se construye sobre el snapshot inmutable de un `BillingClosure` (cabecera + items por IP) y contiene: portada con logos (AlwaysPrint + Robles.AI), resumen del cierre, descripción de conceptos/tarifas/modalidad/tramos, dos gráficos (composición de tramos del mes y evolución histórica de estaciones facturables / monto a lo largo de los cierres), una tabla resumen, un **análisis IA del consumo**, una declaración explícita de que los precios están en **dólares americanos (USD) y no incluyen impuestos**, y el pie de copyright.

El diseño reutiliza patrones ya probados en el repositorio: la generación de PDF con `fpdf2`, la incrustación de logos y el pie de copyright de `app/services/debugging_analysis.py`, y la invocación LLM multi-proveedor (Bedrock por defecto / OpenAI / Anthropic) que respeta la configuración por organización (`org.openai_api_key`, `org.llm_model_id`).

### Decisiones de arquitectura confirmadas

- **(A) PDF y gráficos server-side.** El PDF se genera en el backend con `fpdf2` (ya presente en `backend/requirements.txt`, `fpdf2>=2.7.0`), reutilizando el patrón de `_generate_pdf` / `_upload_to_s3` de `debugging_analysis.py`. Los gráficos se renderizan **server-side** con `matplotlib` a PNG en memoria (`io.BytesIO`) y se incrustan con `pdf.image()`. Esto obliga a incorporar dos **dependencias nuevas pinneadas**: `matplotlib` y `Pillow`, y a usar `matplotlib` en modo **headless** (backend `Agg`, sin display) porque el backend corre en contenedores sin servidor gráfico.

- **(B) Generación on-demand con caché de artefacto en S3.** Al solicitar el reporte se resuelve el cierre, se genera el PDF, se sube a S3 y se devuelve una **presigned URL** (mismo pipeline que debugging). Además, el PDF se **persiste con una S3 key determinista por cierre** (`billing-reports/{organization_id}/{closure_id}/report.pdf`); si el artefacto ya existe y no se solicita regenerar, se sirve el existente sin recomputar (cache-hit).

- **(C) Análisis IA cacheado junto al cierre.** Como el cierre es inmutable, el análisis IA sobre esos datos también lo es: se **persiste** para no recomputar en cada descarga. Se recomienda una **tabla auxiliar `billing_closure_reports`** (1:1 con el cierre) en lugar de una columna en `billing_closures` (justificación en *Data Models*). Un flag `regenerate=true` (solo admin/superadmin) recomputa el análisis IA y sobre-escribe tanto el texto cacheado como el PDF en S3.

### Trazabilidad (design-first)

Este es un flujo **design-first**: los `requirements.md` se derivarán a partir de este diseño y los `tasks.md` a partir de ambos. Cada sección incluye marcadores de intención de requisito (p. ej. *"contenido obligatorio"*, *"fail-safe"*, *"tenant isolation"*) que servirán como semilla para las historias de usuario y criterios de aceptación en la fase de requisitos. No se generan `requirements.md` ni `tasks.md` en este paso.

### Alcance

- **Incluye:** endpoints REST nuevos bajo `/billing`, un servicio nuevo `app/services/closure_report_service.py`, render de gráficos con `matplotlib`, integración LLM con caché y fail-safe, capa de storage/caché en S3, migración de BD, schemas Pydantic y tipos TS nuevos, y UI de descarga/regeneración con vista previa opcional.
- **No incluye:** cambios al motor de cierre (`billing_close_service`), a la resolución de planes/tarifas (`billing_service.resolve_plan` / `compute_amount_monthly`) ni a la semántica de facturación. El reporte es de **solo lectura** sobre datos ya materializados.

---

## Architecture

### Flujo de generación (on-demand con caché)

```mermaid
flowchart TD
    A[Cliente: GET /billing/closures/{closure_id}/report] --> B{Resolver cierre + tenant scope}
    B -->|404 no existe / 403 otra org| Z[Error HTTP]
    B -->|OK| C{regenerate == true?}
    C -->|No| D{Existe PDF en S3?\nbilling-reports/org/closure/report.pdf}
    D -->|Sí cache-hit| P[Generar presigned URL SigV4 regional] --> R[Responder report_url]
    D -->|No cache-miss| E[Cargar cabecera + items del cierre]
    C -->|Sí regenerar| E
    E --> F[Derivar serie histórica de cierres de la org\nciclo = orden por period_year, period_month]
    F --> G{Existe analisis IA cacheado\ny regenerate == false?}
    G -->|Sí| H[Leer ai_analysis cacheado]
    G -->|No| I[Construir prompt: serie historica + tramos del mes + modalidad]
    I --> J[Invocar LLM con retry/backoff\nconfig de la org]
    J -->|OK| K[Persistir ai_analysis + modelo + fecha]
    J -->|Falla tras reintentos| L[ai_analysis = None\nnota fail-safe en PDF]
    H --> M
    K --> M
    L --> M[Render graficos matplotlib -> PNG en memoria]
    M --> N[Componer PDF con fpdf2\nportada, resumen, conceptos, graficos, tabla, IA, nota USD, footer]
    N --> O[Subir PDF a S3 con S3 key determinista]
    O --> P
```

### Componentes que se agregan o tocan

| Elemento | Ruta | Tipo | Cambio |
|---|---|---|---|
| Servicio de reporte | `app/services/closure_report_service.py` | Backend (nuevo) | Orquesta caché S3 → serie histórica → IA cacheada/nueva → gráficos → PDF → upload |
| Endpoints de reporte | `app/api/v1/endpoints/billing_closures.py` | Backend (extender) | `GET .../report`, `POST .../report/regenerate`, opcional `GET .../report-data` |
| Modelo de reporte | `app/models/billing.py` | Backend (extender) | Tabla nueva `billing_closure_reports` (recomendada) |
| Migración | `app/db/migrations/versions/*` | Backend (nuevo) | Crear tabla `billing_closure_reports` |
| Schemas | `app/schemas/billing_closures.py` | Backend (extender) | `ClosureReportUrlResponse`, `ClosureReportMeta`, `ClosureReportDataResponse` |
| Dependencias | `backend/requirements.txt` | Backend | Agregar `matplotlib` y `Pillow` (pinneadas) |
| Cliente API | `src/lib/api/billing.ts` | Frontend (extender) | `getClosureReport`, `regenerateClosureReport`, opcional `getClosureReportData` |
| Tipos TS | `src/types/billing.ts` | Frontend (extender) | `ClosureReportUrlResponse`, `ClosureReportMeta`, `ClosureReportData` |
| UI | dashboard de billing (página de cierres) | Frontend | Botón "Descargar reporte" / "Regenerar análisis", vista previa opcional (recharts) |
| i18n | `messages/en.json`, `messages/es.json` | Frontend | Namespace nuevo `billingReport` |
| Assets | `app/static/alwaysprint_logo.png`, `app/static/robles_ai_logo.png` | Backend | Reutilizados (ya existen) |

### Dependencias nuevas (headless)

En `backend/requirements.txt`, bajo una sección nueva `# === CHARTS (server-side) ===`:

```pascal
matplotlib>=3.8,<4.0   // render server-side de graficos a PNG
Pillow>=10.0,<12.0     // backend de imagen usado por matplotlib / fpdf2 image()
```

El servicio DEBE fijar el backend headless **antes** de importar `pyplot`, para no requerir display:

```pascal
PROCEDURE configurar_matplotlib_headless()
  // Ejecutar una sola vez, a nivel de modulo, antes de 'import matplotlib.pyplot'
  matplotlib.use("Agg")   // backend no interactivo, sin servidor grafico
END PROCEDURE
```

### Migración de BD

Migración Alembic que crea `billing_closure_reports` (FK a `billing_closures`, `ON DELETE CASCADE`), con `closure_id` único (relación 1:1). No modifica `billing_closures` (evita bloqueos/reescrituras sobre una tabla de sustento inmutable).

---

## Components and Interfaces

### 1. Endpoints REST (backend)

Se agregan al router existente de `billing_closures.py` (montado bajo `/billing`, por eso las rutas empiezan en `/billing/...`). Reutilizan los mismos guards de permisos ya usados en ese archivo: `require_operator_or_admin` + `_assert_org_scope` para lectura y `require_admin` para operaciones de superadmin.

#### `GET /billing/closures/{closure_id}/report`

Genera (o sirve desde caché) el PDF del reporte y devuelve una presigned URL.

- **Rol:** `require_operator_or_admin`. Tenant isolation: se resuelve el cierre, se obtiene su `organization_id` y se valida con `_assert_org_scope` (un operador solo su org; superadmin cualquiera). Mismo criterio que `list_closure_items`.
- **Query params:** ninguno obligatorio. `download_filename` opcional (nombre sugerido de descarga).
- **Comportamiento:** cache-hit si el PDF existe en S3 → presigned URL directa; cache-miss → pipeline completo.
- **Respuesta:** `ClosureReportUrlResponse { report_url, expires_in_seconds, cached, ai_analysis_available }`.
- **Errores:** 403 (otra org), 404 (cierre inexistente), 502/500 (fallo S3 al generar presigned). El fallo de IA **no** es error (fail-safe).

#### `POST /billing/closures/{closure_id}/report/regenerate`

Recomputa el análisis IA y el PDF, sobre-escribiendo el artefacto cacheado.

- **Rol:** `require_admin` (superadmin) **o** admin de la organización dueña del cierre. Como el repo distingue superadmin (`UserRole.ADMIN`, global) de operador, la regla es: superadmin siempre; un admin/operador de la org dueña puede regenerar solo su propio cierre. Se implementa con `require_operator_or_admin` + `_assert_org_scope` y una comprobación explícita de rol admin para bloquear operadores de menor privilegio si el proyecto lo exige (a confirmar en requisitos).
- **Efecto:** `regenerate=true` internamente → recomputa IA, sobre-escribe `ai_analysis` en `billing_closure_reports`, re-renderiza gráficos, regenera PDF y **sobre-escribe** la misma S3 key.
- **Respuesta:** `ClosureReportUrlResponse` con `cached=false`.

#### `GET /billing/closures/{closure_id}/report-data` (opcional, para vista previa)

Devuelve los datos estructurados que también alimentan el PDF (serie histórica, desglose de tramos, resumen, texto IA si existe) para renderizar una **vista previa en la UI con recharts** sin descargar el PDF.

- **Rol:** `require_operator_or_admin` + `_assert_org_scope`.
- **Respuesta:** `ClosureReportDataResponse`.

> **Recomendación (vista previa):** exponer `report-data` y mostrar los gráficos en pantalla con `recharts` (^2.10.4, ya presente) como *preview*, manteniendo los gráficos del PDF en `matplotlib` (server-side). Motivo: el PDF debe ser autocontenido y determinista (no depende del navegador), mientras que la UI ya tiene recharts y ofrece interactividad. Ambos consumen el mismo `report-data`, evitando duplicar la lógica de agregación.

### 2. Servicio de generación — `ClosureReportService`

Nuevo `app/services/closure_report_service.py`. Sin estado (recibe `db`, `closure`, `org`), siguiendo el estilo de `BillingService` y `DebuggingAnalysisService`.

```pascal
CLASS ClosureReportService

  // Punto de entrada. Devuelve (s3_key, ai_available, cached).
  PROCEDURE generate_or_get(db, closure, org, regenerate = false) : (String, Boolean, Boolean)
    s3_key <- build_s3_key(closure)            // determinista por cierre
    IF NOT regenerate AND s3_exists(s3_key) THEN
      RETURN (s3_key, analysis_exists(db, closure), TRUE)   // cache-hit
    END IF

    header  <- closure                          // BillingClosure (inmutable)
    items   <- load_items(db, closure)          // BillingClosureItem[]
    history <- build_history_series(db, org)    // serie de cierres con numero de ciclo
    analysis <- resolve_ai_analysis(db, closure, org, header, items, history, regenerate)

    tiers_png   <- render_tiers_chart(header.tiers_applied)     // PNG en memoria
    history_png <- render_history_chart(history)                // PNG en memoria
    pdf_bytes   <- compose_pdf(header, items, history, tiers_png, history_png, analysis, org)
    upload_to_s3(pdf_bytes, s3_key)             // sobre-escribe si regenerate
    RETURN (s3_key, analysis IS NOT NULL, FALSE)
  END PROCEDURE

  // Numero de ciclo/mes de servicio: iterar cierres de la org ordenados por
  // (period_year, period_month). El primer cierre = ciclo 1.
  PROCEDURE build_history_series(db, org) : List<HistoryPoint>
    closures <- db.query(BillingClosure)
                  .filter(organization_id == org.id)     // tenant isolation
                  .order_by(period_year ASC, period_month ASC)
    series <- []
    FOR index, c IN enumerate(closures) DO
      series.append(HistoryPoint {
        cycle: index + 1,
        period_year: c.period_year, period_month: c.period_month,
        total_billable: c.total_billable,
        total_recycled: c.total_recycled,
        total_archived: c.total_archived,
        amount: c.amount
      })
    END FOR
    RETURN series
  END PROCEDURE

  // Caché de IA: leer si existe y no se regenera; si no, invocar LLM (fail-safe).
  PROCEDURE resolve_ai_analysis(db, closure, org, header, items, history, regenerate) : String?
    IF NOT regenerate THEN
      cached <- get_report_row(db, closure)
      IF cached IS NOT NULL AND cached.ai_analysis IS NOT NULL THEN
        RETURN cached.ai_analysis
      END IF
    END IF
    prompt <- build_ai_prompt(header, history, items)
    TRY
      text, model_id <- invoke_llm(prompt, org)     // retry/backoff como debugging
      upsert_report_row(db, closure, ai_analysis = text, model = model_id, generated_at = now())
      RETURN text
    CATCH LLMError
      // FAIL-SAFE: no bloquear la factura por IA. PDF se genera con nota.
      log_warning("Analisis IA no disponible para cierre {closure.id}")
      RETURN NULL
    END TRY
  END PROCEDURE

  PROCEDURE build_s3_key(closure) : String
    RETURN "billing-reports/" + closure.organization_id + "/" + closure.id + "/report.pdf"
  END PROCEDURE

END CLASS
```

### 3. Render de gráficos (matplotlib, headless)

Dos funciones puras que devuelven `bytes` PNG (guardan en `io.BytesIO`, `dpi` fijo, cierran la figura con `plt.close(fig)` para no filtrar memoria):

```pascal
FUNCTION render_tiers_chart(tiers_applied) : bytes
  // Composicion de tramos del mes: barras/pastel con ips_in_tier por tramo
  // Entrada: tiers_applied (JSON de la cabecera) -> [{tier_index, tier_from, tier_to, rate, ips_in_tier, subtotal}]
  // Si no hay tramos con ips_in_tier > 0 -> grafico placeholder "sin IPs facturables"
  fig <- matplotlib.figure()
  ... dibujar ...
  buf <- BytesIO(); fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
  plt.close(fig)
  RETURN buf.getvalue()
END FUNCTION

FUNCTION render_history_chart(history) : bytes
  // Evolucion historica: eje X = ciclo (1..n) o "YYYY-MM"; dos series:
  //   - total_billable (barras)  - amount (linea, eje secundario)
  // Si history tiene 1 solo punto -> render minimo (un marcador + nota "primer ciclo")
  ...
END FUNCTION
```

### 4. Integración LLM

Se reutiliza el patrón de `debugging_analysis.py::_invoke_llm`: `LLMService` (Bedrock por defecto) o `OpenAIProvider` cuando `org.openai_api_key` está presente, respetando `org.llm_model_id`, con `max_retries=3` y backoff. El **prompt** DEBE incluir:

- La **serie histórica** de cierres (por cada mes: ciclo de servicio, `total_billable`, `total_recycled`, `total_archived`, `amount`).
- El **desglose de tramos** del mes objetivo (`tiers_applied`).
- La **modalidad** (`header.mode`) y la moneda (USD).
- Instrucción de producir: **resumen ejecutivo**, **análisis de evolución/crecimiento por ciclo de servicio** (comentando el número de ciclo/mes de servicio), y **observaciones**.

```pascal
FUNCTION build_ai_prompt(header, history, items) : String
  sections <- []
  sections.append("Eres un analista de consumo y facturacion de servicios de impresion. " +
                  "Redacta en espanol, tono profesional, sin exagerar. Precios en USD sin impuestos.")
  sections.append("## Modalidad\n" + header.mode + "  | Moneda: USD (sin impuestos)")
  sections.append("## Serie historica de cierres (por ciclo de servicio)")
  FOR p IN history DO
    sections.append("- Ciclo " + p.cycle + " (" + p.period_year + "-" + p.period_month +
                    "): facturables=" + p.total_billable + ", reciclados=" + p.total_recycled +
                    ", archivados=" + p.total_archived + ", monto=USD " + p.amount)
  END FOR
  sections.append("## Desglose de tramos del mes objetivo\n" + format_tiers(header.tiers_applied))
  sections.append("## Solicitud\n" +
     "1. Resumen ejecutivo (2-3 oraciones).\n" +
     "2. Analisis de evolucion/crecimiento segun el numero de ciclo de servicio.\n" +
     "3. Observaciones y detalle del reporte.")
  RETURN join(sections, "\n")
END FUNCTION
```

### 5. Capa de storage / caché S3

- **S3 key determinista:** `billing-reports/{organization_id}/{closure_id}/report.pdf` en `settings.S3_DOCS_BUCKET` (mismo bucket que usa `debugging_analysis._upload_to_s3`).
- **Cache-hit:** `head_object` sobre la key; si existe (200) y `regenerate=false`, servir presigned.
- **Presigned URL:** cliente S3 con **SigV4** y **endpoint regional explícito** (`https://s3.{AWS_REGION}.amazonaws.com`, `Config(signature_version="s3v4")`), replicando `restore.py::_get_s3_client`. `ResponseContentDisposition='attachment; filename="..."'` y expiración 3600s, como en `debugging.py`.
- **Sobre-escritura:** en regenerate, `put_object` sobre la misma key reemplaza el artefacto.

### 6. Frontend

Tipos y funciones nuevas en `src/types/billing.ts` y `src/lib/api/billing.ts` (sin `any`, snake_case igual al backend):

```pascal
// billing.ts (extension)
FUNCTION getClosureReport(closureId) : Promise<ClosureReportUrlResponse>
  RETURN apiClient.get("/billing/closures/" + closureId + "/report").data
END FUNCTION

FUNCTION regenerateClosureReport(closureId) : Promise<ClosureReportUrlResponse>
  RETURN apiClient.post("/billing/closures/" + closureId + "/report/regenerate").data
END FUNCTION

FUNCTION getClosureReportData(closureId) : Promise<ClosureReportData>   // opcional (preview)
  RETURN apiClient.get("/billing/closures/" + closureId + "/report-data").data
END FUNCTION
```

UI en la página de cierres del dashboard de billing:
- Botón **"Descargar reporte"** → llama `getClosureReport`, abre `report_url` en nueva pestaña.
- Botón **"Regenerar análisis"** (visible solo a admin/superadmin) → `regenerateClosureReport`, con confirmación.
- **Vista previa opcional** (recharts): `ClosureReportData` alimenta un gráfico de composición de tramos y uno de evolución histórica en pantalla.
- Todos los textos visibles usan **next-intl** bajo el namespace nuevo `billingReport` en `messages/en.json` y `messages/es.json`.

---

## Data Models

### Cambio de BD: tabla auxiliar vs columna

**Recomendación: tabla auxiliar `billing_closure_reports` (1:1 con el cierre).** Justificación:

1. **Sustento inmutable intacto.** `billing_closures` y `billing_closure_items` son el sustento inmutable de la factura. Agregar una columna mutable (`ai_analysis`, que se puede **regenerar**) sobre una tabla de sustento mezcla datos inmutables con datos derivados/mutables y complica auditoría. Una tabla aparte aísla el artefacto derivado.
2. **Metadata de generación.** Además del texto, conviene guardar `ai_model`, `ai_generated_at`, `pdf_s3_key`, `pdf_generated_at`. Una tabla lo modela limpio sin ensuciar la cabecera con múltiples columnas nullable.
3. **Escritura sin tocar el snapshot.** Regenerar el análisis o el PDF hace `UPDATE`/`UPSERT` sobre `billing_closure_reports`, nunca sobre el cierre. Evita reescrituras y locks sobre la tabla de facturación.
4. **Extensibilidad.** Si más adelante se cachean variantes (idioma, versión de plantilla), la tabla escala mejor que columnas sueltas.

```pascal
CLASS BillingClosureReport (tabla "billing_closure_reports")
  id            : GUID  PK  default uuid4
  closure_id    : GUID  FK -> billing_closures.id  ON DELETE CASCADE  UNIQUE  // 1:1
  organization_id : GUID  index                    // desnormalizado para tenant isolation / limpieza
  ai_analysis   : Text   nullable                  // NULL = IA no disponible (fail-safe)
  ai_model      : String(100) nullable             // modelo LLM usado (bedrock/openai id)
  ai_generated_at : DateTime nullable
  pdf_s3_key    : String(512) nullable             // key determinista cacheada
  pdf_generated_at : DateTime nullable
  created_at    : DateTime  default utcnow
  updated_at    : DateTime  default utcnow onupdate utcnow
END CLASS
```

> Alternativa descartada: columna `ai_analysis TEXT` + `ai_model`/`ai_generated_at` directamente en `billing_closures`. Es más simple pero contamina el sustento inmutable y no separa el artefacto derivado; se documenta como opción B por si se prefiere minimizar la migración.

### Schemas Pydantic nuevos (`app/schemas/billing_closures.py`)

```pascal
CLASS ClosureReportUrlResponse (BaseModel)
  report_url            : str        // presigned URL SigV4 regional
  expires_in_seconds    : int = 3600
  cached                : bool       // TRUE si se sirvio desde S3 sin regenerar
  ai_analysis_available : bool       // FALSE si el LLM fallo (fail-safe)
END CLASS

CLASS ClosureReportMeta (BaseModel)   // de BillingClosureReport, from_attributes
  closure_id       : UUID
  ai_model         : Optional[str]
  ai_generated_at  : Optional[datetime]
  pdf_generated_at : Optional[datetime]
  ai_analysis_available : bool
END CLASS

CLASS HistoryPoint (BaseModel)
  cycle          : int               // numero de ciclo/mes de servicio (1-based)
  period_year    : int
  period_month   : int
  total_billable : int
  total_recycled : int
  total_archived : int
  amount         : Decimal
END CLASS

CLASS ClosureReportDataResponse (BaseModel)   // para vista previa (recharts)
  header    : ClosureHeaderResponse          // reutiliza el schema existente
  tiers_applied : list                        // desglose de tramos del mes
  history   : List[HistoryPoint]
  ai_analysis : Optional[str]
  currency  : str = "USD"
  taxes_included : bool = False
END CLASS
```

### Tipos TS nuevos (`src/types/billing.ts`)

```pascal
INTERFACE ClosureReportUrlResponse {
  report_url: string
  expires_in_seconds: number
  cached: boolean
  ai_analysis_available: boolean
}

INTERFACE HistoryPoint {
  cycle: number
  period_year: number
  period_month: number
  total_billable: number
  total_recycled: number
  total_archived: number
  amount: number | string
}

INTERFACE ClosureReportData {
  header: ClosureHeader
  tiers_applied: unknown[]
  history: HistoryPoint[]
  ai_analysis: string | null
  currency: string
  taxes_included: boolean
}
```

### Modelo del contenido del PDF

El PDF se compone con las siguientes secciones, en orden (todas con textos en español; sanitización Latin-1 heredada de `debugging_analysis.sanitize`):

| # | Sección | Contenido | Fuente de datos |
|---|---|---|---|
| 1 | **Portada / header** | Logos AlwaysPrint (izq.) y Robles.AI (der.) + "División de Automatización"; título "Reporte de Cierre Mensual - Sustento de Factura"; organización, periodo (`YYYY-MM`), modalidad, fecha de generación. | `app/static/*.png`, `header`, `org` |
| 2 | **Resumen del cierre** | Totales: facturables, reciclados, archivados; monto total (USD); tipo de cierre (retroactivo o normal). | `header.total_*`, `header.amount`, `header.is_retroactive` |
| 3 | **Conceptos, tarifas, modalidad y tramos** | Descripción textual de conceptos (facturable/reciclado/archivado), la modalidad aplicada y la tabla de tramos con tarifa por tramo. | `header.mode`, `header.tiers_applied` |
| 4 | **Gráfico: composición de tramos** | PNG de `render_tiers_chart` (IPs por tramo). | `header.tiers_applied` |
| 5 | **Gráfico: evolución histórica** | PNG de `render_history_chart` (crecimiento de facturables / monto por ciclo). | `build_history_series` |
| 6 | **Tabla resumen** | Tabla del desglose por tramo (from, to, rate, ips_in_tier, subtotal) que **reconcilia** con `amount`. | `header.tiers_applied`, `header.amount` |
| 7 | **Análisis IA** | Texto del LLM (resumen ejecutivo, evolución por ciclo, observaciones). Si no disponible → nota fail-safe. | `ai_analysis` |
| 8 | **Nota USD sin impuestos** | Texto explícito y destacado: *"Todos los precios están expresados en dólares americanos (USD) y no incluyen impuestos."* | fijo (contenido obligatorio) |
| 9 | **Footer copyright** | "(c) {año} Inversiones On Line S.A.C. - Todos los derechos reservados" en cada página. | patrón `DebuggingPDF.footer` |

---

## Error Handling

| Escenario | Manejo | Reversible / fail-safe |
|---|---|---|
| **Fallo del LLM** (timeout, error de proveedor tras reintentos) | **Fail-safe:** no se propaga error. `ai_analysis = NULL`, el PDF se genera igual con una nota "Análisis IA no disponible en este momento". `ai_analysis_available=false` en la respuesta. La factura **no** se bloquea por IA. | Fail-safe (regla de proyecto) |
| **Fallo de S3 al subir PDF** | `put_object` falla → 502/500 con detalle; no se cachea artefacto parcial. El cliente puede reintentar. | Reintentable |
| **Fallo de S3 al generar presigned URL** | 502/500; se distingue de "PDF no existe" (cache-miss regenera). | Reintentable |
| **Cierre inexistente** | 404 (patrón de `list_closure_items`). | — |
| **Permisos / tenant isolation** | Operador consultando otra org → 403 vía `_assert_org_scope`. Regenerar restringido a admin/superadmin. Todas las queries filtran por `organization_id`. | — |
| **Datos insuficientes para gráficos** (1 solo cierre) | `render_history_chart` con 1 punto → render mínimo con marcador único + nota "primer ciclo de servicio"; no lanza excepción. | Degradación elegante |
| **Sin IPs facturables / tramos vacíos** | `render_tiers_chart` muestra placeholder "sin IPs facturables"; tabla resumen muestra monto 0.00. | Degradación elegante |
| **Reconciliación de montos** | Antes de componer, se valida que `sum(items.amount)` reconcilie con `header.amount` con tolerancia `< 0.01` (redondeo half-up: cabecera 2 decimales, items 4). Si excede la tolerancia → se registra warning y el PDF anota la discrepancia (no se falsea el monto de cabecera, que es la fuente de verdad). | Diagnóstico |
| **Caché obsoleta** | El cierre es inmutable, así que un PDF cacheado nunca queda "obsoleto" por cambio de datos; solo `regenerate=true` lo sobre-escribe (p. ej. tras mejorar la plantilla o el prompt). | — |

---

## Testing Strategy

### Unit

- **Render de gráficos:** `render_tiers_chart` y `render_history_chart` devuelven PNG no vacío (bytes con firma PNG) para: caso normal, 1 solo cierre, tramos vacíos. Verificar que `plt.close(fig)` se llama (sin fugas de figuras).
- **Serie histórica / ciclo:** `build_history_series` asigna `cycle=1` al cierre más antiguo por `(period_year, period_month)` y numeración creciente; filtra por `organization_id`.
- **Composición de secciones del PDF:** `compose_pdf` produce bytes PDF válidos e incluye la nota USD sin impuestos y el footer de copyright; con `ai_analysis=None` incluye la nota fail-safe.
- **Caché S3 hit/miss:** con S3 mockeado, `generate_or_get` con artefacto existente y `regenerate=false` → `cached=true` sin recomputar; sin artefacto → pipeline completo → `cached=false`; `regenerate=true` → sobre-escribe aunque exista.
- **Fail-safe IA:** LLM que lanza error tras reintentos → `resolve_ai_analysis` devuelve `None`, no propaga, y `generate_or_get` completa el PDF.
- **Caché IA:** con `ai_analysis` ya persistido y `regenerate=false` → no se invoca el LLM (mock verifica 0 llamadas); `regenerate=true` → se invoca y sobre-escribe.
- **Presigned URL:** el cliente S3 se construye con SigV4 y endpoint regional (assert sobre `Config` y `endpoint_url`).

### Integración

- **Endpoint end-to-end** con un cierre real de fixtures (cabecera + items): `GET .../report` devuelve `report_url` y sube el PDF a S3 (mock/localstack). Segunda llamada → `cached=true`.
- **Regenerate** con admin/superadmin → `cached=false` y `ai_generated_at` actualizado; con operador de otra org → 403.
- **Tenant isolation:** operador de la org A pidiendo el reporte de un cierre de la org B → 403; superadmin → 200.
- **Fail-safe end-to-end:** proveedor LLM forzado a fallar → PDF generado con `ai_analysis_available=false`.

### Validación de reconciliación

- Test que compone el reporte para un cierre con varios tramos y verifica que el **total del reporte** (suma del desglose y de `items.amount`) **reconcilia** con `header.amount` dentro de la tolerancia `< 0.01`, cubriendo el redondeo half-up (cabecera 2 decimales, items 4 decimales).

### Property-based (opcional)

**Librería:** `hypothesis` (ya presente en el repo, ver `.hypothesis/`). Propiedad: para cualquier `count >= 0` y tramos válidos, la suma de `ips_in_tier` del gráfico de composición nunca excede `count`, y el subtotal del desglose reconcilia con el `amount` calculado por `billing_service.compute_amount_monthly` dentro de la tolerancia de redondeo.
