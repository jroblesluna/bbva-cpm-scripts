# Implementation Plan: AlwaysPrint Phase 5 — Resiliencia Offline, Notificaciones y Modo Degradado

## Overview

This plan implements offline resilience for the AlwaysPrintTray application: the OfflineStateManager class for state tracking and notifications, pending telemetry queue in TelemetryReporter, no-config-offline handling, localization strings, offline icon resource, and CloudManager integration. The implementation uses C# (.NET 4.8) exclusively (no backend changes in this phase).

## Tasks

- [x] 1. Add localization strings and offline icon resource
  - [x] 1.1 Add i18n strings to resource files
    - Add the following keys to `AlwaysPrintTray/Resources/Strings.resx` (English): `BalloonOfflineTitle` = "AlwaysPrint", `BalloonOfflineText` = "Using cached config. No cloud connection.", `BalloonOfflineNoConfig` = "No cloud connection and no cached config. Using defaults.", `BalloonReconnected` = "Cloud connection restored.", `TooltipOffline` = "AlwaysPrint (offline)"
    - Add the same keys to `AlwaysPrintTray/Resources/Strings.es.resx` (Spanish): `BalloonOfflineTitle` = "AlwaysPrint", `BalloonOfflineText` = "Usando configuración guardada. Sin conexión a la nube.", `BalloonOfflineNoConfig` = "Sin conexión a la nube y sin configuración guardada. Usando valores por defecto.", `BalloonReconnected` = "Conexión con la nube restaurada.", `TooltipOffline` = "AlwaysPrint (sin conexión)"
    - _Requirements: 7.1, 7.2_

  - [x] 1.2 Create and embed offline icon resource
    - Create a grayscale/desaturated version of the existing tray icon as `AlwaysPrintTray/Resources/logo_offline.ico`
    - Add the icon as an embedded resource in the AlwaysPrintTray.csproj project file
    - Verify the resource is accessible at runtime via `Properties.Resources` or equivalent
    - _Requirements: 3.5, 3.6, 10.7_

