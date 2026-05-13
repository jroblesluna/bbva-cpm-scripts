# Requirements Document

## Introduction

Phase 4 of the AlwaysPrint system adds telemetry reporting and connectivity monitoring capabilities to the Tray application. The Tray periodically collects operational metrics (queue status, disconnection events, print job counts, release times) and sends them to APCM via WebSocket. Additionally, the Tray executes configurable connectivity checks (HTTP, TCP, DNS, ICMP) and reports results individually to APCM, enabling centralized network health visibility for each workstation.

## Glossary

- **Tray**: The AlwaysPrintTray WPF application running in the system tray, responsible for Cloud communication.
- **Service**: The AlwaysPrintService Windows Service that monitors print queues and detects jobs via WMI.
- **APCM**: AlwaysPrint Cloud Manager — the backend platform (FastAPI) that receives telemetry and connectivity data.
- **TelemetryReporter**: A class in AlwaysPrintTray/Cloud/ that periodically collects and sends telemetry to APCM via WebSocket.
- **ConnectivityMonitor**: A class in AlwaysPrintTray/Cloud/ that executes configured connectivity checks and reports results to APCM.
- **CloudManager**: The orchestrator class in AlwaysPrintTray/Cloud/ that manages the lifecycle of Cloud integration components.
- **CloudWebSocketClient**: The WebSocket client class used by the Tray to communicate with APCM.
- **Named_Pipe**: The IPC mechanism (PipeClient/PipeServer) used for communication between Service and Tray.
- **ConnectivityCheck**: A configuration object defining a single connectivity check (type, target, timeout).
- **TelemetryPayload**: The data structure containing telemetry metrics sent from Service to Tray via Named Pipe.
- **DisconnectionEvent**: A record of a WebSocket disconnection including start time, reconnection time, and duration.
- **DomainHealthChecker**: An existing static class that exposes a shared HttpClient instance for HTTP operations.

---

## Requirements

### Requirement 1: Periodic Telemetry Collection and Transmission

**User Story:** As a platform administrator, I want the Tray to periodically collect and send operational telemetry to APCM, so that I can monitor workstation health from the centralized dashboard.

#### Acceptance Criteria

1. WHEN the TelemetryIntervalSeconds timer elapses, THE TelemetryReporter SHALL collect queue status from the Service via Named Pipe, the current contingency_active state, accumulated disconnection events (each with start time, end time, and duration), jobs identified count, and average release time, and send the aggregated telemetry payload to APCM via WebSocket with message type "telemetry".
2. THE TelemetryReporter SHALL use the configured TelemetryIntervalSeconds value (minimum 60 seconds, maximum 3600 seconds, default 300 seconds) as the interval between telemetry transmissions.
3. WHEN a telemetry payload is sent and no WebSocket error or exception occurs during transmission, THE TelemetryReporter SHALL clear the accumulated disconnection log and job records for the completed interval.
4. WHEN no jobs have been recorded during the current interval, THE TelemetryReporter SHALL send avg_release_time_ms as null in the telemetry payload.
5. IF the Named Pipe is not connected when collecting queue status, THEN THE TelemetryReporter SHALL report queue_status as "error" in the telemetry payload.
6. IF the WebSocket connection is not established when the telemetry timer elapses, THEN THE TelemetryReporter SHALL retain the accumulated telemetry data and attempt to send it on the next interval cycle.
7. WHILE TelemetryEnabled is set to false in the configuration, THE TelemetryReporter SHALL not collect or send telemetry payloads.

---

### Requirement 2: Disconnection Event Recording

**User Story:** As a platform administrator, I want disconnection events to be tracked and reported, so that I can identify connectivity patterns and network issues at each workstation.

#### Acceptance Criteria

