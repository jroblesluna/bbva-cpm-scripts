# Documento de Requisitos — Connectivity Check Scheduled

## Introducción

Esta funcionalidad implementa un sistema de verificación periódica de conectividad a URLs críticas para la operación de impresión corporativa. El check se ejecuta como un `OnScheduledTask` configurado en el `.alwaysconfig`, delegando la ejecución de los HTTP checks al Tray (vía Named Pipe) para garantizar acceso al proxy del sistema y credenciales del usuario. Los resultados se presentan como notificaciones visuales en el escritorio del usuario con tres niveles de severidad (verde/amarillo/rojo) y se registran en el log para diagnóstico.

## Glosario

- **ConnectivityCheck**: Nuevo tipo de acción del ActionEngine que envía un comando al Tray vía Pipe para ejecutar verificaciones HTTP de múltiples URLs.
- **ZScaler**: Proxy corporativo local (`127.0.0.1:8999`) que intercepta y autentica tráfico HTTPS. Se registra como proxy del sistema vía WinInet.
- **ProxyHelper**: Clase estática existente que detecta el proxy del sistema y crea HttpHandlers con credenciales del usuario.
- **CheckResult**: Estructura que contiene el resultado de cada URL verificada: status (ok/fail), latencia, código HTTP, número de intentos, error.
- **NotificationForm**: Formulario WPF/WinForms del Tray que muestra el resultado del check con iconografía de semáforo (verde/amarillo/rojo).
- **OnScheduledTask**: Trigger del ActionEngine que se ejecuta periódicamente cada `interval_seconds`.
- **Named_Pipe**: Canal IPC entre Service y Tray (`AlwaysPrintService`).

## Requisitos

### Requisito 1: Trigger OnScheduledTask con acción ConnectivityCheck

**User Story:** Como administrador, quiero configurar un check de conectividad periódico en el `.alwaysconfig` para que las workstations verifiquen automáticamente el acceso a URLs críticas y notifiquen al usuario si hay problemas.

#### Criterios de Aceptación

1. GIVEN un trigger `OnScheduledTask` con `interval_seconds` configurado, WHEN `run_immediately` is `true` (or not specified), THEN la primera ejecución SHALL ocurrir inmediatamente al cargar la configuración. WHEN `run_immediately` is `false`, THEN la primera ejecución SHALL ocurrir después del primer intervalo completo.
2. THE trigger `OnScheduledTask` SHALL support an optional field `run_immediately` (boolean, default: `true`) that controls whether the first execution happens at load time or after the first interval.
2. GIVEN una acción de tipo `ConnectivityCheck` dentro del trigger, WHEN el ActionEngine la ejecuta, THEN SHALL enviar un mensaje Named Pipe al Tray con los parámetros del check (URLs, timeout, reintentos, delays).
3. GIVEN que el Tray no está conectado al Pipe, WHEN el ActionEngine intenta enviar el ConnectivityCheck, THEN SHALL loguear warning y omitir la ejecución sin marcar el trigger como fallido.
4. THE configuración del ConnectivityCheck en el `.alwaysconfig` SHALL incluir: lista de URLs, timeout por URL (segundos), número máximo de reintentos, delay entre reintentos (segundos).
5. THE lista de URLs SHALL soportar el placeholder `{{%SERVER_URL%}}` que el backend resuelve al servir la configuración.

### Requisito 2: Ejecución de checks HTTP en el Tray

**User Story:** Como sistema, necesito que los checks de conectividad se ejecuten en el contexto del usuario logueado para heredar la configuración de proxy y credenciales NTLM/Kerberos necesarias para pasar por ZScaler.

#### Criterios de Aceptación

1. WHEN el Tray recibe un mensaje `ConnectivityCheck` del Service, THEN SHALL crear un HttpClient usando `ProxyHelper.CreateHandler()` con `CredentialCache.DefaultCredentials` para respetar el proxy del sistema.
2. BEFORE de ejecutar los checks de URLs, THE Tray SHALL verificar que el proxy del sistema está activo (TCP connect a la dirección del proxy detectada) y registrar en el log si está activo o no.
3. FOR EACH URL en la lista, THE Tray SHALL ejecutar un HTTP HEAD (o GET si HEAD no es soportado) con el timeout configurado.
4. IF una URL falla, THE Tray SHALL esperar el delay configurado entre reintentos y reintentar hasta el máximo de reintentos configurado.
5. THE Tray SHALL registrar en el log cada URL verificada con: resultado (ok/fail), latencia en ms, código HTTP, número de intentos realizados, y error descriptivo si falló.
6. AFTER completar todos los checks (incluyendo reintentos), THE Tray SHALL calcular el porcentaje de éxito y determinar el nivel de severidad de la notificación.

### Requisito 3: Notificaciones visuales con tres niveles de severidad

**User Story:** Como usuario, quiero recibir una notificación visual clara sobre el estado de mi conectividad para saber si puedo imprimir o si necesito tomar acción.

#### Criterios de Aceptación

