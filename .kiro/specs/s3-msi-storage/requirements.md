# Requirements Document

## Introduction

Almacenamiento centralizado del instalador MSI de AlwaysPrint en Amazon S3. Se crea un nuevo módulo Terraform para provisionar un bucket S3 seguro con versionado, y se modifica el script `reinstall.ps1` para subir automáticamente el MSI al bucket después de una compilación exitosa. Esto permite distribuir el instalador a workstations remotas sin depender del repositorio Git.

## Glossary

- **S3_Module**: Módulo Terraform (`modules/s3`) que define el bucket S3, sus políticas de seguridad y configuración de versionado.
- **MSI_Bucket**: Bucket S3 con nombre `alwaysprint-artifacts` que almacena los artefactos MSI del cliente AlwaysPrint.
- **Reinstall_Script**: Script PowerShell `reinstall.ps1` ubicado en `AlwaysPrintProject/Client/` que gestiona la desinstalación, compilación e instalación del cliente AlwaysPrint.
- **EC2_Role**: Rol IAM (`alwaysprint-prod-ec2-role`) asignado a la instancia EC2 del proyecto, definido en el módulo `modules/ec2`.
- **Upload_Step**: Nuevo paso en el Reinstall_Script que sube el MSI compilado al MSI_Bucket usando AWS CLI.

## Requirements

### Requirement 1: Creación del módulo Terraform S3

**User Story:** Como ingeniero de infraestructura, quiero un módulo Terraform dedicado para el bucket S3 de artefactos MSI, para mantener la infraestructura organizada y reutilizable.

#### Acceptance Criteria

1. WHEN Terraform apply is executed, THE S3_Module SHALL create a bucket named `alwaysprint-artifacts`
2. THE S3_Module SHALL enable versioning on the MSI_Bucket to preserve historical MSI versions
3. THE S3_Module SHALL configure server-side encryption using AES-256 (SSE-S3) on the MSI_Bucket
4. THE S3_Module SHALL block all public access on the MSI_Bucket by enabling all four public access block settings
5. THE S3_Module SHALL output the bucket name and bucket ARN as module outputs
6. THE S3_Module SHALL accept `project_name` and `environment` as input variables

### Requirement 2: Seguridad y acceso al bucket

**User Story:** Como ingeniero de seguridad, quiero que el bucket S3 tenga acceso restringido y cifrado, para proteger los artefactos de instalación contra acceso no autorizado.

#### Acceptance Criteria

1. THE S3_Module SHALL enforce that the bucket owner has full control via object ownership configuration (BucketOwnerEnforced)
2. THE S3_Module SHALL disable ACLs on the MSI_Bucket
3. WHEN the EC2_Role is configured, THE S3_Module SHALL grant read-only access (s3:GetObject, s3:ListBucket) to the EC2_Role on the MSI_Bucket
4. THE S3_Module SHALL accept the EC2 role ARN as an input variable to configure the read policy

### Requirement 3: Integración del módulo S3 en la configuración raíz

**User Story:** Como ingeniero de infraestructura, quiero que el módulo S3 esté integrado en la configuración Terraform raíz, para que se despliegue junto con el resto de la infraestructura.

#### Acceptance Criteria

1. WHEN the root Terraform configuration is applied, THE root module SHALL invoke the S3_Module passing project_name, environment, and the EC2 role ARN
2. THE root module SHALL expose the bucket name and ARN as root-level outputs
3. THE S3_Module SHALL depend on the EC2 module to ensure the IAM role exists before creating the bucket policy

### Requirement 4: Subida del MSI a S3 después de compilación

**User Story:** Como desarrollador, quiero que el MSI se suba automáticamente a S3 después de una compilación exitosa, para que las workstations puedan descargar la última versión sin acceso al repositorio.

#### Acceptance Criteria

1. WHEN the Reinstall_Script completes a successful compilation (PASO 8) and the MSI file exists, THE Upload_Step SHALL upload the MSI to the MSI_Bucket using `aws s3 cp`
2. THE Upload_Step SHALL place the MSI at the S3 key path `latest/AlwaysPrint.msi`
3. THE Upload_Step SHALL include metadata with the upload: version (from git tag or commit short hash), build-date (ISO 8601 format), and commit-hash (full SHA)
4. IF the upload fails, THEN THE Upload_Step SHALL log a warning and prompt the user to decide whether to continue with the installation or abort the script
5. WHEN no compilation occurred (no changes detected), THE Upload_Step SHALL skip the upload and log that it was omitted

### Requirement 5: Mensajes y comentarios en español

**User Story:** Como miembro del equipo, quiero que todos los mensajes de log y comentarios estén en español, para mantener consistencia con las convenciones del proyecto.

#### Acceptance Criteria

1. THE Upload_Step SHALL display all log messages in Spanish using the existing `Write-Step` function
2. THE S3_Module SHALL include all Terraform descriptions in Spanish
3. THE S3_Module SHALL include code comments in Spanish
