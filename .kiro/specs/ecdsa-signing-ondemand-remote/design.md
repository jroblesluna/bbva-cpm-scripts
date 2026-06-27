# Documento de Diseño — Firma Digital ECDSA de AlwaysConfig + Ejecución Remota de OnDemand

## Arquitectura General

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND                                       │
│  ┌──────────────────┐  ┌───────────────────────┐  ┌─────────────────────┐ │
│  │ Org Settings     │  │ Workstation Detail     │  │ Action Config       │ │
│  │ • Generar Cert   │  │ • OnDemand Actions     │  │ • Upload/Activate   │ │
│  │ • Renovar Cert   │  │ • Execute Button       │  │ (triggers signing)  │ │
│  └────────┬─────────┘  └──────────┬────────────┘  └─────────┬───────────┘ │
└───────────┼────────────────────────┼─────────────────────────┼─────────────┘
            │                        │                         │
            ▼                        ▼                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              BACKEND                                        │
│  ┌──────────────────┐  ┌───────────────────────┐  ┌─────────────────────┐ │
│  │ CryptoService    │  │ Workstation Command    │  │ S3ConfigService     │ │
│  │ • generate_keys  │  │ • execute_on_demand    │  │ • upload_signed     │ │
│  │ • sign_config    │  │ • list_ondemand_actions│  │ • delete_signed     │ │
│  │ • rotate_keys    │  │ • wait_response        │  │ • get_public_url    │ │
│  └────────┬─────────┘  └──────────┬────────────┘  └─────────┬───────────┘ │
│           │                        │                         │             │
│           ▼                        ▼                         ▼             │
│  ┌──────────────┐    ┌───────────────────┐    ┌─────────────────────────┐ │
│  │ PostgreSQL   │    │ WebSocket Manager │    │ S3 Bucket               │ │
│  │ • org keys   │    │ • send_to_ws      │    │ • configs/{org}/{h}.sig │ │
│  │ • audit_logs │    │ • command_waiter   │    │ • certs/{org}/v{n}.cer  │ │
│  └──────────────┘    └────────┬──────────┘    └─────────────────────────┘ │
└────────────────────────────────┼────────────────────────────────────────────┘
                                 │ WebSocket
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CLIENTE WINDOWS                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ AlwaysPrintTray                                                       │  │
│  │  ┌──────────────┐  ┌───────────────────┐  ┌───────────────────────┐ │  │
│  │  │ ConfigManager│  │ CloudManager      │  │ SignatureVerifier     │ │  │
│  │  │ • download   │  │ • HandleCommand   │  │ • verify_ecdsa       │ │  │
│  │  │ • verify_sig │  │ • execute_on_demand│  │ • download_cert      │ │  │
│  │  └──────────────┘  └───────────────────┘  └───────────────────────┘ │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ AlwaysPrintService                                                    │  │
│  │  • ActionEngine.ExecuteOnDemandTrigger(label)                         │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Componentes y Decisiones de Diseño

### 1. CryptoService (Backend — nuevo)

**Archivo:** `app/services/crypto_service.py`

**Responsabilidades:**
- Generación de par ECDSA P-256 (secp256r1)
- Cifrado de clave privada con AES-256-GCM (key derivada de `settings.SECRET_KEY` via PBKDF2)
- Generación de certificado X.509 auto-firmado (10 años de validez)
- Firma de hash SHA256 con clave privada
- Re-firma batch de configs activos durante rotación

**Dependencias:** `cryptography` (ya en requirements.txt para JWT)

**Decisión de cifrado de clave privada:**
- Se usa AES-256-GCM con nonce aleatorio de 12 bytes
- La key se deriva de `settings.SECRET_KEY` + salt fijo por org (`org_id` como salt)
- El resultado almacenado es: `base64(nonce || ciphertext || tag)`
- Esto permite que si la BD se compromete, la clave privada no es útil sin el SECRET_KEY del deployment

### 2. S3ConfigService (Backend — nuevo)

**Archivo:** `app/services/s3_config_service.py`

**Responsabilidades:**
- Upload de configs firmados a S3: `configs/{org_id}/{hash_8}.signed`
- Upload de certificados públicos: `certs/{org_id}/v{version}.cer`
- Eliminación de configs/certs de S3
- Generación de URLs públicas

