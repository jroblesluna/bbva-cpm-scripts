# Requirements Document

## Introduction

This feature adds a dedicated section within the System Configuration page that allows corporate administrators to execute inventory synchronization steps from the web UI. The sync_inventory.py script contains 6 independent correction steps that align VLANs, workstations, and devices with a canonical CSV. Currently these steps can only be run manually via SSH into the Docker container. This feature exposes each step individually (and a "run all" option) through a controlled UI with CSV upload, dry-run previewing, and real-time output streaming.

## Glossary

- **Sync_Dashboard**: The UI section within System Configuration that exposes inventory sync operations to corporate admins.
- **Corporate_Admin**: An authenticated admin user whose email ends in `@robles.ai` or `@sistemas.com.pe`.
- **Sync_Step**: One of the 6 independent operations in the inventory synchronization pipeline.
- **CSV_Step**: A Sync_Step that requires a canonical CSV file as input (Steps 1-3).
- **DB_Step**: A Sync_Step that operates exclusively on existing database records (Steps 4-6).
- **Sync_API**: The set of backend FastAPI endpoints that execute inventory sync operations.
- **Dry_Run**: An execution mode where the system computes and reports changes without applying them to the database.
- **Execution_Output**: The structured textual feedback produced during a Sync_Step execution (logs, counts, errors).
- **Canonical_CSV**: A CSV file with columns VLAN_CODE, VLAN_NAME, IP, MODELO, SERIE, UBICACION, DIRECCION, DISTRITO, PROVINCIA, DEPARTAMENTO, TIPO.

## Requirements

### Requirement 1: Corporate Admin Access Control

**User Story:** As a system operator, I want the inventory sync UI to be restricted to corporate admins, so that only authorized personnel can modify inventory data in bulk.

#### Acceptance Criteria

1. WHILE a user is not a Corporate_Admin, THE Sync_Dashboard SHALL not render any sync-related UI elements on the System Configuration page.
2. WHEN a Corporate_Admin navigates to the System Configuration page, THE Sync_Dashboard SHALL display the inventory synchronization section.
3. WHEN a non-Corporate_Admin sends a request to the Sync_API, THE Sync_API SHALL return HTTP 403 Forbidden.
4. THE Sync_API SHALL verify that the authenticated user's email domain matches one of the allowed domains (`@robles.ai`, `@sistemas.com.pe`) before processing any sync request.

### Requirement 2: CSV File Upload

**User Story:** As a corporate admin, I want to upload a canonical CSV file through the UI, so that CSV-dependent steps can execute without SSH access to the server.

#### Acceptance Criteria

1. WHEN a Corporate_Admin selects the inventory sync section, THE Sync_Dashboard SHALL display a file upload area that accepts `.csv` files.
2. WHEN a CSV file is uploaded, THE Sync_Dashboard SHALL validate that the file has the expected column headers (VLAN_CODE, VLAN_NAME, IP, MODELO, SERIE, UBICACION, DIRECCION, DISTRITO, PROVINCIA, DEPARTAMENTO, TIPO) and display an error if validation fails.
3. WHEN a valid CSV file is uploaded, THE Sync_Dashboard SHALL display a confirmation summary including the file name and number of rows parsed.
4. THE Sync_API SHALL accept a CSV file via multipart form upload and store it temporarily for the duration of the execution.
5. IF a CSV_Step is triggered without a CSV file having been uploaded, THEN THE Sync_Dashboard SHALL display an error indicating that a CSV file is required for that step.

### Requirement 3: Individual Step Execution

**User Story:** As a corporate admin, I want to execute each synchronization step independently, so that I can apply only the corrections needed without running the entire pipeline.

#### Acceptance Criteria

1. THE Sync_Dashboard SHALL display all 6 steps as individually selectable operations with descriptive labels: (1) Sync VLANs, (2) Reassign Workstations + CIDRs, (3) Upsert Devices, (4) Assign Orphan Devices, (5) Delete Empty VLANs, (6) Cleanup Redundant CIDRs.
2. WHEN a Corporate_Admin triggers a single step, THE Sync_API SHALL execute only that specific step and return its output.
3. WHILE a step is executing, THE Sync_Dashboard SHALL disable the trigger button for that step and display a loading indicator.
4. THE Sync_Dashboard SHALL visually distinguish CSV_Steps (1-3) from DB_Steps (4-6), indicating which ones require a CSV file.
5. WHEN a DB_Step (4, 5, or 6) is triggered, THE Sync_API SHALL execute it without requiring a CSV file.
6. WHEN a CSV_Step (1, 2, or 3) is triggered, THE Sync_API SHALL require a previously uploaded CSV file.

