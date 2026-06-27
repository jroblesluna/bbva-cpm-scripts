# Documento de Requisitos — Firma Digital ECDSA de AlwaysConfig + Ejecución Remota de OnDemand

## Introducción

Esta funcionalidad implementa tres capacidades: (1) firma digital ECDSA de archivos .alwaysconfig almacenados en S3, con generación de par de claves por organización, validación en el cliente, y rotación con un clic; (2) ejecución remota de acciones OnDemand desde el frontend hacia workstations vía WebSocket; y (3) UI en el detalle de workstation para visualizar y ejecutar acciones OnDemand disponibles. Juntas, estas capacidades aseguran la integridad criptográfica de las configuraciones desplegadas y permiten operación remota de acciones administrativas.

## Glosario

- **ECDSA**: Elliptic Curve Digital Signature Algorithm. Algoritmo de firma digital con curva P-256 (secp256r1).
- **Par_de_Claves**: Conjunto de clave privada (secreto) y clave pública (certificado .cer) generado por organización.
- **Signed_Config**: Estructura JSON envolvente que contiene el config original, hash SHA256 completo y firma ECDSA: `{"config":{...},"hash":"...","signature":"...","cert_version":N}`.
- **Cert_Version**: Número secuencial que identifica la generación del certificado. Permite al cliente detectar rotaciones.
- **S3_Config_Path**: Ruta en S3 donde se almacena el config firmado: `configs/{organization_id}/{hash}.signed`.
- **S3_Cert_Path**: Ruta pública en S3 del certificado: `certs/{organization_id}/v{cert_version}.cer`.
- **OnDemand_Action**: Trigger con evento `"OnDemand"` en un .alwaysconfig que puede ejecutarse bajo demanda.
- **Remote_Execution**: Ejecución de una acción OnDemand iniciada desde el frontend y despachada a la workstation vía WebSocket.
- **Command_Waiter**: Patrón existente en ConnectionManager que permite esperar la respuesta de un comando WebSocket con timeout.
- **Effective_Config**: Configuración resultante de la resolución jerárquica (Org mandatory > VLAN mandatory > Workstation > VLAN > Org default).

## Requisitos

### Feature 1: Firma Digital ECDSA de AlwaysConfig

#### Requisito 1.1: Generación de par de claves ECDSA por organización

**User Story:** Como administrador, quiero generar un par de claves ECDSA para mi organización desde el frontend, para que las configuraciones desplegadas a las workstations tengan integridad criptográfica verificable.

##### Criterios de Aceptación

1. WHEN el administrador hace clic en "Generar Certificado" en la página de organización, THE backend SHALL generar un par ECDSA P-256 (secp256r1) con expiración de 10 años.
2. THE backend SHALL almacenar la clave privada cifrada (AES-256-GCM con key derivada de SECRET_KEY) en la columna `ecdsa_private_key_encrypted` de la tabla `organizations`.
3. THE backend SHALL generar un certificado X.509 auto-firmado con la clave pública y subirlo a S3 en `certs/{organization_id}/v{cert_version}.cer` con acceso público de lectura.
4. THE backend SHALL incrementar `ecdsa_cert_version` en la organización y registrar `ecdsa_cert_expires_at`.
5. THE backend SHALL registrar un AuditLog con action_type=CONFIG_CHANGE, entity_type="organization", incluyendo el cert_version anterior y nuevo en new_values.
6. WHEN el certificado se genera exitosamente, THE frontend SHALL mostrar la URL pública del certificado y la fecha de expiración.

#### Requisito 1.2: Firma y almacenamiento de AlwaysConfig en S3

**User Story:** Como administrador, quiero que al subir o activar una configuración de acciones, esta se firme automáticamente y se almacene en S3, para que las workstations puedan descargarla con garantía de integridad.

##### Criterios de Aceptación

