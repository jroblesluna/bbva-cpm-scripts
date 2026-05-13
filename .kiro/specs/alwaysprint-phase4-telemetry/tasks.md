# Implementation Plan: AlwaysPrint Phase 4 — Telemetry & Connectivity Monitoring

## Overview

This plan implements two new components (TelemetryReporter and ConnectivityMonitor) in the AlwaysPrintTray application, adds the ReportTelemetry IPC message from the Service, and extends the backend WebSocket handler to receive and validate telemetry and connectivity data. The implementation uses C# (.NET 4.8) for the client and Python (FastAPI) for the backend.

## Tasks

- [x] 1. Create shared models and IPC payload
  - [x] 1.1 Add ReportTelemetryPayload class and MessageType enum entry
    - Add `ReportTelemetryPayload` class to `AlwaysPrint.Shared/Messages/Payloads.cs` with `JobCount` (int) and `ReleaseTimeMs` (long) properties using `[JsonProperty]` attributes
    - Add `ReportTelemetry` entry to `MessageType` enum in `AlwaysPrint.Shared/Messages/MessageType.cs` if not already present
    - Add `ConnectivityCheckResult` model class to `AlwaysPrint.Shared/Models/` with properties: CheckId (string), Success (bool), LatencyMs (long?), Error (string?)
    - Add `DisconnectionEvent` model class to `AlwaysPrint.Shared/Models/` with properties: StartedAt (DateTime), ReconnectedAt (DateTime?), DurationSeconds (int?)
    - _Requirements: 3.1, 4.5, 5.5, 2.1_

  - [ ]* 1.2 Write unit tests for shared models
    - Test ReportTelemetryPayload JSON serialization/deserialization
    - Test DisconnectionEvent duration calculation
    - Test ConnectivityCheckResult with null latency and error combinations
    - _Requirements: 3.1, 2.1, 2.2_

