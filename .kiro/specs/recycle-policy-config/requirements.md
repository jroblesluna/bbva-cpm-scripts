# Requirements Document

## Introduction

Actualmente la política de reciclaje del módulo de facturación ("Usage and Billing") está hardcodeada en el backend: los tres offsets de mes (`cutoff=M+1`, `cut1=M-2`, `cut2=M-3`) viven como constantes en `billing_time.py::compute_cuts`, y el umbral de uso efímero (24h) vive como la constante `_CASE1_MAX_USE_SECONDS` en `billing_close_service.py::_should_recycle`. Esto impide ajustar el comportamiento del reciclaje por organización sin recompilar/redesplegar, y no permite que distintas organizaciones tengan reglas distintas.

Esta feature hace configurable la política de reciclaje mediante dos parámetros: (1) la **Regla de Reciclaje** (los 3 offsets de mes `cutoff/cut1/cut2`) y (2) el **Tiempo de Uso Efímero** (en horas). La configuración sigue el patrón existente `BillingRatePlan`/`BillingOrgPlan`: una política DEFAULT GLOBAL del sistema más un OVERRIDE opcional por organización. El versionado es PROSPECTIVO y se ancla al PERIODO de cierre (año-mes `M`), no a la fecha de ejecución, lo que lo hace robusto ante cierres retroactivos.

Cada `BillingClosure` CONGELA (freeze) la política que aplicó, garantizando inmutabilidad histórica: regenerar un PDF o releer un mes viejo reproduce exactamente los mismos totales y montos. Los cierres históricos existentes se rellenan (backfill) con la política LEGACY `+1/-2/-3` + 24h, porque fue la vigente cuando se cerraron. Cambiar la política NUNCA reprocesa cierres ya generados; solo afecta cierres nuevos con periodo `>=` el efectivo.

El uso efímero se mide sobre el ciclo de actividad vigente (`billing_cycle_started_at`), que se reinicia en cada reactivación de la workstation, preservando `created_at` para su semántica histórica (auditoría, UI y el alcance del cierre `created_at < cutoff`).

## Glossary

- **Recycle_Policy (Política de Reciclaje)**: Conjunto de parámetros que rigen cuándo una workstation `billable` se recicla. Compuesta por la Recycle_Rule y el Ephemeral_Use_Threshold.
- **Recycle_Rule (Regla de Reciclaje)**: Los tres offsets de mes con signo (cutoff, cut1, cut2), representados externamente como string tipo `"+1/-2/-3"` e internamente como tres enteros con signo.
- **cutoff**: Offset de mes (entero con signo) que define el corte superior del periodo facturado del cierre `M`. Valor legacy: `+1`.
- **cut1**: Offset de mes (entero con signo) usado en el Caso 1 (poco uso / efímero). Valor legacy: `-2`.
- **cut2**: Offset de mes (entero con signo) usado en el Caso 2 (abandono). Valor legacy: `-3`.
- **Month_Offset (offset de mes)**: Entero con signo que se suma al mes del periodo `M` para obtener una fecha de corte (00:00 del día 1, tz de la organización, datetime naive UTC).
- **Ephemeral_Use (uso efímero)**: Uso de una workstation cuyo intervalo `last_seen - billing_cycle_started_at` es menor que el Ephemeral_Use_Threshold.
- **Billing_Cycle_Started_At (inicio del ciclo de actividad)**: Timestamp persistente que marca el comienzo del ciclo de actividad vigente de una workstation. Se inicializa al crear la workstation y se REINICIA cada vez que la workstation se reactiva de `recycled`/`archived` a `billable` por actividad. Es la base para calcular el uso efímero del ciclo actual, en lugar de `created_at`.
- **Ephemeral_Use_Threshold (Tiempo de Uso Efímero)**: Umbral en horas que define uso efímero. Valor legacy: `24` horas.
- **Period (periodo, M)**: Par año-mes que identifica el cierre. El versionado de política se ancla a este valor, no a la fecha de ejecución.
- **Effective_From_Period (effective_from por periodo)**: Periodo (año-mes) a partir del cual una política entra en vigor de forma prospectiva.
- **Org_Override (override por organización)**: Política específica de una organización que reemplaza el Global_Default para los periodos donde esté vigente.
- **Global_Default (default global)**: Política del sistema aplicada cuando una organización no tiene Org_Override vigente para el periodo.
- **Policy_Freeze (congelamiento / freeze de política)**: Persistencia de la política aplicada dentro del `BillingClosure`, volviéndola inmutable para ese cierre.
- **Backfill**: Relleno de la política congelada en cierres históricos existentes que no tienen la columna nueva, usando la política LEGACY `+1/-2/-3` + 24h.
- **Billable/Recycled/Archived**: Estados de facturación (`billing_status`) de una workstation.
- **last_seen crudo (raw last_seen)**: Valor de `last_seen` de la workstation usado sin transformación en la lógica de reciclaje.
- **Fail_Closed**: Comportamiento de validación que rechaza y NO persiste cuando la entrada no cumple todas las reglas.
- **Superadmin**: Rol con privilegio máximo, único autorizado a editar la Recycle_Policy.
- **Recycle_Policy_Service (Servicio de Política de Reciclaje)**: Componente backend que resuelve, valida, persiste y congela la Recycle_Policy.
- **Recycle_Policy_API (API de Política de Reciclaje)**: Endpoints REST para ver/editar la política global y el override por organización.
- **Recycle_Policy_UI (UI de Política de Reciclaje)**: Interfaz frontend para ver/editar la política, visible solo a Superadmin.
- **Closure_Report (Reporte de Cierre)**: PDF generado por `closure_report_service.py` para un `BillingClosure`.
- **AI_Analysis (Análisis IA)**: Texto generado por el LLM que explica/sustenta el cierre.