1. WHEN se crea o activa un ActionConfig, THE backend SHALL calcular el hash SHA256 completo del `config_json` (64 caracteres hex).
2. THE backend SHALL firmar el hash con la clave privada ECDSA de la organización, produciendo una firma en formato Base64.
3. THE backend SHALL construir el JSON envolvente: `{"config": <config_json_parsed>, "hash": "<sha256_64_chars>", "signature": "<base64_ecdsa_signature>", "cert_version": <int>}`.
4. THE backend SHALL subir el JSON firmado a S3 en `configs/{organization_id}/{hash_8_chars}.signed` con ContentType `application/json`.
5. THE backend SHALL actualizar el campo `storage_path` del ActionConfig con la S3 key.
6. WHEN se elimina un ActionConfig, THE backend SHALL eliminar el archivo correspondiente de S3.
7. IF la organización no tiene par de claves generado, THE backend SHALL rechazar la activación con HTTP 409 y mensaje descriptivo.

#### Requisito 1.3: Descarga y verificación de firma en el cliente

**User Story:** Como workstation, quiero verificar la firma digital de la configuración descargada antes de aplicarla, para asegurar que no fue alterada en tránsito ni inyectada por un tercero.

##### Criterios de Aceptación

1. WHEN el cliente descarga la configuración del endpoint `/workstations/{id}/config/download`, SHALL recibir el JSON envolvente con config, hash y signature.
2. THE cliente SHALL calcular el SHA256 del JSON serializado de "config" y compararlo con el campo "hash". Si no coincide, SHALL rechazar la configuración y loguear un error.
3. THE cliente SHALL verificar la firma ECDSA del hash usando el certificado público (.cer) almacenado localmente. Si la firma es inválida, SHALL rechazar la configuración y loguear un error.
4. IF el campo "cert_version" es mayor que la versión del .cer local, THE cliente SHALL descargar el nuevo certificado desde S3 antes de verificar la firma.
5. WHEN la verificación es exitosa, THE cliente SHALL extraer el contenido de "config" y procesarlo normalmente (enviar al Service vía Named Pipe).
6. WHEN la verificación falla, THE cliente SHALL mantener la configuración anterior sin cambios y registrar en log el motivo del rechazo (hash mismatch o firma inválida).

#### Requisito 1.4: Descarga inicial del certificado al registrarse

**User Story:** Como workstation recién registrada, quiero descargar el certificado público de mi organización para poder verificar futuras configuraciones.

##### Criterios de Aceptación

1. WHEN el registro de la workstation es exitoso (HTTP 201), THE respuesta SHALL incluir el campo `cert_url` con la URL pública del .cer en S3 y `cert_version` con la versión actual.
2. THE cliente SHALL descargar el .cer y almacenarlo en `C:\ProgramData\AlwaysPrint\config\org.cer`.
3. THE cliente SHALL almacenar `cert_version` en el registro de Windows (`HKLM\SOFTWARE\Robles.AI\AlwaysPrint\CertVersion`).
4. IF la descarga del certificado falla, THE cliente SHALL loguear un warning y continuar sin verificación de firma (fail-open en primera ejecución).

#### Requisito 1.5: Rotación de certificado

**User Story:** Como administrador, quiero poder renovar el certificado con un clic, notificando a todas las workstations para que actualicen su copia local.

##### Criterios de Aceptación

1. WHEN el administrador hace clic en "Renovar Certificado", THE backend SHALL generar un nuevo par ECDSA P-256, reemplazar la clave privada cifrada en BD, subir nuevo .cer a S3 con nuevo cert_version.
2. THE backend SHALL re-firmar TODOS los ActionConfigs activos de la organización con la nueva clave y actualizar los archivos en S3.
3. THE backend SHALL enviar un mensaje WebSocket broadcast a todas las workstations online de la organización: `{"type": "cert_rotated", "cert_url": "<url>", "cert_version": <new_version>}`.
4. WHEN el cliente recibe `cert_rotated`, SHALL descargar el nuevo .cer, reemplazar el local, y actualizar `CertVersion` en registro.
5. WHEN una workstation offline durante la rotación reconecta y descarga un config con `cert_version` mayor al local, SHALL descargar el nuevo .cer antes de validar la firma.
6. THE backend SHALL registrar un AuditLog con action_type=CONFIG_CHANGE para la rotación.
7. THE backend SHALL conservar el .cer anterior en S3 por 30 días (no eliminación inmediata) para diagnóstico.

### Feature 2: Ejecución Remota de OnDemand desde Frontend

#### Requisito 2.1: Endpoint para listar acciones OnDemand disponibles

**User Story:** Como operador, quiero ver qué acciones OnDemand tiene disponibles una workstation, para poder ejecutar la que necesite sin conectarme directamente a la máquina.

