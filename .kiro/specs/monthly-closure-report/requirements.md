# Requirements Document

## Introduction

Esta feature agrega un **Reporte de Cierre Mensual** (PDF) al módulo *Usage and Billing* de AlwaysPrint Cloud, concebido como **sustento formal de la factura** de una organización. El reporte se construye sobre el snapshot inmutable de un `BillingClosure` (cabecera + items por IP) y presenta: portada con logos, resumen del cierre, descripción de conceptos/tarifas/modalidad/tramos, dos gráficos (composición de tramos del mes y evolución histórica por ciclo de servicio), una tabla resumen que reconcilia con el monto de cabecera, un análisis IA del consumo, una declaración explícita de precios en dólares americanos (USD) sin impuestos, y el pie de copyright.

Los requisitos aquí descritos se **derivan del documento de diseño** (`design.md`) ya aprobado, en un flujo *design-first*. El reporte es de **solo lectura** sobre datos ya materializados: no modifica el motor de cierre ni la resolución de tarifas. Las decisiones técnicas ya definidas (PDF con `fpdf2`, gráficos con `matplotlib` headless, caché de artefacto en S3, análisis IA cacheado con fail-safe, tabla auxiliar `billing_closure_reports`) se traducen aquí en historias de usuario y criterios de aceptación verificables en formato EARS.

## Glossary

- **Reporte_Cierre**: Documento PDF que sirve como sustento formal de la factura de una organización para un cierre mensual específico. Contiene 9 secciones obligatorias.
- **Reporte_Service**: Componente backend (`ClosureReportService`) que orquesta caché S3, serie histórica, análisis IA, render de gráficos, composición y subida del PDF.
- **BillingClosure**: Registro inmutable de cierre de facturación de una organización, con cabecera (totales, monto, modalidad, tramos aplicados, periodo) e items por IP. Es la fuente de verdad de los datos del reporte.
- **BillingClosureReport**: Fila 1:1 con un `BillingClosure` (tabla `billing_closure_reports`) que cachea el análisis IA y metadata de generación (modelo, fechas, S3 key del PDF).
- **Ciclo_de_Servicio**: Número secuencial 1-based que identifica el mes de servicio de un cierre dentro de la organización, derivado ordenando los cierres por `(period_year, period_month)`; el cierre más antiguo es el ciclo 1.
- **Tramo**: Rango de facturación (`tier`) con un límite inferior, un límite superior, una tarifa por IP y una cantidad de IPs incluidas (`ips_in_tier`) y su subtotal, según `tiers_applied`.
- **Modalidad**: Modo de facturación del cierre (`header.mode`) aplicado al mes.
- **Analisis_IA**: Texto generado por un modelo LLM que describe resumen ejecutivo, evolución/crecimiento por ciclo de servicio y observaciones del consumo.
- **LLM_Service**: Capa de invocación multi-proveedor (Bedrock por defecto, OpenAI cuando `org.openai_api_key` está presente), que respeta `org.llm_model_id`.
- **Cache_Hit**: Situación en la que el PDF del reporte ya existe en S3 bajo la key determinista y se sirve sin recomputar.
- **Cache_Miss**: Situación en la que el PDF no existe en S3 y debe ejecutarse el pipeline completo de generación.
- **S3_Key_Determinista**: Ruta fija del artefacto PDF en S3: `billing-reports/{organization_id}/{closure_id}/report.pdf`.
- **Presigned_URL**: URL temporal firmada con SigV4 y endpoint regional explícito de S3 para descargar el PDF.
- **Tenant_Isolation**: Aislamiento por organización: toda consulta filtra por `organization_id` y valida el scope del solicitante.
- **Operador**: Usuario con permiso `require_operator_or_admin` limitado a su propia organización.
- **Superadmin**: Usuario con rol global `UserRole.ADMIN` que puede acceder a cualquier organización.
- **Fail_Safe_IA**: Comportamiento por el cual, si el LLM falla, el reporte se genera igual con una nota y `ai_analysis_available=false`, sin bloquear la factura.
- **Reconciliacion_de_Montos**: Validación de que el total del desglose del reporte coincide con `header.amount` dentro de una tolerancia `< 0.01` (redondeo half-up; cabecera 2 decimales, items 4).
- **USD_Sin_Impuestos**: Declaración obligatoria de que todos los precios se expresan en dólares americanos y no incluyen impuestos.
- **Reporte_Data**: Datos estructurados (`ClosureReportData`) que alimentan tanto el PDF como la vista previa del frontend (serie histórica, tramos, resumen, texto IA).