- [x] 2. Implement TelemetryReporter class
  - [x] 2.1 Create TelemetryReporter with lifecycle and state management
    - Create `AlwaysPrintTray/Cloud/TelemetryReporter.cs` implementing `IDisposable`
    - Implement constructor accepting `CloudWebSocketClient`, `PipeClient`, `int intervalSeconds`, `bool contingencyActive`
    - Implement interval clamping to [60, 3600] seconds
    - Implement `Start()`, `Stop()`, `Dispose()` methods with `System.Threading.Timer`
    - Implement thread-safe state: `_disconnectionLog` (List, max 1000), `_jobsIdentified` (int), `_releaseTimes` (List<long>), `_contingencyActive` (bool)
    - Implement `lock(_lock)` for all state mutations
    - Log lifecycle events in Spanish via AlwaysPrintLogger
    - _Requirements: 1.2, 1.7, 13.1, 13.3, 14.1, 14.3_

  - [ ]* 2.2 Write property test: Telemetry Interval Clamping
    - **Property 2: Telemetry Interval Clamping**
    - For any integer value, the effective timer interval is clamped to [60, 3600] seconds
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 1.2**

  - [x] 2.3 Implement telemetry payload assembly and transmission
    - Implement timer callback that collects queue status from PipeClient (report "error" if pipe disconnected)
    - Assemble telemetry payload: queue_status, contingency_active, jobs_identified, avg_release_time_ms (null if no jobs), disconnection_log
    - Send payload via WebSocket with type "telemetry"
    - If WebSocket unavailable: retain accumulated data, skip send, log warning in Spanish
    - On successful send: clear disconnection log, reset jobs_identified to 0, clear release times
    - _Requirements: 1.1, 1.3, 1.4, 1.5, 1.6, 14.1_

  - [ ]* 2.4 Write property test: Telemetry Payload Assembly
    - **Property 1: Telemetry Payload Assembly**
    - For any combination of queue status, contingency state, disconnection events, job count, and release times, the assembled payload matches internal state; avg_release_time_ms is null when release times list is empty
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 1.1, 1.4**

  - [ ]* 2.5 Write property test: State Reset After Successful Send
    - **Property 3: State Reset After Successful Send**
    - After a successful WebSocket send, disconnection log is empty, jobs_identified is zero, release times list is empty
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 1.3, 3.5**

  - [ ]* 2.6 Write property test: Data Retention When WebSocket Unavailable
    - **Property 4: Data Retention When WebSocket Unavailable**
    - If WebSocket is not connected when timer fires, accumulated state remains unchanged
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 1.6**

  - [x] 2.7 Implement disconnection event recording
    - Implement `RecordDisconnection(DateTime utcStart)` — adds new DisconnectionEvent with start time; drops oldest if exceeding 1000 cap
    - Implement `RecordReconnection(DateTime utcReconnected)` — finds open event, sets reconnection time and calculates duration (floor of TotalSeconds); discards if no open event
    - Implement `UpdateContingencyState(bool active)` — updates internal state
    - On Stop/Dispose: close any open disconnection event with current UTC time
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [ ]* 2.8 Write property test: Disconnection Event Lifecycle
    - **Property 5: Disconnection Event Lifecycle**
    - For any pair of UTC timestamps (start, reconnection) where reconnection >= start, recording disconnection then reconnection produces a closed event with correct duration
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 2.1, 2.2**

  - [ ]* 2.9 Write property test: Disconnection Events Cap
    - **Property 6: Disconnection Events Cap**
    - For any sequence of N > 1000 disconnection recordings, the log never exceeds 1000 events
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 2.4**

  - [x] 2.10 Implement job data accumulation
    - Implement `AccumulateJobData(int jobCount, long releaseTimeMs)` — increments `_jobsIdentified` by jobCount, appends releaseTimeMs to list
    - Calculate avg_release_time_ms as integer arithmetic mean of all release times (null if empty)
    - _Requirements: 3.3, 3.4, 3.5_

  - [ ]* 2.11 Write property test: Job Accumulation and Average Calculation
    - **Property 7: Job Accumulation and Average Calculation**
    - For any sequence of (jobCount, releaseTimeMs) pairs, jobs_identified equals sum of jobCounts, avg_release_time_ms equals arithmetic mean (integer division); null when empty
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 3.3, 3.4**

