# Requirements — Usage and Billing

## Introducción

Esta funcionalidad añade una sección **Usage and Billing** a AlwaysPrint Cloud que permite
facturar el uso del producto por **dirección IP privada registrada** (la unidad mínima de
facturación según la propuesta comercial de IOL). Cada workstation en el sistema representa
una IP privada única (`workstations.ip_private` es UNIQUE) y adquiere un estado de ciclo de
vida de facturación (`billing_status`): `new`, `billable`, `recycled` o `archived`.

El sistema soporta dos modalidades de facturación por organización (**Mensual** y **Anual**),
ejecuta **cierres mensuales** en la zona horaria de cada organización, aplica reglas
automáticas de reciclaje de IPs con poco o nulo uso, y restringe la eliminación de
workstations que ya formaron parte de un cierre. Todos los cálculos se realizan en la zona
horaria de la organización.

Se introduce además un nuevo campo `last_seen` en `workstations` como fuente confiable de
"última actividad real" (el campo actual `last_connection` no refleja actividad continua y
se mantiene sin cambios para el resto del sistema).

### Contexto de negocio (de la propuesta IOL–Lexmark)

- La unidad de contabilización y facturación es la **IP privada registrada**, independiente
  de hostname, hardware, VLAN o usuario.
- **Modalidad Mensual:** tarifa incremental por tramos; cada tramo factura solo las IPs
  contenidas en él. Se reporta al cierre de cada mes.
- **Modalidad Anual (Pago Anticipado):** tarifa preferencial única del tramo contratado,
  declarada al inicio; liquidación (crédito o cargo) en el aniversario.
- La depuración automática recicla IPs de uso efímero o abandonadas para lograr una
  contabilización justa.

### Definiciones

- **IP registrada:** toda IP privada única de la organización con un registro en BD
  (una fila en `workstations`), con su `created_at`.
- **IP Activa:** IP en estado `new` o `billable` (presenta actividad; no es `recycled` ni
  `archived`). Tras el primer paso del cierre ya no hay `new`; las `billable` se siguen
  considerando activas.
- **IP Reciclada (`recycled`):** IP que el proceso automático de cierre mensual degradó por
  poco uso reciente o abandono. Nunca se recicla manualmente.
- **IP Archivada (`archived`):** eliminación lógica manual por un administrador. El registro
  persiste pero se oculta por defecto del listado de workstations. Reversible por actividad.
- **`last_seen`:** timestamp de la última actividad real conocida de la workstation.
- **`last_seen` capado (cap a M+1):** para el cierre del mes M, si `last_seen > 00:00 del
  día 1 de M+1` (zona horaria de la org), se usa `00:00 del día 1 de M+1` como valor efectivo
  **solo en el sustento/snapshot del cierre**. No modifica la columna en BD. Relevante sobre
  todo en cierres retroactivos (históricos).
- **Cierre del mes M:** proceso que se corta a las `00:00 del día 1 de M+1` (zona horaria de
  la org) y calcula el estado y la facturación del mes M.

---

## Requirements

### Requirement 1 — Campo `last_seen` como fuente de actividad

**User Story:** Como sistema de facturación, necesito un campo `last_seen` confiable que
refleje la última actividad real de cada workstation, para que las reglas de reciclaje y
facturación no penalicen equipos que están en uso continuo.

#### Acceptance Criteria

1. THE SYSTEM SHALL añadir una columna `last_seen` (DateTime) a la tabla `workstations`,
   NOT NULL una vez completada la migración.
2. WHEN se crea un registro nuevo de workstation THE SYSTEM SHALL inicializar `last_seen`
   con el mismo valor que `first_seen` (asignación explícita en código de registro).
3. WHEN se ejecuta la migración sobre datos existentes THE SYSTEM SHALL poblar `last_seen`
   con `COALESCE(last_connection, first_seen)` antes de fijar el `DEFAULT` y el `NOT NULL`.
4. THE SYSTEM SHALL actualizar `last_seen` en cada uno de estos eventos: creación del
   registro, registro/re-registro de la workstation, nueva conexión (donde hoy se actualiza
   `last_connection`), y transición offline→online.
5. WHEN una workstation transiciona offline→online O se marca offline THE SYSTEM SHALL usar
   como valor de `last_seen` el timestamp de la **última telemetría real conocida**, no el
   momento del evento de cambio de estado.
