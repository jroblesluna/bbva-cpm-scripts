# Documento de Requisitos — On-Demand Triggers

## Introducción

Esta funcionalidad extiende el sistema AlwaysPrint con tres capacidades principales: (1) un formulario de Estado/About que se muestra al hacer doble clic en el ícono del escritorio, comunicándose con la instancia existente vía mensaje Win32 broadcast; (2) un submenú de acciones a demanda en el menú contextual del Tray; y (3) la definición de triggers `OnDemand` dentro del array `triggers` existente en archivos `.alwaysconfig`. La ejecución de acciones se delega al AlwaysPrintService vía Named Pipe, manteniendo la separación de responsabilidades existente (Tray = UI, Service = ejecución con permisos LocalSystem).

## Glosario

- **Tray**: Aplicación de bandeja del sistema (`AlwaysPrintTray.exe`) que gestiona el ícono, menú contextual, formularios y comunicación con la Cloud.
- **Service**: Servicio Windows (`AlwaysPrintService`) que ejecuta acciones administrativas con permisos LocalSystem.
- **ActionEngine**: Motor de ejecución de acciones que parsea archivos `.alwaysconfig` y ejecuta secuencias de acciones.
- **Named_Pipe**: Canal de comunicación IPC entre Tray y Service (pipe: `AlwaysPrintService`).
- **Alwaysconfig**: Archivo JSON de configuración de acciones administrativas (`active.alwaysconfig`).
- **Trigger_OnDemand**: Trigger con evento `"OnDemand"` que incluye campos `label` y `description` para identificación y presentación en la UI.
- **Menú_Contextual**: Menú desplegable del ícono del Tray que aparece al hacer clic derecho.
- **Submenú_OnDemand**: Submenú dentro del Menú_Contextual titulado "Acciones A Demanda" que agrupa las opciones OnDemand.
- **PipeMessage**: Estructura de mensaje utilizada para comunicación vía Named Pipe entre Tray y Service.
- **Status_Form**: Formulario de estado que muestra información del sistema, servicios y triggers OnDemand disponibles.
- **Win32_Broadcast**: Mensaje Windows registrado con `RegisterWindowMessage("AlwaysPrintTray_ShowStatus")` para comunicación entre instancias.
- **Mutex**: Primitiva de sincronización (`Global\AlwaysPrintTray-SingleInstance`) que garantiza instancia única del Tray.
- **Cola_Activa**: Cola de impresión gestionada por AlwaysPrint (cola por defecto). En modo CPM apunta a loopback; en modo LPM usa `remote_queue_path` de `resources.json`.
- **Resources_JSON**: Archivo `resources.json` que contiene metadata de VLAN incluyendo `remote_queue_path` para modo LPM.

## Requisitos

### Requisito 1: Detección de segunda instancia y señalización vía Win32 Broadcast

**User Story:** Como usuario, quiero que al hacer doble clic en el ícono de AlwaysPrint en el escritorio se muestre el formulario de estado, para poder consultar rápidamente la información del sistema sin abrir herramientas externas.

#### Criterios de Aceptación

1. WHEN una segunda instancia del Tray detecta que el Mutex ya está tomado, THE Tray SHALL enviar un mensaje Win32_Broadcast registrado con `RegisterWindowMessage("AlwaysPrintTray_ShowStatus")` y terminar inmediatamente sin mostrar UI.
2. WHILE la primera instancia del Tray está en ejecución, THE Tray SHALL escuchar mensajes Win32_Broadcast con el identificador `"AlwaysPrintTray_ShowStatus"` mediante override de `WndProc`.
3. WHEN la primera instancia recibe el mensaje Win32_Broadcast `"AlwaysPrintTray_ShowStatus"`, THE Tray SHALL mostrar el Status_Form (o traerlo al frente si ya está visible).
4. THE Tray SHALL registrar en el log la recepción del mensaje broadcast y la acción tomada (mostrar formulario o traer al frente).

### Requisito 2: Formulario de Estado (Status Form) — Información General

**User Story:** Como usuario, quiero ver un resumen del estado del sistema AlwaysPrint en un formulario dedicado, para poder verificar rápidamente la versión, configuración activa y cola gestionada.

#### Criterios de Aceptación

