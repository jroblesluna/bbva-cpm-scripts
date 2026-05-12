# Fase 1 — Fundamentos: Config Cloud, i18n, Cache Offline

**Prerrequisito**: ninguno  
**Entregable**: Client compila y funciona igual que hoy, pero con la infraestructura base para las fases siguientes  
**Estimación**: 3–5 días

---

## Objetivo

Preparar el Client (Shared + Service + Tray) con:
1. Campos de configuración Cloud en `AppConfiguration` y `RegistryConfigManager`
2. Sistema i18n en el Tray (detección automática de locale Windows + override)
3. Estructura de cache offline en `HKCU`
4. Mensajes Named Pipe nuevos para Cloud
5. Payloads nuevos en `Payloads.cs`

Esta fase **no conecta con la nube** — solo prepara la infraestructura interna.

---

## Tareas

### 1.1 — `AppConfiguration.cs` — Agregar campos Cloud

**Archivo**: `AlwaysPrintProject/Client/AlwaysPrint.Shared/Configuration/AppConfiguration.cs`

Agregar a la clase `AppConfiguration`:

```csharp
// === INTEGRACIÓN CLOUD ===
public bool   CloudEnabled  { get; set; } = false;
public string CloudApiUrl   { get; set; } = string.Empty;
public string CloudLocale   { get; set; } = string.Empty;  // vacío = auto-detect
```

Agregar clase nueva `ConnectivityCheck`:

```csharp
public class ConnectivityCheck
{
    [JsonProperty("id")]
    public string Id { get; set; } = string.Empty;

    /// <summary>Tipo: "http" | "tcp" | "ping" | "dns"</summary>
    [JsonProperty("type")]
    public string Type { get; set; } = "http";

    [JsonProperty("url")]
    public string? Url { get; set; }          // para type=http

    [JsonProperty("host")]
    public string? Host { get; set; }         // para type=tcp, ping, dns

    [JsonProperty("hostname")]
    public string? Hostname { get; set; }     // para type=dns

    [JsonProperty("port")]
    public int? Port { get; set; }            // para type=tcp

    [JsonProperty("timeout_ms")]
    public int TimeoutMs { get; set; } = 5000;
}
```

Agregar a `AppConfiguration`:

```csharp
public List<ConnectivityCheck> ConnectivityChecks { get; set; } = new List<ConnectivityCheck>();
public bool   TelemetryEnabled         { get; set; } = true;
public int    TelemetryIntervalSeconds { get; set; } = 300;  // 5 minutos
```

---

### 1.2 — `RegistryConfigManager.cs` — Leer/escribir campos Cloud

**Archivo**: `AlwaysPrintProject/Client/AlwaysPrint.Shared/Configuration/RegistryConfigManager.cs`

En `Load()`, agregar lectura de campos Cloud:

```csharp
cfg.CloudEnabled = Convert.ToInt32(key.GetValue("CloudEnabled", 0)) == 1;
cfg.CloudApiUrl  = key.GetValue("CloudApiUrl",  string.Empty) as string ?? string.Empty;
cfg.CloudLocale  = key.GetValue("CloudLocale",  string.Empty) as string ?? string.Empty;

var rawChecks = key.GetValue("ConnectivityChecks", null) as string;
if (!string.IsNullOrWhiteSpace(rawChecks))
    cfg.ConnectivityChecks = JsonConvert.DeserializeObject<List<ConnectivityCheck>>(rawChecks!)
                             ?? new List<ConnectivityCheck>();

cfg.TelemetryEnabled         = Convert.ToInt32(key.GetValue("TelemetryEnabled", 1)) == 1;
cfg.TelemetryIntervalSeconds = Math.Max(60, Convert.ToInt32(key.GetValue("TelemetryIntervalSeconds", 300)));
```

En `Save()`, agregar escritura:

```csharp
key.SetValue("CloudEnabled",  cfg.CloudEnabled  ? 1 : 0,                    RegistryValueKind.DWord);
key.SetValue("CloudApiUrl",   cfg.CloudApiUrl   ?? string.Empty,             RegistryValueKind.String);
key.SetValue("CloudLocale",   cfg.CloudLocale   ?? string.Empty,             RegistryValueKind.String);
key.SetValue("ConnectivityChecks",
    JsonConvert.SerializeObject(cfg.ConnectivityChecks ?? new List<ConnectivityCheck>()),
    RegistryValueKind.String);
key.SetValue("TelemetryEnabled",         cfg.TelemetryEnabled ? 1 : 0,      RegistryValueKind.DWord);
key.SetValue("TelemetryIntervalSeconds", cfg.TelemetryIntervalSeconds,       RegistryValueKind.DWord);
```