## Requirements

### Requisito 1: Generación on-demand del reporte PDF

**Historia de Usuario:** Como operador de facturación, quiero solicitar el reporte PDF de un cierre mensual, para descargarlo como sustento formal de la factura de mi organización.

#### Criterios de Aceptación

1. WHEN un usuario autorizado solicita el reporte de un cierre existente vía `GET /billing/closures/{closure_id}/report`, THE Reporte_Service SHALL resolver el `BillingClosure` correspondiente, generar el PDF y devolver una respuesta `ClosureReportUrlResponse` con `report_url`.
2. THE Reporte_Service SHALL generar la `Presigned_URL` con firma SigV4 y endpoint regional explícito de S3 (`https://s3.{AWS_REGION}.amazonaws.com`).
3. THE Reporte_Service SHALL fijar la expiración de la `Presigned_URL` en 3600 segundos y reportar ese valor en el campo `expires_in_seconds`.
4. IF el `closure_id` solicitado no corresponde a ningún `BillingClosure`, THEN THE Reporte_Service SHALL responder con el código HTTP 404.
5. IF la operación de S3 al generar la `Presigned_URL` falla, THEN THE Reporte_Service SHALL responder con un código HTTP 502 o 500 que indique fallo de almacenamiento.
6. THE Reporte_Service SHALL tratar el `BillingClosure` como fuente de datos de solo lectura sin modificar la cabecera, los items ni la lógica del motor de cierre.

### Requisito 2: Caché del artefacto PDF en S3

**Historia de Usuario:** Como administrador de la plataforma, quiero que el PDF generado se cachee en S3 con una ruta determinista, para evitar recomputar el reporte en cada descarga.

#### Criterios de Aceptación

1. THE Reporte_Service SHALL persistir el PDF bajo la `S3_Key_Determinista` `billing-reports/{organization_id}/{closure_id}/report.pdf`.
2. WHEN el PDF ya existe en la `S3_Key_Determinista` y no se solicita regenerar, THE Reporte_Service SHALL servir el artefacto existente como `Cache_Hit` y responder con `cached=true` sin recomputar el PDF ni el análisis IA.
3. WHEN el PDF no existe en la `S3_Key_Determinista`, THE Reporte_Service SHALL ejecutar el pipeline completo de generación como `Cache_Miss` y responder con `cached=false`.
4. WHEN se solicita regenerar el reporte, THE Reporte_Service SHALL sobre-escribir el artefacto en la misma `S3_Key_Determinista` aunque ya exista.
5. IF la operación de subida del PDF a S3 falla, THEN THE Reporte_Service SHALL responder con un código HTTP 502 o 500 sin cachear un artefacto parcial.

### Requisito 3: Contenido obligatorio del PDF

**Historia de Usuario:** Como responsable de facturación, quiero que el reporte PDF contenga todas las secciones definidas, para que sirva como sustento completo y autocontenido de la factura.

#### Criterios de Aceptación

1. THE Reporte_Service SHALL incluir en el PDF una portada con los logos de AlwaysPrint y Robles.AI, el título del reporte, la organización, el periodo (`YYYY-MM`), la modalidad y la fecha de generación.
2. THE Reporte_Service SHALL incluir una sección de resumen del cierre con los totales de facturables, reciclados y archivados, el monto total en USD y el tipo de cierre.
3. THE Reporte_Service SHALL incluir una sección con la descripción de conceptos, tarifas, modalidad aplicada y la tabla de tramos con su tarifa por tramo.
4. THE Reporte_Service SHALL incluir un gráfico de composición de tramos del mes y un gráfico de evolución histórica por ciclo de servicio.
5. THE Reporte_Service SHALL incluir una tabla resumen del desglose por tramo (límite inferior, límite superior, tarifa, `ips_in_tier`, subtotal).
6. THE Reporte_Service SHALL incluir la sección de `Analisis_IA` cuando esté disponible.
7. THE Reporte_Service SHALL incluir un texto explícito de `USD_Sin_Impuestos` que declare que todos los precios están expresados en dólares americanos (USD) y no incluyen impuestos.
8. THE Reporte_Service SHALL incluir en cada página del PDF el pie de copyright de Inversiones On Line S.A.C.

### Requisito 4: Gráficos server-side con degradación elegante

**Historia de Usuario:** Como usuario del reporte, quiero visualizar la composición de tramos y la evolución histórica en gráficos, para entender el consumo de un vistazo aunque haya pocos datos.

#### Criterios de Aceptación

