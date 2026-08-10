# Implementation Plan: User Activity Export

## Overview

This plan implements the User Activity Timeline and Workstation Inventory Export features following the file-by-file plan from the design document. The implementation progresses from backend service layer → backend endpoints → property tests → frontend API → frontend pages → i18n, ensuring each step builds on the previous one with no orphaned code.

## Tasks

- [x] 1. Backend CSV export service and schemas
  - [x] 1.1 Create `app/services/export_csv.py` — shared CSV generation service
    - Implement `CSVExportService` class with static methods:
      - `utf8_bom()` → returns BOM bytes `b'\xef\xbb\xbf'`
      - `generate_activity_csv(logs, entity_names)` → yields CSV rows (header + data) for user activity export with columns: timestamp, action_type, entity_type, entity_name, old_values, new_values, ip_address
      - `generate_workstation_csv(workstations)` → yields CSV rows for workstation inventory with columns: hostname, ip_private, current_user, organization_name, tray_version, action_config_name, last_connection, is_online, vlan_name
    - Use Python `csv` module with `io.StringIO` for proper escaping
    - Convert `is_online` boolean to "Online"/"Offline" text in workstation CSV
    - Serialize `old_values`/`new_values` JSON fields as compact JSON strings
    - _Requirements: 3.2, 4.2, 4.5_

  - [x] 1.2 Add `UserActivityExportParams` schema to `app/schemas/audit.py`
    - Add Pydantic model with optional `start_date: Optional[datetime]` and `end_date: Optional[datetime]` fields
    - _Requirements: 1.2, 1.3_

- [x] 2. Backend user activity endpoints
  - [x] 2.1 Create `app/api/v1/endpoints/user_activity.py` — activity timeline + export endpoints
    - Create APIRouter with prefix for user activity
    - Implement `GET /` (paginated activity list):
      - Accept path param `user_id` (UUID), query params `start_date`, `end_date`, `cursor`, `limit` (default 15, max 100)
      - Validate requesting user's access: Admin → unrestricted; Operator → only users in same org → else 403
      - Query `audit_logs` table filtered by `user_id`, apply date range filters, order by `created_at DESC`
      - Implement cursor-based pagination (base64 encoded timestamp|uuid)
      - Resolve entity names (reuse pattern from existing `audit.py`)
      - Return `{ total, logs[], next_cursor, has_more }`
    - Implement `GET /export` (CSV streaming export):
      - Same auth validation as above
      - Query ALL matching audit logs (no pagination)
      - Use `CSVExportService.generate_activity_csv()` for streaming
      - Return `StreamingResponse` with UTF-8 BOM, Content-Type `text/csv; charset=utf-8`
      - Set Content-Disposition: `attachment; filename="activity_{user_email}_{start}_{end}.csv"`
    - Handle errors: 404 if user_id not found, 403 for cross-org operator access, 422 for invalid date range
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 3.1, 3.2, 3.3, 3.5_

  - [x] 2.2 Add export endpoint to `app/api/v1/endpoints/workstations.py`
    - Add `GET /export` route to existing workstations router
    - Validate auth: Admin → all workstations; Operator → only their org's workstations
    - Query workstations with JOINs to organizations and vlans tables for names
    - Use `CSVExportService.generate_workstation_csv()` for streaming
    - Return `StreamingResponse` with UTF-8 BOM, Content-Type `text/csv; charset=utf-8`
    - Set Content-Disposition: `attachment; filename="workstations_inventory_{YYYY-MM-DD}.csv"`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 2.3 Register user_activity router in `app/api/v1/router.py`
    - Import `user_activity` router
    - Register under prefix `/users/{user_id}/activity` with appropriate tags
    - Ensure it doesn't conflict with existing user routes
    - _Requirements: 1.1_

