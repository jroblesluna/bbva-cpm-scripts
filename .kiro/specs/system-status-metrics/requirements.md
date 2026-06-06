# Requirements Document

## Introduction

Métricas avanzadas de System Status orientadas a escalar el sistema AlwaysPrint Cloud a 5000 workstations concurrentes. El sistema actual ya recolecta métricas básicas del host (CPU, RAM, disco, Docker) mediante el `status_scheduler`. Este feature agrega 5 métricas nuevas enfocadas en los cuellos de botella específicos de escalabilidad: conexiones WebSocket, memoria del proceso Python, file descriptors, tráfico de red y estado del pool de base de datos.

## Glossary

- **Metrics_Endpoint**: Endpoint HTTP `GET /api/v1/system/metrics` que retorna las métricas de escalabilidad en tiempo real
- **Status_Scheduler**: Componente existente (`app/services/status_scheduler.py`) que recolecta métricas del host cada 6 horas
- **Connection_Manager**: Componente existente (`app/services/websocket_manager.py`) que gestiona conexiones WebSocket activas
- **Metrics_Card**: Componente visual en la página System Status del frontend que muestra las métricas de escalabilidad con indicadores de color
- **Pool_BD**: Pool de conexiones SQLAlchemy hacia PostgreSQL/RDS
- **Heap_Python**: Memoria del heap del proceso Python dentro del contenedor Docker, medida vía `tracemalloc` o lectura de `/proc/self/status`
- **File_Descriptors**: Descriptores de archivo abiertos por el proceso Python, leídos de `/proc/PID/fd`
- **Threshold**: Umbral configurable que determina el color del indicador visual (verde/amarillo/rojo)

## Requirements

### Requirement 1: Endpoint de métricas de escalabilidad

**User Story:** Como administrador del sistema, quiero consultar las métricas de escalabilidad del backend en un solo endpoint, para poder evaluar la capacidad del sistema de soportar 5000 workstations concurrentes.

#### Acceptance Criteria

1. WHEN un administrador autenticado realiza una petición GET a `/api/v1/system/metrics`, THE Metrics_Endpoint SHALL retornar HTTP 200 con un objeto JSON que contenga las 5 métricas de escalabilidad: conexiones WebSocket, memoria Python, file descriptors, tráfico de red y estado del Pool_BD, cada una como un objeto anidado con sus campos específicos definidos en los Requirements 2 a 6
2. WHEN un usuario presenta un token JWT inválido, expirado, o no presenta token, THE Metrics_Endpoint SHALL retornar HTTP 401 Unauthorized
3. WHEN un usuario autenticado con rol distinto a admin realiza una petición GET a `/api/v1/system/metrics`, THE Metrics_Endpoint SHALL retornar HTTP 403 Forbidden
4. WHILE el sistema opera con menos de 3000 conexiones WebSocket activas y uso de Pool_BD inferior al 60%, THE Metrics_Endpoint SHALL responder en menos de 2000ms
5. IF el Metrics_Endpoint no puede obtener alguna métrica individual (por error de lectura del sistema de archivos, timeout de consulta a base de datos, o excepción interna), THEN THE Metrics_Endpoint SHALL retornar el valor `null` para esa métrica específica y continuar retornando las demás métricas disponibles con HTTP 200

### Requirement 2: Métrica de conexiones WebSocket activas

**User Story:** Como administrador, quiero ver el número de conexiones WebSocket activas, para poder monitorear la carga de conexiones concurrentes y anticipar saturación.

#### Acceptance Criteria

1. THE Metrics_Endpoint SHALL incluir el conteo de conexiones WebSocket de workstations activas como un valor entero en el rango de 0 a 10,000, obtenido del método get_connection_count() del Connection_Manager
2. THE Metrics_Endpoint SHALL incluir el conteo de conexiones WebSocket de operadores activas como un valor entero en el rango de 0 a 1,000, representando el número de operadores únicos conectados (independientemente de cuántas pestañas tenga cada uno), obtenido del Connection_Manager
3. THE Metrics_Endpoint SHALL incluir el total combinado de conexiones WebSocket calculado como la suma aritmética del conteo de workstations más el conteo de operadores únicos
4. IF el Connection_Manager no está disponible o produce un error al consultar los conteos, THEN THE Metrics_Endpoint SHALL retornar el valor 0 para cada uno de los tres campos de conexiones WebSocket e incluir una indicación de que los datos no pudieron ser obtenidos

### Requirement 3: Métrica de memoria del proceso Python

**User Story:** Como administrador, quiero ver el consumo de memoria del heap Python separado de la memoria total del contenedor Docker, para poder identificar memory leaks y calcular el overhead por workstation conectada.

#### Acceptance Criteria