1. WHEN the CloudManager detects a WebSocket disconnection, THE TelemetryReporter SHALL record a DisconnectionEvent with the disconnection start timestamp (UTC).
2. WHEN the CloudManager detects a WebSocket reconnection and an open DisconnectionEvent exists (one without a reconnection timestamp), THE TelemetryReporter SHALL update that open DisconnectionEvent with the reconnection timestamp (UTC) and the calculated duration as a whole number of seconds (rounded down).
3. IF the CloudManager detects a WebSocket reconnection and no open DisconnectionEvent exists, THEN THE TelemetryReporter SHALL discard the reconnection signal without recording an event.
4. THE TelemetryReporter SHALL accumulate DisconnectionEvents in memory (up to a maximum of 1000 events) until the next telemetry transmission cycle, after which the transmitted events SHALL be cleared from memory.
5. IF the TelemetryReporter is stopped or disposed while an open DisconnectionEvent exists, THEN THE TelemetryReporter SHALL close that event by setting the reconnection timestamp to the current time (UTC) and calculating the duration before the next transmission.

---

### Requirement 3: Service Telemetry Event Forwarding (ReportTelemetry IPC)

**User Story:** As a platform administrator, I want the Service to report completed print job metrics to the Tray, so that telemetry includes accurate job counts and release times.

#### Acceptance Criteria

1. WHEN the Service detects a completed print job, THE Service SHALL send a ReportTelemetry message to the Tray via Named Pipe containing a job count of 1 and the release time as a non-negative integer in milliseconds.
2. IF the Named Pipe is disconnected when the Service attempts to send a ReportTelemetry message, THEN THE Service SHALL discard the message and log a warning indicating the delivery failure.
3. WHEN the Tray receives a ReportTelemetry message, THE TelemetryReporter SHALL increment the accumulated jobs_identified count by the received job count and append the release time to the list of recorded release times for the current telemetry interval.
4. THE TelemetryReporter SHALL calculate avg_release_time_ms as the arithmetic mean of all recorded release times accumulated since the last telemetry send, returning null if no jobs were recorded in the interval.
5. WHEN the TelemetryReporter completes a telemetry send cycle, THE TelemetryReporter SHALL reset the accumulated jobs_identified count to zero and clear all recorded release times for the next interval.

---

### Requirement 4: HTTP Connectivity Check

**User Story:** As a platform administrator, I want the system to verify HTTP endpoint reachability, so that I can detect web service outages affecting workstations.

#### Acceptance Criteria

1. WHEN the ConnectivityMonitor interval timer fires for an HTTP-type check, THE ConnectivityMonitor SHALL perform an HTTP GET request to the URL specified in the ConnectivityCheck configuration using the shared static HttpClient instance from DomainHealthChecker.
2. WHEN an HTTP response is received, THE ConnectivityMonitor SHALL consider the check successful only when the response status code is 200.
3. IF the HTTP request exceeds the configured timeout_ms (range: 1000 to 30000 milliseconds, default 5000), THEN THE ConnectivityMonitor SHALL cancel the request and report the check as failed with an error indicating timeout.
4. IF the HTTP request throws an exception (including network errors, DNS resolution failures, or TLS errors), THEN THE ConnectivityMonitor SHALL report the check as failed with the exception message as error, truncated to a maximum of 256 characters.
5. WHEN an HTTP check completes successfully, THE ConnectivityMonitor SHALL measure and report latency_ms as the elapsed time in milliseconds from request initiation to response received, with millisecond precision.
6. IF an HTTP check fails due to timeout or exception, THEN THE ConnectivityMonitor SHALL report latency_ms as null in the connectivity result.
7. IF the configured URL for an HTTP check is empty or not a valid absolute URI, THEN THE ConnectivityMonitor SHALL skip the check and report it as failed with an error indicating invalid URL configuration.

---

### Requirement 5: TCP Connectivity Check

**User Story:** As a platform administrator, I want the system to verify TCP port reachability, so that I can detect network-level connectivity issues to critical services.

#### Acceptance Criteria

1. WHEN a TCP connectivity check is scheduled, THE ConnectivityMonitor SHALL attempt a TCP connection to the configured host and port using the configured timeout_ms (default 5000 ms).
2. WHEN the TCP connection is established within the configured timeout_ms, THE ConnectivityMonitor SHALL report the check as successful with latency_ms measured from connection start to connection established.
3. IF the TCP connection is not established within the configured timeout_ms, THEN THE ConnectivityMonitor SHALL report the check as failed with error indicating timeout.
4. IF the TCP connection throws an exception, THEN THE ConnectivityMonitor SHALL report the check as failed with the exception message as error and latency_ms omitted.
5. THE ConnectivityMonitor SHALL send each TCP check result via WebSocket as a connectivity_result message containing check_id, success, latency_ms (when successful), and error (when failed).