1. THE Reporte_Service SHALL renderizar los gráficos server-side con `matplotlib` en modo headless configurando el backend `Agg` antes de importar `pyplot`.
2. WHEN se genera el gráfico de composición de tramos, THE Reporte_Service SHALL representar las IPs incluidas por cada tramo a partir de `tiers_applied`.
3. IF el cierre no tiene tramos con IPs facturables, THEN THE Reporte_Service SHALL renderizar un gráfico de composición con un marcador de "sin IPs facturables" sin lanzar una excepción.
4. WHEN se genera el gráfico de evolución histórica, THE Reporte_Service SHALL representar la evolución de estaciones facturables y monto a lo largo de los ciclos de servicio.
5. IF la organización tiene un solo cierre, THEN THE Reporte_Service SHALL renderizar un gráfico de evolución histórica mínimo con un marcador único y una nota de "primer ciclo de servicio" sin lanzar una excepción.
6. THE Reporte_Service SHALL cerrar cada figura de `matplotlib` tras exportarla a PNG para no filtrar memoria.

### Requisito 5: Análisis IA del consumo con fail-safe

**Historia de Usuario:** Como responsable de facturación, quiero un análisis IA que interprete la evolución del consumo, para contar con contexto ejecutivo sin que un fallo del modelo bloquee mi factura.

#### Criterios de Aceptación

1. WHEN se genera el análisis IA, THE LLM_Service SHALL producir un resumen ejecutivo, un análisis de evolución/crecimiento según el número de ciclo de servicio y observaciones del consumo.
2. THE LLM_Service SHALL construir el prompt incluyendo la serie histórica de cierres, el desglose de tramos del mes objetivo, la modalidad y la moneda USD.
3. WHERE la organización tiene configurada una `openai_api_key`, THE LLM_Service SHALL usar el proveedor OpenAI respetando `org.llm_model_id`; en caso contrario SHALL usar Bedrock por defecto.
4. IF el LLM falla tras los reintentos configurados, THEN THE Reporte_Service SHALL fijar el `Analisis_IA` en nulo, generar el PDF con una nota de `Fail_Safe_IA` y responder con `ai_analysis_available=false`.
5. IF el LLM falla tras los reintentos configurados, THEN THE Reporte_Service SHALL completar la generación del reporte sin propagar el error ni bloquear la factura.

### Requisito 6: Cacheo del análisis IA y regeneración manual

**Historia de Usuario:** Como administrador de la organización, quiero que el análisis IA se cachee junto al cierre y poder regenerarlo manualmente, para no recomputarlo en cada descarga y poder actualizarlo cuando sea necesario.

#### Criterios de Aceptación

1. THE Reporte_Service SHALL persistir el `Analisis_IA` en una fila `BillingClosureReport` con relación 1:1 al `BillingClosure`, junto con el modelo LLM usado y la fecha de generación.
2. WHEN existe un `Analisis_IA` cacheado y no se solicita regenerar, THE Reporte_Service SHALL usar el texto cacheado sin invocar al LLM_Service.
3. WHEN un usuario autorizado solicita `POST /billing/closures/{closure_id}/report/regenerate`, THE Reporte_Service SHALL recomputar el `Analisis_IA`, sobre-escribir el texto cacheado, re-renderizar los gráficos, regenerar el PDF y sobre-escribir la `S3_Key_Determinista`.
4. WHEN se regenera el reporte, THE Reporte_Service SHALL responder con `cached=false` y actualizar la fecha de generación del análisis.
5. IF el solicitante de la regeneración no es Superadmin ni administrador de la organización dueña del cierre, THEN THE Reporte_Service SHALL responder con el código HTTP 403.

### Requisito 7: Derivación del número de ciclo de servicio

**Historia de Usuario:** Como analista de facturación, quiero que cada cierre tenga un número de ciclo de servicio consistente, para interpretar la evolución del consumo en el tiempo.

#### Criterios de Aceptación

1. WHEN se construye la serie histórica, THE Reporte_Service SHALL ordenar los cierres de la organización por `period_year` ascendente y luego `period_month` ascendente.
2. THE Reporte_Service SHALL asignar `Ciclo_de_Servicio` igual a 1 al cierre más antiguo y numerar los siguientes de forma creciente y consecutiva.
3. THE Reporte_Service SHALL construir la serie histórica filtrando exclusivamente por el `organization_id` de la organización dueña del cierre.
4. THE Reporte_Service SHALL incluir en cada punto de la serie el ciclo, el periodo, los totales de facturables, reciclados y archivados, y el monto.

