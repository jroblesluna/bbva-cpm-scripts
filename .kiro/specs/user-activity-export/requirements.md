# Requirements Document

## Introduction

This feature adds two compliance-oriented capabilities to the AlwaysPrint Cloud Manager:

1. **User Activity Timeline** — A dedicated view showing the complete activity history for a specific user, including all login/logout events and actions performed. Filterable by date range and exportable for BBVA audit/compliance purposes.

2. **Workstation Inventory Export** — A button on the Workstations page that exports the COMPLETE inventory of all workstations as CSV/Excel, regardless of any frontend filters currently applied.

Both capabilities respect the existing role-based access model (Admin sees everything, Operator is scoped to their organization).

## Glossary

- **Cloud_Manager**: The AlwaysPrint Cloud Manager application (FastAPI backend + Next.js frontend)
- **Activity_Timeline**: A dedicated page displaying the chronological history of actions performed by a specific user
- **Audit_Log**: An existing database record capturing a user action (model: AuditLog with fields user_id, action_type, entity_type, entity_id, old_values, new_values, ip_address, created_at)
- **Workstation_Inventory**: The complete set of workstation records in the system, unfiltered
- **Admin**: A user with the Admin role who has unrestricted access to all organizations
- **Operator**: A user with the Operator role who is restricted to data within their own organization
- **Export_Service**: The backend component responsible for generating export files (CSV/Excel)
- **Timeline_Page**: The frontend page that renders the Activity_Timeline for a selected user
- **Organization**: A tenant entity that scopes data visibility for Operators

## Requirements

### Requirement 1: User Activity Timeline Backend Endpoint

**User Story:** As an Admin or Operator, I want to retrieve the complete activity history for a specific user via an API endpoint, so that I can review their actions for compliance audits.

#### Acceptance Criteria

1. WHEN a GET request is received at `/api/v1/users/{user_id}/activity`, THE Cloud_Manager SHALL return a paginated list of Audit_Log entries filtered by the specified user_id, ordered by created_at descending
2. WHEN the `start_date` query parameter is provided, THE Cloud_Manager SHALL return only Audit_Log entries with created_at greater than or equal to start_date
3. WHEN the `end_date` query parameter is provided, THE Cloud_Manager SHALL return only Audit_Log entries with created_at less than or equal to end_date
4. WHEN an Operator requests the Activity_Timeline for a user outside their Organization, THE Cloud_Manager SHALL return HTTP 403 Forbidden
5. WHEN an Admin requests the Activity_Timeline for any user, THE Cloud_Manager SHALL return the complete activity without organization restrictions
6. THE Cloud_Manager SHALL include login, logout, and all action_type events (CREATE, UPDATE, DELETE, CONFIG_CHANGE, CONTINGENCY_TOGGLE, MESSAGE_SENT, COMMAND_SENT, CERT_GENERATED, CERT_ROTATED, ONDEMAND_EXECUTED, REMOTE_VIEW_START, REMOTE_VIEW_STOP, LOGIN, LOGIN_FAILED) in the Activity_Timeline response

### Requirement 2: User Activity Timeline Frontend Page

**User Story:** As an Admin or Operator, I want a dedicated timeline page showing all activity for a selected user, so that I can visually review their action history.

#### Acceptance Criteria

1. WHEN the Timeline_Page is loaded for a specific user, THE Cloud_Manager SHALL display the user's full name and email at the top of the page
2. WHEN Audit_Log entries are loaded, THE Timeline_Page SHALL render each entry showing the action_type, entity_type, entity_name, ip_address, and created_at timestamp in a chronological list
3. WHEN the user selects a date range filter, THE Timeline_Page SHALL reload the activity data restricted to the selected date range
4. WHEN no Audit_Log entries match the filters, THE Timeline_Page SHALL display an empty state message indicating no activity was found for the selected criteria
5. THE Timeline_Page SHALL provide a navigation path accessible from the Users list page (Admin) or from the audit log user links