1. THE Status_Form SHALL mostrar el campo "Estado" con el valor "Normal" o "En Contingencia" según el estado actual del sistema (lectura de `ContingencyEnabled` en registro).
2. THE Status_Form SHALL mostrar el campo "Versión" con la versión actual del ensamblado de AlwaysPrint.
3. WHEN el modo de operación es CPM (sin `remote_queue_path` en Resources_JSON), THE Status_Form SHALL mostrar el campo "Cola activa gestionada" con el nombre de la cola por defecto (configuración `CorporateQueueName`).
4. WHEN el modo de operación es LPM (con `remote_queue_path` en Resources_JSON), THE Status_Form SHALL mostrar el campo "Cola activa gestionada" con el nombre de la cola seguido de la ruta remota entre paréntesis.
5. THE Status_Form SHALL mostrar el campo "Configuración" con el nombre y versión del Alwaysconfig activo (formato: `"{name} v{version}"`).
6. THE Status_Form SHALL ser un formulario no modal que permite interacción con el Tray mientras está abierto.
7. THE Status_Form SHALL implementar control de instancia única (si ya está abierto, traer al frente en lugar de abrir otro).

### Requisito 3: Formulario de Estado — Sección de Servicios

**User Story:** Como usuario, quiero ver el estado de los servicios del sistema de impresión y poder reiniciarlos o iniciarlos, para poder resolver problemas sin recurrir a herramientas administrativas externas.

#### Criterios de Aceptación

1. THE Status_Form SHALL mostrar una sección "Estado de servicios" con el estado (Running/Stopped) de los siguientes servicios: AlwaysPrintService, lpmc_universal_service (LPMC), LpdServiceMonitor (LPD Service Monitor), LPDSVC (Servicio LPD) y Spooler (Cola de Impresión).
2. WHEN un servicio está en estado Running, THE Status_Form SHALL mostrar un botón o switch para REINICIAR (Restart) ese servicio.
3. WHEN un servicio está en estado Stopped, THE Status_Form SHALL mostrar un botón o switch para INICIAR (Start) ese servicio.
4. THE Status_Form SHALL enviar la solicitud de inicio o reinicio de servicio al Service vía Named_Pipe utilizando PipeMessages existentes (CheckServiceStatus para consulta, y un nuevo mensaje para la acción de reinicio/inicio).
5. THE Status_Form SHALL actualizar el estado visual del servicio tras recibir la respuesta del Service.
6. THE Status_Form SHALL deshabilitar el control del servicio durante la operación de inicio/reinicio para prevenir clics duplicados.
7. IF la conexión al Named_Pipe no está disponible, THEN THE Status_Form SHALL mostrar los servicios como "Estado desconocido" y deshabilitar los controles de acción.

### Requisito 4: Formulario de Estado — Sección de Triggers OnDemand

**User Story:** Como usuario, quiero ver y ejecutar los triggers OnDemand disponibles desde el formulario de estado, para tener un punto centralizado de acciones administrativas manuales.

#### Criterios de Aceptación

1. THE Status_Form SHALL mostrar una sección "On Demand Triggers" con la lista de todos los triggers con evento `"OnDemand"` de la configuración activa, mostrando su campo `label`.
2. WHEN el usuario hace clic en un trigger OnDemand de la lista, THE Status_Form SHALL mostrar un diálogo de confirmación con la `description` del trigger y dos botones: "Confirmar Ejecución" y "Cancelar".
3. WHEN el usuario confirma la ejecución en el diálogo, THE Status_Form SHALL enviar un PipeMessage de tipo `ExecuteOnDemandTrigger` al Service con el `label` del trigger seleccionado.
4. WHEN el usuario cancela en el diálogo de confirmación, THE Status_Form SHALL cerrar el diálogo sin realizar ninguna acción.
5. WHILE un trigger OnDemand está en ejecución, THE Status_Form SHALL deshabilitar el ítem correspondiente en la lista para prevenir ejecuciones duplicadas.
6. WHEN la ejecución del trigger finaliza (éxito o fallo), THE Status_Form SHALL rehabilitar el ítem y mostrar feedback visual del resultado.
7. WHEN la configuración activa no contiene triggers OnDemand, THE Status_Form SHALL mostrar la sección "On Demand Triggers" con un mensaje indicando que no hay acciones disponibles.

