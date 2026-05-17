# Implementation Plan: Almacenamiento S3 para MSI

## Overview

Implementación de un módulo Terraform S3 para almacenar el instalador MSI de AlwaysPrint, con integración en la configuración raíz y modificación del script `reinstall.ps1` para subir automáticamente el artefacto después de compilación exitosa. Las tareas 1 y 2 son independientes entre sí, la tarea 3 depende de ambas, y la tarea 4 es independiente.

## Tasks

- [ ] 1. Crear módulo Terraform S3 (`modules/s3/`)
  - Crear `AlwaysPrintProject/Cloud/terraform/modules/s3/main.tf` con todos los recursos:
    - `aws_s3_bucket.artifacts` con nombre local `alwaysprint-artifacts` y tags
    - `aws_s3_bucket_versioning.artifacts` con status `Enabled`
    - `aws_s3_bucket_server_side_encryption_configuration.artifacts` con `AES256`
    - `aws_s3_bucket_public_access_block.artifacts` con las 4 opciones en `true`
    - `aws_s3_bucket_ownership_controls.artifacts` con `BucketOwnerEnforced`
    - `aws_s3_bucket_policy.artifacts` con statements `PermitirLecturaEC2` (s3:GetObject) y `PermitirListadoEC2` (s3:ListBucket) usando `var.ec2_role_arn`
  - Crear `AlwaysPrintProject/Cloud/terraform/modules/s3/variables.tf` con variables `project_name`, `environment`, `ec2_role_arn` (todas tipo `string`, descripciones en español)
  - Crear `AlwaysPrintProject/Cloud/terraform/modules/s3/outputs.tf` con outputs `bucket_name` y `bucket_arn` (descripciones en español)
  - Todos los comentarios y descripciones en español
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 5.2, 5.3_

- [ ] 2. Agregar output `role_arn` al módulo EC2
  - Agregar en `AlwaysPrintProject/Cloud/terraform/modules/ec2/outputs.tf` el output `role_arn` con valor `aws_iam_role.ec2.arn` y descripción en español
  - _Requirements: 3.3_

- [ ] 3. Integrar módulo S3 en configuración raíz
  - Agregar bloque `module "s3"` en `AlwaysPrintProject/Cloud/terraform/main.tf` pasando `project_name`, `environment`, `ec2_role_arn = module.ec2.role_arn` con `depends_on = [module.ec2]`
  - Agregar outputs `s3_bucket_name` y `s3_bucket_arn` en `AlwaysPrintProject/Cloud/terraform/outputs.tf` con descripciones en español
  - _Requirements: 3.1, 3.2, 3.3_

- [ ] 4. Checkpoint — Validar Terraform
  - Ejecutar `terraform validate` en el directorio `AlwaysPrintProject/Cloud/terraform/` para verificar sintaxis
  - Ejecutar `terraform plan` (si hay credenciales disponibles) para verificar dependencias
  - Ensure all validations pass, ask the user if questions arise.

- [ ] 5. Agregar PASO 8.5 a `reinstall.ps1`
  - Insertar bloque PowerShell entre PASO 8 y PASO 9 en `AlwaysPrintProject/Client/reinstall.ps1`
  - Implementar lógica condicional: si `$hasChanges` y MSI existe → subir; si no hay cambios → omitir con log; si MSI no existe → omitir con warning
  - Comando de subida: `aws s3 cp $msiPath s3://alwaysprint-artifacts/latest/AlwaysPrint.msi --metadata $metadata`
  - Metadata: `version` (short commit 7 chars), `build-date` (ISO 8601), `commit-hash` (full SHA)
  - Manejo de error: `try/catch` con `Write-Step` warning + `Read-Host` preguntando si continuar (S/N)
  - Si usuario responde no-S → `throw` para abortar
  - Todos los mensajes con `Write-Step` en español
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 5.1_

- [ ] 6. Checkpoint final — Verificación completa
  - Verificar que `terraform validate` pasa sin errores
  - Verificar que el script `reinstall.ps1` tiene sintaxis PowerShell válida (parseo sin errores)
  - Ensure all validations pass, ask the user if questions arise.

## Task Dependency Graph

```json
{
  "waves": [
    ["1", "2", "5"],
    ["3"],
    ["4"],
    ["6"]
  ]
}
```

## Notes

- No se aplica Property-Based Testing — esta feature es exclusivamente IaC (Terraform) y scripting (PowerShell)
- El bucket `alwaysprint-artifacts` es un nombre global en AWS; si está ocupado se deberá ajustar
- El script asume que la workstation tiene AWS CLI configurado con permisos `s3:PutObject`
- Las tareas 1 y 2 pueden ejecutarse en paralelo; la tarea 3 requiere que ambas estén completas
- La tarea 5 es independiente de las tareas Terraform
