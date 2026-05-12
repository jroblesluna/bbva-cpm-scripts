# Fase 3 — Sincronización de Configuración por Hash

**Prerrequisito**: Fase 2 completada  
**Entregable**: El Tray descarga y aplica configuración de APCM solo cuando el hash cambia  
**Estimación**: 4–5 días

---

## Objetivo

Implementar el ciclo completo de sincronización de configuración:

1. Al conectar: comparar hash local vs hash del servidor
2. Si difieren: descargar `EffectiveConfig` y aplicarla al Service
3. Al recibir `config_update` por WebSocket: repetir el proceso
4. Persistir config descargada en `HKCU` como cache offline
5. Aplicar locale override si la config lo especifica

---

## Flujo de Sincronización

```
Tray conecta a APCM
    │
    ├─ Envía "register" con workstation_id
    │
    ▼
APCM responde con config_update { config_hash: "abc123" }
    │
    ├─ ¿config_hash == HKCU.ConfigHash?
    │     SÍ → no hacer nada
    │     NO → descargar config
    │
    ▼
GET /api/v1/workstations/{id}/config
    │
    ▼
Recibe EffectiveConfig (JSON)
    │
    ├─ Calcular SHA-256 del JSON recibido
    ├─ Guardar JSON en HKCU (cache offline)
    ├─ Guardar hash en HKCU.ConfigHash
    ├─ Guardar timestamp en HKCU.ConfigCachedAt
    │
    ▼
Enviar CloudConfigurationReceived al Service (Named Pipe)
    │
    ▼
Service aplica config en HKLM Registry
    │
    ▼
Tray envía config_change_report { applied: true, config_hash: "abc123" }
```

---

## Componentes

### 3.1 — `ConfigurationSync.cs`

**Archivo**: `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/ConfigurationSync.cs`

```csharp
namespace AlwaysPrintTray.Cloud
{
    /// <summary>
    /// Gestiona la descarga y aplicación de configuración desde APCM.
    ///
    /// La config se descarga solo si el hash del servidor difiere del hash local.
    /// La config descargada se persiste en HKCU como cache offline.
    /// </summary>
    public sealed class ConfigurationSync
    {
        public ConfigurationSync(
            string cloudApiUrl,
            string workstationId,
            CloudCredentialsManager credentials,
            PipeClient pipe,
            CloudWebSocketClient wsClient) { }

        /// <summary>
        /// Verifica si el hash del servidor difiere del local y descarga si es necesario.
        /// </summary>
        public bool SyncIfNeeded(string serverConfigHash) { }

        /// <summary>
        /// Fuerza descarga de config independientemente del hash.
        /// </summary>
        public bool ForceSync() { }

        /// <summary>
        /// Carga la config desde el cache HKCU (modo offline).
        /// Retorna null si no hay cache.
        /// </summary>
        public AppConfiguration? LoadFromCache() { }
    }
}
```

---

### 3.2 — Endpoint REST para descarga de config

**URL**: `GET {CloudApiUrl}/api/v1/workstations/{workstation_id}/config`

**Headers**: ninguno (autenticación por IP pública)

**Respuesta esperada** (EffectiveConfig del backend):

```json
{
  "corporate_queue_name": "LexmarkBBVA",
  "search_targets": { "ips": "192.168.1.10", "ranges": "192.168.1.0/24" },
  "pending_task_polling_minutes": 3,
  "bootstrap_domains": "robles.ai,iol.pe",
  "connectivity_checks": [
    { "id": "c1", "type": "http", "url": "https://servidor.org/health", "timeout_ms": 5000 }
  ],
  "locale": "",
  "telemetry_enabled": true,
  "telemetry_interval_seconds": 300
}
```

**Mapeo a `AppConfiguration`**:

| Campo JSON (snake_case) | Propiedad C# (PascalCase) |
|---|---|
| `corporate_queue_name` | `CorporateQueueName` |
| `search_targets.ips` | `SearchTargets.Ips` |
| `search_targets.ranges` | `SearchTargets.Ranges` |
| `pending_task_polling_minutes` | `PendingTaskPollingMinutes` |
| `bootstrap_domains` | `BootstrapDomains` |
| `connectivity_checks` | `ConnectivityChecks` |
| `locale` | `CloudLocale` |
| `telemetry_enabled` | `TelemetryEnabled` |
| `telemetry_interval_seconds` | `TelemetryIntervalSeconds` |

---

### 3.3 — Cache Offline en HKCU

**Archivo**: `AlwaysPrintProject/Client/AlwaysPrint.Shared/Configuration/CloudCredentialsManager.cs`

Agregar métodos:

```csharp
/// <summary>Guarda el JSON de config descargado como cache offline.</summary>
public void SaveConfigCache(string configJson, string configHash)
{
    using var key = Registry.CurrentUser.CreateSubKey(RegistryPath, writable: true);
    if (key == null) return;
    key.SetValue("ConfigJson",     configJson,              RegistryValueKind.String);
    key.SetValue("ConfigHash",     configHash,              RegistryValueKind.String);
    key.SetValue("ConfigCachedAt", DateTime.UtcNow.ToString("o"), RegistryValueKind.String);
}

/// <summary>Carga el JSON de config del cache. Retorna null si no hay cache.</summary>
public string? LoadConfigCache()
{
    using var key = Registry.CurrentUser.OpenSubKey(RegistryPath, writable: false);
    return key?.GetValue("ConfigJson") as string;
}
```

---

### 3.4 — Cálculo de Hash

Usar SHA-256 del JSON normalizado (sin espacios extra):

```csharp
private static string ComputeHash(string json)
{
    using var sha = System.Security.Cryptography.SHA256.Create();
    byte[] bytes = System.Text.Encoding.UTF8.GetBytes(json);
    byte[] hash  = sha.ComputeHash(bytes);
    return BitConverter.ToString(hash).Replace("-", "").ToLowerInvariant();
}
```

---

### 3.5 — Aplicar Config al Service

Cuando se descarga config nueva, enviar al Service:

```csharp
var payload = new CloudConfigurationReceivedPayload
{
    Configuration = parsedConfig,
    ConfigHash    = newHash,
    Source        = "cloud"
};
var response = _pipe.Send(PipeMessage.Create(MessageType.CloudConfigurationReceived, payload));
```

El Service, al recibir `CloudConfigurationReceived`:
1. Llama a `_registry.Save(payload.Configuration)`
2. Responde con `AckPayload { Success = true }`
3. Loggea con `EvtConfigSaved`

Agregar handler en `MessageDispatcher.cs`:

```csharp
MessageType.CloudConfigurationReceived => HandleCloudConfigurationReceived(request),
```

---

### 3.6 — Aplicar Locale Override

Después de aplicar la config, si `CloudLocale` no está vacío:

```csharp
if (!string.IsNullOrEmpty(parsedConfig.CloudLocale))
    LocalizationManager.Initialize(parsedConfig.CloudLocale);
```

---

### 3.7 — Confirmar al Servidor

Después de aplicar exitosamente:

```csharp
_wsClient.Send("config_change_report", new
{
    applied     = true,
    config_hash = newHash
});
```

Si falla la aplicación:

```csharp
_wsClient.Send("config_change_report", new
{
    applied       = false,
    config_hash   = newHash,
    error_message = ex.Message
});
```

---

### 3.8 — Backend: endpoint de config (verificar)

El backend ya tiene `GET /api/v1/workstations/{id}/config` que devuelve `EffectiveConfigResponse`.

**Verificar** que el schema incluye todos los campos nuevos (`connectivity_checks`, `locale`, `telemetry_enabled`, `telemetry_interval_seconds`). Si no, agregar a:
- `AlwaysPrintProject/Cloud/backend/app/models/config.py`
- `AlwaysPrintProject/Cloud/backend/app/schemas/config.py`
- Migración Alembic correspondiente

---

## Criterios de Aceptación

- [ ] Al conectar con hash igual al local: no se hace ninguna petición HTTP adicional
- [ ] Al conectar con hash diferente: se descarga la config y se aplica al Service
- [ ] Al recibir `config_update` por WebSocket: se repite el proceso de comparación
- [ ] La config descargada se persiste en `HKCU` como JSON
- [ ] Si el Service rechaza la config (AckPayload.Success=false): se loggea el error y se envía `config_change_report { applied: false }`
- [ ] El locale override de la config se aplica al `LocalizationManager`
- [ ] El hash se calcula con SHA-256 del JSON normalizado
- [ ] En modo offline (sin conexión): `LoadFromCache()` retorna la última config descargada

---

## Notas para el Desarrollador

- El JSON de la config se guarda **tal como viene del servidor** (sin re-serializar) para que el hash sea reproducible.
- El hash se calcula sobre el JSON crudo del servidor, no sobre el objeto deserializado.
- Si el JSON del servidor cambia el orden de campos, el hash cambiará aunque los valores sean iguales. El servidor debe garantizar orden determinístico (FastAPI con Pydantic lo hace por defecto).
- La petición HTTP de descarga usa el mismo `HttpClient` estático de `DomainHealthChecker` — no crear uno nuevo.
- El Service no necesita saber si la config viene de la nube o del usuario — `CloudConfigurationReceived` y `UpdateConfiguration` producen el mismo efecto en el Registry.