- [x] 3. Checkpoint - Ensure TelemetryReporter compiles and tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement ConnectivityMonitor class
  - [x] 4.1 Create ConnectivityMonitor with lifecycle and timer
    - Create `AlwaysPrintTray/Cloud/ConnectivityMonitor.cs` implementing `IDisposable`
    - Implement constructor accepting `CloudWebSocketClient`, `List<ConnectivityCheck> checks`, `int intervalSeconds = 60`
    - Implement `Start()`, `Stop()`, `Dispose()` with `System.Threading.Timer`
    - Implement `UpdateChecks(List<ConnectivityCheck> newChecks)` with volatile reference swap
    - Timer callback reads check list once, executes all checks in parallel, sends each result individually via WebSocket
    - If WebSocket unavailable when sending result: discard and log warning in Spanish
    - Log lifecycle events in Spanish via AlwaysPrintLogger
    - _Requirements: 8.1, 8.2, 8.3, 8.5, 9.1, 9.2, 9.3, 14.2, 14.3_

  - [ ]* 4.2 Write property test: Dynamic Check List Update
    - **Property 14: Dynamic Check List Update**
    - For any new ConnectivityChecks list, after update, the active check list exactly matches the new configuration
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 9.1, 9.2**

  - [x] 4.3 Implement HTTP connectivity check
    - Use `DomainHealthChecker.Http` (shared static HttpClient) for GET requests
    - Success only when status code is exactly 200
    - Measure latency from request start to response received
    - On timeout (configured TimeoutMs): cancel request, report failed with timeout error, latency_ms = null
    - On exception: report failed with truncated message (max 256 chars), latency_ms = null
    - On invalid/empty URL: report failed with "URL inválida" error
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [ ]* 4.4 Write property test: HTTP Status Code Evaluation
    - **Property 8: HTTP Status Code Evaluation**
    - For any HTTP status code in [100, 599], success=true if and only if status code is 200
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 4.2**

  - [ ]* 4.5 Write property test: Error Message Truncation
    - **Property 9: Error Message Truncation**
    - For any exception message of length L, the reported error has length min(L, 256)
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 4.4**

  - [ ]* 4.6 Write property test: Failed Check Latency Invariant
    - **Property 10: Failed Check Latency Invariant**
    - For any failed connectivity check, latency_ms is null
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 4.6, 5.4, 6.4, 7.3**

  - [ ]* 4.7 Write property test: Invalid URL Detection
    - **Property 11: Invalid URL Detection**
    - For any string that is empty or not a valid absolute URI, HTTP check reports success=false with error indicating invalid URL
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 4.7**

  - [x] 4.8 Implement TCP connectivity check
    - Attempt TCP connection to configured host:port with configured timeout_ms
    - On success: report latency_ms from connection start to established
    - On timeout: report failed with timeout error, latency_ms = null
    - On exception: report failed with exception message, latency_ms = null
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 4.9 Implement DNS connectivity check
    - Resolve configured hostname using system DNS (Dns.GetHostAddresses)
    - On success (1+ addresses): report latency_ms from start to completion
    - On zero addresses: report failed with "no addresses resolved" error
    - On exception: report failed with exception message, latency_ms = null
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 4.10 Implement ICMP ping connectivity check
    - Send ICMP echo request with configured timeout_ms using System.Net.NetworkInformation.Ping
    - On Success reply: report latency_ms from ping reply RoundtripTime
    - On non-Success reply: report failed with IPStatus enum name as error
    - On permission exception: log warning in Spanish, report failed with "ICMP no permitido"
    - On other exception: report failed with exception message
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

  - [ ]* 4.11 Write property test: Connectivity Result Message Structure
    - **Property 12: Connectivity Result Message Structure**
    - For any completed check result, the WebSocket message contains check_id (non-empty), success (bool), latency_ms (non-negative or null), error (string or null), with type "connectivity_result"
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 5.5, 6.5, 7.6, 8.2**

  - [ ]* 4.12 Write property test: Non-Success ICMP Status Mapping
    - **Property 13: Non-Success ICMP Status Mapping**
    - For any ICMP reply with status != Success, the error string contains the IPStatus enum name
    - Use FsCheck with xUnit, minimum 100 iterations
    - **Validates: Requirements 7.3**

- [x] 5. Checkpoint - Ensure ConnectivityMonitor compiles and tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Integrate into CloudManager and Service
  - [x] 6.1 Modify CloudManager to manage TelemetryReporter and ConnectivityMonitor lifecycle
    - Add fields `_telemetryReporter` and `_connectivityMonitor` to CloudManager
    - In `Start()`: instantiate and start TelemetryReporter (if TelemetryEnabled) and ConnectivityMonitor (if ConnectivityChecks non-empty)
    - In `Stop()`: call Stop() and Dispose() on both components
    - In disconnect handler: call `_telemetryReporter?.RecordDisconnection(DateTime.UtcNow)`
    - In reconnect handler: call `_telemetryReporter?.RecordReconnection(DateTime.UtcNow)`
    - On config_update: handle TelemetryEnabled toggle (start/stop TelemetryReporter), update ConnectivityMonitor checks, stop ConnectivityMonitor if list becomes empty
    - _Requirements: 10.1, 10.2, 10.3, 11.1, 11.2, 11.3, 13.1, 13.2_

  - [x] 6.2 Add ReportTelemetry IPC handling in Service and Tray
    - In AlwaysPrintService: after detecting a completed print job, send `ReportTelemetry` message via Named Pipe with jobCount=1 and releaseTimeMs; if pipe disconnected, log warning in Spanish and discard
    - In AlwaysPrintTray PipeClient message handler: on receiving `ReportTelemetry` message, deserialize `ReportTelemetryPayload` and call `_telemetryReporter.AccumulateJobData(payload.JobCount, payload.ReleaseTimeMs)`
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ]* 6.3 Write unit tests for CloudManager lifecycle integration
    - Test TelemetryReporter started when TelemetryEnabled=true
    - Test TelemetryReporter NOT started when TelemetryEnabled=false
    - Test ConnectivityMonitor started when ConnectivityChecks non-empty
    - Test ConnectivityMonitor NOT started when ConnectivityChecks empty
    - Test Stop() disposes both components
    - Test config_update toggles TelemetryReporter on/off
    - _Requirements: 10.1, 10.2, 10.3, 11.1, 11.2, 11.3, 13.1, 13.2_