---

### Requirement 6: DNS Connectivity Check

**User Story:** As a platform administrator, I want the system to verify DNS resolution, so that I can detect DNS infrastructure issues affecting workstations.

#### Acceptance Criteria

1. WHEN a DNS connectivity check is scheduled, THE ConnectivityMonitor SHALL resolve the configured hostname using system DNS.
2. WHEN the DNS resolution returns one or more IP addresses, THE ConnectivityMonitor SHALL report the check as successful with latency_ms measured from resolution start to completion.
3. IF the DNS resolution returns zero addresses, THEN THE ConnectivityMonitor SHALL report the check as failed with error indicating no addresses resolved.
4. IF the DNS resolution throws an exception, THEN THE ConnectivityMonitor SHALL report the check as failed with the exception message as error and latency_ms omitted.
5. THE ConnectivityMonitor SHALL send each DNS check result via WebSocket as a connectivity_result message containing check_id, success, latency_ms (when successful), and error (when failed).

---

### Requirement 7: ICMP Ping Connectivity Check

**User Story:** As a platform administrator, I want the system to verify ICMP reachability, so that I can detect low-level network connectivity issues.

#### Acceptance Criteria

1. WHEN a PING connectivity check is scheduled, THE ConnectivityMonitor SHALL send an ICMP echo request to the configured host with the configured timeout_ms (default 5000 ms).
2. WHEN the ICMP reply status is Success, THE ConnectivityMonitor SHALL report the check as successful with latency_ms set to the ICMP round-trip time from the ping reply.
3. IF the ICMP reply status is not Success and no exception is thrown, THEN THE ConnectivityMonitor SHALL report the check as failed with error indicating the reply status value.
4. IF the ICMP ping throws an exception due to insufficient permissions, THEN THE ConnectivityMonitor SHALL log a warning in Spanish via AlwaysPrintLogger and report the check as failed with error indicating ICMP not permitted.
5. IF the ICMP ping throws any other exception, THEN THE ConnectivityMonitor SHALL report the check as failed with the exception message as error.
6. THE ConnectivityMonitor SHALL send each PING check result via WebSocket as a connectivity_result message containing check_id, success, latency_ms (when successful), and error (when failed).

---

### Requirement 8: Parallel Check Execution and Individual Reporting

**User Story:** As a platform administrator, I want connectivity checks to run in parallel and report individually, so that one slow check does not delay reporting of other results.

#### Acceptance Criteria

1. THE ConnectivityMonitor SHALL execute all configured connectivity checks in parallel using background threads.
2. WHEN a connectivity check completes, THE ConnectivityMonitor SHALL send the result individually to APCM via WebSocket with message type "connectivity_result" containing check_id, success, latency_ms, and error fields.
3. THE ConnectivityMonitor SHALL execute checks at the configured interval (minimum 60 seconds, default 60 seconds) without blocking the UI thread.
4. IF a connectivity check does not receive a response within the check's configured TimeoutMs (default 5000 ms), THEN THE ConnectivityMonitor SHALL mark that check as failed with an error indicating timeout and report the result individually without affecting other in-progress checks.
5. IF the WebSocket connection to APCM is unavailable when a check result is ready, THEN THE ConnectivityMonitor SHALL discard the result and log a warning.

---

### Requirement 9: Dynamic Check Configuration Update

**User Story:** As a platform administrator, I want connectivity checks to update when configuration changes, so that I can add or remove checks without restarting the workstation client.

#### Acceptance Criteria

1. WHEN the CloudManager receives an updated configuration from APCM (via Phase 3 config_update), THE ConnectivityMonitor SHALL update its check list with the new ConnectivityChecks configuration.
2. THE ConnectivityMonitor SHALL apply the updated checks on the next execution cycle without requiring a restart of the Tray application, allowing any currently-running checks from the previous cycle to complete before applying the new list.
3. IF the updated ConnectivityChecks list is empty, THEN THE ConnectivityMonitor SHALL stop executing checks and remain idle until a non-empty list is received.

