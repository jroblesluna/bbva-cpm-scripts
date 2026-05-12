# Implementation Plan: AlwaysPrint Phase 2 — Cloud Connect

## Overview

Implementar la conectividad WebSocket persistente entre AlwaysPrintTray y APCM. Se crean tres clases nuevas en `AlwaysPrintTray/Cloud/` (ProxyHelper, CloudWebSocketClient, CloudManager) y se integran en el bootstrap existente del Tray.

## Tasks

- [x] 1. Add WebSocket4Net NuGet dependency
  - [x] 1.1 Add WebSocket4Net PackageReference to AlwaysPrintTray.csproj
    - Verify `<PackageReference Include="WebSocket4Net" Version="0.15.2" />` exists in `AlwaysPrintProject/Client/AlwaysPrintTray/AlwaysPrintTray.csproj` (already present — confirm no version conflicts)
    - Ensure `System.Management` reference is present for WMI access (already present)
    - _Requirements: 9.1, 9.2, 9.3_

- [x] 2. Create ProxyHelper.cs
  - [x] 2.1 Implement ProxyHelper static class
    - Create file `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/ProxyHelper.cs`
    - Implement `static HttpClientHandler CreateHandler()` — returns handler with `UseProxy=true`, system proxy, `DefaultCredentials`
    - Implement `static Uri? GetSystemProxyUri(Uri targetUri)` — returns proxy URI or null if bypassed
    - Use `AlwaysPrintLogger.WriteTrayInfo()` for proxy detection logging (messages in Spanish)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_

- [x] 3. Create CloudWebSocketClient.cs
  - [x] 3.1 Implement CloudWebSocketClient sealed class with full WebSocket lifecycle
    - Create file `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/CloudWebSocketClient.cs`
    - Derive WSS URL: replace `https://` → `wss://`, append `/ws/workstation`
    - Configure WebSocket4Net proxy via `ProxyHelper.GetSystemProxyUri()` + `HttpConnectProxy`
    - Expose events: `Connected`, `Disconnected`, `MessageReceived(type, json)`, `Error(Exception)`
    - Expose `bool IsConnected` property
    - Implement `Connect()`, `Send(string type, object? payload)`, `Disconnect()`, `Dispose()`
    - Implement exponential backoff reconnection: 1s → 2s → 4s → 8s → 16s → 32s → 60s max
    - Reset backoff to 1s on successful connection
    - Implement code 1008 handling: switch to 300s fixed retry interval
    - Reset to standard backoff after successful reconnection from 1008 mode
    - Parse incoming JSON to extract `type` field, raise `MessageReceived`
    - Thread-safe state management with `lock` and `CancellationTokenSource`
    - All logging via `AlwaysPrintLogger` in Spanish
    - _Requirements: 2.1–2.18, 8.1–8.5_

  - [ ]* 3.2 Write property tests for CloudWebSocketClient
    - **Property 1: URL derivation preserves host and appends correct path**
    - **Property 2: Exponential backoff sequence is correct**
    - **Property 3: Long retry mode uses fixed 300s interval**
    - **Property 4: Successful connection resets backoff state**
    - **Validates: Requirements 2.5, 2.8, 2.9, 8.2, 8.3, 8.4, 8.5**

- [x] 4. Create CloudManager.cs
  - [x] 4.1 Implement CloudManager sealed class with registration, heartbeat, and service notification
    - Create file `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/CloudManager.cs`
    - Constructor accepts: `AppConfiguration`, `CloudCredentialsManager`, `PipeClient`, `SynchronizationContext`
    - Implement `Start()`: create `CloudWebSocketClient`, subscribe events, load credentials, connect
    - Implement `Stop()`: disconnect WebSocket, update state
    - Implement `Dispose()`: call Stop, dispose WebSocket client
    - On `Connected`: send registration message, update `IsConnected=true`, notify Service
    - On `Disconnected`: update `IsConnected=false`, notify Service
    - Registration payload: `ip_private` (Dns.GetHostAddresses, filter private IPv4), `hostname`, `os_serial` (WMI Win32_OperatingSystem.SerialNumber), `current_user`, `locale` (LocalizationManager.CurrentLocale), `client_version` (assembly version), `workstation_id` (from credentials or null)
    - Handle `"ping"` → send `"pong"` immediately
    - Handle `"registered"` → save WorkstationId via `CloudCredentialsManager.SaveWorkstationId()`, update `LastConnectedAt`
    - Notify Service via `PipeClient.Send()` with `CloudStatusResponsePayload` (IsConnected, LastConnectedAt ISO-8601, ConfigHash, UsingCachedConfig)
    - Graceful error handling: log warnings/errors, never propagate exceptions
    - All logging via `AlwaysPrintLogger` in Spanish
    - _Requirements: 3.1–3.16, 4.1–4.9, 5.1–5.4, 6.1–6.4, 10.1–10.8_

  - [ ]* 4.2 Write property tests for CloudManager message handling
    - **Property 5: Message parsing extracts type field correctly**
    - **Property 6: Send serializes with type field**
    - **Property 7: Registration payload contains all required fields**
    - **Property 8: Ping always produces pong**
    - **Property 9: Cloud status notification payload is consistent with connection state**
    - **Validates: Requirements 2.12, 2.14, 4.3, 3.12, 5.1, 6.1, 6.2**

- [x] 5. Integrate CloudManager in TrayApplicationContext
  - [x] 5.1 Wire CloudManager into TrayApplicationContext lifecycle
    - Add private field `CloudManager? _cloudManager` to `TrayApplicationContext`
    - In `BootstrapSequence()`, after health check success: check `cfg.CloudEnabled && !string.IsNullOrWhiteSpace(cfg.CloudApiUrl)`
    - If conditions met: instantiate `CloudCredentialsManager`, create `CloudManager(cfg, credentials, _pipe, _uiContext)`, call `Start()`
    - Wrap in try-catch: log error with `AlwaysPrintLogger.WriteTrayError()` and continue in local mode on failure
    - Log successful start with `AlwaysPrintLogger.WriteTrayInfo()`
    - In `Dispose(bool)`: add `_cloudManager?.Dispose()` before existing dispose logic
    - Ensure no behavioral change when `CloudEnabled=false`
    - _Requirements: 7.1–7.7, 10.8_

- [x] 6. Final checkpoint — Static code review and build verification
  - Ensure all new files are in `AlwaysPrintTray/Cloud/` directory
  - Verify no `Console.WriteLine` usage in new code
  - Verify all log messages are in Spanish
  - Verify no HKLM writes in new code (only HKCU via CloudCredentialsManager)
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 10.1–10.8, 11.1–11.5_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The WebSocket4Net dependency is already present in the .csproj — task 1.1 confirms it
- Property tests validate universal correctness properties from the design document
- All new code resides exclusively in `AlwaysPrintTray/Cloud/` per architecture rules
- The implementation language is C# (.NET Framework 4.8) matching the existing project

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["3.2", "4.1"] },
    { "id": 4, "tasks": ["4.2", "5.1"] }
  ]
}
```