### Requisito 5: Definición de triggers OnDemand en alwaysconfig

**User Story:** Como administrador, quiero definir triggers a demanda dentro del array `triggers` existente del alwaysconfig con un label y descripción, para que los usuarios finales puedan ejecutar acciones predefinidas desde la UI del Tray.

#### Criterios de Aceptación

1. THE TriggerConfig SHALL soportar el evento `"OnDemand"` como un valor válido del campo `event` dentro del array `triggers` existente.
2. WHEN el campo `event` de un trigger es `"OnDemand"`, THE TriggerConfig SHALL requerir un campo `label` con texto no vacío que represente el identificador único y texto visible en la UI.
3. WHEN el campo `event` de un trigger es `"OnDemand"`, THE TriggerConfig SHALL incluir un campo `description` con texto que se muestra en el diálogo de confirmación antes de la ejecución.
4. THE ActionConfiguration SHALL permitir múltiples triggers con evento `"OnDemand"` en un mismo archivo Alwaysconfig.
5. IF un trigger `"OnDemand"` tiene el campo `label` vacío o ausente, THEN THE ActionEngine SHALL ignorar ese trigger y registrar una advertencia en el log.
6. IF dos o más triggers `"OnDemand"` tienen el mismo valor de `label`, THEN THE ActionEngine SHALL ejecutar el primero encontrado y registrar una advertencia en el log indicando duplicidad.

### Requisito 6: Submenú de acciones OnDemand en el menú contextual del Tray

**User Story:** Como usuario final, quiero ver las acciones OnDemand en un submenú dedicado del menú contextual del Tray, para poder ejecutarlas rápidamente sin abrir el formulario de estado.

#### Criterios de Aceptación

1. WHEN la configuración activa contiene triggers con evento `"OnDemand"`, THE Tray SHALL mostrar un submenú titulado "Acciones A Demanda" en el Menú_Contextual.
2. THE Tray SHALL posicionar el Submenú_OnDemand después del ítem "Buscar Actualizaciones" y antes del separador que precede al ítem "Salir".
3. THE Tray SHALL mostrar cada trigger OnDemand como un ítem del Submenú_OnDemand con el texto del campo `label`.
4. WHEN la configuración activa no contiene triggers con evento `"OnDemand"`, THE Tray SHALL omitir el Submenú_OnDemand del Menú_Contextual (no mostrar submenú vacío).
5. WHEN el usuario hace clic en un ítem del Submenú_OnDemand, THE Tray SHALL enviar un PipeMessage de tipo `ExecuteOnDemandTrigger` al Service con el `label` del trigger seleccionado.
6. THE Tray SHALL insertar un separador visual antes del Submenú_OnDemand para distinguirlo de las opciones estándar del menú.

### Requisito 7: Comunicación Tray→Service para ejecución de triggers OnDemand

**User Story:** Como desarrollador del sistema, quiero que el Tray envíe un comando al Service vía Named Pipe cuando el usuario solicita ejecutar una acción OnDemand (desde el submenú o desde el formulario), para que la ejecución ocurra con los permisos adecuados (LocalSystem).

#### Criterios de Aceptación

1. WHEN el usuario solicita la ejecución de un trigger OnDemand (desde el Submenú_OnDemand o desde el Status_Form), THE Tray SHALL enviar un PipeMessage de tipo `ExecuteOnDemandTrigger` al Service con un payload que contenga el campo `label` del trigger a ejecutar.
2. THE PipeMessage de tipo `ExecuteOnDemandTrigger` SHALL utilizar un payload `ExecuteOnDemandTriggerPayload` con el campo `label` de tipo string.
3. IF la conexión al Named_Pipe no está disponible al momento de la solicitud, THEN THE Tray SHALL mostrar una notificación balloon indicando que el servicio no está accesible y registrar el error en el log.

### Requisito 8: Ejecución de acciones OnDemand por el Service

**User Story:** Como desarrollador del sistema, quiero que el Service ejecute las acciones definidas en un trigger OnDemand cuando recibe el comando del Tray, para mantener la arquitectura existente donde solo el Service ejecuta acciones administrativas.

#### Criterios de Aceptación

