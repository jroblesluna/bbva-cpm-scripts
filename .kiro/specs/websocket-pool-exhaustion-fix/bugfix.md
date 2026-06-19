# Bugfix Requirements Document

## Introduction

El endpoint WebSocket `/ws/workstation` no logra aceptar más de ~60 conexiones simultáneas de workstations en el ambiente DEV. Las conexiones que exceden ese umbral quedan colgadas indefinidamente sin generar logs en el backend. La causa raíz confirmada es el agotamiento del pool de conexiones de PostgreSQL: la sesión SQLAlchemy obtenida vía `Depends(get_db)` se mantiene durante toda la fase de registro y, debido al modelo `autocommit=False`, una transacción implícita queda abierta cuando se ejecutan los `await` de I/O sobre el WebSocket (`send_json`, `receive_json`). Mientras el `await` está en vuelo, la sesión queda en estado "idle in transaction" reteniendo una conexión del pool. Con 2 workers de uvicorn × (`DB_POOL_SIZE=20` + `DB_MAX_OVERFLOW=10`) = 60 conexiones máximas, la conexión número 61 espera `pool_timeout=30s` y termina por cortar silenciosamente al cliente.

El monitoreo en vivo de `pg_stat_activity` durante una prueba de carga (200 WS concurrentes, ramp-up 0.1s) confirma el patrón: las conexiones suben hasta 60 en estado "idle in transaction" y la CPU cae a ~0%, evidenciando saturación del pool.

Este bugfix debe restaurar la capacidad demostrada por el commit de referencia `64a3a3013dc275286e6f2bd5742a4a8c24c30d86` (1500+ WS con 1 worker), garantizando que la fase de registro del WebSocket no retenga sesiones de BD durante operaciones de I/O asíncrono.

## Bug Analysis

### Current Behavior (Defect)

Comportamiento observado durante la fase de registro del endpoint `/ws/workstation` antes de entrar al loop de mensajes (línea 294, donde recién se cierra `db`):

1.1 WHEN una workstation se registra exitosamente y el endpoint ejecuta una operación SELECT (vía `RegistrationCache.get_effective_config`, `RegistrationCache.get_forced_contingency_state` o `MessageService.get_pending_deliveries_for_workstation`) después de un `db.commit()` previo THEN SQLAlchemy abre una transacción implícita sobre la sesión inyectada por `Depends(get_db)` y la sesión queda en estado "idle in transaction" en PostgreSQL durante los `await websocket.send_json(...)` y `await websocket.receive_json()` siguientes

1.2 WHEN se acumulan N registros concurrentes con N > `DB_POOL_SIZE + DB_MAX_OVERFLOW` por worker (60 sesiones totales con 2 workers en DEV) THEN el pool de conexiones de PostgreSQL queda agotado por sesiones en "idle in transaction" y la conexión (N+1)-ésima no puede adquirir sesión

1.3 WHEN la conexión (N+1)-ésima intenta adquirir una sesión del pool agotado THEN espera durante `pool_timeout=30s` sin emitir logs, termina por timeout y el cliente WebSocket cierra la conexión silenciosamente sin recibir el mensaje `registered`

1.4 WHEN el sistema queda saturado en 60 sesiones "idle in transaction" THEN la CPU del backend cae a ~0% y nuevas conexiones WebSocket entrantes no progresan más allá del handshake

### Expected Behavior (Correct)

Comportamiento esperado tras aplicar el fix:

2.1 WHEN una workstation se registra exitosamente y el endpoint ejecuta queries SELECT después de un `db.commit()` previo THEN ninguna sesión asociada al WebSocket debe permanecer en estado "idle in transaction" durante los `await` de I/O (`websocket.send_json`, `websocket.receive_json`)

2.2 WHEN se reciben N registros concurrentes con N hasta al menos 500 sobre la infraestructura actual (2 workers, `db.t3.micro` con `max_connections=81`, `DB_POOL_SIZE=20`, `DB_MAX_OVERFLOW=10`) THEN el sistema SHALL completar exitosamente todos los registros sin que el pool quede saturado por sesiones en "idle in transaction"

2.3 WHEN se ejecuta la prueba de carga `python load-test.py wss://alwaysprint.dev.iol.pe/ws/workstation 200 600` THEN el sistema SHALL aceptar al menos 200 conexiones WebSocket concurrentes sin timeouts silenciosos

