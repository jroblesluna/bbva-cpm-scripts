# Flujo de Encolamiento CPM Hybrid (Sin Proxy, Solo Encolamiento)

## Referencia

Log capturado: 2026-08-04 18:46:01  
Versión: LexmarkPrintManagementClient/4.0.0 (Java 25.0.2)  
Modo: Hybrid | Cola: LexmarkBBVA | Driver: Lexmark Universal v2 XL  
Proxy: DIRECT (sin proxy)  
**Este log NO incluye release/liberación, solo captura y encolamiento en cloud.**

## Flujo Observado (Paso a Paso del Log)

### Fase 1: Recepción del Job (Thread [36])

```
18:46:01.636 TCPClientHandler: Adding to activejob: {timestamp}-{uuid}_{epoch}.prn
18:46:01.668 TCPClientHandler: Active Job Count: 0
```

El job llega al puerto TCP 9167 (configurado como Source en el Route).

### Fase 2: Autenticación (Thread [59])

```
18:46:01.700 AuthenticatingJobsListener: Started
18:46:01.731 AuthenticatingJobsListener: Checking if authentication required for job: {jobId}
18:46:01.792 SystemProxy: onProxySettingsChange...
18:46:01.889 WindowsSystemProxy: ProxyAgent output: IsSystem: Current user: NT AUTHORITY\SYSTEM
18:46:02.931 WindowsSystemProxy: ProxyAgent output: NOProxy
18:46:02.962 RestTemplateCreator: calling createUnauthenticatedProxyRestTemplate
18:46:02.993 SystemProxy: proxy type : DIRECT
18:46:03.088 TokenHandler: Checking saved token.
18:46:03.118 IDPOauthService: Retrieving token info...
18:46:03.149 HTTP GET https://apis.us.iss.lexmark.com/ciam/identity-authorization-service/oauth/token/info
18:46:03.743 Response 200 OK
18:46:03.836 IDPOauthService: Got valid token info
18:46:03.868 TokenInfo:resource_owner_organization_id: {org_id}
             TokenInfo:email: {email}
             TokenInfo:resource_owner_id: {user_id}
18:46:03.899 AuthenticatingJobsListener: User {username} authenticated successfully
```

**Detalle**: `WindowsSystemProxy` produce output etiquetado "ProxyAgent output" — toma ~1.1s entre la primera y segunda respuesta. La verificación de proxy ocurre como SYSTEM.

### Fase 3: Procesamiento del Job (Thread [60])

```
18:46:04.858 ActiveJobsListener: Got an active Job....
18:46:04.918 CapturedJobHandler: job ticket before processing {JSON del job ticket}
```

**Job Ticket (campos clave)**:
```json
{
  "Id": "{uuid}",
  "JobPath": "C:\\ProgramData/LPMC\\Jobs/{user}/CloudHybrid/pre/{filename}.prn",
  "Route": {
    "Source": 9167,
    "Destination": {
      "DestinationType": "CloudHybrid",
      "APIVersion": "3.0",
      "ServerAddress": "https://apis.us.iss.lexmark.com/cpm",
      "IDPAddress": "https://apis.us.iss.lexmark.com/ciam/identity-authorization-service"
    },
    "AuthenticationMode": "DefaultBrowser",
    "ReleasePort": 9443,
    "queueName": "LexmarkBBVA"
  },
  "Metadata": { "UserName": "{user}", "isPending": false }
}
```

### Fase 4: Parsing del PRN (Thread [60])

```
18:46:05.128 CapturedJobHandler: Parsing job
18:46:06.491 CapturedJobHandler: parserMetadata: {JSON metadata}
```

