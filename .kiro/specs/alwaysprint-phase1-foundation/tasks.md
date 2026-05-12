# Implementation Tasks — Fase 1: Fundamentos de Integración Cloud

## Task Dependency Graph

```
T1 (AppConfiguration + ConnectivityCheck)
  └─► T2 (RegistryConfigManager campos Cloud)
  └─► T3 (CloudCredentialsManager)
  └─► T5 (Payloads Cloud)
T4 (MessageType Cloud)
  └─► T5 (Payloads Cloud)
T5 (Payloads Cloud)
  └─► T9 (MessageDispatcher handler CloudConfigurationReceived)
T6 (LocalizationManager + .resx)
  └─► T7 (TrayApplicationContext i18n)
  └─► T8 (Program.cs Initialize)
T7 (TrayApplicationContext i18n)
  └─► T8 (Program.cs Initialize)
T1, T2, T3, T4, T5 ─► T10 (ConfigurationForm campos Cloud)
T1, T2 ─► T11 (Product.wxs + csproj)
T1..T11 ─► T12 (Verificación de compilación)
```

---

## Tasks

- [x] 1. Agregar campos Cloud y clase `ConnectivityCheck` a `AppConfiguration`
  - Archivo: `AlwaysPrintProject/Client/AlwaysPrint.Shared/Configuration/AppConfiguration.cs`
  - Agregar propiedades `CloudEnabled` (bool, default false), `CloudApiUrl` (string, default ""), `CloudLocale` (string, default ""), `ConnectivityChecks` (List<ConnectivityCheck>, default vacío), `TelemetryEnabled` (bool, default true), `TelemetryIntervalSeconds` (int, default 300)
  - Crear clase `ConnectivityCheck` en el mismo archivo con propiedades `Id`, `Type`, `Url`, `Host`, `Hostname`, `Port`, `TimeoutMs` y atributos `[JsonProperty]` en snake_case
  - Agregar método público `Validate()` que lanza `ArgumentOutOfRangeException` si `TelemetryIntervalSeconds < 60`, `ArgumentException` si `CloudApiUrl` no es URI absoluta válida, `ArgumentOutOfRangeException` si algún `Port` está fuera de 0–65535, y `ArgumentException` si algún `Type` no es `"http"`, `"tcp"`, `"ping"` o `"dns"`
  - Preservar todas las propiedades existentes sin modificación
  - Requisitos: 1.1–1.14

- [x] 2. Extender `RegistryConfigManager` con lectura/escritura de campos Cloud
  - Archivo: `AlwaysPrintProject/Client/AlwaysPrint.Shared/Configuration/RegistryConfigManager.cs`
  - En `Load()`: leer `CloudEnabled` (DWORD, default false), `CloudApiUrl` (String, default ""), `CloudLocale` (String, default ""), `ConnectivityChecks` (JSON String, default lista vacía con manejo de JSON malformado), `TelemetryEnabled` (DWORD, default true), `TelemetryIntervalSeconds` (DWORD, aplicar `Math.Max(60, value)`, default 300)
  - En `Save()`: llamar `cfg.Validate()` antes de escribir; si lanza, no escribir nada; escribir los 6 campos Cloud con los tipos de registro correctos (DWord/String)
  - En `EnsureDefaults()`: agregar `SetIfMissing` para los 6 campos Cloud con sus valores por defecto
  - Preservar todo el comportamiento existente de `Load()`, `Save()` y `EnsureDefaults()` para los campos pre-existentes
  - Requisitos: 2.1–2.15, 10.2, 10.5, 10.7

- [x] 3. Crear `CloudCredentialsManager` para gestión de credenciales en HKCU
  - Archivo nuevo: `AlwaysPrintProject/Client/AlwaysPrint.Shared/Configuration/CloudCredentialsManager.cs`
  - Clase con propiedades de solo lectura: `WorkstationId` (string?), `ConfigHash` (string?), `ConfigCachedAt` (DateTime?), `LastConnectedAt` (DateTime?)
  - Propiedad `IsRegistered` que retorna `true` si `WorkstationId` no es null ni vacío
  - Método `Load()`: leer los 4 valores de `HKCU\SOFTWARE\Robles.AI\AlwaysPrint\Cloud`; parsear fechas ISO-8601; si la clave no existe o hay error, dejar propiedades en null sin lanzar excepción
  - Método `SaveWorkstationId(string id)`: escribir en HKCU y actualizar propiedad en memoria
  - Método `SaveConfigHash(string hash, DateTime cachedAt)`: escribir hash y fecha ISO-8601 en HKCU
  - Método `SaveLastConnected(DateTime connectedAt)`: escribir fecha ISO-8601 en HKCU
  - Todas las excepciones de registro: capturar, loggear con `AlwaysPrintLogger.WriteTrayError()` en español, no propagar
  - Usar `Registry.CurrentUser` exclusivamente — nunca `Registry.LocalMachine`
  - Requisitos: 3.1–3.14, 10.1, 10.4

