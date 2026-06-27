# Tareas de Implementación — Firma Digital ECDSA + Ejecución Remota OnDemand

## Feature 1: Firma Digital ECDSA

### Tarea 1.1: Migración de BD — campos crypto en Organization
- [ ] Crear migración Alembic: agregar columnas `ecdsa_private_key_encrypted` (Text), `ecdsa_cert_s3_key` (String 500), `ecdsa_cert_version` (Integer default 0), `ecdsa_cert_expires_at` (DateTime nullable)
- [ ] Actualizar modelo `Organization` con los campos nuevos
- [ ] Ejecutar migración en DEV y verificar

### Tarea 1.2: CryptoService — generación y firma
- [ ] Crear `app/services/crypto_service.py`
- [ ] Implementar `generate_key_pair(org_id: str, secret_key: str) -> (encrypted_private_key: str, cert_pem: bytes, expires_at: datetime)`
- [ ] Implementar `sign_config(encrypted_private_key: str, config_json: str, secret_key: str, org_id: str) -> (hash_full: str, signature_b64: str)`
- [ ] Implementar `decrypt_private_key(encrypted_data: str, secret_key: str, org_id: str) -> ECPrivateKey`
- [ ] Implementar `build_signed_config(config_json: str, hash_full: str, signature_b64: str, cert_version: int) -> str`
- [ ] Tests unitarios para generate, sign, verify round-trip

### Tarea 1.3: S3ConfigService — upload/download de configs firmados
- [ ] Crear `app/services/s3_config_service.py` siguiendo patrón de `S3DocsService`
- [ ] Implementar `upload_signed_config(org_id: str, hash_short: str, signed_json: str) -> str` (retorna S3 key)
- [ ] Implementar `upload_cert(org_id: str, cert_version: int, cert_pem: bytes) -> str` (retorna URL pública)
- [ ] Implementar `delete_signed_config(s3_key: str)`
- [ ] Implementar `delete_cert(s3_key: str)`
- [ ] Implementar `get_public_url(s3_key: str) -> str`

### Tarea 1.4: API — endpoint generar/renovar certificado
- [ ] Crear endpoint POST `/api/v1/organizations/{org_id}/certificate/generate` (admin only)
- [ ] Crear endpoint POST `/api/v1/organizations/{org_id}/certificate/rotate` (admin only)
- [ ] Crear endpoint GET `/api/v1/organizations/{org_id}/certificate/info` (retorna cert_version, expires_at, cert_url)
- [ ] Integrar audit logging en ambas operaciones
- [ ] Al rotar: re-firmar todos los ActionConfigs activos de la org y re-subir a S3

### Tarea 1.5: Modificar flujo de upload/activación de ActionConfig
- [ ] En `ActionConfigService.create_config()`: tras crear, firmar y subir a S3
- [ ] En `ActionConfigService.activate_config()`: firmar y subir a S3
- [ ] En `ActionConfigService.delete_config()`: eliminar de S3
- [ ] Validar que org tiene certificado antes de permitir activación (HTTP 409 si no)
- [ ] Actualizar `storage_path` con S3 key

### Tarea 1.6: Modificar endpoint de descarga de config para workstations
- [ ] Endpoint `download_workstation_config`: retornar JSON firmado desde S3 (o construir on-the-fly)
- [ ] Incluir `cert_version` en la respuesta de `/config/info`
- [ ] Incluir `cert_url` en la respuesta de registro exitoso (HTTP 201 de `/workstations/register`)

### Tarea 1.7: Cliente — SignatureVerifier
- [ ] Crear `AlwaysPrint.Shared/Security/SignatureVerifier.cs`
- [ ] Implementar `VerifyConfig(signedJson, certPath) -> (bool valid, string configJson)`
- [ ] Implementar `DownloadCertAsync(certUrl, localPath) -> bool`
- [ ] Implementar `GetLocalCertVersion() / SetLocalCertVersion(int)`
- [ ] Usar `ECDsa` + `X509Certificate2` de .NET 4.8 (System.Security.Cryptography)

### Tarea 1.8: Cliente — Integrar verificación en ConfigManager
- [ ] En `DownloadConfigAsync`: parsear JSON firmado envolvente
- [ ] Verificar hash: SHA256 de `config` serializado == campo `hash`
- [ ] Verificar firma: `SignatureVerifier.VerifyConfig()`
- [ ] Si `cert_version` > local: descargar nuevo .cer antes de verificar
- [ ] Si falla: rechazar config, loguear motivo, mantener anterior
- [ ] Si OK: extraer `config` y enviar al Service (flujo existente)