### Requirement 3: User Activity Export

**User Story:** As an Admin or Operator, I want to export a user's activity timeline as a file, so that I can provide it to BBVA compliance teams for audit purposes.

#### Acceptance Criteria

1. WHEN the export button is clicked on the Timeline_Page, THE Cloud_Manager SHALL generate a file containing all Audit_Log entries for the selected user within the applied date range filter
2. WHEN the export is requested, THE Export_Service SHALL generate the file in CSV format with columns: timestamp, action_type, entity_type, entity_name, old_values, new_values, ip_address
3. WHEN the export file is generated, THE Cloud_Manager SHALL trigger a browser download with a filename following the pattern `activity_{user_email}_{start_date}_{end_date}.csv`
4. IF the export request fails due to a server error, THEN THE Cloud_Manager SHALL display an error notification to the user and log the error details
5. WHEN an Operator requests the export for a user outside their Organization, THE Cloud_Manager SHALL return HTTP 403 Forbidden

### Requirement 4: Workstation Inventory Export Backend Endpoint

**User Story:** As an Admin or Operator, I want a backend endpoint that exports the complete workstation inventory, so that I can obtain a full inventory report regardless of frontend filters.

#### Acceptance Criteria

1. WHEN a GET request is received at `/api/v1/workstations/export`, THE Export_Service SHALL return a file containing ALL workstation records accessible to the requesting user, ignoring any pagination or filter parameters
2. THE Export_Service SHALL include the following fields in the export: hostname, ip_private, current_user, organization_name, tray_version, action_config_name, last_connection, is_online (as "Online"/"Offline" text), and vlan_name
3. WHEN an Operator requests the export, THE Export_Service SHALL include only workstations belonging to the Operator's Organization
4. WHEN an Admin requests the export, THE Export_Service SHALL include all workstations across all organizations
5. THE Export_Service SHALL generate the file in CSV format with UTF-8 BOM encoding for Excel compatibility
6. WHEN the export file is generated, THE Cloud_Manager SHALL set the Content-Disposition header with filename `workstations_inventory_{date}.csv`

### Requirement 5: Workstation Inventory Export Frontend Button

**User Story:** As an Admin or Operator, I want a clearly labeled export button on the Workstations page that downloads the full inventory, so that I can obtain a complete report without confusion about applied filters.

#### Acceptance Criteria

1. THE Timeline_Page SHALL display an export button on the Workstations list page with a label indicating full inventory export (e.g., "Exportar inventario completo")
2. WHEN the export button is hovered or focused, THE Cloud_Manager SHALL display a tooltip clarifying that the export includes ALL workstations regardless of current search or filter state
3. WHEN the export button is clicked, THE Cloud_Manager SHALL initiate a download request to the workstation inventory export endpoint
4. WHILE the export file is being generated, THE Cloud_Manager SHALL display a loading indicator on the export button to prevent duplicate requests
5. IF the export request fails, THEN THE Cloud_Manager SHALL display an error notification with a descriptive message
6. THE Cloud_Manager SHALL render the export button for users with Admin or Operator roles only, hiding it from ReadOnly users

### Requirement 6: Internationalization Support

**User Story:** As a user of the Cloud Manager, I want all new UI text to be available in both Spanish and English, so that the interface remains consistent with the existing i18n setup.

#### Acceptance Criteria

1. THE Cloud_Manager SHALL define all new user-facing strings for the Activity_Timeline and Workstation Inventory Export features in both `es.json` and `en.json` translation files
2. THE Cloud_Manager SHALL use next-intl translation keys for all labels, buttons, tooltips, error messages, and empty states introduced by this feature
3. WHEN the user's locale is Spanish, THE Cloud_Manager SHALL display all new text in Spanish
4. WHEN the user's locale is English, THE Cloud_Manager SHALL display all new text in English
