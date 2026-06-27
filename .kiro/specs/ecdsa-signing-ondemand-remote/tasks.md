# Tareas de Implementación — Firma Digital ECDSA + Ejecución Remota OnDemand

## Feature 1: Firma Digital ECDSA

### Tarea 1.1: Migración de BD — campos crypto en Organization
- [x] Crear migración Alembic: agregar columnas `ecdsa_private_key_encrypted` (Text), `ecdsa_cert_s3_key` (String 500), `ecdsa_cert_version` (Integer default 0), `ecdsa_cert_expires_at` (DateTime nullable)
- [x] Actualizar modelo `Organization` con los campos nuevos
- [x] Ejecutar migración en DEV y verificar

### Tarea 1.2: CryptoService — generación y firma
- [x] Crear `app/services/crypto_service.py`
- [x] Implementar `generate_key_pair(org_id: str, secret_key: str) -> (encrypted_private_key: str, cert_pem: bytes, expires_at: datetime)`
- [x] Implementar `sign_config(encrypted_private_key: str, config_json: str, secret_key: str, org_id: str) -> (hash_full: str, signature_b64: str)`
- [x] Implementar `decrypt_private_key(encrypted_data: str, secret_key: str, org_id: str) -> ECPrivateKey`
- [x] Implementar `build_signed_config(config_json: str, hash_full: str, signature_b64: str, cert_version: int) -> str`
- [x] Tests unitarios para generate, sign, verify round-trip

### Tarea 1.3: S3ConfigService — upload/download de configs firmados
- [x] Crear `app/services/s3_config_service.py` siguiendo patrón de `S3DocsService`
- [x] Implementar `upload_signed_config(org_id: str, hash_short: str, signed_json: str) -> str` (retorna S3 key)
- [x] Implementar `upload_cert(org_id: str, cert_version: int, cert_pem: bytes) -> str` (retorna URL pública)
- [x] Implementar `delete_signed_config(s3_key: str)`
- [x] Implementar `delete_cert(s3_key: str)`
- [x] Implementar `get_public_url(s3_key: str) -> str`

### Tarea 1.4: API — endpoint generar/renovar certificado
- [x] Crear endpoint POST `/api/v1/organizations/{org_id}/certificate/generate` (admin only)
- [x] Crear endpoint POST `/api/v1/organizations/{org_id}/certificate/rotate` (admin only)
- [x] Crear endpoint GET `/api/v1/organizations/{org_id}/certificate/info` (retorna cert_version, expires_at, cert_url)
- [x] Integrar audit logging en ambas operaciones
- [x] Al rotar: re-firmar todos los ActionConfigs activos de la org y re-subir a S3

### Tarea 1.5: Modificar flujo de upload/activación de ActionConfig
- [x] En `ActionConfigService.create_config()`: tras crear, firmar y subir a S3
- [x] En `ActionConfigService.activate_config()`: firmar y subir a S3
- [x] En `ActionConfigService.delete_config()`: eliminar de S3
- [x] Validar que org tiene certificado antes de permitir activación (HTTP 409 si no)
- [x] Actualizar `storage_path` con S3 key

### Tarea 1.6: Modificar endpoint de descarga de config para workstations
- [x] Endpoint `download_workstation_config`: retornar JSON firmado desde S3 (o construir on-the-fly)
- [x] Incluir `cert_version` en la respuesta de `/config/info`
- [x] Incluir `cert_url` en la respuesta de registro exitoso (HTTP 201 de `/workstations/register`)

### Tarea 1.7: Cliente — SignatureVerifier
- [x] Crear `AlwaysPrint.Shared/Security/SignatureVerifier.cs`
- [x] Implementar `VerifyConfig(signedJson, certPath) -> (bool valid, string configJson)`
- [x] Implementar `DownloadCertAsync(certUrl, localPath) -> bool`
- [x] Implementar `GetLocalCertVersion() / SetLocalCertVersion(int)`
- [x] Usar `ECDsa` + `X509Certificate2` de .NET 4.8 (System.Security.Cryptography)

### Tarea 1.8: Cliente — Integrar verificación en ConfigManager
- [x] En `DownloadConfigAsync`: parsear JSON firmado envolvente
- [x] Verificar hash: SHA256 de `config` serializado == campo `hash`
- [x] Verificar firma: `SignatureVerifier.VerifyConfig()`
- [x] Si `cert_version` > local: descargar nuevo .cer antes de verificar
- [x] Si falla: rechazar config, loguear motivo, mantener anterior
- [x] Si OK: extraer `config` y enviar al Service (flujo existente)