### Requisito 8: Endpoints REST con roles y tenant isolation

**Historia de Usuario:** Como plataforma multi-tenant, quiero exponer los endpoints del reporte con control de roles y aislamiento por organización, para que cada usuario solo acceda a los datos permitidos.

#### Criterios de Aceptación

1. THE Reporte_Service SHALL exponer los endpoints `GET /billing/closures/{closure_id}/report`, `POST /billing/closures/{closure_id}/report/regenerate` y `GET /billing/closures/{closure_id}/report-data`.
2. WHEN un Operador solicita el reporte de un cierre de su propia organización, THE Reporte_Service SHALL autorizar la operación tras validar el scope de organización.
3. IF un Operador solicita el reporte de un cierre de otra organización, THEN THE Reporte_Service SHALL responder con el código HTTP 403.
4. WHEN un Superadmin solicita el reporte de un cierre de cualquier organización, THE Reporte_Service SHALL autorizar la operación.
5. THE Reporte_Service SHALL restringir la operación de regeneración a Superadmin o al administrador de la organización dueña del cierre.
6. THE Reporte_Service SHALL filtrar por `organization_id` en todas las consultas a la base de datos que sirvan datos del reporte.
7. WHEN un usuario autorizado solicita `GET /billing/closures/{closure_id}/report-data`, THE Reporte_Service SHALL devolver `Reporte_Data` con la serie histórica, el desglose de tramos, el resumen y el texto IA si existe.

### Requisito 9: Frontend de descarga, regeneración y vista previa

**Historia de Usuario:** Como usuario del dashboard de facturación, quiero descargar el reporte, regenerar el análisis y ver una vista previa de los gráficos, para gestionar el sustento de la factura desde la interfaz.

#### Criterios de Aceptación

1. WHEN el usuario acciona "Descargar reporte", THE Frontend SHALL invocar `getClosureReport` y abrir el `report_url` recibido.
2. WHERE el usuario es administrador o superadmin, THE Frontend SHALL mostrar el botón "Regenerar análisis" que invoca `regenerateClosureReport` con confirmación previa.
3. WHERE el usuario no es administrador ni superadmin, THE Frontend SHALL ocultar el botón "Regenerar análisis".
4. WHERE la vista previa está habilitada, THE Frontend SHALL consumir `getClosureReportData` y renderizar los gráficos de composición de tramos y evolución histórica con `recharts`.
5. THE Frontend SHALL mostrar todos los textos dinámicos mediante `next-intl` bajo el namespace `billingReport` con claves definidas en `en.json` y `es.json`.

### Requisito 10: Reconciliación de montos

**Historia de Usuario:** Como responsable de facturación, quiero que el total del reporte coincida con el monto de cabecera, para garantizar la integridad del sustento sin alterar la fuente de verdad.

#### Criterios de Aceptación

1. WHEN se compone el PDF, THE Reporte_Service SHALL validar que la suma del desglose y de `items.amount` reconcilie con `header.amount` dentro de una tolerancia menor a 0.01, aplicando redondeo half-up con cabecera a 2 decimales e items a 4 decimales.
2. IF la diferencia entre el total del desglose y `header.amount` excede la tolerancia de 0.01, THEN THE Reporte_Service SHALL registrar una advertencia y anotar la discrepancia en el PDF.
3. THE Reporte_Service SHALL preservar `header.amount` como fuente de verdad sin alterarlo aunque exista una discrepancia.

### Requisito 11: Restricciones no funcionales y de proyecto

**Historia de Usuario:** Como equipo de ingeniería, quiero que la feature cumpla las convenciones del proyecto, para mantener la seguridad, la reproducibilidad y la integridad del sistema de facturación.

#### Criterios de Aceptación

1. THE Reporte_Service SHALL fijar versiones pinneadas de las dependencias nuevas `matplotlib` y `Pillow` en `requirements.txt`.
2. THE Reporte_Service SHALL usar `matplotlib` en modo headless con el backend `Agg` en entornos de contenedor sin servidor gráfico.
3. THE Reporte_Service SHALL operar como componente de solo lectura sin modificar el motor de cierre (`billing_close_service`) ni la resolución de planes/tarifas (`billing_service`).
4. THE Reporte_Service SHALL persistir el análisis IA y su metadata en la tabla auxiliar `billing_closure_reports` sin agregar columnas mutables a `billing_closures`.
5. THE Reporte_Service SHALL declarar de forma explícita en el reporte que los precios están en USD y no incluyen impuestos.