**Metadata extraída del .prn**:
```json
{
  "jobName": "Página de prueba",
  "hostName": "DESKTOP-CH4HFIH",
  "pageCount": 1,
  "jobSize": 105964,
  "mimeType": "application/pclxl",
  "userName": "{user}",
  "userId": "{user}",
  "options": [
    {"modification": "disabled", "name": "nUp", "value": 1},
    {"modification": "simple", "name": "color", "value": true},
    {"modification": "simple", "name": "fold", "value": "off"},
    {"modification": "simple", "name": "collation", "value": "on"},
    {"modification": "complex", "name": "copies", "value": 1},
    {"modification": "disabled", "name": "mediaSize", "value": [{"name": "a4", "startPage": 1}]},
    {"modification": "complex", "name": "mediaType", "value": [{"name": "plain", "startPage": 1}]},
    {"modification": "complex", "name": "paperSource", "value": [{"name": "tray1", "startPage": 1}]}
  ]
}
```

### Fase 5: Encriptación (Thread [60])

```
18:46:06.566 CapturedJobHandler: Encrypting start
18:46:06.599 FileCryptoUtils: Create parent directory ...\post, success false
18:46:06.629 FileCryptoUtils: Encryption START
18:46:06.660 FileCryptoUtils: Encryption KEY START
18:46:06.692 FileCryptoUtils: Encryption KEY END
18:46:06.723 FileCryptoUtils: Encryption PAYLOAD START
18:46:06.757 FileCryptoUtils: Encryption PAYLOAD END
18:46:06.788 FileCryptoUtils: Encryption END
18:46:06.819 CapturedJobHandler: Finished Encryption
```

**Nota**: "Create parent directory... success false" indica que la carpeta `post/` ya existía (no error, solo que no necesitó crearla).

### Fase 6: Segunda Validación de Token (Thread [60])

```
18:46:06.850 TokenHandler: Checking saved token.
18:46:06.881 PostCaptureHandler: process
18:46:06.911 TokenHandler: Checking saved token.
18:46:06.941 IDPOauthService: Retrieving token info...
18:46:06.972 HTTP GET .../oauth/token/info
18:46:07.547 Response 200 OK
18:46:07.634 IDPOauthService: Got valid token info
```

El token se verifica **dos veces** en el flujo: una en Fase 2 (autenticación inicial) y otra aquí antes de enviar al cloud.

### Fase 7: Envío al Cloud — Crear Documento (Thread [60])

```
18:46:07.885 AbstractJobSubmissionService: POST URL:
  https://apis.us.iss.lexmark.com/cpm/print-management-service/v3.0/organizations/{orgId}/users/{userId}/documents
18:46:07.923 HTTP POST ...documents
18:46:08.887 Response 201 CREATED
```

**Payload del POST** incluye: nombre, title, client info (id, type=lpmc, mode=hybrid, version, OS, hostname, MAC, driver), metadata completa del job, checkSum, y storageClients (la WS misma como storage).

**storageClients** enviado:
```json
{
  "deviceId": "{uuid}",
  "deviceName": "DESKTOP-CH4HFIH",
  "ipAddress": "192.168.1.83",
  "macAddress": "5C:F3:FC:2B:02:C2",
  "port": 9443,
  "type": "workstation"
}
```

### Fase 8: Actualizar Metadata — PATCH (Thread [60])

```
18:46:09.228 HTTP PATCH ...documents
18:46:09.852 Response 200 OK
```

### Fase 9: Registrar en Workload Handler (Thread [60])

```
18:46:09.953 AbstractJobSubmissionService: Sending job to Hybrid Storage Client...
18:46:10.158 HTTP POST https://apis.us.iss.lexmark.com/cpm/continuous-workload-handler/v1.0/organizations/{orgId}/client/documents
18:46:10.816 Response 201 CREATED
```

```
18:46:10.866 HybridJobMirrorProcessor: No Mirror Device Found for {deviceId}
18:46:10.897 UniversalUI: Show Notification: Página de prueba
18:46:10.930 AbstractJobSubmissionService: Hybrid Job successfully submitted to cloud.
```

### Fase 10: Bulk Registration de Jobs en Post (Thread [60])