6. WHEN el Death Ping determina inactividad THE SYSTEM SHALL usar como `last_seen` el
   timestamp de actividad real que disparó la evaluación de inactividad.
7. THE SYSTEM SHALL persistir `last_seen` únicamente en transiciones de estado (online↔offline)
   más un volcado periódico (flush) desde el loop existente de ~60s, que actualice en BD el
   `last_seen` de las workstations online cuyo timestamp de actividad en memoria haya avanzado.
8. THE SYSTEM SHALL NOT actualizar `last_seen` en cada telemetría individual (evitar una
   escritura por cada mensaje cada ~300s por workstation).
9. THE SYSTEM SHALL mantener la columna `last_connection` sin cambios funcionales para el
   resto de la aplicación (dashboard, exports existentes).
10. THE SYSTEM SHALL usar `last_seen` (no `last_connection`) como fuente de actividad para
    todos los cálculos de facturación y reciclaje.

### Requirement 2 — Campo `billing_status` y su ciclo de vida

**User Story:** Como administrador de facturación, necesito que cada IP registrada tenga un
estado de facturación con transiciones bien definidas, para reflejar su elegibilidad de cobro.

#### Acceptance Criteria

1. THE SYSTEM SHALL añadir una columna `billing_status` a `workstations`, de tipo String con
   CHECK constraint que restrinja los valores a `new`, `billable`, `recycled`, `archived`.
2. THE SYSTEM SHALL definir `billing_status` como NOT NULL con DEFAULT `new` una vez
   completada la migración.
3. WHEN se ejecuta la migración THE SYSTEM SHALL: (a) añadir la columna nullable, (b) fijar
   todos los registros existentes a `new`, (c) establecer DEFAULT `new` y NOT NULL.
4. WHEN se crea una workstation nueva THE SYSTEM SHALL asignar `billing_status = new`.
5. THE SYSTEM SHALL permitir únicamente las siguientes transiciones:
   - `new → billable` (durante el cierre mensual, paso 1).
   - `new → (eliminación física del registro)`.
   - `billable → recycled` (durante el cierre, si cumple reglas de reciclaje).
   - `billable → archived` (acción manual del administrador; solo si la workstation está offline).
   - `recycled → billable` (inmediatamente al presentar actividad).
   - `recycled → archived` (acción manual del administrador; solo si la workstation está offline).
   - `archived → billable` (inmediatamente al presentar actividad).
6. THE SYSTEM SHALL NOT permitir la transición `archived → recycled` mediante el proceso
   automático de cierre.
7. THE SYSTEM SHALL NOT permitir que ninguna workstation regrese al estado `new`.
8. WHEN una workstation en estado `recycled` o `archived` presenta cualquier actividad (cambio
   de `last_seen` por registro, conexión o telemetría) THE SYSTEM SHALL cambiar su
   `billing_status` a `billable` de forma **inmediata** (en el evento, no en el cierre).

### Requirement 3 — Restricción de eliminación de workstations

**User Story:** Como administrador, necesito que solo se puedan eliminar físicamente las IPs
que nunca han sido facturadas, para preservar la integridad del histórico de cierres.

#### Acceptance Criteria

1. WHEN un administrador intenta eliminar una workstation con `billing_status = new` THE
   SYSTEM SHALL eliminarla físicamente de la base de datos.
2. WHEN un administrador intenta eliminar una workstation con `billing_status` distinto de
   `new` THE SYSTEM SHALL convertirla a `archived` en lugar de eliminarla físicamente, y
   SHALL requerir que la workstation esté offline.
3. IF una workstation con `billing_status` distinto de `new` está online AND se intenta
   archivar/eliminar THEN THE SYSTEM SHALL rechazar la operación indicando que debe estar
   offline.
4. THE SYSTEM SHALL aplicar esta restricción en **todos** los flujos de eliminación de
   workstations (individual y cualquier operación masiva presente o futura).
5. WHEN una operación de eliminación masiva incluye workstations en distintos estados THE
   SYSTEM SHALL procesar cada una según su estado (eliminar las `new`, archivar las no-`new`
   offline, rechazar las no-`new` online) y SHALL retornar un reporte con el desglose de
   resultados por workstation.
