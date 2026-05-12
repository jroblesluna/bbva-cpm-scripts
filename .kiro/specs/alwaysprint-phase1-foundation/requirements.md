# Requirements Document

## Introduction

La **Fase 1 — Fundamentos de Integración Cloud** prepara el Client de AlwaysPrint (C# .NET 4.8) con la infraestructura interna necesaria para la integración futura con AlwaysPrint Cloud Manager (APCM), **sin conectar aún a la nube**. El Client ya funciona en modo local; esta fase agrega los campos de configuración Cloud, el gestor de credenciales de workstation, los nuevos tipos de mensajes y payloads para el pipe, el sistema de internacionalización (i18n) del Tray, los campos Cloud en el formulario de configuración, y los valores de registro por defecto en el instalador MSI.

Al finalizar esta fase, `dotnet build AlwaysPrint.sln -c Release --nologo` debe producir 0 errores y 0 advertencias, y el comportamiento existente del Client en modo local no debe verse alterado.

## Glossary

- **AlwaysPrintService**: Servicio Windows (LocalSystem) que gestiona la cola de impresión corporativa y expone el Named Pipe. Nunca accede a Internet.
- **AlwaysPrintTray**: Aplicación WinForms de bandeja del sistema que se ejecuta en el contexto del usuario. Es el único componente que puede acceder a Internet y a HKCU.
- **AlwaysPrint.Shared**: Biblioteca de clases compartida entre AlwaysPrintService y AlwaysPrintTray.
- **APCM**: AlwaysPrint Cloud Manager — plataforma SaaS (FastAPI + Next.js) a la que el Tray se conectará en fases posteriores.
- **AppConfiguration**: Clase de configuración compartida que se persiste en `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`.
- **RegistryConfigManager**: Clase en AlwaysPrint.Shared que lee y escribe AppConfiguration en HKLM. Solo el AlwaysPrintService la usa para escritura.
- **CloudCredentialsManager**: Nueva clase en AlwaysPrint.Shared que gestiona credenciales de workstation en `HKCU\SOFTWARE\Robles.AI\AlwaysPrint\Cloud`. No requiere privilegios de administrador.
- **ConnectivityCheck**: Nueva clase que representa un check de conectividad configurable. Los tipos válidos son: `"http"`, `"tcp"`, `"ping"`, `"dns"`.
- **LocalizationManager**: Nueva clase estática en AlwaysPrintTray que gestiona el idioma de la UI.
- **Named Pipe**: Canal IPC `\\.\pipe\AlwaysPrintService` entre el AlwaysPrintService y el AlwaysPrintTray.
- **PipeMessage**: Mensaje serializado en JSON que viaja por el Named Pipe.
- **MessageType**: Enumeración de tipos de mensajes del Named Pipe.
- **AlwaysPrintLogger**: Clase de logging centralizada. Todos los logs deben pasar por ella. Los mensajes de log deben estar en español.
- **HKLM**: `HKEY_LOCAL_MACHINE` — requiere privilegios de administrador para escritura.
- **HKCU**: `HKEY_CURRENT_USER` — accesible sin privilegios de administrador.
- **Product.wxs**: Archivo WiX v4 que define el instalador MSI de AlwaysPrint.
- **build.ps1**: Script PowerShell que compila la solución y genera el MSI.
- **Locale**: Código de idioma/región (ej. `es-PE`, `en-US`). Un locale cuyo código de dos letras es `"es"` indica español.
- **ISO-8601**: Formato de fecha/hora estándar, ej. `"2026-05-11T14:30:00Z"`.

---

## Requirements

### Requirement 1: Campos Cloud en AppConfiguration

**User Story:** Como desarrollador que implementa la integración Cloud, quiero que `AppConfiguration` contenga todos los campos necesarios para la configuración Cloud, para que el AlwaysPrintService y el AlwaysPrintTray puedan leer y aplicar la configuración descargada de APCM en fases posteriores.

#### Acceptance Criteria

1. THE `AppConfiguration` SHALL declare a `CloudEnabled` property of type `bool` with a default value of `false`.
2. THE `AppConfiguration` SHALL declare a `CloudApiUrl` property of type `string` with a default value of `string.Empty`.
3. THE `AppConfiguration` SHALL declare a `CloudLocale` property of type `string` with a default value of `string.Empty`, where an empty value indicates that the locale is auto-detected from the operating system.
4. THE `AppConfiguration` SHALL declare a `ConnectivityChecks` property of type `List<ConnectivityCheck>` with a default value of an empty list.
5. THE `AppConfiguration` SHALL declare a `TelemetryEnabled` property of type `bool` with a default value of `true`.
6. THE `AppConfiguration` SHALL declare a `TelemetryIntervalSeconds` property of type `int` with a default value of `300`.
7. THE `ConnectivityCheck` class SHALL declare the following properties: `Id` (string), `Type` (string), `Url` (string nullable), `Host` (string nullable), `Hostname` (string nullable), `Port` (int nullable), `TimeoutMs` (int, default `5000`).
8. THE `ConnectivityCheck` class SHALL annotate each property with the corresponding `[JsonProperty]` attribute matching the snake_case field names defined in the INTEGRATION-STRATEGY.md coherence table.
9. WHEN `AppConfiguration` is instantiated without arguments, THE `AppConfiguration` SHALL have `CloudEnabled = false`, `CloudApiUrl = ""`, `CloudLocale = ""`, `ConnectivityChecks` as an empty list, `TelemetryEnabled = true`, and `TelemetryIntervalSeconds = 300`.
10. THE `AppConfiguration` SHALL expose a public `Validate()` method that throws `ArgumentOutOfRangeException` when `TelemetryIntervalSeconds` is less than 60, identifying the field name in the exception message.
11. WHEN `AppConfiguration.Validate()` is called and `CloudApiUrl` is a non-empty string that is not a well-formed absolute URI, THE `AppConfiguration.Validate()` SHALL throw `ArgumentException` identifying `CloudApiUrl` in the exception message.
12. WHEN `AppConfiguration.Validate()` is called and any `ConnectivityCheck` in `ConnectivityChecks` has a non-null `Port` value outside the range 0–65535, THE `AppConfiguration.Validate()` SHALL throw `ArgumentOutOfRangeException` identifying the invalid port value.
13. WHEN `AppConfiguration.Validate()` is called and any `ConnectivityCheck` in `ConnectivityChecks` has a `Type` value that is not one of `"http"`, `"tcp"`, `"ping"`, or `"dns"`, THE `AppConfiguration.Validate()` SHALL throw `ArgumentException` identifying the invalid type value.
14. THE `AppConfiguration` SHALL preserve all existing properties (`CorporateQueueName`, `SearchTargets`, `PendingTaskPollingMinutes`, `BootstrapDomains`, `RoblesAiLicenseSerial`) without modification.

---

### Requirement 2: RegistryConfigManager — Lectura y escritura de campos Cloud

**User Story:** Como AlwaysPrintService, quiero que `RegistryConfigManager` lea y escriba los 6 nuevos campos Cloud en `HKLM`, para que la configuración Cloud persista entre reinicios del servicio.

#### Acceptance Criteria

1. WHEN `RegistryConfigManager.Load()` is called and the registry key exists, THE `RegistryConfigManager` SHALL read `CloudEnabled` from `HKLM\SOFTWARE\Robles.AI\AlwaysPrint` as a `DWORD` value where `1` maps to `true` and any other value maps to `false`, defaulting to `false` if absent.
2. WHEN `RegistryConfigManager.Load()` is called and the registry key exists, THE `RegistryConfigManager` SHALL read `CloudApiUrl` and `CloudLocale` from `HKLM\SOFTWARE\Robles.AI\AlwaysPrint` as `String` values, defaulting to `string.Empty` if absent.
3. WHEN `RegistryConfigManager.Load()` is called and the `ConnectivityChecks` registry value contains a valid JSON array, THE `RegistryConfigManager` SHALL deserialize it into `List<ConnectivityCheck>`.
4. IF `RegistryConfigManager.Load()` encounters a null, empty, or malformed `ConnectivityChecks` registry value, THEN THE `RegistryConfigManager` SHALL assign an empty `List<ConnectivityCheck>` without throwing an exception.
5. WHEN `RegistryConfigManager.Load()` is called and the registry key exists, THE `RegistryConfigManager` SHALL read `TelemetryEnabled` as a `DWORD` where `1` maps to `true` and any other value maps to `false`, defaulting to `true` if absent.
6. WHEN `RegistryConfigManager.Load()` is called and the registry key exists, THE `RegistryConfigManager` SHALL read `TelemetryIntervalSeconds` as a `DWORD` and apply `Math.Max(60, value)` to enforce a minimum of 60 seconds, defaulting to `300` if absent.
7. WHEN `RegistryConfigManager.Save(cfg)` is called with a valid `AppConfiguration`, THE `RegistryConfigManager` SHALL call `cfg.Validate()` before writing to the registry, and SHALL NOT write to the registry if `Validate()` throws.
8. WHEN `RegistryConfigManager.Save(cfg)` is called with a valid `AppConfiguration`, THE `RegistryConfigManager` SHALL write `CloudEnabled` to `HKLM` as `RegistryValueKind.DWord` (`1` for `true`, `0` for `false`).
9. WHEN `RegistryConfigManager.Save(cfg)` is called with a valid `AppConfiguration`, THE `RegistryConfigManager` SHALL write `CloudApiUrl` and `CloudLocale` to `HKLM` as `RegistryValueKind.String`.
10. WHEN `RegistryConfigManager.Save(cfg)` is called with a valid `AppConfiguration`, THE `RegistryConfigManager` SHALL serialize `ConnectivityChecks` to a JSON string and write it to `HKLM` as `RegistryValueKind.String`.
11. WHEN `RegistryConfigManager.Save(cfg)` is called with a valid `AppConfiguration`, THE `RegistryConfigManager` SHALL write `TelemetryEnabled` as `RegistryValueKind.DWord` and `TelemetryIntervalSeconds` as `RegistryValueKind.DWord`.
12. WHEN `RegistryConfigManager.EnsureDefaults()` is called, THE `RegistryConfigManager` SHALL write the 6 new Cloud fields with their default values only if those values are absent in the registry, leaving existing values unchanged.
13. WHEN `RegistryConfigManager.EnsureDefaults()` is called twice consecutively, THE `RegistryConfigManager` SHALL produce the same registry state as calling it once (idempotencia).
14. FOR ALL valid `AppConfiguration` objects with Cloud fields set, saving then loading SHALL produce an `AppConfiguration` with equivalent Cloud field values, including the full contents of `ConnectivityChecks` (round-trip property).
15. THE `RegistryConfigManager` SHALL preserve all existing `Load()`, `Save()`, and `EnsureDefaults()` behavior for the pre-existing fields without modification.

---

### Requirement 3: CloudCredentialsManager — Credenciales de workstation en HKCU

**User Story:** Como AlwaysPrintTray, quiero gestionar las credenciales de workstation en `HKCU` sin requerir privilegios de administrador, para que el Tray pueda almacenar y recuperar el `WorkstationId` y el hash de configuración de forma independiente al AlwaysPrintService.

#### Acceptance Criteria

1. THE `CloudCredentialsManager` SHALL be a new class in `AlwaysPrint.Shared/Configuration/CloudCredentialsManager.cs` that reads and writes exclusively to `HKCU\SOFTWARE\Robles.AI\AlwaysPrint\Cloud`.
2. THE `CloudCredentialsManager` SHALL declare the following readable properties: `WorkstationId` (string nullable), `ConfigHash` (string nullable), `ConfigCachedAt` (DateTime nullable), `LastConnectedAt` (DateTime nullable).
3. THE `CloudCredentialsManager` SHALL declare an `IsRegistered` property that returns `true` if and only if `WorkstationId` is not null and not empty.
4. WHEN `CloudCredentialsManager.Load()` is called, THE `CloudCredentialsManager` SHALL read all four credential values from `HKCU\SOFTWARE\Robles.AI\AlwaysPrint\Cloud`, parsing `ConfigCachedAt` and `LastConnectedAt` from ISO-8601 strings.
5. IF `CloudCredentialsManager.Load()` encounters a missing or inaccessible registry key, THEN THE `CloudCredentialsManager` SHALL leave all properties as `null` without throwing an exception.
6. IF `CloudCredentialsManager.Load()` encounters a `ConfigCachedAt` or `LastConnectedAt` registry value that cannot be parsed as ISO-8601, THEN THE `CloudCredentialsManager` SHALL set the corresponding property to `null` without throwing an exception.
7. WHEN `CloudCredentialsManager.SaveWorkstationId(id)` is called with a non-empty string, THE `CloudCredentialsManager` SHALL write the value to `HKCU\SOFTWARE\Robles.AI\AlwaysPrint\Cloud` as `RegistryValueKind.String` and update the in-memory `WorkstationId` property.
8. WHEN `CloudCredentialsManager.SaveConfigHash(hash, cachedAt)` is called, THE `CloudCredentialsManager` SHALL write `ConfigHash` as `RegistryValueKind.String` and `ConfigCachedAt` as an ISO-8601 string in `RegistryValueKind.String`, and update the corresponding in-memory properties.
9. WHEN `CloudCredentialsManager.SaveLastConnected(connectedAt)` is called, THE `CloudCredentialsManager` SHALL write `LastConnectedAt` as an ISO-8601 string in `RegistryValueKind.String` and update the in-memory `LastConnectedAt` property.
10. FOR ALL non-empty string values `id`, calling `SaveWorkstationId(id)` followed by `Load()` SHALL return the same `id` value in `WorkstationId` (round-trip property).
11. FOR ALL valid `(hash, cachedAt)` pairs, calling `SaveConfigHash(hash, cachedAt)` followed by `Load()` SHALL return equivalent `ConfigHash` and `ConfigCachedAt` values (round-trip property).
12. FOR ALL valid `connectedAt` values, calling `SaveLastConnected(connectedAt)` followed by `Load()` SHALL return an equivalent `LastConnectedAt` value (round-trip property).
13. THE `CloudCredentialsManager` SHALL NOT write to `HKLM` under any circumstance.
14. WHEN any registry operation in `CloudCredentialsManager` throws an exception, THE `CloudCredentialsManager` SHALL log the error using `AlwaysPrintLogger.WriteTrayError()` with a message in Spanish and SHALL NOT propagate the exception to the caller.

---

### Requirement 4: MessageType — Nuevos tipos de mensajes Cloud

**User Story:** Como desarrollador del protocolo Named Pipe, quiero que `MessageType` incluya los 4 nuevos tipos de mensajes Cloud, para que el AlwaysPrintService y el AlwaysPrintTray puedan comunicar eventos Cloud a través del pipe existente.

#### Acceptance Criteria

1. THE `MessageType` enum SHALL include a `CloudConfigurationReceived` value representing a message sent from the AlwaysPrintTray to the AlwaysPrintService to apply a configuration downloaded from APCM.
2. THE `MessageType` enum SHALL include a `ReportTelemetry` value representing a message sent from the AlwaysPrintService to the AlwaysPrintTray containing a telemetry event to be forwarded to APCM.
3. THE `MessageType` enum SHALL include a `GetCloudStatus` value representing a message sent from the AlwaysPrintTray to the AlwaysPrintService to query the current Cloud connection status.
4. THE `MessageType` enum SHALL include a `CloudStatusResponse` value representing a message sent from the AlwaysPrintService to the AlwaysPrintTray with the current Cloud status.
5. THE `MessageType` enum SHALL preserve all existing values (`Ping`, `Pong`, `TrayInitialized`, `UpdateConfiguration`, `GetCurrentConfiguration`, `CheckCorporateQueue`, `CheckServiceStatus`, `Ack`, `Error`) without modification or renumbering.
6. THE `MessageType` enum SHALL NOT contain duplicate integer values across all existing and new members.

---

### Requirement 5: Payloads — Nuevos payloads Cloud

**User Story:** Como desarrollador del protocolo Named Pipe, quiero que `Payloads.cs` incluya los payloads para los 4 nuevos tipos de mensajes Cloud, para que los datos Cloud puedan ser serializados y deserializados correctamente a través del pipe.

#### Acceptance Criteria

1. THE `Payloads.cs` file SHALL declare a `CloudConfigurationReceivedPayload` class with the following properties, each annotated with `[JsonProperty]`: `Configuration` (AppConfiguration), `ConfigHash` (string, default `string.Empty`), `Source` (string, valid values: `"cloud"` or `"cache"`, default `"cloud"`).
2. THE `Payloads.cs` file SHALL declare a `TelemetryPayload` class with the following properties, each annotated with `[JsonProperty]`: `QueueStatus` (string, valid values: `"ok"`, `"missing"`, `"error"`), `ContingencyActive` (bool), `JobsIdentified` (int), `AvgReleaseTimeMs` (long nullable), `DisconnectionLog` (List\<DisconnectionEvent\>, default empty list).
3. THE `Payloads.cs` file SHALL declare a `DisconnectionEvent` class with the following properties, each annotated with `[JsonProperty]`: `StartedAt` (string, ISO-8601), `ReconnectedAt` (string nullable), `DurationSeconds` (long nullable).
4. THE `Payloads.cs` file SHALL declare a `CloudStatusResponsePayload` class with the following properties, each annotated with `[JsonProperty]`: `IsConnected` (bool), `LastConnectedAt` (string nullable), `ConfigHash` (string nullable), `UsingCachedConfig` (bool).
5. FOR ALL valid `CloudConfigurationReceivedPayload` instances, JSON serialization followed by deserialization SHALL produce an instance with equivalent property values (round-trip property).
6. FOR ALL valid `TelemetryPayload` instances including non-empty `DisconnectionLog` lists, JSON serialization followed by deserialization SHALL produce an instance with equivalent property values (round-trip property).
7. FOR ALL valid `CloudStatusResponsePayload` instances, JSON serialization followed by deserialization SHALL produce an instance with equivalent property values (round-trip property).
8. THE `Payloads.cs` file SHALL preserve all existing payload classes (`TrayInitializedPayload`, `UpdateConfigurationPayload`, `CheckCorporateQueuePayload`, `CheckServiceStatusPayload`, `AckPayload`, `GetConfigurationResponsePayload`, `CheckCorporateQueueResponsePayload`, `CheckServiceStatusResponsePayload`, `ErrorPayload`) without modification.

---

### Requirement 6: Sistema i18n en el Tray

**User Story:** Como usuario de AlwaysPrint en una workstation con locale español, quiero que el menú del Tray y las notificaciones aparezcan en español, para que la interfaz sea comprensible sin necesidad de configuración adicional.

#### Acceptance Criteria

1. THE `AlwaysPrintTray` project SHALL contain a `Resources/` folder with at least two resource files: `Strings.resx` (inglés, default) and `Strings.es.resx` (español), both declared as `EmbeddedResource` in `AlwaysPrintTray.csproj`.
2. THE `LocalizationManager` class SHALL be a new `static` class in `AlwaysPrintTray/Localization/LocalizationManager.cs`.
3. THE `LocalizationManager` SHALL expose a `static void Initialize(string? localeOverride = null)` method and a `static string Get(string key)` method.
4. THE `LocalizationManager` SHALL expose a `static string CurrentLocale` property that returns the two-letter ISO language code of the active locale.
5. THE `LocalizationManager` SHALL expose a `static readonly string[] SupportedLocales` array containing exactly `"es"` and `"en"`.
6. WHEN `LocalizationManager.Initialize()` is called without a `localeOverride`, THE `LocalizationManager` SHALL detect the Windows UI locale from `CultureInfo.CurrentUICulture` and use it to select the active locale.
7. WHEN `LocalizationManager.Initialize(localeOverride)` is called with a non-null, non-empty `localeOverride`, THE `LocalizationManager` SHALL use the override locale regardless of the Windows system locale.
8. WHEN the active locale (detected or overridden) starts with `"es"` (e.g., `es-PE`, `es-MX`, `es-ES`), THE `LocalizationManager` SHALL set `CurrentLocale` to `"es"` and return Spanish strings from `Get(key)`.
9. WHEN the active locale does NOT start with `"es"`, THE `LocalizationManager` SHALL set `CurrentLocale` to `"en"` and return English strings from `Get(key)`.
10. FOR ALL locale strings starting with `"es-"`, calling `LocalizationManager.Initialize(locale)` followed by reading `CurrentLocale` SHALL return `"es"` (metamorphic property).
11. IF `LocalizationManager.Initialize()` encounters an error while loading the Spanish resource file for an `"es-*"` locale (e.g., missing embedded resource), THEN THE `LocalizationManager` SHALL fall back to English mode, set `CurrentLocale` to `"en"`, log the error using `AlwaysPrintLogger.WriteTrayError()` with a message in Spanish, and continue operating without throwing an exception.
12. THE `LocalizationManager` SHALL provide localized strings for the following keys in both `"es"` and `"en"`: `TrayTooltip`, `MenuAbout`, `MenuConfiguration`, `MenuExit`, `BalloonInitOk`, `BalloonInitFail`, `BalloonServiceNotRunning`, `BalloonOfflineWarning`.
13. IF `LocalizationManager.Get(key)` is called with a key that does not exist in the active resource file, THEN THE `LocalizationManager` SHALL return the key name as a fallback string without throwing an exception.
14. WHEN `LocalizationManager.Initialize()` is called twice with the same locale, THE `LocalizationManager` SHALL produce the same `CurrentLocale` value as calling it once (idempotencia).
15. WHEN `Program.Main()` is executed, THE `AlwaysPrintTray` SHALL call `LocalizationManager.Initialize()` before constructing `TrayApplicationContext`, so that the tray icon and context menu are built with the correct locale from the start.
16. WHEN `TrayApplicationContext.BuildTrayIcon()` builds the context menu, THE `TrayApplicationContext` SHALL use `LocalizationManager.Get("MenuAbout")`, `LocalizationManager.Get("MenuConfiguration")`, and `LocalizationManager.Get("MenuExit")` for the menu item labels.
17. WHEN `TrayApplicationContext.BuildTrayIcon()` sets the tray icon tooltip, THE `TrayApplicationContext` SHALL use `LocalizationManager.Get("TrayTooltip")` for the tooltip text.
18. WHEN a balloon notification is shown in `TrayApplicationContext`, THE `TrayApplicationContext` SHALL use the corresponding `LocalizationManager.Get(key)` string for the balloon text.
19. THE `LocalizationManager` SHALL NOT use `Console.WriteLine` for any output — all diagnostic output SHALL use `AlwaysPrintLogger.WriteTrayInfo()`, `AlwaysPrintLogger.WriteTrayWarning()`, or `AlwaysPrintLogger.WriteTrayError()` with messages in Spanish.

---

### Requirement 7: ConfigurationForm — Campos Cloud

**User Story:** Como administrador de AlwaysPrint, quiero que el formulario de configuración muestre los campos Cloud, para que pueda habilitar la integración Cloud y configurar la URL del servidor APCM desde la interfaz gráfica.

#### Acceptance Criteria

1. THE `ConfigurationForm` SHALL include a `CheckBox` control with the label `"Integración Cloud habilitada"` that maps to the `AppConfiguration.CloudEnabled` property.
2. THE `ConfigurationForm` SHALL include a `TextBox` control with the label `"URL del servidor Cloud (APCM):"` that maps to the `AppConfiguration.CloudApiUrl` property.
3. THE `ConfigurationForm` SHALL include a `ComboBox` control with the label `"Idioma (locale):"` with three items: `"Auto"` (maps to `""`), `"Español"` (maps to `"es"`), `"English"` (maps to `"en"`), that maps to the `AppConfiguration.CloudLocale` property.
4. WHEN `ConfigurationForm` receives a valid `AppConfiguration` from the AlwaysPrintService via the `GetCurrentConfiguration` Named Pipe message, THE `ConfigurationForm` SHALL populate the three Cloud controls with the values from `AppConfiguration.CloudEnabled`, `AppConfiguration.CloudApiUrl`, and `AppConfiguration.CloudLocale`.
5. WHEN the user clicks "Guardar" in `ConfigurationForm`, THE `ConfigurationForm` SHALL include the current values of the three Cloud controls in the `UpdateConfigurationPayload` sent to the AlwaysPrintService via the `UpdateConfiguration` Named Pipe message.
6. WHEN the user selects `"Auto"` in the `CloudLocale` ComboBox, THE `ConfigurationForm` SHALL set `AppConfiguration.CloudLocale` to `string.Empty` in the `UpdateConfigurationPayload`.
7. THE `ConfigurationForm` SHALL preserve all existing user-facing behavior for the pre-existing fields (`CorporateQueueName`, `SearchTargets`, `PendingTaskPollingMinutes`, `BootstrapDomains`, `RoblesAiLicenseSerial`); internal implementation changes are permitted as long as the user-facing behavior remains unchanged.
8. THE `ConfigurationForm` SHALL NOT call `RegistryConfigManager.Save()` directly — all persistence is delegated to the AlwaysPrintService via the `UpdateConfiguration` Named Pipe message.

---

### Requirement 8: Product.wxs — Valores de registro por defecto Cloud

**User Story:** Como instalador de AlwaysPrint, quiero que el MSI escriba los valores de registro por defecto para los 6 nuevos campos Cloud, para que el AlwaysPrintService encuentre valores válidos en el registro desde la primera ejecución tras la instalación.

#### Acceptance Criteria

1. THE `Product.wxs` file SHALL include a `<RegistryValue>` element for `CloudEnabled` of type `integer` with value `0` under `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`.
2. THE `Product.wxs` file SHALL include a `<RegistryValue>` element for `CloudApiUrl` of type `string` with value `""` under `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`.
3. THE `Product.wxs` file SHALL include a `<RegistryValue>` element for `CloudLocale` of type `string` with value `""` under `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`.
4. THE `Product.wxs` file SHALL include a `<RegistryValue>` element for `ConnectivityChecks` of type `string` with value `"[]"` under `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`.
5. THE `Product.wxs` file SHALL include a `<RegistryValue>` element for `TelemetryEnabled` of type `integer` with value `1` under `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`.
6. THE `Product.wxs` file SHALL include a `<RegistryValue>` element for `TelemetryIntervalSeconds` of type `integer` with value `300` under `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`.
7. THE `Product.wxs` file SHALL preserve all existing `<RegistryValue>` elements without modification.

---

### Requirement 9: Compilación sin errores ni advertencias

**User Story:** Como desarrollador de AlwaysPrint, quiero que la solución compile sin errores ni advertencias después de implementar la Fase 1, para que el pipeline de CI/CD no se vea afectado y el instalador MSI pueda generarse correctamente.

#### Acceptance Criteria

1. WHEN `dotnet build AlwaysPrint.sln -c Release --nologo` is executed after all Phase 1 changes, THE `AlwaysPrint.Shared` project SHALL compile with 0 errors and 0 warnings.
2. WHEN `dotnet build AlwaysPrint.sln -c Release --nologo` is executed after all Phase 1 changes, THE `AlwaysPrintService` project SHALL compile with 0 errors and 0 warnings.
3. WHEN `dotnet build AlwaysPrint.sln -c Release --nologo` is executed after all Phase 1 changes, THE `AlwaysPrintTray` project SHALL compile with 0 errors and 0 warnings.
4. WHEN `build.ps1` is executed after all Phase 1 changes, THE `build.ps1` script SHALL generate the MSI file without errors; IF any of the three projects (`AlwaysPrint.Shared`, `AlwaysPrintService`, `AlwaysPrintTray`) has compilation errors, THEN `build.ps1` SHALL abort before invoking WiX and SHALL NOT produce an `AlwaysPrint.msi` file.
5. THE new `.resx` resource files SHALL be declared as `EmbeddedResource` in `AlwaysPrintTray.csproj` to prevent MSB3245 build errors.
6. THE `LocalizationManager.cs` source file SHALL be included in `AlwaysPrintTray.csproj` so that the `AlwaysPrintTray` project compiles without CS0246 (type not found) errors.

---

### Requirement 10: Reglas de arquitectura y logging

**User Story:** Como arquitecto del sistema AlwaysPrint, quiero que todos los cambios de la Fase 1 respeten las reglas de arquitectura establecidas, para que la separación de responsabilidades entre AlwaysPrintService y AlwaysPrintTray se mantenga y el sistema sea auditable.

#### Acceptance Criteria

1. THE `CloudCredentialsManager` SHALL reference `Registry.CurrentUser` exclusively and SHALL NOT reference `Registry.LocalMachine` anywhere in its implementation.
2. THE `RegistryConfigManager` SHALL reference `Registry.LocalMachine` exclusively for all Cloud field operations, consistent with existing behavior for pre-existing fields.
3. THE `AlwaysPrintTray` project SHALL NOT call `RegistryConfigManager.Save()` directly under any circumstance — all HKLM writes are strictly delegated to the AlwaysPrintService via the `UpdateConfiguration` Named Pipe message.
4. WHEN any registry operation in `CloudCredentialsManager` throws an exception, THE `CloudCredentialsManager` SHALL log the error using `AlwaysPrintLogger.WriteTrayError()` with a message in Spanish and SHALL NOT propagate the exception to the caller.
5. WHEN any registry operation in `RegistryConfigManager` throws an exception for the new Cloud fields, THE `RegistryConfigManager` SHALL log the error using `AlwaysPrintLogger.WriteWarning()` or `AlwaysPrintLogger.WriteError()` with a message in Spanish, consistent with the existing error handling pattern in `RegistryConfigManager.Load()`.
6. THE `AlwaysPrintService` project SHALL NOT reference `LocalizationManager` or any class under `AlwaysPrintTray/Localization/`.
7. WHEN `AppConfiguration.Validate()` is called by `RegistryConfigManager.Save()`, THE `AlwaysPrintService` SHALL not persist a configuration that fails validation — the exception from `Validate()` SHALL propagate to the caller of `Save()`.
8. THE new code added in Phase 1 SHALL NOT use `Console.WriteLine` anywhere — all diagnostic output SHALL use `AlwaysPrintLogger` with messages in Spanish.