```
18:46:10.978 JobRegistrationProcessor: docId is {docId1} for Job ...post/{file1}.prn.json
18:46:11.009 JobRegistrationProcessor: docId is {docId2} for Job ...post/{file2}.prn.json
18:46:11.040 JobRegistrationProcessor: Sending bulk update to cloud...
18:46:11.235 HTTP PATCH ...documents (con 2 documentos)
18:46:11.823 Response 200 OK
18:46:11.930 JobRegistrationProcessor: V3 Hybrid Registration/Un-registration returned
18:46:11.964 BulkUpdateResponseProcessor: Bulk update success count: 2
18:46:11.995 BulkUpdateResponseProcessor: Deleted 0/0 local jobs.
```

## Tiempos Clave

| Segmento | Duración | Notas |
|----------|----------|-------|
| Recepción TCP → Auth completa | ~2.3s | Incluye detección de proxy (~1.1s) + validación token (~0.6s) |
| Auth completa → Job activo detectado | ~1.0s | ActiveJobsListener polling (espera 1s entre checks) |
| Parsing del PRN | ~1.4s | Incluye segunda detección de proxy |
| Encriptación | ~220ms | KEY + PAYLOAD |
| Segunda validación de token | ~700ms | Redundante con Fase 2 |
| POST crear documento | ~1.0s | Incluye creación de RestTemplate |
| PATCH metadata | ~624ms | |
| POST workload-handler | ~658ms | |
| Bulk registration | ~783ms | 2 docs en una sola request |
| **Total captura→encolado** | **~10.3s** | |

## Estructura de Carpetas (del Log)

```
C:\ProgramData\LPMC\Jobs\{username}\CloudHybrid\
├── pre\   ← .prn recibido del spooler (raw)
└── post\  ← .prn encriptado + .prn.json (metadata)
```

## APIs Cloud (Observadas en el Log)

| # | Método | Endpoint | Response | Propósito |
|---|--------|----------|----------|-----------|
| 1 | GET | `/ciam/identity-authorization-service/oauth/token/info` | 200 | Validar token (×2) |
| 2 | POST | `/cpm/print-management-service/v3.0/organizations/{orgId}/users/{userId}/documents` | 201 | Crear documento |
| 3 | PATCH | `/cpm/print-management-service/v3.0/organizations/{orgId}/users/{userId}/documents` | 200 | Actualizar metadata |
| 4 | POST | `/cpm/continuous-workload-handler/v1.0/organizations/{orgId}/client/documents` | 201 | Registrar en workload handler |
| 5 | PATCH | `.../documents` (bulk) | 200 | Sync todos los jobs en post/ |

## Threads Observados

| Thread | Clase Principal | Rol |
|--------|-----------------|-----|
| [36] | TCPClientHandler | Recibe datos TCP del spooler |
| [59] | AuthenticatingJobsListener | Autenticación del job |
| [60] | ActiveJobsListener → CapturedJobHandler → PostCaptureHandler | Procesa, encripta, sube |
| [42] | IPChangeMonitor | Monitoreo periódico de IP |
| [43] | WindowsSysTrayMonitor | Verifica systray del usuario |

## Observaciones del Log

1. El job **no sube al cloud** como archivo. Solo se envía metadata. El `.prn` encriptado queda en la WS en `post/` y se sirve vía puerto 9443 (ReleasePort del job ticket) cuando se libera.
2. La detección de proxy ocurre **múltiples veces** durante el flujo (no se cachea entre fases).
3. `WindowsSystemProxy` muestra output con prefijo "ProxyAgent output" — componente que detecta proxy como SYSTEM.
4. El `ActiveJobsListener` hace polling con intervalos de 1 segundo (visible: "waiting for N/30 seconds").
5. `BulkUpdateResponseProcessor` al final sincroniza TODOS los jobs en `post/` con el cloud, no solo el job actual.
6. `HybridJobMirrorProcessor: No Mirror Device Found` — no hay mirror configurado (normal en single-workstation).
7. La notificación al systray (`UniversalUI: Show Notification`) ocurre después del POST exitoso al cloud.

---

## Flujo Sin Token: Job Pasa a Post Pero No Se Envía al Cloud

### Referencia