### Requirement 4: Run All Steps

**User Story:** As a corporate admin, I want to execute all 6 steps in sequence with a single action, so that I can perform a full inventory sync conveniently.

#### Acceptance Criteria

1. THE Sync_Dashboard SHALL provide a "Run All" button that executes all 6 steps in sequential order (1 through 6).
2. WHEN "Run All" is triggered, THE Sync_API SHALL execute each step sequentially and return the combined output of all steps.
3. IF any step fails during a "Run All" execution, THEN THE Sync_API SHALL stop execution, rollback the failed step, and return the output accumulated so far along with the error details.
4. WHEN "Run All" is triggered, THE Sync_Dashboard SHALL require a CSV file since Steps 1-3 depend on it.

### Requirement 5: Dry-Run Mode

**User Story:** As a corporate admin, I want to preview what changes a step would make before applying them, so that I can verify correctness and avoid unintended modifications.

#### Acceptance Criteria

1. THE Sync_Dashboard SHALL provide a "Dry Run" toggle that is enabled by default.
2. WHEN dry-run mode is active, THE Sync_API SHALL compute and report all changes without applying them to the database.
3. WHEN dry-run mode is active, THE Sync_Dashboard SHALL display a visual indicator (badge or banner) confirming that no changes are being applied.
4. WHEN dry-run results are satisfactory, THE Corporate_Admin SHALL be able to disable dry-run mode and re-execute the step to apply changes.

### Requirement 6: Execution Output Display

**User Story:** As a corporate admin, I want to see the detailed output of each step execution, so that I can verify what was created, updated, or deleted.

#### Acceptance Criteria

1. WHEN a step completes execution, THE Sync_Dashboard SHALL display the execution output including action counts (created, updated, deleted, unchanged, skipped).
2. THE Sync_Dashboard SHALL display the output in a scrollable, monospace-formatted area that preserves the line structure of the script output.
3. WHEN multiple steps are executed (Run All), THE Sync_Dashboard SHALL display output grouped by step with clear separators.
4. IF an error occurs during execution, THEN THE Sync_Dashboard SHALL display the error message in a visually distinct error style (red text or error badge).
5. WHEN a step completes, THE Sync_Dashboard SHALL display a summary badge indicating success or failure.

### Requirement 7: Organization Selection

**User Story:** As a corporate admin managing multiple organizations, I want to select which organization the sync operates on, so that I can target the correct tenant.

#### Acceptance Criteria

1. THE Sync_Dashboard SHALL display an organization selector defaulting to the first available organization.
2. WHEN a Corporate_Admin selects an organization, THE Sync_API SHALL scope all operations to that organization's data (tenant isolation).
3. THE Sync_API SHALL validate that the selected organization exists before executing any step.

### Requirement 8: Backend Sync API Endpoints

**User Story:** As the frontend application, I want dedicated API endpoints for inventory sync operations, so that each step can be triggered programmatically with proper authentication and validation.

#### Acceptance Criteria

1. THE Sync_API SHALL expose a POST endpoint for executing a single step: `POST /api/v1/admin/sync-inventory/execute`.
2. THE Sync_API SHALL accept parameters: `step` (integer 1-6 or "all"), `dry_run` (boolean), `organization_id` (UUID), and optionally a CSV file (multipart).
3. THE Sync_API SHALL return a JSON response containing: `success` (boolean), `step` (identifier), `dry_run` (boolean), `output` (string with execution logs), and `summary` (object with counts).
4. IF the CSV is malformed or missing required columns, THEN THE Sync_API SHALL return HTTP 422 with a descriptive error message.
5. IF a database error occurs during execution, THEN THE Sync_API SHALL rollback the transaction, return HTTP 500, and include the error details in the response.
6. THE Sync_API SHALL require admin authentication and Corporate_Admin domain verification on all sync endpoints.

### Requirement 9: Internationalization

**User Story:** As a user of the multilingual platform, I want all UI text in the sync inventory section to be translatable, so that the interface is consistent with the rest of the application.

#### Acceptance Criteria

1. THE Sync_Dashboard SHALL use `next-intl` translation keys for all user-visible text (labels, buttons, messages, errors, tooltips).
2. THE Sync_Dashboard SHALL define translation keys under a dedicated `syncInventory` namespace in both `messages/en.json` and `messages/es.json`.
3. THE Sync_Dashboard SHALL not contain any hardcoded user-visible strings in JSX.