## Requirements

### Requirement 1: Configurabilidad de los dos parámetros de la política

**User Story:** Como Superadmin, quiero configurar los offsets de mes y el umbral de uso efímero, para ajustar la política de reciclaje sin recompilar ni redesplegar el backend.

#### Acceptance Criteria

1. THE Recycle_Policy_Service SHALL almacenar la Recycle_Rule como tres enteros con signo (cutoff, cut1, cut2).
2. THE Recycle_Policy_Service SHALL almacenar el Ephemeral_Use_Threshold como un entero en horas.
3. WHEN un Superadmin envía una Recycle_Rule en formato string, THE Recycle_Policy_Service SHALL parsearla a exactamente tres enteros con signo (cutoff, cut1, cut2).
4. THE Recycle_Policy_Service SHALL exponer la Recycle_Rule en formato string tipo `"+1/-2/-3"` cuando la política sea leída.

### Requirement 2: Política a nivel Global_Default y Org_Override

**User Story:** Como Superadmin, quiero definir una política global por defecto y overrides por organización, para que cada organización pueda tener reglas de reciclaje distintas siguiendo el patrón RatePlan/OrgPlan existente.

#### Acceptance Criteria

1. THE Recycle_Policy_Service SHALL mantener una política Global_Default del sistema.
2. THE Recycle_Policy_Service SHALL permitir una política Org_Override por organización.
3. WHEN una organización tiene un Org_Override vigente para el periodo `M`, THE Recycle_Policy_Service SHALL usar el Org_Override para ese periodo.
4. IF una organización no tiene Org_Override vigente para el periodo `M`, THEN THE Recycle_Policy_Service SHALL usar el Global_Default vigente para ese periodo.
5. THE Recycle_Policy_Service SHALL filtrar toda consulta de Org_Override por `organization_id` (tenant isolation).

### Requirement 3: Versionado prospectivo anclado al periodo de cierre

**User Story:** Como Superadmin, quiero que un cambio de política sea prospectivo y se ancle al periodo de cierre (año-mes), para que los cierres anteriores sigan usando la política previa incluso si se ejecutan retroactivamente.

#### Acceptance Criteria

