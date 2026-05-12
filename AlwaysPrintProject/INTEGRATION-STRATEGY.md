# AlwaysPrint — Estrategia de Integración Client ↔ Cloud

**Versión**: 1.0.0  
**Fecha**: 11 de mayo de 2026  
**Estado**: Documento de referencia para desarrollo por fases

---

## Visión General

Este documento define la estrategia completa para integrar el **AlwaysPrint Client** (Windows Service + Tray) con el **AlwaysPrint Cloud Manager** (APCM). La integración es **opcional y resiliente**: el Client funciona en modo local sin Cloud, y cuando Cloud está disponible, agrega monitoreo centralizado, configuración remota y telemetría.

### Principios de Diseño

1. **Offline-first**: el Tray opera con la última configuración descargada. La nube es un enriquecimiento, no una dependencia.
2. **Coherencia de nombres**: las variables, claves de registro, campos de BD y mensajes del pipe usan los mismos nombres en todos los componentes.
3. **Configuración jerárquica**: `GlobalConfig → VLANConfig → WorkstationConfig`. El Tray descarga solo si el hash cambió.
4. **Monitoreo configurable**: los mecanismos de conectividad (ping, HTTP, TCP, DNS) se definen en el portal y se descargan como parte de la configuración.
5. **i18n completo**: el Tray detecta el locale de Windows y permite override desde el portal y desde el propio Tray.
6. **Telemetría útil**: estado de cola, log de desconexiones, trabajos identificados, tiempo promedio de liberación.

---

## Arquitectura de Integración

