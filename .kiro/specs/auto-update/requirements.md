# Requirements Document

## Introduction

Sistema de actualizaciones automáticas para el cliente AlwaysPrint. Permite que las workstations se actualicen automáticamente cuando hay una nueva versión del MSI disponible en el bucket S3 (`alwaysprint-artifacts`). El sistema involucra tres capas: el cliente Windows (Tray + Service), el backend Cloud (FastAPI), y el frontend Cloud (Next.js). La verificación se realiza al inicio del Tray y cada 24 horas, la descarga la ejecuta el Tray, y la instalación la ejecuta el Service (que tiene permisos de administrador) comunicándose via Named Pipe.

## Glossary

- **Tray_App**: Aplicación de bandeja del sistema AlwaysPrint (`AlwaysPrintTray`) que ejecuta en contexto de usuario y gestiona la interfaz, comunicación con Cloud, y verificación de actualizaciones.
- **Service**: Servicio Windows AlwaysPrint (`AlwaysPrintService`) que ejecuta como LocalSystem con permisos de administrador, responsable de instalar el MSI.
- **Update_Checker**: Componente del Tray_App que verifica periódicamente si hay actualizaciones disponibles consultando al Cloud_Backend.
- **Cloud_Backend**: API REST FastAPI que expone endpoints para consultar versión disponible y estado de actualizaciones automáticas por organización.
- **Cloud_Frontend**: Dashboard Next.js donde los administradores gestionan la configuración de actualizaciones automáticas a nivel de organización.
- **MSI_Bucket**: Bucket S3 `alwaysprint-artifacts` que almacena el instalador MSI en `latest/AlwaysPrint.msi` con metadata (version, build-date, commit-hash).
- **Registry_Config**: Configuración almacenada en el registro de Windows (`HKLM\SOFTWARE\Robles.AI\AlwaysPrint`) gestionada por `RegistryConfigManager`.
- **Named_Pipe**: Canal de comunicación IPC entre Tray_App y Service usando el pipe `AlwaysPrintService`.
- **Organization_Flag**: Flag booleano a nivel de organización en la base de datos Cloud que habilita o deshabilita actualizaciones automáticas para todas las workstations de esa organización.
- **Local_Flag**: Configuración booleana por workstation en el Registry_Config que habilita o deshabilita actualizaciones automáticas localmente.

## Requirements

### Requirement 1: Configuración local de actualizaciones automáticas

**User Story:** Como administrador de workstation, quiero habilitar o deshabilitar actualizaciones automáticas localmente en cada máquina, para controlar qué equipos se actualizan de forma autónoma.

#### Acceptance Criteria

1. THE Tray_App SHALL display a toggle option "Habilitar Actualizaciones Automáticas" in the configuration screen
2. WHEN the user toggles the auto-update option, THE Tray_App SHALL persist the value in the Registry_Config as a DWORD field named `AutoUpdateEnabled` (1 = enabled, 0 = disabled)
3. THE Registry_Config SHALL default the `AutoUpdateEnabled` field to 0 (disabled) when the field does not exist
4. WHEN the Service starts, THE Service SHALL ensure the `AutoUpdateEnabled` default value exists in the registry via `EnsureDefaults()`

### Requirement 2: Verificación periódica de actualizaciones

**User Story:** Como administrador de sistemas, quiero que las workstations verifiquen automáticamente si hay actualizaciones disponibles, para mantener el software actualizado sin intervención manual.

#### Acceptance Criteria

1. WHEN the Tray_App starts and the Local_Flag is enabled, THE Update_Checker SHALL perform an update check immediately
2. WHILE the Tray_App is running and the Local_Flag is enabled, THE Update_Checker SHALL perform an update check every 24 hours
3. WHEN the Update_Checker performs a check, THE Update_Checker SHALL call the Cloud_Backend endpoint to retrieve the available version and the Organization_Flag status
4. WHEN the Cloud_Backend is unreachable, THE Update_Checker SHALL log a warning and retry on the next scheduled interval without interrupting normal Tray_App operation
5. WHEN the Local_Flag is disabled, THE Update_Checker SHALL not perform any update checks

