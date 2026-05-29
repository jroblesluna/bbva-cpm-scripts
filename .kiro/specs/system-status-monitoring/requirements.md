# Requirements Document

## Introduction

Sistema de monitoreo automatizado del estado de la infraestructura Cloud de AlwaysPrint. Ejecuta validaciones periódicas (cada 6 horas) equivalentes al script `check-status.sh` pero directamente desde el backend (sin SSM), almacena métricas históricas en PostgreSQL para análisis de evolución, y presenta dashboards gráficos con reportes de 30 días para evaluar necesidades de upgrade o identificar picos. Acceso restringido exclusivamente al rol Administrador.

## Glossary

- **System_Status_Collector**: Servicio backend que recolecta métricas del sistema directamente desde la instancia EC2 donde corre el backend (memoria, disco, CPU, swap, Docker stats, endpoints)
- **Status_Snapshot**: Registro completo de una ejecución de recolección de métricas en un momento dado
- **Status_Scheduler**: Componente que programa la ejecución automática del System_Status_Collector cada 6 horas (0:00, 6:00, 12:00, 18:00)
- **Status_Dashboard**: Interfaz gráfica en el frontend que visualiza métricas actuales e históricas con gráficos de evolución
- **Metric_Record**: Registro individual de una métrica específica (CPU, memoria, disco, etc.) dentro de un Status_Snapshot
- **Admin_User**: Usuario autenticado con rol `admin` en el sistema
- **Health_Check**: Validación de disponibilidad de un servicio (backend, frontend, Redis, Nginx, RDS)
- **Threshold_Alert**: Indicador visual que señala cuando una métrica supera un umbral predefinido

## Requirements

### Requirement 1: Recolección directa de métricas del sistema

**User Story:** Como administrador, quiero que el backend recolecte métricas del sistema directamente desde la instancia EC2 donde corre, para evitar la dependencia de SSM y obtener datos más eficientemente.

#### Acceptance Criteria

1. THE System_Status_Collector SHALL recolectar uso de memoria RAM (total, usada, disponible en MB, y porcentaje con 1 decimal de precisión) leyendo directamente de `/proc/meminfo` o equivalente del sistema operativo
2. THE System_Status_Collector SHALL recolectar uso de disco (total, usado, disponible en MB, y porcentaje con 1 decimal de precisión) del filesystem raíz (`/`)
3. THE System_Status_Collector SHALL recolectar uso de CPU (porcentaje promedio en el último minuto, con 1 decimal de precisión)
4. THE System_Status_Collector SHALL recolectar estado de swap (total, usado, disponible en MB)
5. THE System_Status_Collector SHALL recolectar estadísticas de Docker por contenedor (CPU%, memoria usada en MB, memoria límite en MB, network I/O en bytes) ejecutando comandos Docker directamente, con un timeout máximo de 10 segundos por comando
6. THE System_Status_Collector SHALL recolectar el uptime del sistema operativo expresado en segundos
7. THE System_Status_Collector SHALL recolectar el estado de cada contenedor Docker (running, stopped, restarting) y su tiempo de actividad en segundos
8. IF el daemon de Docker no está disponible o no responde dentro del timeout, THEN THE System_Status_Collector SHALL retornar las métricas del sistema operativo (RAM, disco, CPU, swap, uptime) e indicar que las métricas de Docker no están disponibles, sin interrumpir el ciclo de recolección
9. IF la lectura de cualquier métrica individual del sistema operativo falla, THEN THE System_Status_Collector SHALL registrar el error en el log y continuar recolectando las métricas restantes, reportando la métrica fallida como no disponible

### Requirement 2: Validación de servicios y endpoints

**User Story:** Como administrador, quiero que se valide la disponibilidad de todos los servicios críticos, para detectar problemas antes de que afecten a los usuarios.

#### Acceptance Criteria