```
┌─────────────────────────────────────────────────────────────────┐
│                    WORKSTATION WINDOWS                           │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  AlwaysPrintService.exe  (LocalSystem, sin Internet)     │  │
│  │                                                          │  │
│  │  - Gestiona cola de impresión (WMI)                      │  │
│  │  - Aplica configuración en Registry                      │  │
│  │  - Detecta contingencia (CPM no disponible)              │  │
│  │  - Expone Named Pipe                                     │  │
│  └──────────────────────┬───────────────────────────────────┘  │
│                         │ Named Pipe \\.\pipe\AlwaysPrintService │
│  ┌──────────────────────▼───────────────────────────────────┐  │
│  │  AlwaysPrintTray.exe  (Usuario, con Internet)            │  │
│  │                                                          │  │
│  │  - Icono de bandeja + menú contextual (i18n)             │  │
│  │  - Cliente WebSocket persistente → APCM                  │  │
│  │  - Descarga config si hash cambió                        │  │
│  │  - Monitoreo de conectividad (ping/HTTP/TCP/DNS)         │  │
│  │  - Telemetría: cola, desconexiones, jobs, tiempos        │  │
│  │  - Modo offline: config cacheada + notificación 1h/2h    │  │
│  └──────────────────────┬───────────────────────────────────┘  │
└─────────────────────────┼───────────────────────────────────────┘
                          │ WSS + HTTPS (vía Proxy Corporativo)
                          │
┌─────────────────────────▼───────────────────────────────────────┐
│              ALWAYSPRINT CLOUD MANAGER (APCM)                   │
│  https://alwaysprint.apps.iol.pe                                │
│                                                                  │
│  Backend FastAPI  ←→  PostgreSQL  ←→  Redis                    │
│  Frontend Next.js (Dashboard multi-tenant)                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Coherencia de Nombres

### Claves de Registro (HKLM)

| Clave | Tipo | Default | Descripción |
|---|---|---|---|
| `CorporateQueueName` | String | `""` | Cola de impresión corporativa |
| `SearchTargets` | String (JSON) | `{"ips":"","ranges":""}` | IPs/CIDR de impresoras |
| `PendingTaskPollingMinutes` | DWORD | `3` | Intervalo de monitoreo local |
| `BootstrapDomains` | String (CSV) | `"robles.ai,iol.pe"` | Dominios para health check |
| `RoblesAiLicenseSerial` | String | `""` | Serial de licencia |
| `CloudEnabled` | DWORD | `0` | 1 = integración Cloud activa |
| `CloudApiUrl` | String | `""` | URL del backend APCM |
| `CloudLocale` | String | `""` | Override de idioma (vacío = auto) |

### Claves de Registro (HKCU) — credenciales de workstation

Ruta: `HKCU\SOFTWARE\Robles.AI\AlwaysPrint\Cloud`

| Clave | Tipo | Descripción |
|---|---|---|
| `WorkstationId` | String | UUID asignado por APCM al registrarse |
| `ConfigHash` | String | Hash SHA-256 de la última config descargada |
| `ConfigCachedAt` | String | ISO-8601 de cuándo se descargó la config |
| `LastConnectedAt` | String | ISO-8601 de la última conexión exitosa a APCM |

### Mensajes Named Pipe (nuevos para Cloud)

| Tipo | Dirección | Descripción |
|---|---|---|
| `CloudConfigurationReceived` | Tray → Service | Config descargada de APCM, aplicar en Registry |
| `ReportTelemetry` | Service → Tray | Evento de telemetría para enviar a APCM |
| `GetCloudStatus` | Tray → Service | Consultar estado de conexión Cloud |
| `CloudStatusResponse` | Service → Tray | Respuesta con estado Cloud actual |

### Campos de Configuración Cloud (descargados de APCM)

Estos campos forman parte de la `EffectiveConfig` que el Tray descarga:

| Campo | Tipo | Descripción |
|---|---|---|
| `corporate_queue_name` | string | Nombre de la cola corporativa |
| `search_targets` | object | `{ips: [], ranges: []}` |
| `pending_task_polling_minutes` | int | Intervalo de monitoreo |
| `bootstrap_domains` | string[] | Dominios de health check |
| `connectivity_checks` | object[] | Checks de conectividad configurados |
| `locale` | string | Idioma override (vacío = auto) |
| `telemetry_enabled` | bool | Habilitar envío de telemetría |
| `telemetry_interval_seconds` | int | Intervalo de envío de telemetría |

### Checks de Conectividad (configurados en portal)

```json
{
  "connectivity_checks": [
    { "id": "check-1", "type": "http", "url": "https://servidor.org/health", "timeout_ms": 5000 },
    { "id": "check-2", "type": "tcp",  "host": "192.168.1.1", "port": 515, "timeout_ms": 3000 },
    { "id": "check-3", "type": "ping", "host": "8.8.8.8", "timeout_ms": 2000 },
    { "id": "check-4", "type": "dns",  "hostname": "servidor.org", "timeout_ms": 3000 }
  ]
}
```

### Protocolo WebSocket (Tray ↔ APCM)

**Tray → APCM:**

| Tipo | Payload | Descripción |
|---|---|---|
| `register` | `{ip_private, hostname, os_serial, current_user, locale, client_version}` | Registro inicial |
| `pong` | — | Respuesta a ping del servidor |
| `status_update` | `{contingency_active, current_user}` | Cambio de estado |
| `config_change_report` | `{applied: bool, config_hash: string}` | Confirmación de config aplicada |
| `telemetry` | `{queue_status, disconnection_log, jobs_identified, avg_release_time_ms}` | Telemetría periódica |
| `connectivity_result` | `{check_id, success, latency_ms, error?}` | Resultado de check de conectividad |
| `command_result` | `{command_id, success, output?}` | Resultado de comando remoto |

**APCM → Tray:**

| Tipo | Payload | Descripción |
|---|---|---|
| `ping` | — | Keep-alive (cada 30 s) |
| `config_update` | `{config_hash}` | Hay nueva config disponible |
| `message` | `{message_id, content, severity}` | Mensaje del admin |
| `command` | `{command_id, command_type, parameters}` | Comando remoto |

---

## Fases de Desarrollo

Ver documentos individuales por fase:

- **[PHASE-1-FOUNDATION.md](./PHASE-1-FOUNDATION.md)** — Fundamentos: config Cloud, i18n, cache offline
- **[PHASE-2-CLOUD-CONNECT.md](./PHASE-2-CLOUD-CONNECT.md)** — Conexión WebSocket, registro, heartbeat
- **[PHASE-3-CONFIG-SYNC.md](./PHASE-3-CONFIG-SYNC.md)** — Sincronización de configuración por hash
- **[PHASE-4-TELEMETRY.md](./PHASE-4-TELEMETRY.md)** — Telemetría, monitoreo de conectividad
- **[PHASE-5-RESILIENCE.md](./PHASE-5-RESILIENCE.md)** — Resiliencia offline, notificaciones, modo degradado
- **[PHASE-6-PORTAL.md](./PHASE-6-PORTAL.md)** — Mejoras al portal Cloud para soportar nuevas capacidades

---

## Convenciones para Desarrolladores

### Idioma del código
- Comentarios técnicos: **inglés**
- Mensajes de log y UI: **español** (i18n via archivos de recursos)
- Nombres de variables/métodos: **inglés** (camelCase/PascalCase según C#/Python)

### Reglas de arquitectura
- El **Service** nunca accede a Internet. Todo lo que necesite de la nube lo recibe del Tray por Named Pipe.
- El **Tray** nunca escribe en `HKLM`. Solo el Service escribe en `HKLM` (requiere LocalSystem).
- El **Tray** guarda sus propias credenciales Cloud en `HKCU`.
- La configuración descargada de APCM se aplica al Service vía mensaje `CloudConfigurationReceived`.
- El hash de configuración se almacena en `HKCU` y se compara antes de descargar.

### Gestión de errores
- Toda operación de red en el Tray debe tener timeout explícito.
- Los errores de red no deben propagar excepciones al hilo UI — usar try/catch con log.
- El modo offline no es un error: es un estado válido con comportamiento definido.

---

© 2026 Inversiones On Line SAC — Robles.AI  
Prohibida la utilización sin autorización.