**Reutilización:** Sigue el patrón exacto de `S3DocsService` existente (boto3 session, bucket config).

**Bucket:** Reutiliza `S3_DOCS_BUCKET` existente (ya tiene política pública de lectura). No se necesita un bucket nuevo.

### 3. Modelo Organization (Modificación)

**Campos nuevos:**
```python
ecdsa_private_key_encrypted = Column(Text, nullable=True)  # Base64 del AES-GCM encrypted key
ecdsa_cert_s3_key = Column(String(500), nullable=True)      # S3 key del .cer activo
ecdsa_cert_version = Column(Integer, nullable=False, default=0, server_default='0')
ecdsa_cert_expires_at = Column(DateTime, nullable=True)
```

**Migración:** Alembic migration para agregar columnas con default null/0.

### 4. Endpoint de descarga de config (Modificación)

**Archivo:** `app/api/v1/endpoints/action_config.py` — endpoint `download_workstation_config`

**Cambio:** En vez de retornar `config_json` directamente, retorna el JSON firmado desde S3 (o lo construye on-the-fly si no está en S3).

**Formato de respuesta:**
```json
{
  "config": { /* contenido original del .alwaysconfig */ },
  "hash": "a1b2c3d4e5f6...64chars",
  "signature": "MEUCIQD...base64...",
  "cert_version": 2
}
```

### 5. SignatureVerifier (Cliente — nuevo)

**Archivo:** `AlwaysPrint.Shared/Security/SignatureVerifier.cs` (compartido entre Tray y Service)

**Responsabilidades:**
- Carga de certificado .cer (X509Certificate2)
- Verificación de firma ECDSA con ECDsa.VerifyData
- Descarga de certificado desde URL S3
- Almacenamiento local en `C:\ProgramData\AlwaysPrint\config\org.cer`
- Lectura/escritura de `CertVersion` en registro

**API:**
```csharp
public static class SignatureVerifier
{
    public static bool VerifyConfig(string signedJson, string certPath, out string configJson);
    public static async Task<bool> DownloadCertAsync(string certUrl, string localPath);
    public static int GetLocalCertVersion();
    public static void SetLocalCertVersion(int version);
}
```

### 6. OnDemand Actions API (Backend — nuevo endpoint)

**Archivo:** `app/api/v1/endpoints/workstations.py` — nuevo endpoint

```python
@router.get("/{workstation_id}/ondemand-actions")
def get_ondemand_actions(workstation_id: UUID, ...) -> List[OnDemandActionInfo]:
    # 1. Resolver config efectivo via resolve_effective_config()
    # 2. Parsear config_json
    # 3. Extraer triggers con event="OnDemand"
    # 4. Retornar [{label, description}]
```

### 7. Execute OnDemand Command (Backend — extensión del endpoint existente)

**Archivo:** `app/api/v1/endpoints/workstations.py` — endpoint `send_command`

**Cambio:** Agregar `"execute_on_demand"` a `valid_commands`. Agregar validación de que el label existe en el config efectivo.

### 8. HandleCommand — execute_on_demand (Cliente — extensión)

**Archivo:** `AlwaysPrintTray/Cloud/CloudManager.cs`

**Nuevo case en `HandleCommand`:**
```csharp
case "execute_on_demand":
    var label = paramsObj?["label"]?.ToString();
    HandleExecuteOnDemandCommand(commandId, label);
    break;
```

**Implementación:** Envía mensaje al Service via Named Pipe con `ExecuteOnDemandTrigger` (ya existe).

### 9. WorkstationDetailModal — Sección OnDemand (Frontend — extensión)

**Archivo:** `src/app/dashboard/workstations/page.tsx`

**Componente nuevo interno:** `OnDemandActionsSection` que:
- Hace GET `/workstations/{id}/ondemand-actions` al montar
- Muestra lista de acciones con botón Ejecutar
- Maneja ejecución con confirmación → POST command → mostrar resultado

## Flujo de Datos: Firma y Verificación