Log capturado: 2026-08-04 18:58:23 — Mismo equipo, misma versión  
Condición: Token no existe, usuario no autenticó en browser, browser cerrado sin completar OAuth

### Secuencia Observada (del log)

#### Startup del Servicio

```
18:58:23.172 LPMCUniversalService: Starting (PID 19332)
18:58:23.424 Profile activo: "Hybrid"
18:58:28.528 Started in 6.35 seconds
18:58:30.272 StartupProcessor: reloadTokenCache: begin
18:58:30.311 TokenHandler: Checking saved token.
18:58:30.343 TokenHandler: Token does not exist
```

**Dato clave**: Al inicio, CPM verifica token. Si no existe, continúa sin error.

#### Recuperación de Job Previo en `pre/`

```
18:58:30.572 StartupProcessor: recoverPreFolderJobs — buscando .prn/.ps en Jobs/
18:58:30.607 addPrnFilesToActiveQueue — encontró archivo en pre/
18:58:30.741 Done adding to active job (archivo previo recuperado)
```

**Dato clave**: Al reiniciar, CPM recupera jobs huérfanos de `pre/` y los vuelve a encolar.

#### Procesamiento del Job Recuperado (sin token)

```
18:58:31.025 ActiveJobsListener: Got an active Job....
18:58:33.290 CapturedJobHandler: Parsing job
18:58:34.776 parserMetadata: {metadata completa del job}
18:58:34.879 CapturedJobHandler: Encrypting start
18:58:35.162 CapturedJobHandler: Finished Encryption
```

**Dato clave**: El job se parsea y se encripta ANTES de verificar token. El archivo pasa de `pre/` a `post/` sin necesitar autenticación.

#### Intento de Autenticación (falla)

```
18:58:35.200 TokenHandler: Checking saved token.
18:58:35.232 TokenHandler: Token does not exist
18:58:35.263 IDPOauthService: Probing for Proxy Credential info
18:58:35.337 HTTP HEAD https://apis.us.iss.lexmark.com/ciam/identity-authorization-service
18:58:36.252 LPMCRedirectStrategy: Redirected URI: https://us.iss.lexmark.com/
18:58:37.143 Response 200 OK
18:58:37.183 AuthenticationUILauncher: Launching WebView
```

**Dato clave**: Después de encriptar, CPM necesita token para enviar al cloud. No lo tiene → lanza browser para OAuth.

#### Browser Lanzado — Usuario No Autentica

```
18:58:37.251 AbstractUILauncher: executing command = -t 1 -u https://apis.us.iss.lexmark.com/ciam/.../oauth/authorize?response_type=code&client_id=lpmc-client&redirect_uri=http://127.0.0.1:3333/
18:58:37.489 AbstractUILauncher: InputStream: IsSystem: Current user: NT AUTHORITY\SYSTEM
18:58:39.468 AbstractUILauncher: InputStream: LPMCUI::DefaultBrowser::NoOp
18:58:39.500 IDPOauthService: Browser No Op
18:58:40.092 AbstractUILauncher: ErrorStream: WARNING: A restricted method in java.lang.System has been called
```

**Dato clave**: 
- CPM lanza el browser para autenticación OAuth
- El parámetro `-t 1` parece ser un tipo/modo del launcher
- `redirect_uri=http://127.0.0.1:3333/` — CPM escucha en localhost:3333 esperando el callback OAuth
- `LPMCUI::DefaultBrowser::NoOp` — el launcher indica que no hubo acción del usuario
- El WARNING de "restricted method" es un mensaje de Java 25 (no es error funcional)

#### PostCaptureHandler Espera Indefinidamente

```
18:58:37.217 PostCaptureHandler: process
18:58:37.269 TokenHandler: Checking saved token.
18:58:37.304 TokenHandler: Token does not exist
18:58:37.342 PostCaptureHandler: Waiting for login to complete
```

Desde este punto, `PostCaptureHandler` queda bloqueado esperando que aparezca un token. El `ActiveJobsListener` muestra "Current Active job is still processing..." cada ~1 segundo **indefinidamente**.