1. WHEN el System_Status_Collector ejecuta la verificación de estado, THE System_Status_Collector SHALL realizar una petición HTTP GET al endpoint `/api/v1/health` del backend (puerto 8000 local) y registrar el servicio como disponible si la respuesta contiene el indicador "healthy", o como no disponible en caso contrario
2. WHEN el System_Status_Collector ejecuta la verificación de estado, THE System_Status_Collector SHALL realizar una petición HTTP GET al frontend (puerto 3000 local) y registrar el servicio como disponible si el código de respuesta HTTP es 200, 302 o 307, o como no disponible para cualquier otro código o ausencia de respuesta
3. WHEN el System_Status_Collector ejecuta la verificación de estado, THE System_Status_Collector SHALL consultar el estado del servicio Nginx mediante el sistema de gestión de servicios del sistema operativo y registrar el servicio como disponible si el estado es "active", o como no disponible en caso contrario
4. WHEN el System_Status_Collector ejecuta la verificación de estado, THE System_Status_Collector SHALL verificar que el contenedor de Redis se encuentra en estado "running" y registrar el servicio como disponible si lo está, o como no disponible en caso contrario
5. WHEN el System_Status_Collector ejecuta la verificación de estado, THE System_Status_Collector SHALL verificar la conectividad con la base de datos PostgreSQL (RDS) consultando su estado de instancia y registrar el servicio como disponible si el estado es "available", o como no disponible en caso contrario
6. WHEN el System_Status_Collector ejecuta la verificación de estado, THE System_Status_Collector SHALL verificar la validez del certificado SSL, calcular los días restantes hasta su expiración, y clasificar el resultado como: válido (más de 14 días restantes), advertencia (entre 1 y 14 días restantes), o expirado (0 o menos días restantes)
7. IF un servicio no responde dentro de 10 segundos, THEN THE System_Status_Collector SHALL registrar el servicio como no disponible con el mensaje de error correspondiente y continuar con la verificación de los servicios restantes
8. WHEN la verificación de todos los servicios finaliza, THE System_Status_Collector SHALL presentar un resumen con el conteo total de servicios verificados correctamente, servicios con advertencia y servicios fallidos

### Requirement 3: Ejecución programada cada 6 horas

**User Story:** Como administrador, quiero que la recolección de métricas se ejecute automáticamente 4 veces al día, para tener datos consistentes sin intervención manual.

#### Acceptance Criteria

1. THE Status_Scheduler SHALL ejecutar el System_Status_Collector a las 0:00, 6:00, 12:00 y 18:00 horas UTC cada día
2. WHEN el backend arranca, THE Status_Scheduler SHALL iniciar automáticamente y programar las ejecuciones pendientes sin intervención del administrador
3. IF una ejecución programada no completa dentro de 10 minutos o el System_Status_Collector retorna un error, THEN THE Status_Scheduler SHALL registrar el error en los logs indicando la causa de la falla y reintentar una única vez después de 5 minutos
4. IF el reintento de una ejecución fallida también falla, THEN THE Status_Scheduler SHALL registrar el error en los logs y no realizar más reintentos hasta la siguiente ejecución programada
5. THE Status_Scheduler SHALL permitir al Admin_User ejecutar una recolección manual bajo demanda a través de la API, con un tiempo máximo de ejecución de 10 minutos
6. WHILE una recolección está en progreso, IF se recibe una nueva solicitud de ejecución (programada o manual), THEN THE Status_Scheduler SHALL descartar la nueva solicitud y retornar una indicación de que ya existe una ejecución en curso

### Requirement 4: Almacenamiento persistente de métricas

**User Story:** Como administrador, quiero que las métricas se almacenen en base de datos, para poder analizar la evolución del sistema a lo largo del tiempo.

#### Acceptance Criteria