1. WHEN 100% de las URLs respondieron OK, THEN THE Tray SHALL mostrar una notificación verde con texto "Todo OK 100%" y botón "Ver Reporte", que se autocierra a los 5 segundos o al hacer clic en acknowledge.
2. WHEN al menos una URL falló pero no todas, THEN THE Tray SHALL mostrar una notificación amarilla (warning) con el porcentaje de URLs fallidas y botón "Ver Reporte", que se autocierra a los 10 segundos o al hacer acknowledge.
3. WHEN 0% de las URLs respondieron OK (todas fallaron), THEN THE Tray SHALL mostrar una notificación roja con icono visual de impresora en rojo/error, texto indicando "Sin acceso a Internet — Requiere autenticación en ZScaler", y botón de acknowledge. La notificación roja SHALL permanecer visible hasta que el usuario haga clic en acknowledge.
4. ONLY ONE notification form SHALL exist at any time. IF a new scheduled check completes while a previous notification is still visible, THEN the previous notification SHALL cerrarse y ser reemplazada por la nueva.
5. THE notification form SHALL include a "Ver Reporte" button that, when clicked, shows a detail view with the table of results (URL, status, latency, attempts, error).

### Requisito 4: Registro de estadísticas en log

**User Story:** Como administrador, quiero que las estadísticas de cada check se graben en el log para poder diagnosticar problemas de conectividad remotamente.

#### Criterios de Aceptación

1. AFTER cada ejecución del check, THE Tray SHALL escribir en el log un resumen: timestamp, total URLs, exitosas, fallidas, porcentaje, proxy activo (sí/no), IP de salida del proxy (si se puede obtener).
2. FOR EACH URL that failed after all retries, THE Tray SHALL registrar: URL, error code, latencia del último intento, número total de intentos.
3. THE log entries SHALL use Event ID 1090 para resultados normales y Event ID 1091 para fallos.

### Requisito 5: Configuración en `.alwaysconfig`

**User Story:** Como administrador, quiero definir la lista de URLs y parámetros del check en el `.alwaysconfig` centralizado para poder actualizarlo remotamente sin tocar el cliente.

#### Criterios de Aceptación

1. THE action type SHALL be `"ConnectivityCheck"` with the following parameters:
   - `urls`: Array de strings con las URLs a verificar (soporta `{{%SERVER_URL%}}`)
   - `timeout_seconds`: Timeout por URL individual (default: 5)
   - `max_retries`: Número máximo de reintentos por URL fallida (default: 2)
   - `retry_delay_seconds`: Delay entre reintentos (default: 30)
   - `notification_green_timeout_seconds`: Tiempo de autocierre de notificación verde (default: 5)
   - `notification_yellow_timeout_seconds`: Tiempo de autocierre de notificación amarilla (default: 10)
2. THE `OnScheduledTask` trigger SHALL define `interval_seconds` para la frecuencia del check (ej: 300 para cada 5 minutos) y opcionalmente `run_immediately` (boolean, default: `true`) para controlar si la primera ejecución es inmediata o diferida al primer intervalo.
3. THE `ConnectivityCheck` action SHALL be the only action type that delegates execution entirely to the Tray via Named Pipe (el Service no ejecuta HTTP requests).

## Ejemplo de Configuración

```json
{
  "event": "OnScheduledTask",
  "interval_seconds": 300,
  "run_immediately": false,
  "description": "Verificación periódica de conectividad a servicios críticos de impresión",
  "actions": [
    {
      "type": "ConnectivityCheck",
      "description": "Verificar acceso a URLs de impresión corporativa vía proxy",
      "parameters": {
        "urls": [
          "{{%SERVER_URL%}}",
          "https://cloud.lexmark.com",
          "https://idp.us.iss.lexmark.com",
          "https://login.microsoftonline.com",
          "https://lexmarkb2c.b2clogin.com",
          "https://api.us.iss.lexmark.com",
          "https://apis.us.iss.lexmark.com",
          "https://us.iss.lexmark.com",
          "https://prod-lex-cloud-iot.azure-devices.net",
          "https://apis.iss.lexmark.com",
          "https://iss.lexmark.com",
          "https://global.azure-devices-provisioning.net",
          "https://prodlexcloudk8s239.blob.core.windows.net",
          "https://ccs.lexmark.com",
          "https://ccs-cdn.lexmark.com",
          "https://prodlexcloudk8s19.blob.core.windows.net"
        ],
        "timeout_seconds": 5,
        "max_retries": 2,
        "retry_delay_seconds": 30,
        "notification_green_timeout_seconds": 5,
        "notification_yellow_timeout_seconds": 10
      }
    }
  ]
}
```

## Restricciones Técnicas

1. Los checks HTTP DEBEN ejecutarse en el Tray (no en el Service) para heredar el proxy del sistema y credenciales del usuario.
2. La comunicación Service → Tray para el check es fire-and-forget: el Service envía el comando y no espera respuesta. El Tray gestiona todo el flujo (checks + notificación + log).
3. El NotificationForm debe ser un singleton — nunca más de uno visible simultáneamente.
4. El formulario de notificación debe funcionar en Windows 7+ (WinForms, no WPF moderno).
5. Los checks deben respetar el proxy del sistema (`WebRequest.GetSystemWebProxy()`) — NO hardcodear `127.0.0.1:8999`.