#### CallHomePoller — Sin usuario registrado

```
18:59:32.802 CallHomePoller: No user found skipping calls home.
```

**Dato clave**: Sin token, CPM no tiene usuario registrado → no puede hacer "call home" al cloud.

#### Segundo Job Enviado (19:04:18) — Mismo Comportamiento

```
19:04:18.667 TCPClientHandler: Adding to activejob: {segundo_archivo}.prn
19:04:18.700 TCPClientHandler: Active Job Count: 1
19:04:18.732 AuthenticatingJobsListener: Started
19:04:18.770 AuthenticatingJobsListener: Checking if authentication required for job
19:04:20.154 TokenHandler: Checking saved token.
19:04:20.185 TokenHandler: Token does not exist
19:04:20.216 IDPOauthService: Probing for Proxy Credential info
19:04:21.571 Response 200 OK
19:04:21.615 AuthenticationUILauncher: Launching WebView
19:04:21.646 AuthenticatingJobsListener: No authenticating jobs found, stopping...
```

**Dato clave**: El segundo job triggerea OTRA instancia del `AuthenticatingJobsListener` (thread [50]). Este también detecta "Token does not exist", lanza WebView, y luego dice "No authenticating jobs found, stopping..." — lo cual no tiene sentido lógico dado que hay un job pendiente. Posible race condition o el job ya fue consumido por el thread [37] del primer job.

#### Shutdown del Servicio (19:06:16)

```
19:06:16.983 LPMCUniversalService: Shutdown hook invoked
19:06:17.016 ShutdownProcessor: Got ticket (con AuthenticationMode: "WebView")
19:06:17.096 ShutdownProcessor: No local jobs found to detach from server
19:06:17.128 IPChangeMonitor: InterruptedException (shutdown normal)
19:06:17.127 TCPListener: SocketException: Socket closed (shutdown normal)
```

**Dato clave**: En shutdown, el ticket muestra `AuthenticationMode: "WebView"` (vs "DefaultBrowser" en el job ticket del startup). Esto podría significar que el servicio cambió a modo WebView después de que DefaultBrowser falló.

#### Segundo Inicio del Servicio (19:06:22) — Mismo Patrón

```
19:06:22.905 Starting LPMCUniversalService (PID 16360)
19:06:29.833 TokenHandler: Checking saved token.
19:06:29.865 TokenHandler: Token does not exist
19:06:30.164 addPrnFilesToActiveQueue — recupera job de pre/
19:06:30.527 ActiveJobsListener: Got an active Job....
19:06:34.497 CapturedJobHandler: Finished Encryption
19:06:34.534 TokenHandler: Checking saved token.
19:06:34.565 TokenHandler: Token does not exist
19:06:36.766 AuthenticationUILauncher: Launching WebView
19:06:36.862 TokenHandler: Token does not exist
19:06:36.942 PostCaptureHandler: Waiting for login to complete
19:06:39.009 AbstractUILauncher: InputStream: LPMCUI::DefaultBrowser::NoOp
19:06:39.041 IDPOauthService: Browser No Op
```

Mismo ciclo: encripta → no tiene token → lanza browser → usuario no autentica → queda esperando infinitamente.

### Hallazgos Clave

| # | Observación | Evidencia del Log |
|---|------------|-------------------|
| 1 | **El job se encripta y pasa a `post/` SIN necesitar token** | Encryption completa antes de `TokenHandler: Token does not exist` |
| 2 | **El token solo se necesita para enviar metadata al cloud** | `PostCaptureHandler: Waiting for login to complete` bloquea después de encriptar |
| 3 | **Sin token, el job queda atascado en `post/` indefinidamente** | `ActiveJobsListener: Current Active job is still processing...` por minutos |
| 4 | **No hay timeout para la espera de autenticación** | El log muestra polling cada 1s sin límite (minutos) |
| 5 | **`Browser No Op` no genera error ni retry** | Solo un INFO log, luego silencio |
| 6 | **Al reiniciar CPM, recupera jobs de `pre/` y repite el ciclo** | `recoverPreFolderJobs` + mismo flujo |
| 7 | **El segundo job llega mientras el primero sigue bloqueado** | `Active Job Count: 1` cuando llega el segundo |
| 8 | **`CallHomePoller: No user found`** confirma que sin token no hay usuario registrado | Explícito en log |
| 9 | **Shutdown ticket cambia a `AuthenticationMode: "WebView"`** | Diferente al "DefaultBrowser" del job ticket original |