1. THE Metrics_Endpoint SHALL incluir el uso de memoria RSS del proceso Python en megabytes (redondeado a 2 decimales), obtenido leyendo el campo VmRSS de `/proc/self/status` y convirtiendo de kB a MB (dividiendo entre 1024)
2. THE Metrics_Endpoint SHALL incluir la memoria total del contenedor Docker en megabytes (redondeado a 2 decimales), obtenida del sistema de métricas existente del Status_Scheduler
3. WHEN hay al menos una conexión WebSocket de workstation activa, THE Metrics_Endpoint SHALL calcular y retornar el promedio de memoria Python por workstation conectada (heap_python_mb / ws_count, redondeado a 2 decimales), donde ws_count es exclusivamente el conteo de conexiones WebSocket de workstations (excluyendo operadores)
4. WHEN no hay conexiones WebSocket de workstation activas, THE Metrics_Endpoint SHALL retornar 0 para el promedio de memoria por workstation
5. IF la lectura de `/proc/self/status` falla o el campo VmRSS no está presente, THEN THE Metrics_Endpoint SHALL retornar `null` para la métrica de memoria RSS del proceso Python y `null` para el promedio por workstation

### Requirement 4: Métrica de file descriptors

**User Story:** Como administrador, quiero ver el número de file descriptors en uso por el proceso Python versus el límite del sistema, para poder detectar fugas de descriptores antes de que provoquen errores de conexión.

#### Acceptance Criteria

1. THE Metrics_Endpoint SHALL incluir el conteo de file descriptors abiertos por el proceso Python, obtenido contando las entradas en `/proc/self/fd`, representado como un entero mayor o igual a 0
2. THE Metrics_Endpoint SHALL incluir el límite máximo de file descriptors permitido, obtenido del soft limit de `resource.getrlimit(resource.RLIMIT_NOFILE)`, representado como un entero positivo
3. THE Metrics_Endpoint SHALL incluir el porcentaje de uso de file descriptors calculado como (fd_count / fd_limit * 100) redondeado a 1 decimal
4. IF el valor de fd_limit no está disponible o es cero, THEN THE Metrics_Endpoint SHALL retornar `null` para el porcentaje de uso de file descriptors

### Requirement 5: Métrica de tráfico de red

**User Story:** Como administrador, quiero ver el tráfico de red del contenedor y su tasa de transferencia, para poder identificar saturación de ancho de banda con muchas workstations conectadas.

#### Acceptance Criteria

1. THE Metrics_Endpoint SHALL incluir los bytes totales recibidos (rx) y transmitidos (tx) como enteros, leídos de `/proc/net/dev` para la interfaz de red principal no-loopback del contenedor (típicamente eth0); si existen múltiples interfaces no-loopback, THE Metrics_Endpoint SHALL sumar los contadores de todas ellas
2. THE Metrics_Endpoint SHALL calcular y retornar la tasa de transferencia en bytes por segundo (rx_rate_bps, tx_rate_bps) comparando la lectura actual con la medición anterior almacenada en memoria; si el tiempo transcurrido desde la medición anterior es menor a 500ms, THE Metrics_Endpoint SHALL retornar las tasas calculadas en la invocación previa sin recalcular
3. WHEN no existe una medición anterior disponible (primera invocación tras reinicio), THE Metrics_Endpoint SHALL retornar `null` para las tasas de transferencia y almacenar la medición actual como referencia
4. IF los bytes totales actuales son menores que los de la medición anterior (indicando un reinicio de contadores), THEN THE Metrics_Endpoint SHALL descartar la medición anterior, almacenar la medición actual como nueva referencia y retornar `null` para las tasas de transferencia

### Requirement 6: Métrica del pool de base de datos

**User Story:** Como administrador, quiero ver el estado del pool de conexiones SQLAlchemy y las conexiones activas en PostgreSQL, para poder detectar agotamiento del pool antes de que cause timeouts.

#### Acceptance Criteria

1. THE Metrics_Endpoint SHALL incluir el estado del pool SQLAlchemy: conexiones checked_out (en uso), conexiones idle (disponibles), tamaño base del pool (pool_size), y conexiones de overflow actuales junto con el máximo de overflow permitido (max_overflow)
2. THE Metrics_Endpoint SHALL incluir el conteo de conexiones en PostgreSQL obtenido mediante una consulta a `pg_stat_activity` filtrada por el usuario de la aplicación, contando conexiones en cualquier estado distinto de 'idle' (es decir, state IN ('active', 'idle in transaction', 'idle in transaction (aborted)', 'fastpath function call'))
3. THE Metrics_Endpoint SHALL incluir el porcentaje de uso del pool calculado como (checked_out / pool_size * 100), redondeado a un decimal
4. IF la consulta a `pg_stat_activity` falla por timeout o error de permisos, THEN THE Metrics_Endpoint SHALL retornar `null` para el conteo de conexiones PostgreSQL y continuar retornando las métricas del pool SQLAlchemy disponibles localmente