---

### Requirement 10: Telemetry Feature Toggle

**User Story:** As a platform administrator, I want to enable or disable telemetry per workstation, so that I can control bandwidth and data collection.

#### Acceptance Criteria

1. WHILE TelemetryEnabled is false in the configuration, THE CloudManager SHALL not start the TelemetryReporter and no telemetry messages shall be sent to APCM.
2. WHILE TelemetryEnabled is true in the configuration, THE CloudManager SHALL start the TelemetryReporter and telemetry shall be sent at the configured TelemetryIntervalSeconds (minimum 60 seconds, default 300 seconds).
3. WHEN TelemetryEnabled changes from true to false via a configuration update, THE CloudManager SHALL stop the TelemetryReporter and discard any unsent accumulated telemetry data.

---

### Requirement 11: Conditional ConnectivityMonitor Startup

**User Story:** As a platform administrator, I want the ConnectivityMonitor to only run when checks are configured, so that no unnecessary background work occurs on workstations without checks.

#### Acceptance Criteria

1. WHILE the ConnectivityChecks list is empty in the configuration, THE CloudManager SHALL not start the ConnectivityMonitor.
2. WHILE the ConnectivityChecks list contains one or more entries, THE CloudManager SHALL start the ConnectivityMonitor with the configured checks.
3. WHEN the ConnectivityChecks list transitions from containing entries to empty via a configuration update, THE CloudManager SHALL stop the ConnectivityMonitor and release its background threads.

---

### Requirement 12: Backend Telemetry Reception

**User Story:** As a platform administrator, I want the backend to receive and process telemetry and connectivity results, so that data is available for dashboards and alerting.

#### Acceptance Criteria

1. WHEN the backend WebSocket handler receives a message with type "telemetry", THE Backend SHALL validate the payload structure (queue_status, contingency_active, jobs_identified, avg_release_time_ms, disconnection_log) and update the workstation's last_connection timestamp in the database.
2. WHEN the backend WebSocket handler receives a message with type "connectivity_result", THE Backend SHALL validate the payload (check_id, success, latency_ms, error) and associate the result with the originating workstation.
3. IF the backend receives a telemetry or connectivity_result message with an invalid payload (missing required fields or wrong types), THEN THE Backend SHALL log the error with the workstation identifier and discard the message without closing the WebSocket connection.

---

### Requirement 13: CloudManager Lifecycle Integration

**User Story:** As a developer, I want TelemetryReporter and ConnectivityMonitor to follow the CloudManager lifecycle, so that resources are properly managed on start and stop.

#### Acceptance Criteria

1. WHEN CloudManager.Start() is called, THE CloudManager SHALL instantiate TelemetryReporter with the WebSocket client, pipe client, and configured TelemetryIntervalSeconds, and instantiate ConnectivityMonitor with the WebSocket client and configured ConnectivityChecks list.
2. WHEN CloudManager.Stop() is called, THE CloudManager SHALL call Stop() and Dispose() on both TelemetryReporter and ConnectivityMonitor, releasing all background threads and timers.
3. THE TelemetryReporter SHALL accumulate telemetry data in memory only; data loss on Tray restart is acceptable and SHALL NOT be persisted to disk or registry.

---

### Requirement 14: Logging and Observability

**User Story:** As a developer, I want all telemetry and connectivity operations to be logged in Spanish via AlwaysPrintLogger, so that troubleshooting follows project conventions.

#### Acceptance Criteria

1. THE TelemetryReporter SHALL log telemetry send events (including payload summary), errors during collection or transmission, and lifecycle changes (start, stop) using AlwaysPrintLogger with messages in Spanish.
2. THE ConnectivityMonitor SHALL log check execution start, individual check results (success/failure with latency), errors, and lifecycle changes (start, stop, config update) using AlwaysPrintLogger with messages in Spanish.
3. THE TelemetryReporter and ConnectivityMonitor SHALL NOT use Console.WriteLine for any output — all diagnostic output SHALL use AlwaysPrintLogger exclusively.