1. THE Recycle_Policy_Service SHALL asociar cada política a un Effective_From_Period expresado como año-mes en formato AAAA-MM, donde el año está en el rango 2000 a 2999 y el mes en el rango 01 a 12.
2. WHEN se resuelve la política para un cierre de periodo M, THE Recycle_Policy_Service SHALL seleccionar la política cuyo Effective_From_Period sea el mayor valor que cumpla `Effective_From_Period <= M`, usando la clave cronológica entera `(año * 12 + mes)` para la comparación.
3. IF dos o más políticas del mismo alcance (Global_Default u Org_Override) tienen Effective_From_Period con idéntica clave cronológica `(año * 12 + mes)`, THEN THE Recycle_Policy_Service SHALL rechazar la resolución, conservar el estado de políticas sin modificarlo y devolver un error indicando la existencia de periodos efectivos duplicados.
4. WHEN un cierre de periodo M se ejecuta en una fecha de ejecución posterior a M, THE Recycle_Policy_Service SHALL resolver la política usando el periodo M y SHALL ignorar la fecha de ejecución en la selección de política.
5. IF no existe ninguna política con `Effective_From_Period <= M`, THEN THE Recycle_Policy_Service SHALL usar el Global_Default base sembrado.
6. IF el Org_Override de la organización tiene Effective_From_Period con clave cronológica mayor que la de M, THEN THE Recycle_Policy_Service SHALL usar el Global_Default cuyo Effective_From_Period sea el mayor valor que cumpla `Effective_From_Period <= M`.
7. WHERE existe un Org_Override para BBVA con Effective_From_Period 2026-09, THE Recycle_Policy_Service SHALL aplicar el Org_Override a cada cierre de BBVA cuyo periodo M cumpla `M >= 2026-09` según la clave cronológica `(año * 12 + mes)`.
8. WHERE existe un Org_Override para BBVA con Effective_From_Period 2026-09, THE Recycle_Policy_Service SHALL aplicar la política previa vigente a cada cierre de BBVA cuyo periodo M cumpla `2026-05 <= M <= 2026-08` según la clave cronológica `(año * 12 + mes)`.

> **Nota (semántica de vigencia — decisión de negocio):** La relación de vigencia es `M >= Effective_From_Period` (INCLUSIVA en el propio periodo efectivo), no `M > Effective_From_Period`. Por lo tanto, el propio Effective_From_Period ya usa la política nueva: el Org_Override de BBVA con Effective_From_Period 2026-09 aplica a `M = 2026-09` y posteriores. Se evaluó adoptar una comparación "estrictamente mayor" en el borde del override, pero se resolvió MANTENER la semántica inclusiva por decisión de negocio del usuario, para que Setiembre 2026 (2026-09) YA use el override. Los AC7 y AC8 reflejan esta semántica (`M >= 2026-09` aplica el override; `2026-05 <= M <= 2026-08` usa la política previa).

### Requirement 4: Congelamiento de la política en el cierre (inmutabilidad histórica)

**User Story:** Como responsable de facturación, quiero que cada cierre congele la política que aplicó, para que regenerar un PDF o releer un mes viejo reproduzca exactamente los mismos totales y muestre la política vigente ese mes.

#### Acceptance Criteria

1. WHEN se genera un `BillingClosure` para el periodo `M`, THE Recycle_Policy_Service SHALL congelar dentro del cierre la Recycle_Policy resuelta para `M`.
2. WHEN se regenera el Closure_Report de un cierre existente, THE Closure_Report SHALL leer la Recycle_Policy congelada del cierre y no la política vigente.
3. WHEN se relee un cierre existente, THE Recycle_Policy_Service SHALL reproducir los mismos totales y montos usando la Recycle_Policy congelada.
4. THE Recycle_Policy_Service SHALL tratar la Recycle_Policy congelada de un `BillingClosure` como inmutable.
5. THE Recycle_Policy_Service SHALL exigir inmutabilidad únicamente sobre la Recycle_Policy congelada dentro de un `BillingClosure`; la política configurable (Global_Default u Org_Override aún NO congelada en un cierre) SHALL permanecer editable por un Superadmin.