1. WHEN el System_Status_Collector genera un Status_Snapshot, THE System_Status_Collector SHALL almacenarlo en PostgreSQL incluyendo timestamp (UTC, precisión de segundos), estado general (uno de: healthy, degraded, critical) y todas las métricas recolectadas en esa ejecución
2. WHEN el System_Status_Collector almacena un Status_Snapshot, THE System_Status_Collector SHALL almacenar cada métrica individual como un Metric_Record asociado al Status_Snapshot correspondiente, incluyendo nombre de la métrica, valor numérico, unidad de medida y timestamp de recolección
3. THE System_Status_Collector SHALL retener datos de los últimos 90 días en la base de datos
4. WHEN un Status_Snapshot tiene más de 90 días, THE System_Status_Collector SHALL eliminar automáticamente el registro y sus Metric_Records asociados durante la siguiente ejecución programada
5. WHEN el System_Status_Collector almacena un Status_Snapshot, THE System_Status_Collector SHALL almacenar el resultado de cada Health_Check (nombre del servicio, estado, latencia en milisegundos, mensaje de error si aplica) asociado al Status_Snapshot
6. IF PostgreSQL no está disponible o la operación de escritura falla, THEN THE System_Status_Collector SHALL reintentar la escritura hasta 3 veces con un intervalo de 5 segundos entre intentos, y si todos los reintentos fallan, registrar el fallo en el log local y continuar con la siguiente ejecución programada sin perder el snapshot en memoria hasta el próximo ciclo
7. IF una escritura de Status_Snapshot falla después de insertar registros parciales, THEN THE System_Status_Collector SHALL revertir la transacción completa para evitar snapshots incompletos en la base de datos

### Requirement 5: Control de acceso exclusivo para administradores

**User Story:** Como administrador, quiero que solo los usuarios con rol admin puedan acceder a la sección de System Status, para proteger información sensible de la infraestructura.

#### Acceptance Criteria

1. THE System_Status_Collector SHALL exponer todos los endpoints API de System Status protegidos mediante la dependencia `require_admin`, que valida autenticación JWT y verifica rol admin
2. IF un usuario autenticado sin rol admin intenta acceder a cualquier endpoint de System Status, THEN THE System_Status_Collector SHALL retornar HTTP 403 Forbidden sin incluir datos de métricas en la respuesta
3. IF una petición a los endpoints de System Status no incluye token JWT o el token es inválido o está expirado, THEN THE System_Status_Collector SHALL retornar HTTP 401 Unauthorized
4. IF el usuario autenticado tiene rol admin, THEN THE Status_Dashboard SHALL mostrar la sección de System Status en la interfaz y en el menú de navegación
5. IF el usuario autenticado no tiene rol admin, THEN THE Status_Dashboard SHALL ocultar la sección de System Status y su enlace de navegación, sin revelar la existencia de la ruta
6. IF un usuario sin rol admin accede directamente a la URL de System Status en el navegador, THEN THE Status_Dashboard SHALL redirigir al usuario a la página principal del dashboard

### Requirement 6: Dashboard gráfico de estado actual

**User Story:** Como administrador, quiero ver el estado actual del sistema de forma gráfica e intuitiva, para evaluar rápidamente la salud de la infraestructura.

#### Acceptance Criteria

1. THE Status_Dashboard SHALL mostrar un resumen del último Status_Snapshot con indicadores visuales de estado (verde/amarillo/rojo) para cada categoría de métrica (memoria, disco, CPU, swap, Docker, servicios), donde el color se determina según los umbrales definidos en el Requirement 8
2. THE Status_Dashboard SHALL mostrar gauges de porcentaje (rango 0% a 100%) para memoria, disco y CPU, representando los valores del último Status_Snapshot
3. THE Status_Dashboard SHALL mostrar el estado de cada contenedor Docker incluyendo: nombre del contenedor, estado (running/stopped/restarting), porcentaje de CPU, memoria usada en MB y tiempo de actividad
4. THE Status_Dashboard SHALL mostrar el estado de cada Health_Check incluyendo: nombre del servicio, indicador de disponibilidad (disponible/no disponible) y latencia de respuesta en milisegundos
5. THE Status_Dashboard SHALL mostrar la fecha y hora de la última recolección exitosa formateada en la zona horaria del usuario
6. WHEN el Admin_User presiona el botón de recolección manual, THE Status_Dashboard SHALL deshabilitar el botón, mostrar un indicador de progreso, y actualizar los datos mostrados al completarse la recolección
7. IF el Admin_User dispara una recolección manual y la operación falla o no responde dentro de 30 segundos, THEN THE Status_Dashboard SHALL rehabilitar el botón y mostrar un mensaje de error indicando que la recolección no pudo completarse
8. IF no existe ningún Status_Snapshot almacenado, THEN THE Status_Dashboard SHALL mostrar un estado vacío indicando que no hay datos disponibles y ofrecer el botón de recolección manual como acción principal