### Implicación para AlwaysPrint

Este comportamiento confirma que cuando un usuario no autentica (o pierde el token), los jobs se acumulan en `post/` encriptados pero **nunca se envían al cloud**. Desde la perspectiva de AlwaysPrint:

- El comando remoto "Listar jobs en post" mostrará archivos `.prn` acumulados
- El comando "Listar carpeta Jobs del usuario (token)" NO mostrará archivo de token
- La acción "Limpiar Sistema de Impresión" eliminará estos jobs atascados
- Para resolver: el usuario debe autenticarse vía browser cuando CPM lo solicite


---

## Flujo Con Login OAuth en Browser (Token No Existía, Usuario Autentica)

### Referencia

Log capturado: 2026-08-04 19:17:52 — Mismo equipo, misma versión  
Condición: Token no existe al inicio, usuario completa login en browser, job se envía exitosamente

### Diferencia Clave vs Flujo Normal

En el flujo normal (token ya existe), el job se procesa en ~10s. Aquí el flujo se bifurca:
- El `AuthenticatingJobsListener` (thread [48]) detecta que no hay token y lanza el browser
- El flujo OAuth se completa en un thread separado (thread [49]) 
- Una vez obtenido el token, el job se procesa normalmente en otro thread (thread [51])

### Secuencia de Autenticación OAuth (del log)

#### 1. Job llega, no hay token

```
19:18:13.220 [36] TCPClientHandler: Adding to activejob
19:18:13.283 [48] AuthenticatingJobsListener: Checking if authentication required
19:18:15.001 [48] TokenHandler: Checking saved token.
19:18:15.034 [48] TokenHandler: Token does not exist
19:18:15.068 [48] IDPOauthService: Probing for Proxy Credential info
19:18:15.150 [48] HTTP HEAD https://apis.us.iss.lexmark.com/ciam/identity-authorization-service
19:18:16.922 [48] Response 200 OK
19:18:16.965 [48] AuthenticationUILauncher: Launching WebView
19:18:16.996 [48] AuthenticatingJobsListener: No authenticating jobs found, stopping...
```

#### 2. Browser lanzado — espera que usuario ingrese credenciales

```
19:18:17.006 [49] AbstractUILauncher: executing command = -t 1 -u https://apis.us.iss.lexmark.com/ciam/.../oauth/authorize?response_type=code&client_id=lpmc-client&redirect_uri=http://127.0.0.1:3333/
19:18:17.110 [49] AbstractUILauncher: InputStream: IsSystem: Current user: NT AUTHORITY\SYSTEM
```

**~19 segundos pasan mientras el usuario ingresa credenciales en el browser**

#### 3. Browser retorna authorization code

```
19:18:36.510 [49] AbstractUILauncher: InputStream: LPMCUI::DefaultBrowser::Code::/?code={authorization_code}
19:18:36.547 [49] IDPOauthService: code={authorization_code}
```

**Dato clave**: El formato del callback es `LPMCUI::DefaultBrowser::Code::/?code={code}`. El servicio escucha en `http://127.0.0.1:3333/` y recibe el redirect del IDP.

#### 4. Intercambio code → token (authorization_code grant)

```
19:18:36.593 [49] HTTP POST https://apis.us.iss.lexmark.com/ciam/identity-authorization-service/oauth/token
19:18:36.680 [49] Writing [{grant_type=[authorization_code], client_id=[lpmc-client], client_secret=[[filtered]], code={code}, redirect_uri=[http://127.0.0.1:3333/]}]
19:18:37.162 [49] Response 200 OK
19:18:37.246 [49] TokenHandler: Token Received
```