6. THE SYSTEM SHALL exponer al frontend información suficiente para indicar, antes de
   ejecutar, si una workstation será eliminada físicamente o solo archivada, y por qué.

### Requirement 4 — Modalidad y zona horaria de la organización

**User Story:** Como superadministrador, necesito configurar por organización su modalidad de
facturación y su zona horaria, con reglas de bloqueo que garanticen consistencia contable.

#### Acceptance Criteria

1. THE SYSTEM SHALL permitir asignar a cada organización una modalidad de facturación:
   `monthly` (Mensual) o `annual` (Anual).
2. THE SYSTEM SHALL usar la zona horaria de la organización (`organizations.timezone`) para
   todos los cálculos de cierre, cortes de mes y capping.
3. WHEN una organización ya tiene al menos un cierre mensual registrado THE SYSTEM SHALL
   impedir modificar su `timezone`.
4. IF se intenta modificar la `timezone` de una organización con uno o más cierres THEN THE
   SYSTEM SHALL rechazar la operación con un mensaje explicativo.
5. THE SYSTEM SHALL permitir configurar la zona horaria de BBVA como `America/Lima` mediante
   una tarea de la implementación (antes de su primer cierre).
6. WHEN no se ha configurado modalidad THE SYSTEM SHALL usar un valor por defecto seguro y
   documentado hasta que un superadministrador la defina.

### Requirement 5 — Cierre mensual (cálculo de estados)

**User Story:** Como sistema de facturación, necesito ejecutar un cierre mensual por
organización que actualice estados y produzca el sustento de facturación del mes.

#### Acceptance Criteria

1. THE SYSTEM SHALL ejecutar el cierre del mes M con corte a las `00:00 del día 1 de M+1` en
   la zona horaria de la organización.
2. WHEN se ejecuta el cierre THE SYSTEM SHALL considerar únicamente las workstations con
   `created_at` anterior al corte (`00:00 del día 1 de M+1`).
3. THE SYSTEM SHALL ejecutar el cierre en este orden:
   1. Convertir todas las `new` (dentro del corte) a `billable`.
   2. Evaluar las reglas de reciclaje sobre las `billable`.
   3. NO modificar las `archived`.
4. **Regla de reciclaje — Caso 1 (poco uso):** WHEN una workstation `billable` tiene
   `last_seen` (crudo) anterior a las `00:00 del día 1 de (M−2)` AND `(last_seen − created_at)
   < 24 horas` THEN THE SYSTEM SHALL cambiar su estado a `recycled`.
   (Ejemplo: cerrando noviembre, corte de inactividad = 00:00 del 1 de septiembre.)
5. **Regla de reciclaje — Caso 2 (abandono):** WHEN una workstation `billable` tiene
   `last_seen` (crudo) anterior a las `00:00 del día 1 de (M−3)`, independientemente del
   tiempo de uso, THEN THE SYSTEM SHALL cambiar su estado a `recycled`.
   (Ejemplo: cerrando noviembre, corte de abandono = 00:00 del 1 de agosto.)
6. THE SYSTEM SHALL usar el `last_seen` **crudo** (valor de BD) para evaluar las reglas de
   reciclaje.
7. THE SYSTEM SHALL usar el `last_seen` **capado a 00:00 del día 1 de M+1** para el valor
   registrado en el sustento/snapshot del cierre.
8. THE SYSTEM SHALL ejecutar el cierre por organización, aislado por `organization_id`
   (tenant isolation).

### Requirement 6 — Sustento del cierre (snapshot)

**User Story:** Como auditor de facturación, necesito un sustento inmutable de cada cierre
para poder justificar el monto facturado.

#### Acceptance Criteria

1. WHEN se completa un cierre THE SYSTEM SHALL persistir una **cabecera de cierre** por
   `(organization_id, año, mes)` con: fecha de corte, modalidad, timezone usada, totales por
   estado (`billable`, `recycled`, `archived`), monto calculado y tarifa/tramos aplicados.
2. WHEN se completa un cierre THE SYSTEM SHALL persistir un **detalle por IP** (una fila por
   workstation incluida en el corte) con al menos: `ip_private`, `created_at`, `last_seen`
   capado, `billing_status` resultante en ese cierre, y el aporte de monto/tramo asignado.
