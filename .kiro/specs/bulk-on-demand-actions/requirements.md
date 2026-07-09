# Requirements Document

## Introduction

Sistema de ejecución masiva de acciones OnDemand a nivel de organización con throttling configurable. Permite a operadores y administradores ejecutar una acción OnDemand del alwaysconfig activo contra todas las workstations online de una organización, con control de velocidad de envío, progreso en tiempo real y cancelación.

## Glossary

- **Bulk_Executor**: Servicio backend que orquesta la ejecución masiva de comandos `execute_on_demand` iterando sobre las workstations online de una organización con throttling configurable.
- **Bulk_Session**: Instancia única de una ejecución masiva, identificada por un UUID, con estado (running, completed, cancelled, failed) y métricas de progreso.
- **Throttle_Config**: Configuración de velocidad de envío que define el delay (en milisegundos) entre cada comando enviado a una workstation.
- **Progress_Report**: Mensaje enviado al frontend vía WebSocket con las métricas actualizadas de una Bulk_Session (total, enviados, éxitos, errores, cancelado).
- **OnDemand_Label**: Identificador string de un trigger OnDemand definido en el alwaysconfig activo de la organización (campo `label` en triggers con `event: "OnDemand"`).
- **Connection_Manager**: Componente existente que gestiona conexiones WebSocket con workstations y operadores, provee `is_workstation_online` y `send_to_workstation`.
- **Operator**: Usuario con rol `operator` o `admin` autenticado en el sistema.

## Requirements

### Requirement 1: Obtener acciones OnDemand disponibles

**User Story:** Como operador, quiero ver la lista de acciones OnDemand disponibles en mi organización, para poder seleccionar cuál ejecutar de forma masiva.

#### Acceptance Criteria

1. WHEN el Operator solicita las acciones OnDemand disponibles, THE Bulk_Executor SHALL obtener el alwaysconfig activo (scope=org) de la organización del Operator y extraer todos los triggers con `event: "OnDemand"` que tengan un `label` definido.
2. THE Bulk_Executor SHALL retornar una lista de objetos con los campos `label` y `description` (si existe) de cada trigger OnDemand encontrado.
3. IF la organización no tiene un alwaysconfig activo, THEN THE Bulk_Executor SHALL retornar un error indicando que no hay configuración activa.
4. IF el alwaysconfig activo no contiene triggers OnDemand, THEN THE Bulk_Executor SHALL retornar una lista vacía.

### Requirement 2: Iniciar ejecución masiva con throttling

**User Story:** Como operador, quiero iniciar la ejecución masiva de una acción OnDemand contra todas las workstations online de mi organización con un delay configurable entre envíos, para no saturar el sistema.

#### Acceptance Criteria

1. WHEN el Operator solicita iniciar una Bulk_Session proporcionando un OnDemand_Label y un Throttle_Config, THE Bulk_Executor SHALL validar que el label existe en el alwaysconfig activo de la organización.
2. WHEN la validación es exitosa, THE Bulk_Executor SHALL crear una Bulk_Session con estado `running` y retornar el session_id, la cantidad total de workstations online a procesar, y el timestamp de inicio.
3. THE Bulk_Executor SHALL iterar las workstations online de la organización enviando el comando `execute_on_demand` con el label especificado a cada una, respetando el delay definido en Throttle_Config entre cada envío.
4. THE Bulk_Executor SHALL aceptar un Throttle_Config con un campo `delay_ms` entre 50 y 10000 milisegundos.
5. IF el Throttle_Config tiene un `delay_ms` fuera del rango permitido, THEN THE Bulk_Executor SHALL rechazar la solicitud con un error de validación.
6. IF el OnDemand_Label no existe en el alwaysconfig activo, THEN THE Bulk_Executor SHALL rechazar la solicitud indicando que el label no es válido.
7. IF ya existe una Bulk_Session en estado `running` para la misma organización, THEN THE Bulk_Executor SHALL rechazar la nueva solicitud indicando que ya hay una ejecución en curso.

### Requirement 3: Reportar progreso en tiempo real

**User Story:** Como operador, quiero ver el progreso de la ejecución masiva en tiempo real, para saber cuántas workstations se han procesado y si hay errores.

#### Acceptance Criteria