En `EnsureDefaults()`, agregar:

```csharp
SetIfMissing(key, "CloudEnabled",              0,             RegistryValueKind.DWord);
SetIfMissing(key, "CloudApiUrl",               string.Empty,  RegistryValueKind.String);
SetIfMissing(key, "CloudLocale",               string.Empty,  RegistryValueKind.String);
SetIfMissing(key, "ConnectivityChecks",        "[]",          RegistryValueKind.String);
SetIfMissing(key, "TelemetryEnabled",          1,             RegistryValueKind.DWord);
SetIfMissing(key, "TelemetryIntervalSeconds",  300,           RegistryValueKind.DWord);
```

---

### 1.3 — `CloudCredentialsManager.cs` — Nuevo archivo en Shared

**Archivo nuevo**: `AlwaysPrintProject/Client/AlwaysPrint.Shared/Configuration/CloudCredentialsManager.cs`

Gestiona las credenciales de workstation en `HKCU` (no requiere admin):

```csharp
namespace AlwaysPrint.Shared.Configuration
{
    /// <summary>
    /// Gestiona credenciales Cloud de la workstation en HKCU.
    /// No requiere privilegios de administrador.
    /// </summary>
    public class CloudCredentialsManager
    {
        public const string RegistryPath = @"SOFTWARE\Robles.AI\AlwaysPrint\Cloud";

        public string? WorkstationId    { get; private set; }
        public string? ConfigHash       { get; private set; }
        public DateTime? ConfigCachedAt { get; private set; }
        public DateTime? LastConnectedAt{ get; private set; }

        public void Load() { /* leer de HKCU */ }
        public void SaveWorkstationId(string id) { /* escribir en HKCU */ }
        public void SaveConfigHash(string hash, DateTime cachedAt) { /* escribir en HKCU */ }
        public void SaveLastConnected(DateTime connectedAt) { /* escribir en HKCU */ }
        public bool IsRegistered => !string.IsNullOrEmpty(WorkstationId);
    }
}
```

---

### 1.4 — `MessageType.cs` — Agregar tipos Cloud

**Archivo**: `AlwaysPrintProject/Client/AlwaysPrint.Shared/Messages/MessageType.cs`

```csharp
// Cloud integration
CloudConfigurationReceived,   // Tray → Service: aplicar config descargada de APCM
ReportTelemetry,              // Service → Tray: evento de telemetría para enviar
GetCloudStatus,               // Tray → Service: consultar estado Cloud
CloudStatusResponse,          // Service → Tray: respuesta con estado Cloud
```

---

### 1.5 — `Payloads.cs` — Agregar payloads Cloud

**Archivo**: `AlwaysPrintProject/Client/AlwaysPrint.Shared/Messages/Payloads.cs`

```csharp
// === Cloud Payloads ===

public class CloudConfigurationReceivedPayload
{
    [JsonProperty("configuration")]
    public AppConfiguration Configuration { get; set; } = new AppConfiguration();

    [JsonProperty("configHash")]
    public string ConfigHash { get; set; } = string.Empty;

    [JsonProperty("source")]
    public string Source { get; set; } = "cloud";  // "cloud" | "cache"
}

public class TelemetryPayload
{
    [JsonProperty("queueStatus")]
    public string QueueStatus { get; set; } = string.Empty;  // "ok" | "missing" | "error"

    [JsonProperty("contingencyActive")]
    public bool ContingencyActive { get; set; }

    [JsonProperty("jobsIdentified")]
    public int JobsIdentified { get; set; }

    [JsonProperty("avgReleaseTimeMs")]
    public long? AvgReleaseTimeMs { get; set; }

    [JsonProperty("disconnectionLog")]
    public List<DisconnectionEvent> DisconnectionLog { get; set; } = new List<DisconnectionEvent>();
}

public class DisconnectionEvent
{
    [JsonProperty("startedAt")]
    public string StartedAt { get; set; } = string.Empty;

    [JsonProperty("reconnectedAt")]
    public string? ReconnectedAt { get; set; }

    [JsonProperty("durationSeconds")]
    public long? DurationSeconds { get; set; }
}

public class CloudStatusResponsePayload
{
    [JsonProperty("isConnected")]
    public bool IsConnected { get; set; }

    [JsonProperty("lastConnectedAt")]
    public string? LastConnectedAt { get; set; }

    [JsonProperty("configHash")]
    public string? ConfigHash { get; set; }

    [JsonProperty("usingCachedConfig")]
    public bool UsingCachedConfig { get; set; }
}
```