3. THE SYSTEM SHALL registrar en el snapshot todas las workstations creadas antes del corte,
   con el estado calculado (no habrá `new` porque el paso 1 las convierte a `billable`).
4. THE SYSTEM SHALL tratar el snapshot como **inmutable**: un cierre ya generado no se
   recalcula ni se sobrescribe.
5. THE SYSTEM SHALL almacenar en el snapshot el estado histórico correspondiente a ese cierre,
   mientras que la columna `billing_status` viva de la workstation refleja el estado del
   último cierre ejecutado; un cierre retroactivo SHALL NOT retroceder el `billing_status`
   vivo actual.

### Requirement 7 — Ejecución automática y cierres retroactivos

**User Story:** Como operador del sistema, necesito que los cierres se ejecuten
automáticamente cada mes y que un superadministrador pueda generar cierres históricos
faltantes.

#### Acceptance Criteria

1. THE SYSTEM SHALL ejecutar automáticamente el cierre del mes que finaliza a las `00:00 del
   día 1` en la zona horaria de cada organización (job programado / cron de medianoche).
2. WHEN existen cierres pendientes anteriores al mes en curso O la organización no tiene
   cierres THE SYSTEM SHALL permitir a un superadministrador generar cierres retroactivos.
3. THE SYSTEM SHALL permitir la generación retroactiva **uno por uno**, comenzando por el mes
   más antiguo (definido por el `created_at` más antiguo de una IP de la organización).
4. IF un superadministrador intenta cerrar un mes M mientras exista un mes anterior sin cerrar
   THEN THE SYSTEM SHALL rechazar la operación (los cierres deben ser secuenciales, sin saltos).
5. WHEN se ejecuta un cierre retroactivo THE SYSTEM SHALL aplicar el capping de `last_seen` a
   `00:00 del día 1 de M+1` en el snapshot, evitando registrar actividad posterior al mes
   cerrado.
6. THE SYSTEM SHALL garantizar la idempotencia: un mes ya cerrado no puede volver a cerrarse.

### Requirement 8 — Modelos tarifarios y facturación mensual

**User Story:** Como superadministrador, necesito definir tarifas por defecto y planes por
organización, y que el sistema calcule la facturación mensual por tramos.

#### Acceptance Criteria

1. THE SYSTEM SHALL almacenar tarifas por defecto del sistema para ambas modalidades,
   editables **solo por superadministradores**, con estos valores iniciales:
   - **Mensual (incremental por tramos, US$/IP):** T1 1–100 = 0.500; T2 101–2,000 = 0.250;
     T3 2,001–5,000 = 0.200; T4 5,001–10,000 = 0.180; T5 10,001+ = 0.175.
   - **Anual (US$/IP/año, tarifa del tramo contratado):** 1–100 = 5.00 (crec. libre 200);
     201–2,000 = 2.50 (2,250); 2,251–5,000 = 2.25 (5,800); 5,801–10,000 = 1.95 (11,200);
     11,201+ = 1.75.
2. THE SYSTEM SHALL permitir asignar a cada organización un **plan tarifario individual** por
   modalidad, que puede diferir de los defaults.
3. WHEN la modalidad es Mensual THE SYSTEM SHALL calcular la facturación del cierre como la
   **suma incremental por tramos**: cada tramo aplica su tarifa solo a las IPs contenidas en
   él (ejemplo: 3,136 IPs = 100×0.50 + 1,900×0.25 + 1,136×0.20 = 752.20).
4. THE SYSTEM SHALL contar como base de facturación mensual las workstations en estado
   `billable` tras ejecutar el cierre del mes.
5. THE SYSTEM SHALL permitir modificar las tarifas de la modalidad **Mensual** y aplicarlas
   en cierres futuros.
6. THE SYSTEM SHALL congelar la tarifa de la modalidad **Anual** durante la vigencia de la
   suscripción; los cambios de tarifa anual SHALL aplicarse solo antes de una renovación.
7. THE SYSTEM SHALL redondear los montos a 2 decimales (redondeo estándar half-up), aunque
   las tarifas unitarias tengan hasta 3 decimales.
8. WHEN un superadministrador programa un cambio de tarifas por defecto THE SYSTEM SHALL
   conservar los planes individuales asignados por organización (los defaults no sobrescriben
   planes existentes).