### Requirement 5: No reprocesamiento de cierres existentes

**User Story:** Como responsable de facturación, quiero que cambiar la política nunca altere cierres ya generados, para preservar el sustento inmutable de facturación.

#### Acceptance Criteria

1. WHEN un Superadmin cambia la Recycle_Policy, THE Recycle_Policy_Service SHALL dejar sin modificar los `BillingClosure` ya generados.
2. WHEN un Superadmin cambia la Recycle_Policy, THE Recycle_Policy_Service SHALL aplicar la nueva política únicamente a cierres nuevos con periodo `M >=` el Effective_From_Period.
3. IF un cambio de política tendría un Effective_From_Period cuya vigencia afectaría uno o más periodos `M` para los que YA existe un `BillingClosure`, THEN THE Recycle_Policy_API y THE Recycle_Policy_Service SHALL rechazar el cambio (fail-closed), NO persistirlo, y retornar un error que identifique el conflicto con los cierres existentes.

### Requirement 6: Backfill de cierres históricos

**User Story:** Como responsable de migración, quiero que los cierres históricos existentes reciban una política congelada legacy, para que sus PDFs muestren la política que realmente aplicó cuando se cerraron.

#### Acceptance Criteria

1. WHEN se ejecuta la migración de datos, THE Recycle_Policy_Service SHALL rellenar cada `BillingClosure` existente sin política congelada con la Recycle_Rule `+1/-2/-3` y el Ephemeral_Use_Threshold de 24 horas.
2. WHEN se genera el Closure_Report de un cierre rellenado por backfill, THE Closure_Report SHALL mostrar la Recycle_Rule `+1/-2/-3`.
3. THE migración de backfill SHALL considerarse completa únicamente cuando TODOS los `BillingClosure` existentes queden con Recycle_Policy congelada; IF el backfill de algún `BillingClosure` falla, THEN THE migración SHALL abortar de forma transaccional, revertir los cambios parciales y NO marcarse como completa.

### Requirement 7: Validaciones fail-closed antes de persistir

**User Story:** Como Superadmin, quiero que la política se valide antes de grabarse, para evitar configuraciones que rompan la facturación.

#### Acceptance Criteria

1. IF la Recycle_Rule en string no parsea a exactamente tres enteros con signo explícito separados por "/" (formato "+1/-2/-3"), THEN THE Recycle_Policy_Service SHALL rechazar la política, NO persistirla, y retornar un indicador de error identificando la regla de formato violada.
2. IF los offsets no cumplen `cutoff > cut1 >= cut2`, THEN THE Recycle_Policy_Service SHALL rechazar la política, NO persistirla, y retornar un indicador de error identificando la regla de orden violada.
3. IF `cutoff < +1`, THEN THE Recycle_Policy_Service SHALL rechazar la política, NO persistirla, y retornar un indicador de error identificando la regla de cutoff mínimo violada.
4. IF algún offset queda fuera del rango `-24 <= offset <= +1`, THEN THE Recycle_Policy_Service SHALL rechazar la política, NO persistirla, y retornar un indicador de error identificando el offset fuera de rango.
5. IF el Ephemeral_Use_Threshold queda fuera del rango `1 <= horas <= 168`, THEN THE Recycle_Policy_Service SHALL rechazar la política, NO persistirla, y retornar un indicador de error identificando el umbral fuera de rango.
6. WHEN se recibe una solicitud de guardado de política, THE Recycle_Policy_API SHALL validar la política contra el schema Pydantic antes de invocar al servicio, y THE Recycle_Policy_Service SHALL validar la política antes de persistir, independientemente del resultado de la validación del schema.
7. IF la política viola una o más reglas de validación simultáneamente, THEN THE Recycle_Policy_Service SHALL rechazar la política, NO persistirla, y retornar un indicador de error por cada regla violada.
8. IF el Effective_From_Period no representa un año-mes válido con mes en el rango `1 <= mes <= 12`, THEN THE Recycle_Policy_Service SHALL rechazar la política, NO persistirla, y retornar un indicador de error identificando el periodo inválido.
9. WHEN THE Recycle_Policy_Service rechaza una política, THE Recycle_Policy_Service SHALL preservar sin cambios la política previamente persistida.