2.4 WHEN se monitorea `pg_stat_activity` durante una prueba de carga sostenida THEN el conteo de sesiones en estado "idle in transaction" SHALL mantenerse cercano a 0 (puntualmente bajo, no acumulativo) durante toda la duración del test

2.5 WHEN el endpoint completa la fase de setup (registro + envío de `registered` + `config_update` + `forced_contingency` + entrega de mensajes pendientes) THEN ninguna conexión del pool de BD SHALL quedar retenida por la sesión usada durante esa fase

### Unchanged Behavior (Regression Prevention)

Comportamiento existente que debe preservarse íntegramente tras aplicar el fix:

3.1 WHEN una workstation envía un mensaje `register` válido y la organización está autorizada THEN el sistema SHALL CONTINUE TO crear/actualizar el registro de `Workstation` con los mismos datos (ip_private, public_ip, hostname, os_serial, current_user, cidr, tray_version) y enviar el mensaje `registered` con `workstation_id`

3.2 WHEN una workstation se registra exitosamente THEN el sistema SHALL CONTINUE TO enviar el mensaje `config_update` con la configuración efectiva resuelta (precedencia WorkstationConfig > VLANConfig > GlobalConfig) y el mismo `config_hash` SHA256

3.3 WHEN una workstation se registra exitosamente THEN el sistema SHALL CONTINUE TO enviar el mensaje `forced_contingency` con el estado de contingencia forzada resuelto (prioridad organización > VLAN > workstation), incluyendo `enabled`, `source`, `source_name` y `printer_ip`

3.4 WHEN una workstation se registra y existen deliveries pendientes en BD THEN el sistema SHALL CONTINUE TO enviar todos los mensajes `message` pendientes y marcarlos como entregados vía `MessageService.mark_delivery_as_sent`

3.5 WHEN la IP pública del cliente no está autorizada THEN el sistema SHALL CONTINUE TO cerrar el WebSocket con código 1008 y razón "IP {client_host} no autorizada"

3.6 WHEN la organización está desactivada THEN el sistema SHALL CONTINUE TO cerrar el WebSocket con código 1008 y razón "Organizacion desactivada"

3.7 WHEN el primer mensaje recibido no es de tipo `register` THEN el sistema SHALL CONTINUE TO cerrar el WebSocket con código 1008 y razón "First message must be register"

3.8 WHEN el mensaje `register` no pasa la validación Pydantic (`RegisterMessage`) THEN el sistema SHALL CONTINUE TO cerrar el WebSocket con código 1008 y razón "Registro inválido: ..."

3.9 WHEN el endpoint completa el setup THEN el sistema SHALL CONTINUE TO entrar en el loop `while True: await websocket.receive_json()` con creación on-demand de `SessionLocal()` por mensaje recibido (comportamiento ya existente desde línea 294)

3.10 WHEN se procesan mensajes en el loop principal (`pong`, `status_update`, `config_change_report`, `command_result`, `telemetry`, `connectivity_result`) THEN el sistema SHALL CONTINUE TO comportarse exactamente igual: misma validación, misma persistencia, mismos broadcasts a operadores y mismo manejo de re-registro automático

3.11 WHEN el WebSocket se desconecta (limpia o por excepción) THEN el sistema SHALL CONTINUE TO invocar `connection_manager.disconnect_workstation` con la sesión apropiada y marcar la workstation como offline vía el batch de desconexión

3.12 WHEN `RegistrationCache` no puede resolver la configuración efectiva (cache miss + Redis no disponible o error) THEN el sistema SHALL CONTINUE TO hacer fallback a `ConfigService.get_effective_config(db, workstation_id)` con el mismo resultado funcional

3.13 WHEN `connection_manager.connect_workstation` se invoca durante el registro THEN el sistema SHALL CONTINUE TO actualizar el estado `is_online=True` de la workstation en BD y disparar las operaciones fire-and-forget de Redis (WorkerRegistry SADD, lazy subscribe a `org:{id}`)

3.14 WHEN una workstation envía mensajes en el loop principal después del setup THEN el sistema SHALL CONTINUE TO usar sesiones de BD de corta vida creadas con `SessionLocal()` y cerradas tras procesar cada mensaje (patrón ya existente)