- [x] 3. Checkpoint — Backend verification
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Property-based tests (Hypothesis)
  - [x] 4.1 Create `tests/test_export_csv_service.py` — unit tests for CSV service
    - Test `utf8_bom()` returns correct bytes
    - Test `generate_activity_csv()` with sample data produces valid CSV with correct headers
    - Test `generate_workstation_csv()` with sample data produces valid CSV with correct headers
    - Test `is_online` → "Online"/"Offline" conversion
    - Test empty data produces headers-only CSV
    - _Requirements: 3.2, 4.2, 4.5_

  - [x] 4.2 Create `tests/test_user_activity.py` — property tests for activity endpoint
    - **Property 1: User activity filter returns only target user's logs**
    - **Validates: Requirements 1.1**
    - Generate random audit log datasets with multiple user_ids using Hypothesis
    - Call filter logic, verify all returned logs have matching user_id and are ordered by created_at DESC

  - [x] 4.3 Write property test for date range filtering in `tests/test_user_activity.py`
    - **Property 2: Date range filtering preserves bounds**
    - **Validates: Requirements 1.2, 1.3**
    - Generate random timestamps and date bounds using Hypothesis
    - Verify all returned logs have `created_at >= start_date` and `created_at <= end_date`

  - [x] 4.4 Write property test for operator tenant isolation in `tests/test_user_activity.py`
    - **Property 3: Operator tenant isolation**
    - **Validates: Requirements 1.4, 3.5, 4.3**
    - Generate random org assignments, verify 403 when operator accesses user from different org

  - [x] 4.5 Write property test for action type inclusion in `tests/test_user_activity.py`
    - **Property 5: All action types are included without filtering**
    - **Validates: Requirements 1.6**
    - Generate logs with all possible ActionType values, verify none are filtered out

  - [x] 4.6 Write property test for activity CSV column completeness in `tests/test_user_activity.py`
    - **Property 7: Activity CSV column completeness**
    - **Validates: Requirements 3.2**
    - Generate random audit data, export via CSV service, verify every row has exactly 7 columns with correct headers

  - [x] 4.7 Create `tests/test_workstation_export.py` — property tests for workstation export
    - **Property 9: Workstation CSV column completeness**
    - **Validates: Requirements 4.2**
    - Generate random workstation data, export via CSV service, verify every row has exactly 9 columns with correct headers

  - [x] 4.8 Write property test for UTF-8 BOM encoding in `tests/test_workstation_export.py`
    - **Property 10: UTF-8 BOM encoding for Excel compatibility**
    - **Validates: Requirements 4.5**
    - Generate any export (activity or workstation), verify file content begins with BOM bytes (0xEF, 0xBB, 0xBF)

- [x] 5. Frontend API extensions
  - [x] 5.1 Extend `src/lib/api.ts` with user activity and workstation export methods
    - Add to `usersApi`:
      - `activity(userId, params?)` → GET `/api/v1/users/{userId}/activity` with query params (start_date, end_date, cursor, limit), returns `AuditLogListResponse`
      - `exportActivity(userId, params?)` → GET `/api/v1/users/{userId}/activity/export`, triggers browser file download via blob URL
    - Add to `workstationsApi`:
      - `exportInventory()` → GET `/api/v1/workstations/export`, triggers browser file download via blob URL
    - Use existing auth token pattern from other API methods
    - _Requirements: 2.3, 3.1, 3.3, 4.1, 5.3_

- [x] 6. Frontend pages and components
  - [x] 6.1 Create Timeline page at `src/app/dashboard/admin/users/[userId]/activity/page.tsx`
    - Display user info header (full_name, email) fetched via existing users API
    - Implement date range picker (start_date, end_date) with form validation
    - Render timeline list with audit log entries showing: action_type, entity_type, entity_name, ip_address, created_at
    - Implement cursor-based infinite scroll pagination using `usersApi.activity()`
    - Add "Exportar CSV" button calling `usersApi.exportActivity()` with loading state
    - Show empty state message when no results match filters
    - Use `useTranslations('timeline')` for all text
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.4_

  - [x] 6.2 Add "Ver actividad" link to Users list page (`src/app/dashboard/admin/users/page.tsx`)
    - Add a link/button per user row that navigates to `/dashboard/admin/users/[userId]/activity`
    - Use translated label from `timeline` namespace
    - _Requirements: 2.5_

  - [x] 6.3 Add "Exportar inventario completo" button to Workstations page (`src/app/dashboard/workstations/page.tsx`)
    - Add export button in the page header area
    - Show tooltip on hover clarifying "Exporta TODAS las workstations, sin importar filtros aplicados"
    - Call `workstationsApi.exportInventory()` on click
    - Show loading indicator during export to prevent duplicate requests
    - Show error toast on failure
    - Hide button for ReadOnly users (role check)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

- [x] 7. Internationalization
  - [x] 7.1 Add `timeline` namespace translations to `messages/es.json` and `messages/en.json`
    - Add Spanish translations in `es.json` for: page title, user info labels, date range picker labels, export button, empty state message, error messages, tooltip text, loading states
    - Add English translations in `en.json` with equivalent keys
    - Include keys for: timeline.title, timeline.exportCsv, timeline.exportInventory, timeline.emptyState, timeline.dateRange.start, timeline.dateRange.end, timeline.tooltip.fullExport, timeline.errors.exportFailed, timeline.errors.loadFailed, timeline.loading
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 8. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (Properties 1, 2, 3, 5, 7, 9, 10)
- Unit tests validate specific examples and edge cases
- Backend uses Python 3.12 / FastAPI; Frontend uses TypeScript / Next.js 15
- Import `Base` from `app.core.database` (never from `app.db`)
- All backend queries must respect tenant isolation (filter by `organization_id` for Operators)
- Use `hypothesis` library (already installed in project) for property-based tests

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["2.3"] },
    { "id": 3, "tasks": ["4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7", "4.8", "5.1"] },
    { "id": 4, "tasks": ["6.1", "6.3"] },
    { "id": 5, "tasks": ["6.2", "7.1"] }
  ]
}
```