- [x] 2. Implement OfflineStateManager class
  - [x] 2.1 Create OfflineStateManager with lifecycle and state tracking
    - Create `AlwaysPrintTray/Cloud/OfflineStateManager.cs` implementing `IDisposable`
    - Implement constructor accepting `SynchronizationContext uiContext` and `NotifyIcon trayIcon`
    - Implement `OnDisconnected()` — records `_disconnectedAt = DateTime.UtcNow`, clears `_lastNotifiedAt`, starts 5-minute timer
    - Implement `OnReconnected()` — clears `_disconnectedAt`, clears `_lastNotifiedAt`, stops timer, restores normal icon and tooltip, shows reconnection balloon tip
    - Implement `Dispose()` — stops and disposes timer, idempotent with `_disposed` guard
    - Expose `bool IsOffline` and `TimeSpan? OfflineDuration` read-only properties
    - All state mutations under `lock(_lock)` for thread safety
    - Log lifecycle events in Spanish via AlwaysPrintLogger
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 8.5_

  - [x]* 2.2 Write property test: Grace Period Notification Suppression
    - **Property 1: Grace Period Notification Suppression**
    - For any disconnection duration less than 1 hour, no balloon tip is shown and no icon change occurs
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 2.1, 3.1**

  - [x] 2.3 Implement CheckAndNotify logic with balloon tips
    - Implement private `CheckAndNotify()` method called by timer callback
    - If not offline: return immediately
    - If offline duration < 1 hour (GracePeriod): no action
    - If offline duration >= 1 hour and `_lastNotifiedAt == null`: show first notification, set `_lastNotifiedAt`, change icon to offline
    - If `_lastNotifiedAt` has value and elapsed >= 2 hours (NotifyRepeatEvery): show repeat notification, update `_lastNotifiedAt`
    - Show balloon tip via `SynchronizationContext.Post()` with `ToolTipIcon.Warning`, title from `LocalizationManager.Get("BalloonOfflineTitle")`, text from `LocalizationManager.Get("BalloonOfflineText")`, duration 4000ms
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6_

  - [x]* 2.4 Write property test: First Notification Timing
    - **Property 2: First Notification Timing**
    - For any disconnection persisting >= 1 hour, the first balloon tip is shown at or after the 1-hour mark
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 2.2**

  - [x]* 2.5 Write property test: Notification Repeat Interval
    - **Property 3: Notification Repeat Interval**
    - After the first notification, subsequent notifications occur at 2-hour intervals from the previous notification
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 2.3**

  - [x] 2.6 Implement icon and tooltip changes
    - Implement private `SetOfflineIcon()` — loads `logo_offline.ico` from embedded resources, sets `_trayIcon.Icon`, sets tooltip to `LocalizationManager.Get("TooltipOffline")`, via `SynchronizationContext.Post()`
    - Implement private `SetNormalIcon()` — loads normal icon from embedded resources, sets `_trayIcon.Icon`, sets tooltip to `LocalizationManager.Get("TrayTooltip")`, via `SynchronizationContext.Post()`
    - Call `SetOfflineIcon()` when first notification is shown (at 1-hour mark)
    - Call `SetNormalIcon()` in `OnReconnected()`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6_

  - [x]* 2.7 Write property test: Reconnection Clears State
    - **Property 4: Reconnection Clears State**
    - For any offline state, calling OnReconnected() results in IsOffline==false, OfflineDuration==null, timer stopped, icon normal
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 1.4, 3.2, 3.4**

  - [x] 2.8 Implement reconnection balloon tip
    - In `OnReconnected()`: if a notification was previously shown (`_lastNotifiedAt != null` or `_iconIsOffline`), show reconnection balloon tip with `ToolTipIcon.Info`, title from `LocalizationManager.Get("BalloonOfflineTitle")`, text from `LocalizationManager.Get("BalloonReconnected")`, duration 3000ms
    - Show via `SynchronizationContext.Post()`
    - _Requirements: 2.5, 6.3_

- [x] 3. Checkpoint - Ensure OfflineStateManager compiles
  - Ensure all code compiles without errors, ask the user if questions arise.

- [x] 4. Extend TelemetryReporter with pending telemetry queue
  - [x] 4.1 Add pending telemetry queue and SendOrQueue method
    - Add `Queue<object> _pendingTelemetry` field to TelemetryReporter (protected by existing `_lock`)
    - Add `const int MaxPendingTelemetry = 100`
    - Implement private `SendOrQueue(object payload)` method: if WS connected → send via `_wsClient.Send("telemetry", payload)`; if not → enqueue (dequeue oldest if at capacity)
    - Modify `OnTimerElapsed`: instead of skipping when WS unavailable, assemble payload and call `SendOrQueue(payload)`, then clear accumulators regardless
    - Log enqueue events in Spanish via AlwaysPrintLogger
    - _Requirements: 4.1, 4.2, 4.6, 4.7_

  - [x]* 4.2 Write property test: Pending Telemetry Queue Cap
    - **Property 5: Pending Telemetry Queue Cap**
    - For any sequence of N > 100 telemetry cycles with WS disconnected, the queue never exceeds 100 entries
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 4.2**

  - [x] 4.3 Implement FlushPending method
    - Implement public `void FlushPending()` method in TelemetryReporter
    - Under `lock(_lock)`: dequeue and send each payload via `_wsClient.Send("telemetry", payload)` while WS is connected
    - If WS disconnects during flush: stop, retain remaining payloads in queue
    - Log flush results in Spanish (count sent, count remaining)
    - _Requirements: 4.3, 4.4, 4.5, 6.5_

  - [x]* 4.4 Write property test: Pending Telemetry FIFO Order
    - **Property 6: Pending Telemetry FIFO Order**
    - For any sequence of enqueued payloads, FlushPending sends them in FIFO order
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 4.3**

  - [x]* 4.5 Write property test: Flush Partial Failure Retention
    - **Property 7: Flush Partial Failure Retention**
    - If WS disconnects after sending K of N pending payloads, the remaining N-K are retained in order
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 6.5**

  - [x]* 4.6 Write property test: Accumulator Reset After Queue
    - **Property 9: Accumulator Reset After Queue**
    - After enqueueing a payload (WS offline), accumulators are cleared identically to after a successful send
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 4.7**