- [x] 4. Agregar 4 nuevos tipos Cloud al enum `MessageType`
  - Archivo: `AlwaysPrintProject/Client/AlwaysPrint.Shared/Messages/MessageType.cs`
  - Agregar al final del enum: `CloudConfigurationReceived`, `ReportTelemetry`, `GetCloudStatus`, `CloudStatusResponse`
  - Preservar todos los valores existentes sin modificación ni renumeración
  - Verificar que no haya valores enteros duplicados
  - Requisitos: 4.1–4.6

- [x] 5. Agregar 4 nuevos payloads Cloud a `Payloads.cs`
  - Archivo: `AlwaysPrintProject/Client/AlwaysPrint.Shared/Messages/Payloads.cs`
  - Agregar clase `CloudConfigurationReceivedPayload` con propiedades `Configuration` (AppConfiguration), `ConfigHash` (string, default ""), `Source` (string, default "cloud"), todas con `[JsonProperty]`
  - Agregar clase `DisconnectionEvent` con propiedades `StartedAt` (string), `ReconnectedAt` (string?), `DurationSeconds` (long?), todas con `[JsonProperty]`
  - Agregar clase `TelemetryPayload` con propiedades `QueueStatus` (string), `ContingencyActive` (bool), `JobsIdentified` (int), `AvgReleaseTimeMs` (long?), `DisconnectionLog` (List<DisconnectionEvent>, default vacío), todas con `[JsonProperty]`
  - Agregar clase `CloudStatusResponsePayload` con propiedades `IsConnected` (bool), `LastConnectedAt` (string?), `ConfigHash` (string?), `UsingCachedConfig` (bool), todas con `[JsonProperty]`
  - Preservar todas las clases de payload existentes sin modificación
  - Requisitos: 5.1–5.8

- [x] 6. Crear sistema i18n: `LocalizationManager` y archivos `.resx`
  - Crear carpeta `AlwaysPrintProject/Client/AlwaysPrintTray/Resources/`
  - Crear `Strings.resx` (inglés, default) con los 8 strings: `TrayTooltip`, `MenuAbout`, `MenuConfiguration`, `MenuExit`, `BalloonInitOk`, `BalloonInitFail`, `BalloonServiceNotRunning`, `BalloonOfflineWarning`
  - Crear `Strings.es.resx` (español) con los mismos 8 keys en español
  - Crear carpeta `AlwaysPrintProject/Client/AlwaysPrintTray/Localization/`
  - Crear `LocalizationManager.cs` como clase `static` con: `SupportedLocales` (string[]), `CurrentLocale` (string), `Initialize(string? localeOverride = null)`, `Get(string key)`
  - `Initialize()` sin override: detectar locale de `CultureInfo.CurrentUICulture`; si empieza con "es" → español; si no → inglés
  - `Initialize()` con override: usar el override ignorando el locale del SO
  - Si falla la carga del recurso español: fallback a inglés, loggear con `AlwaysPrintLogger.WriteTrayError()` en español, no lanzar excepción
  - `Get(key)` con key inexistente: devolver el nombre del key como fallback sin lanzar excepción
  - Sin `Console.WriteLine` — todo output por `AlwaysPrintLogger`
  - Actualizar `AlwaysPrintTray.csproj`: agregar `<EmbeddedResource>` para `Strings.resx` y `Strings.es.resx`
  - Requisitos: 6.1–6.19, 9.5, 9.6, 10.6, 10.8