#### 5. Token se encripta y persiste en disco

```
19:18:37.321 [49] FileCryptoUtils: Create parent directory C:\ProgramData\LPMC\Jobs\lex, success false
19:18:37.352 [49] FileCryptoUtils: Encryption START
19:18:37.518 [49] FileCryptoUtils: Encryption END
```

**Dato clave**: El token se guarda encriptado en `C:\ProgramData\LPMC\Jobs\{username}\` (el "success false" del create directory indica que ya existía).

#### 6. Validación del token recién obtenido

```
19:18:37.710 [49] IDPOauthService: Retrieving token info...
19:18:37.743 [49] HTTP GET .../oauth/token/info
19:18:38.313 [49] Response 200 OK
19:18:38.381 [49] IDPOauthService: Got valid token info
19:18:38.420 [49] TokenInfo:resource_owner_organization_id: {org_id}
               TokenInfo:email: {email}
               TokenInfo:resource_owner_id: {user_id}
```

#### 7. Obtención de Application Token (client_credentials grant)

```
19:18:38.666 [49] HTTP POST .../oauth/token
19:18:38.733 [49] Writing [{grant_type=[client_credentials], client_id=[lpmc-client], client_secret=[[filtered]]}]
19:18:39.351 [49] Response 200 OK
```

**Dato clave**: Después del token de usuario, CPM obtiene un **application token** separado usando `client_credentials`. Este se usa para operaciones de aplicación (GET_JOBS, GET_CONFIG, etc.).

#### 8. Application Token Info

```
19:18:39.843 [49] ApplicationTokenCommand: tokenInfo: {
  "application": {
    "id": "a42ab747-...",
    "organization_id": "922570ee-...",
    "client_id": "lpmc-client",
    "name": "LPMC Applications"
  },
  "scopes": "msa-lpm:org-policy-read",
  "expires_in_seconds": 21600
}
```

**Dato clave**: El application token tiene su propio `organization_id` diferente al del usuario. Expira en 6 horas (21600s).

#### 9. Call Home — GET_JOBS, GET_CONFIG, GET_PRINT_POLICY

```
19:18:40.174 [49] JobRequestCommand: Sending job request for jobType:GET_JOBS
19:18:40.971 [49] Response 201 CREATED → response:["GET_CONFIG","GET_PRINT_POLICY"]
19:18:41.087 [49] JobRequestCommand: Sending job request for jobType:GET_CONFIG
19:18:41.579 [49] Response 201 CREATED → response: {clientCallHomeFrequencyInHours:4, offlinePrintEnabled:true, printers:[], ...}
```

**Dato clave**: Después de autenticarse, CPM hace un "call home" completo: obtiene lista de jobs pendientes del cloud, configuración del cliente, y print policies.

#### 10. Configuración de usuario local

```
19:18:41.964 [49] PrinterAssignmentHandler: Building local user mapping for 1 users
19:18:41.995 [49] PrinterAssignmentHandler: Set resourceOwnerId for user: lex
19:18:42.026 [49] PrinterAssignmentHandler: Set email for user: lex
19:18:42.058 [50] AbstractUILauncher: executing command = -t 17 -lu lex
19:18:43.594 [50] AbstractUILauncher: InputStream: LPMCUI::GetUserLocale::es
```

**Dato clave**: CPM ejecuta un comando `-t 17 -lu {username}` para obtener el locale del usuario. Responde `LPMCUI::GetUserLocale::es`.

#### 11. GET_PRINT_POLICY + ACK

```
19:18:43.725 [49] JobRequestCommand: Sending job request for jobType:GET_PRINT_POLICY
19:18:44.265 [49] response: {policies: [{name:"Default Print Policy", monoPolicy:{enforce:false}, duplexPolicy:{enforce:false}, ...}]}
19:18:44.315 [49] JobProcessor: Attempting to Sending ACK
19:18:45.636 [49] Response 200 OK
```

#### 12. Token info pasado al handler → usuario autenticado

```
19:18:45.710 [49] TokenHandler: passing token info back to handler
19:18:45.741 [49] AuthenticatingJobsListener: User lex authenticated successfully
```

#### 13. Job procesado normalmente (thread [51])

A partir de aquí, el flujo es idéntico al flujo normal documentado arriba:

```
19:18:45.772 [51] ActiveJobsListener: Started ActiveJobsListener
19:18:45.803 [51] ActiveJobsListener: Got an active Job....
19:18:46.236 [51] CapturedJobHandler: Parsing job
19:18:47.773 [51] CapturedJobHandler: Encrypting start
19:18:48.033 [51] CapturedJobHandler: Finished Encryption
19:18:48.069 [51] TokenHandler: Checking saved token. (ahora SÍ existe)
19:18:48.868 [51] IDPOauthService: Got valid token info
19:18:49.125 [51] AbstractJobSubmissionService: POST .../documents
19:18:49.865 [51] Response 201 CREATED
19:18:50.981 [51] PATCH .../documents → 200 OK
19:18:51.945 [51] POST .../client/documents → 201 CREATED
19:18:52.032 [51] UniversalUI: Show Notification: Página de prueba
19:18:52.069 [51] AbstractJobSubmissionService: Hybrid Job successfully submitted to cloud.
```

#### 14. CallHome con frecuencia actualizada

```
19:19:10.007 [45] CallHomeTask: Calls home frequency change to:240
19:19:10.038 [45] CallHomeTask: Calls home task end, will wait for next interval 240.
```

**Dato clave**: Después del primer call home exitoso, la frecuencia cambia de 60s a 240 minutos (4 horas), según `clientCallHomeFrequencyInHours:4` del GET_CONFIG.

### Tiempos Clave (Flujo con Login)

| Segmento | Inicio | Fin | Duración |
|----------|--------|-----|----------|
| Job llega → browser lanzado | 19:18:13.220 | 19:18:17.006 | ~3.8s |
| Espera de login del usuario | 19:18:17.006 | 19:18:36.510 | **~19.5s** |
| Code → Token received | 19:18:36.510 | 19:18:37.246 | ~736ms |
| Token encrypt + validate | 19:18:37.246 | 19:18:38.381 | ~1.1s |
| Application token + call home | 19:18:38.381 | 19:18:45.710 | ~7.3s |
| Job procesado (flujo normal) | 19:18:45.772 | 19:18:52.069 | ~6.3s |
| **Total job recibido → enviado** | 19:18:13.220 | 19:18:52.069 | **~38.8s** |

Sin contar el tiempo del usuario (19.5s), el overhead del OAuth es ~12s.

### Hallazgos Adicionales (vs logs anteriores)

| # | Observación | Evidencia |
|---|------------|-----------|
| 1 | **Hay 2 tokens**: usuario (authorization_code) + aplicación (client_credentials) | Dos POSTs a /oauth/token con diferentes grant_types |
| 2 | **El token de usuario se encripta en disco** | FileCryptoUtils después de "Token Received" |
| 3 | **`-t 1`** = lanzar browser para OAuth | Comando del AbstractUILauncher |
| 4 | **`-t 17`** = obtener locale del usuario | Comando separado después de autenticación |
| 5 | **Callback format**: `LPMCUI::DefaultBrowser::Code::/?code={code}` | InputStream del launcher |
| 6 | **El application token pertenece a org diferente** | user org = `c4b8005d-...`, app org = `922570ee-...` |
| 7 | **CallHome frequency cambia de 60s→240min** después del primer call home exitoso | CallHomeTask log explícito |
| 8 | **`ActiveJobsListener` del thread original [37] expira a los 30s** | "stopping after waiting for 30 seconds" — el job lo procesa el nuevo thread [51] |
| 9 | **Systray "not running for user: lex. Launching..."** al final | WindowsSysTrayMonitor detecta y relanza |