### Tarea 1.9: Cliente — Descarga de cert al registrarse
- [x] En `OnCloudRegistrationSuccessful`: leer `cert_url` y `cert_version` de la respuesta
- [x] Descargar .cer desde S3 URL pública
- [x] Guardar en `C:\ProgramData\AlwaysPrint\config\org.cer`
- [x] Guardar `CertVersion` en registro HKLM

### Tarea 1.10: Cliente — Manejo de cert_rotated vía WebSocket
- [x] En `CloudManager`: agregar handler para mensaje tipo `cert_rotated`
- [x] Descargar nuevo .cer desde `cert_url` del mensaje
- [x] Reemplazar archivo local y actualizar `CertVersion` en registro
- [x] Loguear la rotación

### Tarea 1.11: Frontend — UI de certificado en página de organización
- [x] Agregar sección "Certificado Digital" en la página de organización
- [x] Mostrar: estado (generado/no generado), versión, fecha expiración, URL .cer
- [x] Botón "Generar Certificado" (si no existe)
- [x] Botón "Renovar Certificado" (si existe) con confirmación
- [x] Localización es/en

### Tarea 1.12: Extender AuditLog
- [x] Agregar `CERT_GENERATED = "cert_generated"` y `CERT_ROTATED = "cert_rotated"` al enum ActionType
- [x] Migración Alembic para el enum (si usa create_type)
- [x] Agregar `ONDEMAND_EXECUTED = "ondemand_executed"` al enum

## Feature 2: Ejecución Remota de OnDemand

### Tarea 2.1: Endpoint GET ondemand-actions
- [x] Crear GET `/api/v1/workstations/{workstation_id}/ondemand-actions`
- [x] Resolver config efectivo con `resolve_effective_config()`
- [x] Parsear `config_json`, extraer triggers con `event == "OnDemand"`
- [x] Retornar `[{label: str, description: str}]`
- [x] Validar tenant isolation (operador solo su org)
- [x] Schema Pydantic: `OnDemandActionInfo`

### Tarea 2.2: Extender endpoint de comando con execute_on_demand
- [x] Agregar `"execute_on_demand"` a `valid_commands` en `send_command`
- [x] Agregar validación: verificar que `params.label` existe en config efectivo de la WS
- [x] Timeout: 120 segundos para este tipo de comando (override del default 30s)
- [x] Registrar AuditLog con action_type=ONDEMAND_EXECUTED

### Tarea 2.3: Cliente — handler execute_on_demand en CloudManager
- [x] Agregar case `"execute_on_demand"` en `HandleCommand` switch
- [x] Extraer `params.label`
- [x] Enviar al Service via Pipe: `ExecuteOnDemandTriggerPayload { Label = label }`
- [x] Esperar respuesta del Service (ya implementado en el flujo local)
- [x] Responder vía WebSocket con `SendCommandResult(commandId, success, message)`
- [x] Incluir `duration_ms` en la respuesta

## Feature 3: UI Frontend — OnDemand en Detalle de Workstation

### Tarea 3.1: Componente OnDemandActionsSection
- [x] Crear componente interno en `workstations/page.tsx` (o extraer a archivo separado)
- [x] GET `/workstations/{id}/ondemand-actions` con react-query
- [x] Renderizar lista de acciones con label, description y botón Ejecutar
- [x] Botón deshabilitado si `!workstation.is_online`
- [x] Loading state mientras se carga la lista

### Tarea 3.2: Ejecución con confirmación y feedback
- [x] Diálogo de confirmación (AlertDialog o window.confirm) con description de la acción
- [x] POST command con loading spinner en el botón
- [x] Toast success/failure con duración de la ejecución
- [x] Manejar HTTP 409 (offline) y timeout (408/504)

### Tarea 3.3: Localización
- [x] Agregar keys en `messages/es.json` namespace `workstations`: onDemandSection, executeAction, actionExecuted, actionFailed, actionConfirm, wsOfflineTooltip, noActionsAvailable
- [x] Agregar keys equivalentes en `messages/en.json`

### Tarea 3.4: Integrar en WorkstationDetailModal
- [x] Agregar `<OnDemandActionsSection>` después de la sección "Action Config"
- [x] Pasar `workstation.id` y `workstation.is_online` como props