### Requirement 8: Permisos de edición restringidos a Superadmin

**User Story:** Como Superadmin, quiero ser el único que pueda editar la política, para evitar que operadores modifiquen la facturación.

#### Acceptance Criteria

1. WHEN un usuario con rol Superadmin solicita editar el Global_Default o un Org_Override, THE Recycle_Policy_API SHALL permitir la operación.
2. IF un usuario sin rol Superadmin solicita editar el Global_Default o un Org_Override, THEN THE Recycle_Policy_API SHALL rechazar la operación.
3. THE Recycle_Policy_UI SHALL exponer los controles de edición de la política únicamente a usuarios con rol Superadmin.

### Requirement 9: Auditoría de cambios de política

**User Story:** Como auditor, quiero que cada cambio de política quede registrado, para poder rastrear quién cambió qué y cuándo.

#### Acceptance Criteria

1. WHEN se persiste un cambio de Recycle_Policy, THE Recycle_Policy_Service SHALL registrar una acción de auditoría de tipo `BILLING_RECYCLE_POLICY_CHANGE`.
2. WHEN se registra la acción de auditoría, THE Recycle_Policy_Service SHALL incluir el valor anterior y el valor nuevo de la política.
3. WHEN se registra la acción de auditoría, THE Recycle_Policy_Service SHALL incluir el `organization_id` afectado o la marca de que el cambio fue al Global_Default.
4. WHEN se registra la acción de auditoría, THE Recycle_Policy_Service SHALL incluir la identidad del usuario que realizó el cambio.
5. IF el registro de auditoría del cambio de política falla, THEN THE Recycle_Policy_Service SHALL rechazar y revertir el cambio de política (NO persistirlo), de modo que no exista ningún cambio de política sin su correspondiente rastro de auditoría (fail-closed).

### Requirement 10: Determinismo del recálculo

**User Story:** Como ingeniero de facturación, quiero que recalcular desde cero con la misma política congelada reproduzca estados y montos idénticos, para garantizar reproducibilidad.

#### Acceptance Criteria

1. THE Recycle_Policy_Service SHALL determinar el reciclaje de una workstation usando únicamente `created_at`, Billing_Cycle_Started_At, el last_seen crudo, el timezone de la organización y la Recycle_Policy congelada.
2. WHEN se borran todos los cierres, se resetea el `billing_status` a `new` y se recalcula mes a mes con la misma Recycle_Policy congelada, THE Recycle_Policy_Service SHALL reproducir de forma idéntica TANTO los estados de facturación (`billing_status`) COMO los montos (ambos por igual).
3. THE Recycle_Policy_Service SHALL restringir, a nivel de la interfaz del servicio (no solo por documentación), que la decisión de reciclaje use únicamente los insumos `created_at`, Billing_Cycle_Started_At, el last_seen crudo, el timezone de la organización y la Recycle_Policy congelada.

### Requirement 11: Inclusión de la política en el PDF del reporte de cierre

**User Story:** Como lector del reporte de cierre, quiero ver la política de reciclaje aplicada explicada en prosa, para entender qué significan los cortes y el umbral de uso efímero.

#### Acceptance Criteria

1. WHEN se genera el Closure_Report, THE Closure_Report SHALL incluir en prosa la Recycle_Policy congelada del cierre.
2. THE Closure_Report SHALL describir en prosa el significado de los offsets cutoff, cut1 y cut2 y del Ephemeral_Use_Threshold.
3. THE Closure_Report SHALL leer la Recycle_Policy congelada del cierre y no la política vigente.
4. IF la Recycle_Policy congelada del cierre está ausente o corrupta, THEN THE Closure_Report SHALL abortar la generación del reporte y retornar un error, sin generar un PDF que carezca de la política (fail-closed).