---

### 1.6 — Sistema i18n en el Tray

**Carpeta nueva**: `AlwaysPrintProject/Client/AlwaysPrintTray/Resources/`

Crear archivos de recursos:
- `Strings.resx` — inglés (default)
- `Strings.es.resx` — español
- `Strings.en.resx` — inglés explícito

**Clase nueva**: `AlwaysPrintProject/Client/AlwaysPrintTray/Localization/LocalizationManager.cs`

```csharp
namespace AlwaysPrintTray.Localization
{
    /// <summary>
    /// Gestiona el idioma del Tray.
    /// Prioridad: override de config Cloud > override local (HKCU) > locale del SO.
    /// </summary>
    public static class LocalizationManager
    {
        private static CultureInfo _current = CultureInfo.CurrentUICulture;

        /// <summary>Idiomas soportados: "es", "en"</summary>
        public static readonly string[] SupportedLocales = { "es", "en" };

        public static void Initialize(string? localeOverride = null)
        {
            // Aplicar override si es válido, si no usar locale del SO
        }

        public static string Get(string key) { /* retornar string localizado */ }

        public static string CurrentLocale => _current.TwoLetterISOLanguageName;
    }
}
```

**Strings mínimos para Fase 1** (en ambos idiomas):
- `TrayTooltip` — "AlwaysPrint"
- `MenuAbout` — "Acerca de" / "About"
- `MenuConfiguration` — "Configuración de Valores" / "Configuration"
- `MenuExit` — "Salir" / "Exit"
- `BalloonInitOk` — "Inicializado correctamente ({0})." / "Initialized successfully ({0})."
- `BalloonInitFail` — "Operando en modo local." / "Operating in local mode."
- `BalloonServiceNotRunning` — "El servicio no está en ejecución." / "Service is not running."
- `BalloonOfflineWarning` — "Usando configuración guardada. Sin conexión a la nube." / "Using cached config. No cloud connection."

---

### 1.7 — `ConfigurationForm.cs` — Agregar campos Cloud

Agregar al formulario de configuración:
- Checkbox `CloudEnabled`
- TextBox `CloudApiUrl`
- ComboBox `CloudLocale` (Auto, Español, English)

---

### 1.8 — `Product.wxs` — Agregar valores por defecto Cloud

```xml
<RegistryValue Name="CloudEnabled"              Type="integer" Value="0" />
<RegistryValue Name="CloudApiUrl"               Type="string"  Value="" />
<RegistryValue Name="CloudLocale"               Type="string"  Value="" />
<RegistryValue Name="ConnectivityChecks"        Type="string"  Value="[]" />
<RegistryValue Name="TelemetryEnabled"          Type="integer" Value="1" />
<RegistryValue Name="TelemetryIntervalSeconds"  Type="integer" Value="300" />
```

---

## Criterios de Aceptación

- [ ] `dotnet build AlwaysPrint.sln -c Release --nologo` → 0 errores, 0 advertencias
- [ ] `AppConfiguration` tiene todos los campos Cloud
- [ ] `RegistryConfigManager` lee y escribe todos los campos Cloud
- [ ] `CloudCredentialsManager` lee/escribe `HKCU` sin requerir admin
- [ ] `MessageType` tiene los 4 nuevos tipos Cloud
- [ ] `Payloads.cs` tiene los 4 nuevos payloads Cloud
- [ ] El Tray muestra el menú en español cuando el locale de Windows es `es-*`
- [ ] El Tray muestra el menú en inglés cuando el locale es cualquier otro
- [ ] `ConfigurationForm` muestra los campos Cloud (aunque no conecte aún)
- [ ] `Product.wxs` incluye los nuevos valores de registro
- [ ] `build.ps1` genera MSI sin errores

---

## Notas para el Desarrollador

- `CloudCredentialsManager` escribe en `HKCU`, no en `HKLM`. No necesita pasar por el Service.
- Los archivos `.resx` deben estar marcados como `EmbeddedResource` en el `.csproj`.
- `LocalizationManager.Initialize()` se llama en `Program.Main()` antes de crear `TrayApplicationContext`.
- El locale override de la config Cloud se aplica **después** del bootstrap, cuando se descarga la config. En Fase 1 solo se implementa la detección del SO.
- No implementar la conexión WebSocket en esta fase — solo la infraestructura.