### Requirement 9 — Suscripción y liquidación anual (informativa)

**User Story:** Como superadministrador, necesito registrar suscripciones anuales y ver el
cálculo de liquidación en el aniversario, confirmando manualmente el ajuste.

#### Acceptance Criteria

1. WHEN se crea una suscripción Anual THE SYSTEM SHALL registrar: fecha de inicio (= `created_at`
   del primer registro de la organización), fecha de fin (= un día antes del aniversario),
   volumen declarado (input manual del superadministrador) y tarifa del tramo (congelada).
   (Ejemplo: primer registro 5-may-2026 ⇒ inicio 5-may-2026, fin 4-may-2027.)
2. WHILE una suscripción Anual está vigente THE SYSTEM SHALL ejecutar los cierres mensuales
   normalmente pero generar el invoice mensual en **US$ 0.00** (ya hay contrato anual pagado).
3. WHEN llega el aniversario (00:00 del día de renovación en timezone de la org) THE SYSTEM
   SHALL ejecutar el cierre y calcular la liquidación: base = IPs activas (`billable`) al
   aniversario, con el **tope del tramo contratado** (ej. 10,500 ⇒ 10,000).
4. THE SYSTEM SHALL calcular la diferencia entre volumen declarado y uso real, y multiplicar
   por la tarifa del tramo para obtener un **crédito** (si real < declarado) o un **cargo**
   (si real > declarado).
5. THE SYSTEM SHALL presentar la liquidación anual de forma **informativa** (declarado, real,
   diferencia, crédito/cargo sugerido); la aplicación/emisión de la liquidación SHALL requerir
   confirmación manual del superadministrador (no se aplica automáticamente).
6. THE SYSTEM SHALL considerar, de forma informativa, el margen de "crecimiento libre" del
   tramo para indicar si el uso real permanece dentro del tramo contratado o requiere
   reclasificación.

### Requirement 10 — Interfaz de usuario (sección Usage and Billing)

**User Story:** Como administrador/superadministrador, necesito una sección en el dashboard
para configurar facturación, ver cierres, y gestionar estados de IPs.

#### Acceptance Criteria

1. THE SYSTEM SHALL añadir una sección **Usage and Billing** en el dashboard.
2. THE SYSTEM SHALL mostrar, por organización, la modalidad, la zona horaria (bloqueada tras
   el primer cierre) y el plan tarifario vigente.
3. THE SYSTEM SHALL listar los cierres mensuales con su cabecera (totales por estado y monto)
   y permitir ver el detalle por IP de cada cierre.
4. THE SYSTEM SHALL permitir a superadministradores editar tarifas por defecto y planes por
   organización, y programar cambios de tarifas.
5. THE SYSTEM SHALL permitir a superadministradores generar cierres retroactivos uno por uno
   desde el más antiguo, respetando la secuencialidad.
6. WHEN se lista workstations THE SYSTEM SHALL incluir un filtro "ocultar archived" activado
   por defecto (análogo al filtro de online existente).
7. WHEN el usuario intenta eliminar una workstation THE SYSTEM SHALL indicar claramente si la
   acción resultará en eliminación física (solo `new`) o en archivado (no-`new`, requiere
   offline), y por qué.
8. THE SYSTEM SHALL restringir la edición de modelos tarifarios y de rangos/planes por defecto
   exclusivamente a superadministradores.

### Requirement 11 — Permisos y aislamiento

**User Story:** Como responsable de seguridad, necesito que las operaciones de facturación
respeten los roles y el aislamiento multi-tenant.

#### Acceptance Criteria

1. THE SYSTEM SHALL restringir la edición de modelos tarifarios por defecto y de planes por
   organización a superadministradores.
2. THE SYSTEM SHALL restringir la generación de cierres retroactivos a superadministradores.
3. THE SYSTEM SHALL filtrar todas las consultas de cierres, snapshots y estados por
   `organization_id` (tenant isolation).
4. THE SYSTEM SHALL registrar en auditoría las acciones sensibles: cambio de modalidad,
   intento/bloqueo de cambio de timezone, archivado manual, edición de tarifas, ejecución de
   cierres (automáticos y retroactivos) y liquidaciones anuales.