### Requirement 7: Integración con el flujo de recolección existente

**User Story:** Como desarrollador, quiero que las nuevas métricas se integren al flujo del `status_scheduler` existente, para que se persistan en los snapshots periódicos y estén disponibles en el historial.

#### Acceptance Criteria

1. WHEN el Status_Scheduler ejecuta una recolección programada o manual, THE Status_Scheduler SHALL recolectar las 5 métricas de escalabilidad (conexiones WebSocket, memoria Python, file descriptors, tráfico de red, estado del Pool_BD) dentro del método `collect_all`, en el mismo ciclo que las métricas existentes de sistema operativo, Docker y health checks
2. THE Status_Scheduler SHALL persistir las métricas de escalabilidad como parte del mismo snapshot de estado del sistema, dentro de la misma transacción atómica utilizada para las métricas existentes
3. IF la recolección de una métrica de escalabilidad individual falla, THEN THE Status_Scheduler SHALL registrar el error en el log indicando el nombre de la métrica fallida, persistir el valor `null` para esa métrica en el snapshot, y continuar con la recolección de las demás métricas sin interrumpir el proceso
4. WHEN el Status_Scheduler persiste un snapshot que contiene métricas de escalabilidad con valor `null` por fallo de recolección, THE Status_Scheduler SHALL completar la persistencia del snapshot sin considerar los valores `null` como error de transacción

### Requirement 8: Visualización en la página System Status

**User Story:** Como administrador, quiero ver las métricas de escalabilidad en una nueva sección/card dentro de la página System Status, para poder monitorear visualmente el estado del sistema orientado a la capacidad de escalar.

#### Acceptance Criteria

1. THE Metrics_Card SHALL mostrar las 5 métricas de escalabilidad en una card dedicada dentro de la página System Status, presentando para cada métrica su label descriptivo, el valor numérico actual con su unidad, y un indicador visual de color según su Threshold
2. THE Metrics_Card SHALL mostrar indicadores de color basados en Thresholds: verde (normal), amarillo (warning), rojo (crítico) para cada métrica, aplicados como color de fondo o borde del indicador visual junto al valor
3. THE Metrics_Card SHALL utilizar textos dinámicos mediante `next-intl` para todos los labels, unidades, estados y valores mostrados al usuario, sin strings hardcodeados en el JSX
4. WHEN el Metrics_Endpoint retorna `null` para una métrica individual, THE Metrics_Card SHALL mostrar un texto localizado de "no disponible" (obtenido de `next-intl`) en lugar del valor numérico, y ocultar el indicador de color para esa métrica
5. IF la llamada al Metrics_Endpoint falla con error de red o HTTP 5xx, THEN THE Metrics_Card SHALL mostrar un estado de error dentro de la card con un mensaje localizado indicando que no se pudieron cargar las métricas
6. WHILE la llamada al Metrics_Endpoint está en curso, THE Metrics_Card SHALL mostrar un indicador de carga (spinner) dentro de la card hasta que los datos estén disponibles o se produzca un error

### Requirement 9: Definición de umbrales para indicadores

**User Story:** Como administrador, quiero que los umbrales de color reflejen los límites operativos reales del sistema escalando a 5000 workstations, para poder actuar proactivamente ante degradación.

#### Acceptance Criteria

1. THE Metrics_Card SHALL aplicar los siguientes Thresholds para el total combinado de conexiones WebSocket (workstations + operadores): verde (0–3000), amarillo (3001–4500), rojo (>4500)
2. THE Metrics_Card SHALL aplicar los siguientes Thresholds para memoria Python por workstation: verde (0–2 MB/ws), amarillo (2.1–4 MB/ws), rojo (>4 MB/ws)
3. THE Metrics_Card SHALL aplicar los siguientes Thresholds para file descriptors: verde (0–60%), amarillo (61–80%), rojo (>80%)
4. THE Metrics_Card SHALL aplicar los siguientes Thresholds para uso del pool de BD: verde (0–60%), amarillo (61–80%), rojo (>80%)
5. THE Metrics_Card SHALL aplicar los siguientes Thresholds para tráfico de red tx_rate: verde (0–49.99 MB/s), amarillo (50–80 MB/s), rojo (>80 MB/s)
6. THE Metrics_Card SHALL evaluar cada valor de métrica utilizando comparación con límite superior inclusivo para el rango inferior (≤) y exclusivo para el rango superior (>), de modo que un valor en el límite exacto entre dos zonas pertenezca siempre a la zona inferior
7. IF el Metrics_Endpoint retorna `null` para una métrica, THEN THE Metrics_Card SHALL no aplicar ningún color de Threshold y mostrar el indicador de "no disponible" definido en Requirement 8