##### Criterios de Aceptación

1. THE backend SHALL exponer GET `/api/v1/workstations/{workstation_id}/ondemand-actions` que retorna la lista de acciones OnDemand del config efectivo de esa workstation.
2. THE respuesta SHALL incluir para cada acción: `label` (string), `description` (string).
3. IF la workstation no tiene config efectivo o no tiene triggers OnDemand, SHALL retornar lista vacía `[]`.
4. THE endpoint SHALL respetar tenant isolation: operadores solo ven acciones de workstations de su organización.
5. Admins pueden ver acciones de cualquier workstation.

#### Requisito 2.2: Comando WebSocket para ejecutar OnDemand

**User Story:** Como operador, quiero ejecutar una acción OnDemand en una workstation remota y ver el resultado, para resolver problemas sin necesidad de acceso físico.

##### Criterios de Aceptación

1. THE backend SHALL aceptar POST `/api/v1/workstations/{workstation_id}/command` con `command_type: "execute_on_demand"` y `params: {"label": "<trigger_label>"}`.
2. THE backend SHALL validar que el label existe en el config efectivo de la workstation antes de enviar el comando.
3. THE backend SHALL enviar vía WebSocket: `{"type": "command", "command_id": "<uuid>", "command_type": "execute_on_demand", "params": {"label": "<trigger_label>"}}`.
4. THE cliente SHALL ejecutar el trigger OnDemand correspondiente vía ActionEngine (igual que la ejecución local desde el Tray).
5. THE cliente SHALL responder con: `{"type": "cmd_response", "command_id": "<uuid>", "success": true/false, "message": "<resultado>", "duration_ms": <int>}`.
6. THE backend SHALL esperar la respuesta con timeout de 120 segundos (las acciones OnDemand pueden tardar, incluyen dism.exe que toma ~60s).
7. THE backend SHALL registrar un AuditLog con action_type=COMMAND_SENT, entity_type="workstation", incluyendo label, success y duration en new_values.
8. IF la workstation está offline, SHALL retornar HTTP 409 con mensaje descriptivo.

#### Requisito 2.3: Handler de comando en el cliente

**User Story:** Como workstation, quiero poder recibir y ejecutar comandos OnDemand desde la Cloud de forma segura.

##### Criterios de Aceptación

1. THE cliente SHALL agregar case `"execute_on_demand"` en `HandleCommand` de `CloudManager.cs`.
2. THE cliente SHALL extraer `params.label` y buscar el trigger OnDemand correspondiente en la configuración activa.
3. THE cliente SHALL invocar `ActionEngine.ExecuteOnDemandTrigger(label)` existente (ya implementado para la UI local).
4. THE cliente SHALL responder con success/failure y duración via `SendCommandResult`.
5. IF el label no existe en la configuración activa, SHALL responder con `success: false, message: "Trigger no encontrado: {label}"`.

### Feature 3: UI de OnDemand en Detalle de Workstation

#### Requisito 3.1: Sección de acciones OnDemand en WorkstationDetailModal

**User Story:** Como operador, quiero ver las acciones disponibles y ejecutarlas directamente desde el detalle de una workstation en el dashboard.

##### Criterios de Aceptación

1. THE WorkstationDetailModal SHALL incluir una sección "Acciones A Demanda" después de la sección de Action Config.
2. THE sección SHALL mostrar la lista de acciones OnDemand obtenidas del endpoint GET `/workstations/{id}/ondemand-actions`.
3. EACH acción SHALL mostrar su label, description, y un botón "Ejecutar" (habilitado solo si la workstation está online).
4. WHEN el operador hace clic en "Ejecutar", SHALL mostrar diálogo de confirmación con la description de la acción.
5. WHEN se confirma, SHALL llamar a POST `/workstations/{id}/command` con `execute_on_demand` y mostrar un spinner durante la ejecución.
6. WHEN la respuesta llega, SHALL mostrar toast con success/failure y duración.
7. IF la workstation está offline, los botones "Ejecutar" SHALL estar deshabilitados con tooltip explicativo.
8. Todos los textos SHALL usar next-intl con namespace `workstations` (keys: `onDemandActions`, `executeAction`, `actionExecuted`, `actionFailed`, `actionConfirm`, `wsOfflineTooltip`).