1. WHEN el Service recibe un PipeMessage de tipo `ExecuteOnDemandTrigger`, THE ActionEngine SHALL buscar el primer trigger OnDemand cuyo `label` coincide exactamente con el payload recibido y ejecutar sus acciones.
2. IF el Service recibe un `ExecuteOnDemandTrigger` con un `label` que no corresponde a ningún trigger OnDemand cargado, THEN THE Service SHALL responder con un PipeMessage de tipo `Error` indicando que el trigger no fue encontrado.
3. WHEN el ActionEngine completa la ejecución del trigger OnDemand, THE Service SHALL responder al Tray con un PipeMessage de tipo `Ack` indicando el resultado (éxito o fallo) en el campo `success` del payload.
4. THE ActionEngine SHALL registrar en el log el inicio y resultado de la ejecución de cada trigger OnDemand, incluyendo el `label` del trigger ejecutado y la duración de la ejecución.
5. IF dos triggers OnDemand tienen el mismo `label`, THEN THE ActionEngine SHALL ejecutar el primero encontrado en el array y registrar una advertencia en el log indicando la duplicidad.

### Requisito 9: Retroalimentación al usuario tras la ejecución

**User Story:** Como usuario final, quiero recibir retroalimentación visual cuando ejecuto una acción OnDemand, para saber si la acción se completó correctamente o falló.

#### Criterios de Aceptación

1. WHEN el Tray recibe una respuesta `Ack` con `success=true` del Service tras un `ExecuteOnDemandTrigger`, THE Tray SHALL mostrar una notificación balloon con un mensaje confirmando la ejecución exitosa que incluya el `label` del trigger.
2. WHEN el Tray recibe una respuesta `Ack` con `success=false` o un `Error` del Service, THE Tray SHALL mostrar una notificación balloon indicando que la acción falló, incluyendo el mensaje de error si está disponible.
3. WHILE un trigger OnDemand está en ejecución (desde el submenú), THE Tray SHALL deshabilitar (grayed out) el ítem correspondiente en el Submenú_OnDemand para prevenir ejecuciones duplicadas.
4. WHEN la ejecución del trigger OnDemand finaliza (éxito o fallo), THE Tray SHALL rehabilitar el ítem en el Submenú_OnDemand y en el Status_Form si está abierto.

### Requisito 10: Actualización dinámica del menú y formulario ante cambios de configuración

**User Story:** Como usuario, quiero que el submenú de acciones OnDemand y el formulario de estado se actualicen automáticamente cuando la configuración activa cambia, para siempre ver las opciones vigentes sin reiniciar el Tray.

#### Criterios de Aceptación

1. WHEN la configuración activa cambia (evento `ActionConfigChanged` recibido vía Named_Pipe), THE Tray SHALL reconstruir el Submenú_OnDemand del Menú_Contextual para reflejar los triggers OnDemand actualizados.
2. WHEN la configuración activa cambia y el Status_Form está abierto, THE Tray SHALL actualizar la sección "On Demand Triggers" del formulario para reflejar la nueva lista de triggers disponibles.
3. WHEN la configuración activa cambia y el Status_Form está abierto, THE Tray SHALL actualizar el campo "Configuración" con el nombre y versión de la nueva configuración.
4. IF la nueva configuración elimina un trigger OnDemand que estaba en ejecución, THEN THE Tray SHALL esperar la respuesta del Service antes de actualizar la UI (no cancelar ejecución en curso).

### Requisito 11: Lectura de configuración OnDemand por el Tray

**User Story:** Como desarrollador del sistema, quiero que el Tray pueda leer los triggers OnDemand desde la configuración activa, para construir dinámicamente el submenú y la lista del formulario.

#### Criterios de Aceptación

1. THE Tray SHALL leer el archivo de configuración activa desde la ruta definida en `PipeConstants.ActionConfigFilePath` para obtener los triggers OnDemand al inicio y ante cambios.
2. WHEN el Tray inicia (bootstrap), THE Tray SHALL leer la configuración activa y construir el Submenú_OnDemand con las opciones OnDemand disponibles.
3. IF el archivo de configuración activa no existe o no es parseable, THEN THE Tray SHALL construir el Menú_Contextual sin el Submenú_OnDemand y registrar una advertencia en el log.
4. THE Tray SHALL filtrar de la lista de triggers solo aquellos con `event == "OnDemand"` y `label` no vacío, descartando triggers malformados.