- [x] 5. Checkpoint - Ensure TelemetryReporter changes compile
  - Ensure all code compiles without errors, ask the user if questions arise.

- [x] 6. Integrate into CloudManager
  - [x] 6.1 Add OfflineStateManager lifecycle to CloudManager
    - Add field `_offlineState` (OfflineStateManager?) to CloudManager
    - In `Start()`: instantiate `OfflineStateManager` with `_uiContext` and `_trayIcon` (only if `CloudEnabled=true`)
    - In `OnDisconnected()`: call `_offlineState?.OnDisconnected()` (in addition to existing `_telemetryReporter?.RecordDisconnection()`)
    - In `OnConnected()`: call `_offlineState?.OnReconnected()` and `_telemetryReporter?.FlushPending()` (in addition to existing `_telemetryReporter?.RecordReconnection()`)
    - In `Stop()`: call `_offlineState?.Dispose()` and set to null
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [x] 6.2 Implement no-config-offline detection at startup
    - In `CloudManager.Start()`: after attempting to load cached config via `_configSync.LoadFromCache()`, if result is null and WS is not connected, log warning in Spanish and show `BalloonOfflineNoConfig` balloon tip once
    - The balloon tip SHALL be shown only once at startup (use a flag `_noConfigWarningShown`)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x]* 6.3 Write property test: CloudEnabled=false Inertness
    - **Property 8: CloudEnabled=false Inertness**
    - When CloudEnabled=false, no OfflineStateManager is instantiated, no balloon tips shown, no icon changes
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 9.1, 9.2**

  - [x]* 6.4 Write property test: No-Config-Offline Single Notification
    - **Property 10: No-Config-Offline Single Notification**
    - The BalloonOfflineNoConfig balloon tip is shown exactly once at startup and does not repeat
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 5.5**

  - [x]* 6.5 Write unit tests for CloudManager integration
    - Test OfflineStateManager instantiated when CloudEnabled=true
    - Test OfflineStateManager NOT instantiated when CloudEnabled=false
    - Test OnDisconnected calls both OfflineStateManager and TelemetryReporter
    - Test OnConnected calls OnReconnected + FlushPending + RecordReconnection
    - Test Stop() disposes OfflineStateManager
    - Test no-config-offline balloon shown once
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 9.1_

- [x] 7. Final checkpoint - Ensure all code compiles and solution builds cleanly
  - Ensure `dotnet build AlwaysPrint.sln -c Release --nologo` produces 0 errors and 0 warnings
  - Verify all three projects compile: AlwaysPrint.Shared, AlwaysPrintService, AlwaysPrintTray
  - _Requirements: 11.1, 11.2, 11.3_

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (FsCheck for C#)
- Unit tests validate specific examples and edge cases
- All log messages and error strings must be in Spanish per project conventions
- Use AlwaysPrintLogger exclusively (no Console.WriteLine)
- The offline icon can be a simple grayscale conversion of the existing icon — pixel-perfect design is not required
- This phase has NO backend changes — all work is in the C# client

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.6", "2.8"] },
    { "id": 3, "tasks": ["2.4", "2.5", "2.7"] },
    { "id": 4, "tasks": ["4.1"] },
    { "id": 5, "tasks": ["4.2", "4.3"] },
    { "id": 6, "tasks": ["4.4", "4.5", "4.6"] },
    { "id": 7, "tasks": ["6.1", "6.2"] },
    { "id": 8, "tasks": ["6.3", "6.4", "6.5"] }
  ]
}
```