### Tarea 1.9: Cliente — Descarga de cert al registrarse
- [ ] En `OnCloudRegistrationSuccessful`: leer `cert_url` y `cert_version` de la respuesta
- [ ] Descargar .cer desde S3 URL pública
- [ ] Guardar en `C:\ProgramData\AlwaysPrint\config\org.cer`
- [ ] Guardar `CertVersion` en registro HKLM

### Tarea 1.10: Cliente — Manejo de cert_rotated vía WebSocket
- [ ] En `CloudManager`: agregar handler para mensaje tipo `cert_rotated`
- [ ] Descargar nuevo .cer desde `cert_url` del mensaje
- [ ] Reemplazar archivo local y actualizar `CertVersion` en registro
- [ ] Loguear la rotación

### Tarea 1.11: Frontend — UI de certificado en página de organización
- [ ] Agregar sección "Certificado Digital" en la página de organización
- [ ] Mostrar: estado (generado/no generado), versión, fecha expiración, URL .cer
- [ ] Botón "Generar Certificado" (si no existe)
- [ ] Botón "Renovar Certificado" (si existe) con confirmación
- [ ] Localización es/en

### Tarea 1.12: Extender AuditLog
- [ ] Agregar `CERT_GENERATED = "cert_generated"` y `CERT_ROTATED = "cert_rotated"` al enum ActionType
- [ ] Migración Alembic para el enum (si usa create_type)
- [ ] Agregar `ONDEMAND_EXECUTED = "ondemand_executed"` al enum

## Feature 2: Ejecución Remota de OnDemand

### Tarea 2.1: Endpoint GET ondemand-actions
- [ ] Crear GET `/api/v1/workstations/{workstation_id}/ondemand-actions`
- [ ] Resolver config efectivo con `resolve_effective_config()`
- [ ] Parsear `config_json`, extraer triggers con `event == "OnDemand"`
- [ ] Retornar `[{label: str, description: str}]`
- [ ] Validar tenant isolation (operador solo su org)
- [ ] Schema Pydantic: `OnDemandActionInfo`

### Tarea 2.2: Extender endpoint de comando con execute_on_demand
- [ ] Agregar `"execute_on_demand"` a `valid_commands` en `send_command`
- [ ] Agregar validación: verificar que `params.label` existe en config efectivo de la WS
- [ ] Timeout: 120 segundos para este tipo de comando (override del default 30s)
- [ ] Registrar AuditLog con action_type=ONDEMAND_EXECUTED

### Tarea 2.3: Cliente — handler execute_on_demand en CloudManager
- [ ] Agregar case `"execute_on_demand"` en `HandleCommand` switch
- [ ] Extraer `params.label`
- [ ] Enviar al Service via Pipe: `ExecuteOnDemandTriggerPayload { Label = label }`
- [ ] Esperar respuesta del Service (ya implementado en el flujo local)
- [ ] Responder vía WebSocket con `SendCommandResult(commandId, success, message)`
- [ ] Incluir `duration_ms` en la respuesta

## Feature 3: UI Frontend — OnDemand en Detalle de Workstation

### Tarea 3.1: Componente OnDemandActionsSection
- [ ] Crear componente interno en `workstations/page.tsx` (o extraer a archivo separado)
- [ ] GET `/workstations/{id}/ondemand-actions` con react-query
- [ ] Renderizar lista de acciones con label, description y botón Ejecutar
- [ ] Botón deshabilitado si `!workstation.is_online`
- [ ] Loading state mientras se carga la lista

### Tarea 3.2: Ejecución con confirmación y feedback
- [ ] Diálogo de confirmación (AlertDialog o window.confirm) con description de la acción
- [ ] POST command con loading spinner en el botón
- [ ] Toast success/failure con duración de la ejecución
- [ ] Manejar HTTP 409 (offline) y timeout (408/504)

### Tarea 3.3: Localización
- [ ] Agregar keys en `messages/es.json` namespace `workstations`: onDemandSection, executeAction, actionExecuted, actionFailed, actionConfirm, wsOfflineTooltip, noActionsAvailable
- [ ] Agregar keys equivalentes en `messages/en.json`

### Tarea 3.4: Integrar en WorkstationDetailModal
- [ ] Agregar `<OnDemandActionsSection>` después de la sección "Action Config"
- [ ] Pasar `workstation.id` y `workstation.is_online` como props