1. WHILE una Bulk_Session está en estado `running`, THE Bulk_Executor SHALL enviar un Progress_Report al Operator vía WebSocket cada vez que se complete el envío a una workstation (sea éxito o error).
2. THE Progress_Report SHALL contener: session_id, total de workstations target, cantidad de envíos completados, cantidad de éxitos, cantidad de errores, y estado actual de la sesión.
3. WHEN la Bulk_Session procesa la última workstation sin ser cancelada, THE Bulk_Executor SHALL actualizar el estado a `completed` y enviar un Progress_Report final.
4. IF el envío a una workstation individual falla (workstation se desconectó entre el check y el envío), THEN THE Bulk_Executor SHALL incrementar el contador de errores, registrar el workstation_id fallido, y continuar con la siguiente workstation.

### Requirement 4: Cancelar ejecución en curso

**User Story:** Como operador, quiero poder cancelar una ejecución masiva en curso, para detener el envío de comandos si detecto un problema.

#### Acceptance Criteria

1. WHEN el Operator solicita cancelar una Bulk_Session en estado `running`, THE Bulk_Executor SHALL actualizar el estado a `cancelled` y detener el envío de nuevos comandos.
2. THE Bulk_Executor SHALL enviar un Progress_Report final con el estado `cancelled` y las métricas acumuladas hasta el momento de la cancelación.
3. THE Bulk_Executor SHALL completar el envío del comando en curso (si hay uno en vuelo) antes de detenerse, sin iniciar nuevos envíos.
4. IF la Bulk_Session no está en estado `running`, THEN THE Bulk_Executor SHALL rechazar la cancelación indicando que la sesión no es cancelable.

### Requirement 5: Seguridad y autorización

**User Story:** Como administrador del sistema, quiero que solo operadores y admins puedan ejecutar acciones masivas, para prevenir uso no autorizado de funcionalidad crítica.

#### Acceptance Criteria

1. THE Bulk_Executor SHALL requerir que el usuario tenga rol `admin` o `operator` para iniciar, consultar o cancelar una Bulk_Session.
2. WHILE el Operator tiene rol `operator`, THE Bulk_Executor SHALL restringir las operaciones exclusivamente a la organización asignada al Operator (tenant isolation).
3. IF un usuario con rol `readonly` intenta interactuar con el Bulk_Executor, THEN THE Bulk_Executor SHALL retornar un error HTTP 403.

### Requirement 6: Confirmación antes de ejecución

**User Story:** Como operador, quiero ver un resumen de la acción masiva antes de confirmarla, para evitar ejecuciones accidentales.

#### Acceptance Criteria

1. WHEN el Operator solicita un preview de la ejecución masiva proporcionando un OnDemand_Label, THE Bulk_Executor SHALL retornar: el nombre de la acción, el número de workstations online en la organización en ese momento, y el tiempo estimado de ejecución basado en el Throttle_Config.
2. THE Bulk_Executor SHALL calcular el tiempo estimado como: (workstations_online - 1) * delay_ms milisegundos.

### Requirement 7: Registro de auditoría

**User Story:** Como administrador, quiero que todas las ejecuciones masivas queden registradas en auditoría, para poder investigar incidentes y tener trazabilidad completa.

#### Acceptance Criteria

1. WHEN una Bulk_Session se inicia, THE Bulk_Executor SHALL registrar en el sistema de auditoría: user_id del Operator, organization_id, OnDemand_Label ejecutado, Throttle_Config, cantidad total de workstations target, y timestamp.
2. WHEN una Bulk_Session finaliza (por completación o cancelación), THE Bulk_Executor SHALL registrar en auditoría: session_id, estado final, duración total, cantidad de éxitos, cantidad de errores.

### Requirement 8: Interfaz de usuario para ejecución masiva

**User Story:** Como operador, quiero una interfaz en el dashboard que me permita seleccionar la acción, configurar el throttling, ver el progreso y cancelar la ejecución, para operar de forma autónoma sin necesidad de scripts manuales.

#### Acceptance Criteria

1. THE Frontend SHALL presentar un componente de ejecución masiva en la sección de la organización del dashboard, accesible solo para usuarios con rol `admin` u `operator`.
2. THE Frontend SHALL mostrar un selector con las acciones OnDemand disponibles obtenidas del endpoint de listado.
3. THE Frontend SHALL permitir al Operator configurar el delay entre envíos mediante un campo numérico con valor por defecto de 500ms y rango de 50ms a 10000ms.
4. WHEN el Operator confirma la ejecución, THE Frontend SHALL mostrar un diálogo de confirmación indicando la acción seleccionada y el número de workstations que se verán afectadas.
5. WHILE una Bulk_Session está en estado `running`, THE Frontend SHALL mostrar una barra de progreso, los contadores de total/enviados/éxitos/errores, y un botón de cancelación.
6. WHEN la Bulk_Session finaliza, THE Frontend SHALL mostrar un resumen con el resultado final (completado, cancelado) y las métricas.
