# Documento de Requisitos — Death Ping Optimization

## Introducción

Optimización del mecanismo de detección de conexiones muertas en el backend de AlwaysPrint Cloud. El sistema actual envía un ping cada 60 segundos a TODAS las workstations conectadas independientemente de su actividad. Con 5000 workstations, esto genera 5000 pings/minuto innecesarios dado que la mayoría de las workstations están enviando telemetría activamente.

El nuevo mecanismo "Death Ping" reemplaza el ping masivo por detección inteligente de inactividad: solo se envía un ping a workstations que han excedido el tiempo de inactividad configurado por organización. Si no responden en 30 segundos, se marcan para desconexión batch.

## Glosario

- **Connection_Manager**: Singleton (`connection_manager`) que gestiona todas las conexiones WebSocket del backend, implementado en `app/services/websocket_manager.py`.
- **Workstation**: Equipo Windows con AlwaysPrintTray conectado via WebSocket al backend.
- **Death_Ping**: Ping selectivo enviado únicamente a workstations que han superado el timeout de inactividad de su organización.
- **Last_Activity**: Timestamp UTC del último mensaje recibido de una workstation (register, telemetry, pong, status_update, connectivity_result).
- **Offline_Timeout_Minutes**: Campo configurable a nivel de organización que define los minutos de inactividad antes de enviar un Death Ping. Valor por defecto: 10 minutos.
- **Pong_Timeout**: Tiempo máximo de espera para un pong después de enviar un Death Ping. Valor fijo: 30 segundos.
- **Check_Interval**: Intervalo del loop de verificación de inactividad. Valor fijo: 60 segundos.
- **Batch_Disconnect**: Mecanismo existente que marca múltiples workstations como offline en una sola query UPDATE (commit bef6b8c).
- **Organization**: Modelo multi-tenant que agrupa workstations y define configuración global, implementado en `app/models/organization.py`.

## Requisitos

### Requisito 1: Rastreo de última actividad por workstation

**User Story:** Como administrador del sistema, quiero que el backend rastree la última actividad de cada workstation conectada, para poder identificar cuáles están inactivas sin necesidad de enviarles ping.

#### Criterios de Aceptación

1. WHEN una workstation envía un mensaje de tipo register, THE Connection_Manager SHALL actualizar el campo Last_Activity de esa workstation con el timestamp UTC actual.
2. WHEN una workstation envía un mensaje de tipo telemetry, THE Connection_Manager SHALL actualizar el campo Last_Activity de esa workstation con el timestamp UTC actual.
3. WHEN una workstation envía un mensaje de tipo pong, THE Connection_Manager SHALL actualizar el campo Last_Activity de esa workstation con el timestamp UTC actual.
4. WHEN una workstation envía un mensaje de tipo status_update, THE Connection_Manager SHALL actualizar el campo Last_Activity de esa workstation con el timestamp UTC actual.
5. WHEN una workstation envía un mensaje de tipo connectivity_result, THE Connection_Manager SHALL actualizar el campo Last_Activity de esa workstation con el timestamp UTC actual.
6. WHEN una workstation se conecta por primera vez (register), THE Connection_Manager SHALL inicializar el campo Last_Activity con el timestamp UTC del momento de conexión.

### Requisito 2: Timeout de inactividad configurable por organización

**User Story:** Como administrador, quiero configurar el tiempo de inactividad permitido por organización, para ajustar la sensibilidad de detección según las necesidades de cada cliente.

#### Criterios de Aceptación

1. THE Organization SHALL incluir un campo Offline_Timeout_Minutes de tipo entero con valor por defecto de 10.
2. WHEN un administrador no configura Offline_Timeout_Minutes para una organización, THE System SHALL utilizar el valor por defecto de 10 minutos.
3. WHEN un administrador actualiza Offline_Timeout_Minutes de una organización, THE System SHALL aplicar el nuevo valor en el siguiente ciclo del loop de verificación sin requerir reinicio.
4. THE Organization SHALL validar que Offline_Timeout_Minutes sea un valor entero mayor o igual a 1.

### Requisito 3: Loop de verificación de inactividad selectivo

**User Story:** Como operador de la plataforma, quiero que el loop de ping solo contacte workstations inactivas, para reducir el tráfico de red y la carga del servidor.

