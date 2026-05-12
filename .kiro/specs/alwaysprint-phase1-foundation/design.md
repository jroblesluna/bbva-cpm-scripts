# Design Document — Fase 1: Fundamentos de Integración Cloud

## Overview

La Fase 1 extiende el Client de AlwaysPrint (C# .NET 4.8) con la infraestructura interna necesaria para la integración futura con AlwaysPrint Cloud Manager (APCM). No se conecta a la nube en esta fase — solo se prepara el terreno. Los cambios se distribuyen en tres proyectos: `AlwaysPrint.Shared`, `AlwaysPrintTray` y el instalador WiX (`Product.wxs`). `AlwaysPrintService` no requiere cambios de código en esta fase.

## Architecture

### Componentes afectados

```
AlwaysPrint.Shared/
├── Configuration/
│   ├── AppConfiguration.cs          ← MODIFICAR: agregar campos Cloud + ConnectivityCheck + Validate()
│   ├── RegistryConfigManager.cs     ← MODIFICAR: Load/Save/EnsureDefaults para campos Cloud
│   └── CloudCredentialsManager.cs   ← CREAR: gestión de HKCU
└── Messages/
    ├── MessageType.cs               ← MODIFICAR: agregar 4 tipos Cloud
    └── Payloads.cs                  ← MODIFICAR: agregar 4 payloads Cloud

AlwaysPrintTray/
├── Localization/
│   └── LocalizationManager.cs       ← CREAR: sistema i18n estático
├── Resources/
│   ├── Strings.resx                 ← CREAR: strings en inglés (default)
│   └── Strings.es.resx              ← CREAR: strings en español
├── Forms/
│   └── ConfigurationForm.cs         ← MODIFICAR: agregar controles Cloud
├── Program.cs                       ← MODIFICAR: llamar LocalizationManager.Initialize()
├── TrayApplicationContext.cs        ← MODIFICAR: usar LocalizationManager en menú y balloons
└── AlwaysPrintTray.csproj           ← MODIFICAR: agregar EmbeddedResource para .resx

Product.wxs                          ← MODIFICAR: agregar 6 RegistryValue Cloud
```

### Reglas de arquitectura (invariantes)

| Regla | Componente |
|---|---|
| Solo `AlwaysPrintService` escribe en `HKLM` | `RegistryConfigManager.Save()` solo lo llama el Service |
| Solo `AlwaysPrintTray` escribe en `HKCU` | `CloudCredentialsManager` usa `Registry.CurrentUser` exclusivamente |
| El Tray nunca llama `RegistryConfigManager.Save()` directamente | Toda persistencia HKLM va por Named Pipe → `UpdateConfiguration` |
| Todos los logs en español | `AlwaysPrintLogger` con mensajes en español |
| Sin `Console.WriteLine` | Todo output diagnóstico por `AlwaysPrintLogger` |
| `AlwaysPrintService` no referencia `LocalizationManager` | `LocalizationManager` vive solo en `AlwaysPrintTray` |

## Components

### 1. `AppConfiguration` + `ConnectivityCheck`

**Archivo**: `AlwaysPrint.Shared/Configuration/AppConfiguration.cs`

Agregar a la clase `AppConfiguration` existente:

```csharp
// === INTEGRACIÓN CLOUD ===
public bool   CloudEnabled             { get; set; } = false;
public string CloudApiUrl              { get; set; } = string.Empty;
public string CloudLocale              { get; set; } = string.Empty;
public List<ConnectivityCheck> ConnectivityChecks { get; set; } = new List<ConnectivityCheck>();
public bool   TelemetryEnabled         { get; set; } = true;
public int    TelemetryIntervalSeconds { get; set; } = 300;

public void Validate()
{
    if (TelemetryIntervalSeconds < 60)
        throw new ArgumentOutOfRangeException(nameof(TelemetryIntervalSeconds),
            "TelemetryIntervalSeconds debe ser >= 60.");
    if (!string.IsNullOrEmpty(CloudApiUrl) && !Uri.IsWellFormedUriString(CloudApiUrl, UriKind.Absolute))
        throw new ArgumentException("CloudApiUrl debe ser una URI absoluta válida.", nameof(CloudApiUrl));
    foreach (var check in ConnectivityChecks ?? new List<ConnectivityCheck>())
    {
        if (check.Port.HasValue && (check.Port.Value < 0 || check.Port.Value > 65535))
            throw new ArgumentOutOfRangeException(nameof(check.Port),
                $"Port {check.Port.Value} fuera del rango 0-65535.");
        var validTypes = new[] { "http", "tcp", "ping", "dns" };
        if (!Array.Exists(validTypes, t => t == check.Type))
            throw new ArgumentException($"Tipo de check inválido: '{check.Type}'.", nameof(check.Type));
    }
}
```

Nueva clase `ConnectivityCheck` en el mismo archivo:

```csharp
public class ConnectivityCheck
{
    [JsonProperty("id")]         public string  Id        { get; set; } = string.Empty;
    [JsonProperty("type")]       public string  Type      { get; set; } = "http";
    [JsonProperty("url")]        public string? Url       { get; set; }
    [JsonProperty("host")]       public string? Host      { get; set; }
    [JsonProperty("hostname")]   public string? Hostname  { get; set; }
    [JsonProperty("port")]       public int?    Port      { get; set; }
    [JsonProperty("timeout_ms")] public int     TimeoutMs { get; set; } = 5000;
}
```

---

### 2. `RegistryConfigManager` — campos Cloud

**Archivo**: `AlwaysPrint.Shared/Configuration/RegistryConfigManager.cs`

Agregar en `Load()` (dentro del bloque `using (var key = ...)`):

```csharp
cfg.CloudEnabled  = Convert.ToInt32(key.GetValue("CloudEnabled",  0)) == 1;
cfg.CloudApiUrl   = key.GetValue("CloudApiUrl",  string.Empty) as string ?? string.Empty;
cfg.CloudLocale   = key.GetValue("CloudLocale",  string.Empty) as string ?? string.Empty;

var rawChecks = key.GetValue("ConnectivityChecks", null) as string;
cfg.ConnectivityChecks = string.IsNullOrWhiteSpace(rawChecks)
    ? new List<ConnectivityCheck>()
    : JsonConvert.DeserializeObject<List<ConnectivityCheck>>(rawChecks!) ?? new List<ConnectivityCheck>();

cfg.TelemetryEnabled         = Convert.ToInt32(key.GetValue("TelemetryEnabled",         1))   == 1;
cfg.TelemetryIntervalSeconds = Math.Max(60, Convert.ToInt32(key.GetValue("TelemetryIntervalSeconds", 300)));
```

Agregar en `Save()` (después de la llamada a `ValidateConfiguration`):

```csharp
// Llamar Validate() antes de escribir
cfg.Validate();

key.SetValue("CloudEnabled",             cfg.CloudEnabled  ? 1 : 0,                    RegistryValueKind.DWord);
key.SetValue("CloudApiUrl",              cfg.CloudApiUrl   ?? string.Empty,             RegistryValueKind.String);
key.SetValue("CloudLocale",              cfg.CloudLocale   ?? string.Empty,             RegistryValueKind.String);
key.SetValue("ConnectivityChecks",
    JsonConvert.SerializeObject(cfg.ConnectivityChecks ?? new List<ConnectivityCheck>()),
    RegistryValueKind.String);
key.SetValue("TelemetryEnabled",         cfg.TelemetryEnabled ? 1 : 0,                 RegistryValueKind.DWord);
key.SetValue("TelemetryIntervalSeconds", cfg.TelemetryIntervalSeconds,                  RegistryValueKind.DWord);
```

Agregar en `EnsureDefaults()`:

```csharp
SetIfMissing(key, "CloudEnabled",             0,             RegistryValueKind.DWord);
SetIfMissing(key, "CloudApiUrl",              string.Empty,  RegistryValueKind.String);
SetIfMissing(key, "CloudLocale",              string.Empty,  RegistryValueKind.String);
SetIfMissing(key, "ConnectivityChecks",       "[]",          RegistryValueKind.String);
SetIfMissing(key, "TelemetryEnabled",         1,             RegistryValueKind.DWord);
SetIfMissing(key, "TelemetryIntervalSeconds", 300,           RegistryValueKind.DWord);
```

---

### 3. `CloudCredentialsManager` — nuevo archivo

**Archivo**: `AlwaysPrint.Shared/Configuration/CloudCredentialsManager.cs`

```csharp
using System;
using Microsoft.Win32;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrint.Shared.Configuration
{
    /// <summary>
    /// Gestiona credenciales Cloud de la workstation en HKCU.
    /// No requiere privilegios de administrador.
    /// </summary>
    public class CloudCredentialsManager
    {
        public const string RegistryPath = @"SOFTWARE\Robles.AI\AlwaysPrint\Cloud";

        public string?   WorkstationId   { get; private set; }
        public string?   ConfigHash      { get; private set; }
        public DateTime? ConfigCachedAt  { get; private set; }
        public DateTime? LastConnectedAt { get; private set; }

        public bool IsRegistered => !string.IsNullOrEmpty(WorkstationId);

        public void Load() { /* leer de HKCU, parsear ISO-8601, swallow exceptions */ }
        public void SaveWorkstationId(string id) { /* escribir en HKCU, actualizar propiedad */ }
        public void SaveConfigHash(string hash, DateTime cachedAt) { /* escribir en HKCU */ }
        public void SaveLastConnected(DateTime connectedAt) { /* escribir en HKCU */ }
    }
}
```

Todas las operaciones de registro usan `Registry.CurrentUser` y capturan excepciones con `AlwaysPrintLogger.WriteTrayError()`.

---

### 4. `MessageType` — 4 nuevos valores

**Archivo**: `AlwaysPrint.Shared/Messages/MessageType.cs`

```csharp
// Cloud integration
CloudConfigurationReceived,  // Tray → Service: aplicar config descargada de APCM
ReportTelemetry,             // Service → Tray: evento de telemetría para enviar
GetCloudStatus,              // Tray → Service: consultar estado Cloud
CloudStatusResponse,         // Service → Tray: respuesta con estado Cloud
```

---

### 5. `Payloads.cs` — 4 nuevos payloads

**Archivo**: `AlwaysPrint.Shared/Messages/Payloads.cs`

```csharp
public class CloudConfigurationReceivedPayload
{
    [JsonProperty("configuration")] public AppConfiguration Configuration { get; set; } = new AppConfiguration();
    [JsonProperty("configHash")]    public string ConfigHash { get; set; } = string.Empty;
    [JsonProperty("source")]        public string Source     { get; set; } = "cloud";
}

public class DisconnectionEvent
{
    [JsonProperty("startedAt")]      public string  StartedAt       { get; set; } = string.Empty;
    [JsonProperty("reconnectedAt")]  public string? ReconnectedAt   { get; set; }
    [JsonProperty("durationSeconds")]public long?   DurationSeconds { get; set; }
}

public class TelemetryPayload
{
    [JsonProperty("queueStatus")]       public string QueueStatus      { get; set; } = string.Empty;
    [JsonProperty("contingencyActive")] public bool   ContingencyActive { get; set; }
    [JsonProperty("jobsIdentified")]    public int    JobsIdentified   { get; set; }
    [JsonProperty("avgReleaseTimeMs")]  public long?  AvgReleaseTimeMs { get; set; }
    [JsonProperty("disconnectionLog")]  public List<DisconnectionEvent> DisconnectionLog { get; set; } = new List<DisconnectionEvent>();
}

public class CloudStatusResponsePayload
{
    [JsonProperty("isConnected")]      public bool    IsConnected      { get; set; }
    [JsonProperty("lastConnectedAt")]  public string? LastConnectedAt  { get; set; }
    [JsonProperty("configHash")]       public string? ConfigHash       { get; set; }
    [JsonProperty("usingCachedConfig")]public bool    UsingCachedConfig { get; set; }
}
```

---

### 6. `LocalizationManager` — sistema i18n

**Archivo**: `AlwaysPrintTray/Localization/LocalizationManager.cs`

```csharp
using System;
using System.Globalization;
using System.Resources;
using AlwaysPrint.Shared.Logging;

namespace AlwaysPrintTray.Localization
{
    public static class LocalizationManager
    {
        public static readonly string[] SupportedLocales = { "es", "en" };
        private static string _currentLocale = "en";
        private static ResourceManager? _rm;

        public static string CurrentLocale => _currentLocale;

        public static void Initialize(string? localeOverride = null)
        {
            string target = string.IsNullOrEmpty(localeOverride)
                ? CultureInfo.CurrentUICulture.TwoLetterISOLanguageName
                : localeOverride;

            _currentLocale = target.StartsWith("es", StringComparison.OrdinalIgnoreCase) ? "es" : "en";

            try
            {
                var culture = new CultureInfo(_currentLocale);
                _rm = new ResourceManager("AlwaysPrintTray.Resources.Strings",
                    typeof(LocalizationManager).Assembly);
                // Probar que el recurso carga correctamente
                _rm.GetString("TrayTooltip", culture);
            }
            catch (Exception ex)
            {
                AlwaysPrintLogger.WriteTrayError(
                    $"Error cargando recursos de idioma '{_currentLocale}'. Usando inglés. {ex.Message}");
                _currentLocale = "en";
                _rm = new ResourceManager("AlwaysPrintTray.Resources.Strings",
                    typeof(LocalizationManager).Assembly);
            }
        }

        public static string Get(string key)
        {
            try
            {
                var culture = new CultureInfo(_currentLocale);
                return _rm?.GetString(key, culture) ?? key;
            }
            catch
            {
                return key;
            }
        }
    }
}
```

**Strings mínimos** (en `Strings.resx` y `Strings.es.resx`):

| Key | Español | English |
|---|---|---|
| `TrayTooltip` | `AlwaysPrint` | `AlwaysPrint` |
| `MenuAbout` | `Acerca de` | `About` |
| `MenuConfiguration` | `Configuración de Valores` | `Configuration` |
| `MenuExit` | `Salir` | `Exit` |
| `BalloonInitOk` | `Inicializado correctamente ({0}).` | `Initialized successfully ({0}).` |
| `BalloonInitFail` | `Operando en modo local.` | `Operating in local mode.` |
| `BalloonServiceNotRunning` | `El servicio no está en ejecución.` | `Service is not running.` |
| `BalloonOfflineWarning` | `Usando configuración guardada. Sin conexión a la nube.` | `Using cached config. No cloud connection.` |

---

### 7. `TrayApplicationContext` — integración i18n

Cambios en `TrayApplicationContext.cs`:

- `BuildTrayIcon()`: usar `LocalizationManager.Get("MenuAbout")`, `Get("MenuConfiguration")`, `Get("MenuExit")` para labels del menú; `Get("TrayTooltip")` para el tooltip.
- `ShowBalloon()`: usar `LocalizationManager.Get(key)` para los textos de balloon.

---

### 8. `Program.cs` — llamar `Initialize()` antes del contexto

```csharp
// Antes de Application.Run(new TrayApplicationContext()):
LocalizationManager.Initialize();
```

---

### 9. `ConfigurationForm` — campos Cloud

Agregar tres controles al formulario existente:

- `CheckBox _chkCloudEnabled` — label: `"Integración Cloud habilitada"`
- `TextBox _txtCloudApiUrl` — label: `"URL del servidor Cloud (APCM):"`
- `ComboBox _cmbCloudLocale` — label: `"Idioma (locale):"` — items: `"Auto"/"Español"/"English"` → valores `""`/`"es"`/`"en"`

Actualizar `PopulateFields()` para leer los tres campos de `AppConfiguration`.
Actualizar `BtnSave_Click()` para incluir los tres campos en `UpdateConfigurationPayload`.
Validar que `CloudApiUrl` sea URI absoluta válida antes de enviar; mostrar error inline si no.

---

### 10. `Product.wxs` — valores de registro Cloud

Agregar dentro del `<RegistryKey Root="HKLM" Key="SOFTWARE\Robles.AI\AlwaysPrint">` existente:

```xml
<RegistryValue Name="CloudEnabled"             Type="integer" Value="0"   />
<RegistryValue Name="CloudApiUrl"              Type="string"  Value=""    />
<RegistryValue Name="CloudLocale"              Type="string"  Value=""    />
<RegistryValue Name="ConnectivityChecks"       Type="string"  Value="[]"  />
<RegistryValue Name="TelemetryEnabled"         Type="integer" Value="1"   />
<RegistryValue Name="TelemetryIntervalSeconds" Type="integer" Value="300" />
```

---

### 11. `AlwaysPrintTray.csproj` — recursos embebidos

```xml
<ItemGroup>
  <EmbeddedResource Include="Resources\Strings.resx"    />
  <EmbeddedResource Include="Resources\Strings.es.resx" />
</ItemGroup>
```

## Data Models

### Flujo de datos — configuración Cloud

```
HKLM (escrito por Service)
  └─ CloudEnabled, CloudApiUrl, CloudLocale,
     ConnectivityChecks, TelemetryEnabled, TelemetryIntervalSeconds
       ↑ RegistryConfigManager.Save(cfg)   [solo Service]
       ↓ RegistryConfigManager.Load()      [Service + Tray read-only]

HKCU (escrito por Tray)
  └─ WorkstationId, ConfigHash, ConfigCachedAt, LastConnectedAt
       ↑↓ CloudCredentialsManager           [solo Tray]

Named Pipe
  Tray → Service: UpdateConfiguration (con campos Cloud)
  Tray → Service: CloudConfigurationReceived (config descargada de APCM)
  Tray → Service: GetCloudStatus
  Service → Tray: CloudStatusResponse
  Service → Tray: ReportTelemetry
```

### Jerarquía de locale

```
1. localeOverride explícito (parámetro de Initialize)
2. CultureInfo.CurrentUICulture del SO Windows
3. Fallback a "en" si error al cargar recurso
```

## Error Handling

| Escenario | Comportamiento |
|---|---|
| `RegistryConfigManager.Load()` falla | Log warning en español, devolver `AppConfiguration` con defaults |
| `RegistryConfigManager.Save()` — `Validate()` lanza | Excepción propagada al caller (Service responde con `ErrorPayload`) |
| `CloudCredentialsManager` — cualquier excepción de registro | Log error en español, no propagar, propiedades quedan como estaban |
| `LocalizationManager.Initialize()` — falla carga de recurso español | Log error, fallback a inglés, continuar sin excepción |
| `LocalizationManager.Get(key)` — key no existe | Devolver el nombre del key como fallback |
| `ConfigurationForm` — `CloudApiUrl` inválida al guardar | Mostrar error inline, no enviar `UpdateConfigurationPayload` |
| `ConfigurationForm` — pipe falla al cargar config | Mostrar error en `_lblStatus`, controles Cloud en estado default |