```
1. Admin sube config → Backend
2. Backend: hash = SHA256(config_json) → 64 chars hex
3. Backend: signature = ECDSA_Sign(private_key, hash_bytes)
4. Backend: signed_json = {config, hash, signature, cert_version}
5. Backend: S3.upload(configs/{org}/{hash8}.signed, signed_json)
6. ...
7. Workstation: GET /config/download → recibe signed_json
8. Workstation: computed_hash = SHA256(JSON.serialize(config))
9. Workstation: assert computed_hash == signed_json.hash
10. Workstation: assert ECDSA_Verify(public_key, hash_bytes, signature)
11. Workstation: Si OK → procesar config. Si NO → rechazar, mantener anterior.
```

## Flujo de Datos: Rotación de Certificado

```
1. Admin clic "Renovar" → Backend
2. Backend: new_key_pair = generate ECDSA P-256
3. Backend: encrypt(new_private_key) → BD
4. Backend: new_cert = X509(new_public_key, 10 años) → S3 certs/{org}/v{N+1}.cer
5. Backend: para cada ActionConfig activo de la org:
   a. re-calcular hash (mismo config_json)
   b. re-firmar con nueva clave
   c. re-subir {hash8}.signed a S3
6. Backend: WebSocket broadcast → todas las WS online: {type:"cert_rotated", cert_url, cert_version}
7. WS online: descarga nuevo .cer, reemplaza local, actualiza CertVersion en registro
8. WS offline: al reconectar, detecta cert_version mismatch → descarga .cer → valida
```

## Flujo de Datos: Ejecución Remota OnDemand

```
1. Operador abre detalle de WS en frontend
2. Frontend: GET /workstations/{id}/ondemand-actions → [{label, description}]
3. Operador clic "Ejecutar" en "Limpiar Sistema de Impresión"
4. Frontend: POST /workstations/{id}/command → {command_type:"execute_on_demand", params:{label:"..."}}
5. Backend: valida label existe en config efectivo
6. Backend: WebSocket → WS: {type:"command", command_id, command_type:"execute_on_demand", params:{label}}
7. WS/Tray: CloudManager.HandleCommand → case "execute_on_demand"
8. WS/Tray: envía ExecuteOnDemandTrigger al Service via Pipe
9. WS/Service: ActionEngine ejecuta el trigger (puede tardar 60-120s)
10. WS/Service: responde al Tray via Pipe con success/failure/duration
11. WS/Tray: SendCommandResult → WebSocket → Backend
12. Backend: resolve_command_response → retorna al frontend
13. Frontend: muestra toast con resultado
```

## Seguridad

| Aspecto | Implementación |
|---------|---------------|
| Clave privada en reposo | AES-256-GCM con key derivada de SECRET_KEY |
| Clave privada en tránsito | Nunca sale del backend. Solo se usa para firmar. |
| Certificado público | S3 público (read-only). No contiene información secreta. |
| Integridad de config | SHA256 + ECDSA P-256 = resistente a colisiones y falsificación |
| Rotación | Un clic. Re-firma todos los configs. Broadcast a WS online. |
| Fail-open | Solo en primera ejecución (sin .cer local). Después es fail-closed. |
| Audit trail | Toda operación de crypto (generate, rotate, sign) queda en audit_logs |
| Tenant isolation | Cada org tiene su propio par de claves. No hay cross-org. |
| Replay protection | cert_version previene uso de configs firmados con claves viejas |

## Dependencias Existentes Reutilizadas

| Componente | Reutilización |
|---|---|
| `S3DocsService` | Patrón para `S3ConfigService` (boto3, bucket, upload/delete) |
| `ConnectionManager.send_to_workstation` | Envío de comandos y broadcast |
| `ConnectionManager.wait_for_command_response` | Esperar respuesta del OnDemand |
| `POST /{id}/command` endpoint | Extender con `execute_on_demand` |
| `AuditLog` model | Registrar operaciones de crypto y ejecuciones remotas |
| `resolve_effective_config()` | Determinar config y acciones disponibles |
| `ActionEngine.ExecuteOnDemandTrigger` | Ejecución local ya implementada |
| `ConfigManager.CalculateHash` | Verificación de integridad (se mantiene) |
| `CloudManager.HandleCommand` | Switch para nuevo tipo de comando |
| `cryptography` library | Ya en requirements (usada por python-jose/JWT) |