#### Criterios de Aceptación

1. THE Connection_Manager SHALL ejecutar el loop de verificación cada 60 segundos (Check_Interval).
2. WHEN el loop de verificación se ejecuta, THE Connection_Manager SHALL consultar el campo Offline_Timeout_Minutes de cada organización con workstations conectadas.
3. WHEN una workstation tiene un Last_Activity anterior al momento actual menos el Offline_Timeout_Minutes de su organización, THE Connection_Manager SHALL enviar un Death Ping únicamente a esa workstation.
4. WHEN una workstation tiene un Last_Activity dentro del Offline_Timeout_Minutes de su organización, THE Connection_Manager SHALL omitir el envío de ping a esa workstation.
5. THE Connection_Manager SHALL dejar de enviar ping a todas las workstations conectadas en cada ciclo del loop.

### Requisito 4: Death Ping con timeout de pong

**User Story:** Como operador del sistema, quiero que las workstations que no responden al Death Ping se marquen como offline, para mantener el estado de conectividad preciso.

#### Criterios de Aceptación

1. WHEN el Connection_Manager envía un Death Ping a una workstation, THE Connection_Manager SHALL esperar un máximo de 30 segundos (Pong_Timeout) por la respuesta pong.
2. WHEN una workstation responde con pong dentro de los 30 segundos, THE Connection_Manager SHALL actualizar el campo Last_Activity de esa workstation y considerarla activa.
3. WHEN una workstation no responde con pong dentro de los 30 segundos, THE Connection_Manager SHALL agregar esa workstation a la cola de desconexión para el Batch_Disconnect.
4. IF el envío del Death Ping falla con una excepción, THEN THE Connection_Manager SHALL agregar esa workstation a la cola de desconexión inmediatamente.

### Requisito 5: Batch disconnect de workstations muertas

**User Story:** Como operador del sistema, quiero que las workstations muertas se actualicen en batch en la base de datos, para minimizar el número de queries y mantener la eficiencia.

#### Criterios de Aceptación

1. WHEN el loop de verificación acumula workstations sin respuesta de pong, THE Connection_Manager SHALL ejecutar una sola query UPDATE para marcar todas las workstations muertas como offline.
2. WHEN una workstation es marcada como offline, THE Connection_Manager SHALL remover su conexión WebSocket del diccionario de conexiones activas.
3. WHEN una workstation es marcada como offline, THE Connection_Manager SHALL remover su entrada de Last_Activity del registro en memoria.
4. IF la query UPDATE batch falla, THEN THE Connection_Manager SHALL hacer rollback de la transacción y registrar el error en el log.

### Requisito 6: Compatibilidad con protocolo WebSocket existente

**User Story:** Como equipo de desarrollo, quiero que la optimización sea transparente para el cliente (AlwaysPrintTray), para evitar cambios en el software de las workstations.

#### Criterios de Aceptación

1. THE Connection_Manager SHALL mantener el formato de mensaje ping existente (`{"type": "ping"}`).
2. THE Connection_Manager SHALL aceptar el formato de mensaje pong existente sin modificaciones.
3. THE System SHALL funcionar sin cambios en el código del cliente AlwaysPrintTray.
4. THE Connection_Manager SHALL mantener la funcionalidad existente de Batch_Disconnect (commit bef6b8c) sin modificaciones en su mecanismo de ejecución.

### Requisito 7: Administración del timeout por organización

**User Story:** Como administrador, quiero poder configurar el Offline_Timeout_Minutes desde la interfaz de administración, para ajustar el comportamiento sin intervención técnica directa.

#### Criterios de Aceptación

1. WHEN un administrador accede a la configuración de una organización, THE Admin_UI SHALL mostrar el campo Offline_Timeout_Minutes con su valor actual.
2. WHEN un administrador modifica el valor de Offline_Timeout_Minutes y guarda, THE API SHALL persistir el nuevo valor en la base de datos.
3. IF un administrador intenta guardar un valor de Offline_Timeout_Minutes menor a 1, THEN THE API SHALL rechazar la operación con un mensaje de error descriptivo.
4. THE API SHALL exponer Offline_Timeout_Minutes en los endpoints existentes de lectura y actualización de organizaciones.