### Requirement 3: Lógica de decisión de actualización

**User Story:** Como administrador de sistemas, quiero que la actualización solo proceda cuando ambos flags (local y organización) están activos y la versión es diferente, para evitar actualizaciones no deseadas.

#### Acceptance Criteria

1. WHEN the Update_Checker receives the response from Cloud_Backend, THE Update_Checker SHALL compare the available version with the locally installed version
2. WHEN the available version equals the installed version, THE Update_Checker SHALL log that no update is needed and skip the download
3. WHEN the Organization_Flag is disabled in the Cloud_Backend response, THE Update_Checker SHALL log that auto-updates are disabled for the organization and skip the download
4. WHEN both the Organization_Flag is enabled AND the available version differs from the installed version AND the Local_Flag is enabled, THE Update_Checker SHALL proceed to download the MSI

### Requirement 4: Descarga del MSI

**User Story:** Como workstation, quiero descargar el MSI actualizado de forma segura desde la Cloud, para tener el instalador listo para la actualización.

#### Acceptance Criteria

1. WHEN the Update_Checker determines an update is available, THE Tray_App SHALL download the MSI file from the Cloud_Backend download endpoint
2. THE Tray_App SHALL save the downloaded MSI to a temporary directory (`%TEMP%\AlwaysPrint\Updates\`)
3. THE Tray_App SHALL verify the integrity of the downloaded MSI by comparing its size with the expected size reported by the Cloud_Backend
4. IF the download fails or the integrity check fails, THEN THE Tray_App SHALL log an error, delete the partial file, and retry on the next scheduled interval
5. WHILE the download is in progress, THE Tray_App SHALL continue normal operation without blocking the user interface

### Requirement 5: Instalación del MSI via Service

**User Story:** Como sistema, quiero que el Service ejecute la instalación del MSI con permisos de administrador, para garantizar que la actualización se aplique correctamente.

#### Acceptance Criteria

1. WHEN the Tray_App completes the MSI download successfully, THE Tray_App SHALL send an `InstallUpdate` message to the Service via the Named_Pipe including the MSI file path
2. WHEN the Service receives the `InstallUpdate` message, THE Service SHALL verify that the MSI file exists at the specified path
3. WHEN the MSI file exists, THE Service SHALL execute a silent installation using `msiexec /i <path> /quiet /norestart`
4. IF the MSI file does not exist at the specified path, THEN THE Service SHALL log an error and respond with a failure acknowledgment
5. IF the installation process fails (non-zero exit code), THEN THE Service SHALL log the error with the exit code and respond with a failure acknowledgment
6. WHEN the installation completes successfully, THE Service SHALL restart the Tray_App process
7. WHEN the installation completes successfully, THE Service SHALL delete the temporary MSI file

### Requirement 6: Cloud Backend - Endpoint de verificación de actualización

**User Story:** Como desarrollador del cliente, quiero un endpoint API que retorne la versión disponible y el estado del flag de organización, para que las workstations puedan verificar actualizaciones con una sola llamada.

#### Acceptance Criteria

1. THE Cloud_Backend SHALL expose a GET endpoint at `/api/v1/updates/check` that accepts the workstation identifier
2. WHEN the endpoint is called, THE Cloud_Backend SHALL return the available MSI version, the Organization_Flag status, and the MSI file size
3. THE Cloud_Backend SHALL read the available version from the S3 object metadata of `latest/AlwaysPrint.msi` in the MSI_Bucket
4. THE Cloud_Backend SHALL read the Organization_Flag from the organization record in the database filtered by the workstation's `organization_id`
5. IF the S3 metadata is unavailable, THEN THE Cloud_Backend SHALL return an error response indicating the version cannot be determined

### Requirement 7: Cloud Backend - Endpoint de descarga del MSI

**User Story:** Como desarrollador del cliente, quiero un endpoint para descargar el MSI de forma segura, para que las workstations no necesiten acceso directo a S3.

#### Acceptance Criteria

1. THE Cloud_Backend SHALL expose a GET endpoint at `/api/v1/updates/download` that returns the MSI file
2. WHEN the endpoint is called, THE Cloud_Backend SHALL generate a presigned S3 URL for `latest/AlwaysPrint.msi` and redirect the client to it
3. THE Cloud_Backend SHALL validate that the requesting workstation belongs to an organization with the Organization_Flag enabled
4. IF the Organization_Flag is disabled for the workstation's organization, THEN THE Cloud_Backend SHALL return a 403 Forbidden response

### Requirement 8: Cloud Backend - Modelo de datos para Organization_Flag

**User Story:** Como administrador de la plataforma, quiero un campo en la base de datos que controle las actualizaciones automáticas por organización, para gestionar el despliegue de forma centralizada.

#### Acceptance Criteria

1. THE Cloud_Backend SHALL add a boolean field `auto_update_enabled` to the organization model with a default value of `false`
2. THE Cloud_Backend SHALL expose a PATCH endpoint at `/api/v1/organizations/{org_id}/auto-update` to toggle the Organization_Flag
3. WHEN the PATCH endpoint is called with `{"enabled": true}`, THE Cloud_Backend SHALL set `auto_update_enabled` to true for the specified organization
4. WHEN the PATCH endpoint is called with `{"enabled": false}`, THE Cloud_Backend SHALL set `auto_update_enabled` to false for the specified organization
5. THE Cloud_Backend SHALL require admin authentication for the PATCH endpoint

### Requirement 9: Cloud Frontend - Panel de administración de actualizaciones

**User Story:** Como administrador de la plataforma, quiero visualizar la versión vigente del MSI y controlar las actualizaciones automáticas desde el dashboard, para gestionar el despliegue sin acceder directamente a la base de datos.

#### Acceptance Criteria

1. THE Cloud_Frontend SHALL display the current MSI version (read from the MSI_Bucket metadata via Cloud_Backend) in the admin dashboard
2. THE Cloud_Frontend SHALL display a toggle control to enable or disable the Organization_Flag
3. WHEN the administrator toggles the auto-update control, THE Cloud_Frontend SHALL call the PATCH endpoint on the Cloud_Backend to update the Organization_Flag
4. THE Cloud_Frontend SHALL display the build date and commit hash of the current MSI version
5. THE Cloud_Frontend SHALL display a confirmation dialog before enabling auto-updates for the organization

### Requirement 10: Comunicación IPC para instalación de actualizaciones

**User Story:** Como desarrollador del cliente, quiero un nuevo tipo de mensaje Named Pipe para la instalación de actualizaciones, para mantener la arquitectura IPC consistente con el resto del sistema.

#### Acceptance Criteria

1. THE MessageType enum SHALL include a new value `InstallUpdate` for update installation requests
2. THE MessageType enum SHALL include a new value `InstallUpdateResponse` for update installation responses
3. THE Payloads SHALL include an `InstallUpdatePayload` class with a `MsiFilePath` string property
4. THE Payloads SHALL include an `InstallUpdateResponsePayload` class with `Success` (bool), `Message` (string), and `ExitCode` (int) properties
5. WHEN the Service receives an `InstallUpdate` message, THE MessageDispatcher SHALL route it to the update installation handler

### Requirement 11: Logging y observabilidad

**User Story:** Como ingeniero de soporte, quiero que todas las operaciones de actualización se registren en los logs, para diagnosticar problemas de actualización en workstations remotas.

#### Acceptance Criteria

1. THE Update_Checker SHALL log each check attempt with timestamp, result (update available/not available/error), and version information
2. THE Tray_App SHALL log the download progress start and completion with file size and duration
3. THE Service SHALL log the installation start, completion, and any errors with the MSI exit code
4. IF an update check, download, or installation fails, THEN THE system SHALL log the error with sufficient context for remote diagnosis
5. THE Cloud_Backend SHALL log each update check request with the workstation identifier and response status