- [x] 7. Checkpoint - Ensure client integration compiles and tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implement backend telemetry and connectivity handlers
  - [x] 8.1 Add Pydantic schemas for telemetry and connectivity messages
    - Create/update schemas in backend: `TelemetryMessage` (queue_status, contingency_active, jobs_identified, avg_release_time_ms, disconnection_log), `DisconnectionEventSchema` (started_at, reconnected_at, duration_seconds), `ConnectivityResultMessage` (check_id, success, latency_ms, error)
    - _Requirements: 12.1, 12.2_

  - [x] 8.2 Implement WebSocket message handlers for telemetry and connectivity_result
    - In `workstation.py` WebSocket handler: add cases for `message_type == "telemetry"` and `message_type == "connectivity_result"`
    - Validate payload using Pydantic schemas
    - On valid telemetry: update workstation's `last_connection` timestamp in database
    - On valid connectivity_result: associate result with workstation (store or update as needed)
    - On invalid payload: log error with workstation_id, discard message, do NOT close WebSocket
    - Filter queries by `organization_id` for tenant isolation
    - _Requirements: 12.1, 12.2, 12.3_

  - [ ]* 8.3 Write property test: Backend Payload Validation
    - **Property 15: Backend Payload Validation**
    - For any WebSocket message with type "telemetry" or "connectivity_result", invalid payloads are logged and discarded without closing WebSocket; valid payloads update last_connection
    - Use Hypothesis with pytest, `@settings(max_examples=100)`
    - **Validates: Requirements 12.1, 12.2, 12.3**

  - [ ]* 8.4 Write unit tests for backend handlers
    - Test valid telemetry message updates last_connection
    - Test valid connectivity_result is stored
    - Test invalid payload logged and discarded
    - Test WebSocket not closed on invalid payload
    - _Requirements: 12.1, 12.2, 12.3_

- [x] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (FsCheck for C#, Hypothesis for Python)
- Unit tests validate specific examples and edge cases
- All log messages and error strings must be in Spanish per project conventions
- Use AlwaysPrintLogger exclusively (no Console.WriteLine)
- Use existing `DomainHealthChecker.Http` for HTTP checks to avoid socket exhaustion

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.7", "2.10"] },
    { "id": 3, "tasks": ["2.4", "2.5", "2.6", "2.8", "2.9", "2.11"] },
    { "id": 4, "tasks": ["4.1"] },
    { "id": 5, "tasks": ["4.2", "4.3", "4.8", "4.9", "4.10"] },
    { "id": 6, "tasks": ["4.4", "4.5", "4.6", "4.7", "4.11", "4.12"] },
    { "id": 7, "tasks": ["6.1", "6.2"] },
    { "id": 8, "tasks": ["6.3", "8.1"] },
    { "id": 9, "tasks": ["8.2"] },
    { "id": 10, "tasks": ["8.3", "8.4"] }
  ]
}
```
