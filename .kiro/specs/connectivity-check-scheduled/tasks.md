# Tareas de Implementación — Connectivity Check Scheduled

## Task 1: Definir mensajes IPC y modelo de datos
- [x] Agregar `ConnectivityCheck` a `MessageType.cs`
- [x] Crear `ConnectivityCheckPayload` en `Payloads.cs` con campos: urls, timeout_seconds, max_retries, retry_delay_seconds, notification_green_timeout_seconds, notification_yellow_timeout_seconds
- [x] Crear clase `UrlCheckResult` en `AlwaysPrintTray/Connectivity/UrlCheckResult.cs` con: Url, Success, LatencyMs, StatusCode, Attempts, Error
- [x] Agregar `ActionTypes.ConnectivityCheck = "ConnectivityCheck"` en `ActionConfig.cs`

## Task 2: Implementar ExecuteConnectivityCheck en ActionEngine
- [x] Agregar case `ActionTypes.ConnectivityCheck` en el switch de `ExecuteAction()`
- [x] Implementar `ExecuteConnectivityCheck(ActionConfig action)`:
  - Extraer parámetros del JSON (urls, timeout, retries, delays, notification timeouts)
  - Construir `ConnectivityCheckPayload`
  - Enviar vía `PipeServer.SendToClient()` con tipo `MessageType.ConnectivityCheck`
  - Si pipe no conectado → loguear warning, retornar true
  - Retornar true siempre (fire-and-forget)
- [x] El ActionEngine necesita acceso al PipeServer — pasar referencia vía constructor o callback (evaluar approach menos invasivo)

## Task 3: Implementar ConnectivityCheckHandler en el Tray
- [x] Crear `AlwaysPrintTray/Connectivity/ConnectivityCheckHandler.cs`
- [x] Implementar `ExecuteCheckAsync(ConnectivityCheckPayload payload)`:
  - Flag `_checkInProgress` (volatile bool) para evitar ejecuciones superpuestas
  - Detectar proxy del sistema con `ProxyHelper.GetSystemProxyUri()`
  - Verificar proxy activo con TCP connect (timeout 2s)
  - Crear HttpClient con `ProxyHelper.CreateHandler()` y timeout del payload
  - Ejecutar checks secuencialmente con `CheckUrlWithRetriesAsync()`
  - Calcular porcentaje de éxito
  - Escribir resultados en log
  - Invocar NotificationForm en UI thread
- [x] Implementar `CheckUrlWithRetriesAsync(HttpClient, url, payload)`:
  - Loop de 1 + max_retries intentos
  - HTTP HEAD con fallback a GET si HEAD retorna 405
  - Delay entre reintentos (retry_delay_seconds)
  - Capturar TimeoutException, HttpRequestException
  - Considerar códigos 2xx, 301, 302, 403 como "accesible"
  - Retornar UrlCheckResult
- [x] Implementar `TestTcpConnectAsync(host, port, timeoutMs)` para verificar proxy activo

## Task 4: Registrar handler en TrayApplicationContext
- [x] En `OnPipeMessageReceived`, agregar case `MessageType.ConnectivityCheck`:
  - Deserializar `ConnectivityCheckPayload`
  - Lanzar `_connectivityHandler.ExecuteCheckAsync(payload)` en `Task.Run` (no bloquear pipe)
- [x] Instanciar `ConnectivityCheckHandler` en el constructor de `TrayApplicationContext` (pasando `SynchronizationContext` para UI thread y logger)

## Task 5: Implementar ConnectivityNotificationForm
- [x] Crear `AlwaysPrintTray/Forms/ConnectivityNotificationForm.cs` (WinForms)
- [x] Diseño visual:
  - Form sin bordes, TopMost, posición esquina inferior derecha
  - Panel de color según severidad (verde #E8F5E9, amarillo #FFF3E0, rojo #FFEBEE)
  - Icono según severidad (checkmark verde, warning naranja, impresora roja)
  - Label con texto del resultado
  - Botón "Ver Reporte" (abre ConnectivityReportForm)
  - Botón "OK"/"Entendido" (cierra)
- [x] Lógica singleton:
  - Propiedad estática `Current` — si existe form previo, cerrarlo antes de mostrar nuevo
  - Método estático `ShowResult(results, percent, payload)` que gestiona el singleton
- [x] Timer de auto-cierre:
  - Verde: `notification_green_timeout_seconds` (default 5s)
  - Amarillo: `notification_yellow_timeout_seconds` (default 10s)
  - Rojo: sin auto-cierre (solo acknowledge manual)
- [x] Animación fade-in (opacity de 0 a 1 en 300ms)

## Task 6: Implementar ConnectivityReportForm
- [x] Crear `AlwaysPrintTray/Forms/ConnectivityReportForm.cs` (WinForms)
- [x] DataGridView o ListView con columnas: URL, Estado (✓/✗), Latencia, Intentos, Error
- [x] Header con info resumen: proxy detectado, estado, total URLs, exitosas, fallidas
- [x] Botón "Cerrar"
- [x] Se abre como modal desde el NotificationForm

## Task 7: Logging de resultados
- [x] En `ConnectivityCheckHandler`, después de completar todos los checks:
  - Log resumen: `ConnectivityCheck: completado. OK={n}/{total} ({percent}%). Proxy={uri} ({activo/inactivo}). Duración={ms}ms`
  - Log por cada URL fallida: `ConnectivityCheck: FALLO {url} — {error} ({attempts} intentos, latencia={ms}ms)`
  - Usar Event ID 1090 para éxito/resumen, 1091 para fallos individuales
- [x] En `ActionEngine.ExecuteConnectivityCheck`: log al enviar comando: `ConnectivityCheck: comando enviado al Tray ({n} URLs, timeout={t}s, retries={r})`

## Task 8: Actualizar CPM_Compliant.alwaysconfig
- [x] Agregar trigger `OnScheduledTask` con acción `ConnectivityCheck`:
  - `interval_seconds`: 300
  - `run_immediately`: false (primera ejecución diferida al primer intervalo)
  - `urls`: lista de 16 URLs (con `{{%SERVER_URL%}}` como primera)
  - `timeout_seconds`: 5
  - `max_retries`: 2
  - `retry_delay_seconds`: 30
  - `notification_green_timeout_seconds`: 5
  - `notification_yellow_timeout_seconds`: 10
- [x] Bump versión del alwaysconfig

## Task 9: Testing manual
- [x] Verificar que con `run_immediately: true` el check se ejecuta inmediatamente al cargar config
- [x] Verificar que con `run_immediately: false` el check NO se dispara al inicio sino después del primer intervalo
- [x] Verificar check con todas las URLs accesibles → notificación verde (auto-cierre 5s)
- [x] Verificar check con algunas URLs bloqueadas → notificación amarilla con % correcto
- [x] Verificar check con red desconectada → notificación roja persistente
- [x] Verificar que acknowledge cierra la notificación
- [x] Verificar que "Ver Reporte" muestra tabla detallada correcta
- [x] Verificar que un segundo check reemplaza notificación anterior si aún está visible
- [x] Verificar que sin Tray conectado el Service loguea warning sin error
- [x] Verificar reintentos: URL que falla 2 veces y luego responde → se marca como OK
- [x] Verificar log con formato correcto (resumen + fallos individuales)