### Requirement 7: Reportes históricos de 30 días

**User Story:** Como administrador, quiero ver gráficos de evolución de los últimos 30 días, para analizar tendencias y determinar si se requiere un upgrade de infraestructura.

#### Acceptance Criteria

1. THE Status_Dashboard SHALL mostrar gráficos de línea temporal para memoria, disco, CPU y swap con datos de los últimos 30 días, con una resolución mínima de 1 punto de datos por hora y eje Y de 0% a 100%
2. WHEN el Admin_User selecciona un rango de tiempo (7 días, 14 días o 30 días), THE Status_Dashboard SHALL actualizar todos los gráficos y estadísticas para mostrar únicamente los datos del período seleccionado en un máximo de 5 segundos
3. THE Status_Dashboard SHALL resaltar visualmente con un marcador diferenciado cada punto de datos que supere los umbrales predefinidos (memoria mayor a 80%, disco mayor a 85%, CPU mayor a 90%, swap mayor a 80%)
4. THE Status_Dashboard SHALL mostrar estadísticas agregadas del período seleccionado (promedio, máximo y mínimo) para cada métrica: memoria, disco, CPU y swap
5. THE Status_Dashboard SHALL mostrar un historial de disponibilidad (uptime percentage con precisión de 2 decimales) para cada servicio monitoreado durante el período seleccionado
6. IF los datos históricos del período seleccionado están incompletos o no disponibles, THEN THE Status_Dashboard SHALL indicar visualmente los intervalos sin datos en el gráfico y mostrar el porcentaje de cobertura de datos disponible para ese período

### Requirement 8: Umbrales y alertas visuales

**User Story:** Como administrador, quiero que el dashboard me alerte visualmente cuando las métricas superen umbrales críticos, para tomar acción preventiva.

#### Acceptance Criteria

1. IF la memoria usada del último Status_Snapshot supera el 80% del total, THEN THE Status_Dashboard SHALL mostrar una Threshold_Alert que indique el nombre de la métrica, el valor actual y el umbral superado
2. IF el disco usado del último Status_Snapshot supera el 85% del total, THEN THE Status_Dashboard SHALL mostrar una Threshold_Alert que indique el nombre de la métrica, el valor actual y el umbral superado
3. IF el CPU promedio del último Status_Snapshot supera el 90%, THEN THE Status_Dashboard SHALL mostrar una Threshold_Alert que indique el nombre de la métrica, el valor actual y el umbral superado
4. IF el certificado SSL del último Status_Snapshot tiene menos de 14 días para expirar, THEN THE Status_Dashboard SHALL mostrar una Threshold_Alert que indique los días restantes hasta la expiración
5. IF un contenedor Docker del último Status_Snapshot no está en estado running, THEN THE Status_Dashboard SHALL mostrar una Threshold_Alert que indique el nombre del contenedor y su estado actual
6. WHEN el estado general del último Status_Snapshot sea critical, THE Status_Dashboard SHALL mostrar un banner fijo en la parte superior del dashboard, visualmente diferenciado del contenido normal mediante color de fondo y un icono de alerta, indicando el estado critical y el número de métricas que superan sus umbrales
7. WHEN las métricas del último Status_Snapshot vuelven a estar dentro de los umbrales definidos, THE Status_Dashboard SHALL dejar de mostrar las Threshold_Alerts correspondientes sin requerir acción manual del Admin_User
8. THE Status_Dashboard SHALL mostrar todas las Threshold_Alerts activas agrupadas en una sección dedicada visible sin necesidad de scroll, mostrando un máximo de 10 alertas simultáneas con indicación del total si hay más