### Requirement 12: Inclusión de la política en el prompt del Análisis IA

**User Story:** Como lector del Análisis IA, quiero que el LLM conozca la política aplicada, para que pueda explicar y sustentar el mes.

#### Acceptance Criteria

1. WHEN se construye el prompt del AI_Analysis, THE Recycle_Policy_Service SHALL incluir la Recycle_Policy congelada del cierre en el prompt.
2. WHEN se regenera el AI_Analysis de un cierre, THE Recycle_Policy_Service SHALL mantener sin cambios los totales y montos del `BillingClosure`.
3. IF la Recycle_Policy congelada del cierre está ausente o corrupta al construir el prompt, THEN THE Recycle_Policy_Service SHALL abortar la construcción del prompt y fallar la solicitud de AI_Analysis, sin generar análisis con política faltante (fail-closed). En este caso el fallo SHALL limitarse al AI_Analysis, y THE Closure_Report SHALL caer en el comportamiento fail-safe de "IA no disponible" (el PDF se genera igual), sin bloquear la generación completa del PDF.

### Requirement 13: Comportamiento del reciclaje con uso efímero

**User Story:** Como responsable de facturación, quiero que las IPs de uso efímero se reciclen según la política, para no facturar workstations que se usaron una sola vez brevemente.

#### Acceptance Criteria

1. WHERE la Recycle_Policy es `+1/0/-1` con Ephemeral_Use_Threshold de 24 horas, WHEN una workstation tiene uso efímero (intervalo `last_seen - billing_cycle_started_at` menor al Ephemeral_Use_Threshold) en el periodo `M` y sin uso en `M+1` ni `M+2`, THE Recycle_Policy_Service SHALL marcarla como `billable` en `M`, `recycled` en `M+1` y `recycled` en `M+2`.
2. WHERE la Recycle_Policy es `+1/0/-1`, WHEN una workstation de uso efímero en `M` registra actividad en `M+x` con `x > 2`, THE Recycle_Policy_Service SHALL marcarla como `billable` en `M+x`.

### Requirement 14: Comportamiento del reciclaje con uso normal

**User Story:** Como responsable de facturación, quiero que las IPs de uso normal solo se reciclen por abandono, para facturarlas mientras se sigan usando de forma efectiva.

#### Acceptance Criteria

1. WHERE la Recycle_Policy es `+1/0/-1` con Ephemeral_Use_Threshold de 24 horas, WHEN una workstation tiene uso normal (intervalo `last_seen - billing_cycle_started_at` mayor o igual al Ephemeral_Use_Threshold) en el periodo `M` y sin uso en `M+1` ni `M+2`, THE Recycle_Policy_Service SHALL marcarla como `billable` en `M`, `billable` en `M+1` y `recycled` en `M+2`.
2. WHERE la Recycle_Policy es `+1/0/-1`, WHEN una workstation de uso normal en `M` registra actividad en `M+x` con `x > 2`, THE Recycle_Policy_Service SHALL marcarla como `billable` en `M+x`.

### Requirement 15: Facturación garantizada en el primer cierre

**User Story:** Como responsable de facturación, quiero que toda IP nueva se facture al menos una vez, para asegurar el cobro del primer uso.

#### Acceptance Criteria

1. WHEN una workstation nueva aparece en su primer periodo de cierre `M`, THE Recycle_Policy_Service SHALL marcarla como `billable` en `M`.
2. THE Recycle_Policy_Service SHALL no reciclar una workstation en su primer periodo de cierre `M`.

### Requirement 16: Seed inicial de políticas

**User Story:** Como responsable de despliegue, quiero sembrar políticas iniciales, para que el sistema arranque con el comportamiento legacy y el override acordado para BBVA.

#### Acceptance Criteria