- [x] 7. Integrar `LocalizationManager` en `TrayApplicationContext`
  - Archivo: `AlwaysPrintProject/Client/AlwaysPrintTray/TrayApplicationContext.cs`
  - En `BuildTrayIcon()`: reemplazar strings hardcodeados del menú por `LocalizationManager.Get("MenuAbout")`, `LocalizationManager.Get("MenuConfiguration")`, `LocalizationManager.Get("MenuExit")`
  - En `BuildTrayIcon()`: usar `LocalizationManager.Get("TrayTooltip")` para el tooltip del icono
  - En `BootstrapSequence()`: reemplazar strings hardcodeados de balloon por `LocalizationManager.Get("BalloonInitOk")`, `LocalizationManager.Get("BalloonInitFail")`, `LocalizationManager.Get("BalloonServiceNotRunning")`
  - Requisitos: 6.15–6.18

- [x] 8. Llamar `LocalizationManager.Initialize()` en `Program.cs` antes del contexto
  - Archivo: `AlwaysPrintProject/Client/AlwaysPrintTray/Program.cs`
  - Agregar llamada a `LocalizationManager.Initialize()` después de `Application.EnableVisualStyles()` y antes de `Application.Run(new TrayApplicationContext())`
  - Requisitos: 6.14–6.15

- [x] 9. Agregar handler `CloudConfigurationReceived` en `MessageDispatcher`
  - Archivo: `AlwaysPrintProject/Client/AlwaysPrintService/Pipe/MessageDispatcher.cs`
  - Agregar case para `MessageType.CloudConfigurationReceived` que: deserialice el payload como `CloudConfigurationReceivedPayload`, llame a `_registry.Save(payload.Configuration)` (que internamente llama `Validate()`), responda con `AckPayload { Success = true }` si éxito, o con `ErrorPayload` si `Save()` lanza excepción
  - Loggear el resultado con `AlwaysPrintLogger` en español
  - Requisitos: 2.7, 10.7

- [x] 10. Agregar campos Cloud al `ConfigurationForm`
  - Archivo: `AlwaysPrintProject/Client/AlwaysPrintTray/Forms/ConfigurationForm.cs`
  - Agregar `CheckBox _chkCloudEnabled` con label `"Integración Cloud habilitada"`
  - Agregar `TextBox _txtCloudApiUrl` con label `"URL del servidor Cloud (APCM):"`
  - Agregar `ComboBox _cmbCloudLocale` con label `"Idioma (locale):"` y tres items: `"Auto"` (valor ""), `"Español"` (valor "es"), `"English"` (valor "en")
  - En `PopulateFields()`: poblar los tres controles Cloud desde `AppConfiguration`; si la llamada al pipe falla o devuelve null, mostrar error en `_lblStatus` y dejar controles en estado default
  - En `BtnSave_Click()`: validar que `_txtCloudApiUrl` sea URI absoluta válida si no está vacío; si no es válida, mostrar error inline y no enviar; incluir los tres valores Cloud en `UpdateConfigurationPayload`
  - Preservar todo el comportamiento existente para los campos pre-existentes
  - No llamar `RegistryConfigManager.Save()` directamente
  - Requisitos: 7.1–7.8, 10.3

- [x] 11. Agregar valores de registro Cloud a `Product.wxs` y actualizar `.csproj`
  - Archivo: `AlwaysPrintProject/Client/Product.wxs`
  - Dentro del `<RegistryKey Root="HKLM" Key="SOFTWARE\Robles.AI\AlwaysPrint">` existente, agregar 6 `<RegistryValue>`: `CloudEnabled` (integer, 0), `CloudApiUrl` (string, ""), `CloudLocale` (string, ""), `ConnectivityChecks` (string, "[]"), `TelemetryEnabled` (integer, 1), `TelemetryIntervalSeconds` (integer, 300)
  - Preservar todos los `<RegistryValue>` existentes sin modificación
  - Verificar que `AlwaysPrintTray.csproj` tenga `<EmbeddedResource>` para `Resources\Strings.resx` y `Resources\Strings.es.resx` (si no se hizo en T6)
  - Requisitos: 8.1–8.7, 9.5

- [x] 12. Verificar compilación completa y generar MSI
  - Ejecutar `dotnet build AlwaysPrint.sln -c Release --nologo` desde `AlwaysPrintProject/Client/`
  - Confirmar 0 errores y 0 advertencias en los tres proyectos (`AlwaysPrint.Shared`, `AlwaysPrintService`, `AlwaysPrintTray`)
  - Ejecutar `.\build.ps1` desde `AlwaysPrintProject/Client/`
  - Confirmar que `AlwaysPrint.msi` se genera en `AlwaysPrintProject/Client/`
  - Si hay errores de compilación, `build.ps1` debe abortar antes de invocar WiX
  - Requisitos: 9.1–9.6