1. WHEN se ejecuta el seed inicial, THE Recycle_Policy_Service SHALL crear el Global_Default con Recycle_Rule `+1/-2/-3` y Ephemeral_Use_Threshold de 24 horas.
2. WHEN se ejecuta el seed inicial, THE Recycle_Policy_Service SHALL crear un Org_Override para la organización BBVA con Recycle_Rule `+1/0/-1`, Ephemeral_Use_Threshold de 24 horas y Effective_From_Period Setiembre 2026.
3. THE seed inicial SHALL ser atómico; IF la creación de alguna política (Global_Default u Org_Override) falla, THEN THE proceso de seed SHALL revertir todos los cambios del seed (rollback) y NO dejar un estado parcial.

### Requirement 17: API y UI de gestión de la política

**User Story:** Como Superadmin, quiero endpoints y una interfaz para ver y editar la política global y los overrides por organización, para gestionarla de forma centralizada.

#### Acceptance Criteria

1. THE Recycle_Policy_API SHALL exponer endpoints para leer el Global_Default y los Org_Override.
2. THE Recycle_Policy_API SHALL exponer endpoints para editar el Global_Default y los Org_Override.
3. WHEN un Superadmin edita la política desde la Recycle_Policy_UI, THE Recycle_Policy_API SHALL aplicar las validaciones del Requirement 7 antes de persistir.
4. THE Recycle_Policy_UI SHALL mostrar la Recycle_Rule en formato string tipo `"+1/-2/-3"` y el Ephemeral_Use_Threshold en horas.
5. WHEN una edición de Superadmin falla la validación, THE Recycle_Policy_API SHALL devolver mensajes de error de validación explícitos identificando cada regla violada, y THE Recycle_Policy_UI SHALL mostrarlos al usuario, sin rechazar la edición de forma silenciosa.

### Requirement 18: Inicio de ciclo de actividad para el cálculo de uso efímero

**User Story:** Como responsable de facturación, quiero que el uso efímero se calcule sobre el ciclo de actividad vigente y no sobre la antigüedad total de la workstation, para que una workstation reactivada que vuelve a tener uso efímero se detecte correctamente como efímera.

#### Acceptance Criteria

1. THE Workstation SHALL tener un campo persistente Billing_Cycle_Started_At (timestamp).
2. WHEN se crea una nueva Workstation, THE sistema SHALL inicializar Billing_Cycle_Started_At con el mismo instante que `created_at`.
3. WHEN una Workstation transiciona desde el estado de origen `recycled` o `archived` al estado `billable` por actividad, THE sistema SHALL reiniciar Billing_Cycle_Started_At al timestamp de esa actividad (el mismo `last_seen` que dispara la reactivación), únicamente en esa transición; IF la actividad NO corresponde a una transición cuyo estado de origen sea `recycled` o `archived` hacia `billable`, THEN THE sistema SHALL NO reiniciar Billing_Cycle_Started_At.
4. THE Recycle_Policy_Service SHALL calcular el uso efímero como `last_seen - Billing_Cycle_Started_At` y compararlo contra el Ephemeral_Use_Threshold.
5. THE sistema SHALL preservar `created_at` sin modificarlo durante la reactivación (su semántica histórica y el alcance del cierre `created_at < cutoff` no cambian).
6. WHEN se ejecuta la migración de datos, THE sistema SHALL inicializar Billing_Cycle_Started_At de cada Workstation existente con su `created_at` actual (comportamiento idéntico al previo para workstations no reactivadas).
7. THE Billing_Cycle_Started_At SHALL tratarse como dato crudo persistente (igual que `last_seen`): se conserva en backup/restore y el recálculo lo usa tal cual, sin recomputarlo desde otras columnas.

## Notes

- **NO se reprocesan cierres existentes**: cambiar la Recycle_Policy nunca altera un `BillingClosure` ya generado. La nueva política solo aplica a cierres nuevos con periodo `M >=` el Effective_From_Period. Los cierres históricos conservan su política congelada (o la política legacy `+1/-2/-3` + 24h vía backfill).
