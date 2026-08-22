# Requirements Document: Backup & Restore para Migración de Cuenta AWS

## Introducción

Esta feature implementa un sistema completo de backup y restauración de la plataforma AlwaysPrint Cloud Manager. El objetivo es permitir la migración completa de una cuenta AWS a otra, exportando la base de datos íntegra, archivos de configuración (.alwaysconfig) almacenados en BD, e imágenes de mapas de VLANs almacenadas en S3. El backup se genera de forma asíncrona (puede tardar), se almacena cifrado en S3, y la restauración se realiza desde la pantalla de setup inicial cuando la BD está vacía.

## Glosario

- **Backup_Bundle**: Conjunto de 2 archivos ZIP (datos BD + imágenes) protegidos con password AES-256, almacenados en S3.
- **DB_ZIP**: Archivo ZIP con password conteniendo el dump completo de la base de datos en formato JSON estructurado por tablas.
- **Images_ZIP**: Archivo ZIP con password conteniendo las imágenes de VLANs referenciadas en la BD.
- **Corporate_Admin**: Un usuario autenticado con rol ADMIN cuyo email termina en `@robles.ai` o `@sistemas.com.pe`.
- **Backup_Status_Flag**: Archivo JSON en S3 que indica el estado actual de un proceso de backup o restore (idle, generating, completed, failed, restoring).
- **Presigned_URL**: URL temporal de S3 con permisos de escritura para subir archivos directamente desde el navegador.
- **Restore_Progress**: Indicador almacenado en S3 que refleja la etapa actual del proceso de restauración.
- **Relative_Image_Path**: Path relativo de imagen en S3 (ej: `vlan-images/{vlan_id}.jpg`) sin incluir bucket ni región, permitiendo portabilidad entre cuentas.

## Requirements

### Requirement 1: Control de Acceso — Solo Corporate Admin

**User Story:** Como operador del sistema, quiero que solo los Corporate Admins puedan generar y descargar backups, para que datos sensibles no sean accesibles por usuarios no autorizados.

#### Criterios de Aceptación

1. WHEN un usuario con rol ADMIN y email de dominio autorizado (`@robles.ai`, `@sistemas.com.pe`) navega al dashboard admin, THEN el sistema DEBE mostrar la sección "Backup & Restore" en la navegación.
2. WHEN un usuario sin dominio autorizado intenta acceder a los endpoints de backup, THEN el backend DEBE retornar HTTP 403 Forbidden.
3. WHEN un usuario no-ADMIN intenta acceder a los endpoints de backup, THEN el backend DEBE retornar HTTP 403 Forbidden.
4. THE sección de Backup DEBE estar oculta en el frontend para usuarios que no sean Corporate Admin (verificación de dominio en cliente).

### Requirement 2: Generación de Backup (Export)

**User Story:** Como Corporate Admin, quiero solicitar la generación de un backup completo del sistema desde la UI, para poder migrar la instalación a otra cuenta AWS.

#### Criterios de Aceptación

1. WHEN un Corporate Admin accede a la sección de Backup, THE sistema DEBE mostrar un formulario con un campo de contraseña (opcional) para cifrar los archivos ZIP.
2. WHEN el Corporate Admin hace click en "Generar Backup", THE sistema DEBE iniciar un proceso asíncrono en el backend que:
   a. Exporta TODAS las tablas de la BD en formato JSON estructurado (un archivo por tabla).
   b. Descarga las imágenes de VLANs referenciadas en `VLAN.location_image_url` desde S3.
   c. Genera un `DB_ZIP` con el dump de BD.
   d. Genera un `Images_ZIP` con las imágenes descargadas.
   e. Si se proporcionó password, ambos ZIPs se cifran con AES-256 (formato ZIP estándar con password).
   f. Sube ambos ZIPs al bucket S3 bajo el prefijo `backups/{timestamp}/`.
3. WHILE el backup está en proceso de generación, THE UI DEBE mostrar un indicador de "backup en generación" y DEBE deshabilitar el botón de generar nuevo backup.
4. WHEN el backup finaliza exitosamente, THE UI DEBE mostrar botones de descarga para cada archivo ZIP.
5. WHEN el Corporate Admin cierra la ventana durante la generación, THE proceso DEBE continuar ejecutándose en el backend sin interrupción.
6. IF el backup falla, THE sistema DEBE actualizar el estado a "failed" con un mensaje de error descriptivo.
7. THE sistema DEBE almacenar solo el último backup generado. Al generar uno nuevo, el anterior se elimina.
8. THE campo `VLAN.location_image_url` DEBE almacenarse en el DB_ZIP como path relativo (sin bucket ni región), para permitir portabilidad entre cuentas AWS.

### Requirement 3: Estado del Backup (Polling)

**User Story:** Como Corporate Admin, quiero poder ver el estado actual del proceso de backup sin mantener la ventana abierta, para saber cuándo está listo para descargar.

#### Criterios de Aceptación

1. THE backend DEBE exponer un endpoint que retorne el estado actual del backup: `idle`, `generating`, `completed`, `failed`.
2. WHEN el estado es `generating`, THE respuesta DEBE incluir un indicador de progreso (etapa actual: "Exportando BD", "Descargando imágenes", "Generando ZIP BD", "Generando ZIP imágenes", "Subiendo a S3").
3. WHEN el estado es `completed`, THE respuesta DEBE incluir URLs presignadas de descarga para ambos ZIPs y metadata (tamaño, fecha de generación, si tiene password).
4. THE estado del backup se DEBE persistir en un archivo JSON en S3 (`backups/status.json`) para sobrevivir reinicios del servicio.
5. THE frontend DEBE hacer polling cada 5 segundos mientras el estado sea `generating`.

### Requirement 4: Descarga del Backup

**User Story:** Como Corporate Admin, quiero descargar los archivos de backup generados para almacenarlos de forma segura fuera de AWS.

#### Criterios de Aceptación

1. WHEN el backup está en estado `completed`, THE UI DEBE mostrar 2 botones de descarga: "Descargar BD" y "Descargar Imágenes".
2. THE descargas DEBEN usar presigned URLs de S3 con expiración de 1 hora.
3. WHEN se hace click en descargar, THE navegador DEBE iniciar la descarga directamente sin pasar por el backend.
4. THE UI DEBE mostrar el tamaño de cada archivo junto al botón de descarga.

### Requirement 5: Restauración — Pantalla de Setup Inicial

**User Story:** Como Corporate Admin, quiero poder restaurar un backup completo desde la pantalla de setup inicial, para migrar la plataforma a una nueva cuenta AWS sin perder datos.

#### Criterios de Aceptación

1. WHEN la BD está vacía (no hay usuarios), THE página de setup DEBE mostrar 2 opciones:
   a. "Crear primer administrador" (comportamiento actual).
   b. "Restaurar desde backup".
2. THE 2 opciones DEBEN presentarse como tabs o toggle que oculte/muestre el formulario correspondiente.
3. WHEN el usuario selecciona "Restaurar desde backup", THE formulario DEBE solicitar:
   a. Selector de archivo para DB_ZIP (archivo local).
   b. Selector de archivo para Images_ZIP (archivo local).
   c. Campo de contraseña (requerido si los ZIPs están protegidos, con indicación de que es opcional si no tienen password).
4. WHEN el usuario hace click en "Restaurar", THE sistema DEBE:
   a. Subir ambos archivos a S3 vía presigned URLs.
   b. Mostrar un indicador de progreso de upload con porcentaje.
   c. Indicar al usuario que NO cierre la ventana mientras los archivos se suben.
5. WHEN los archivos terminan de subirse a S3, THE sistema DEBE:
   a. Iniciar el proceso de restauración en el backend (API call).
   b. Redirigir al usuario a una pantalla de "Restauración en proceso" con indicador de progreso por etapas.
6. IF el usuario navega de vuelta a la página de setup mientras el restore está en proceso, THE sistema DEBE detectarlo y mostrar la pantalla de "Restauración en proceso" (no el formulario de setup).
7. WHEN la restauración finaliza exitosamente, THE sistema DEBE redirigir automáticamente al login.
8. IF la restauración falla, THE sistema DEBE mostrar el error y permitir reintentar.

### Requirement 6: Proceso de Restauración (Backend)

**User Story:** Como sistema, debo restaurar la BD completa e imágenes desde los archivos subidos, para que la plataforma quede operativa con los datos migrados.

#### Criterios de Aceptación

1. WHEN se inicia el restore, THE backend DEBE ejecutar las siguientes etapas en orden:
   a. **Validación**: Verificar password de ambos ZIPs, verificar estructura interna (archivos esperados), verificar integridad.
   b. **Limpieza**: Limpiar cualquier dato residual en la BD (si existe).
   c. **Restauración BD**: Insertar registros tabla por tabla respetando relaciones (foreign keys) en orden de dependencias.
   d. **Restauración imágenes**: Subir imágenes al bucket S3 configurado en la nueva cuenta.
   e. **Reconstrucción URLs**: Actualizar `VLAN.location_image_url` con la URL completa del nuevo bucket/región.
   f. **Verificación**: Contar registros restaurados vs esperados, verificar integridad referencial.
2. EACH etapa DEBE actualizar el Restore_Progress en S3 con: nombre de etapa, porcentaje estimado, timestamp.
3. IF la validación falla (password incorrecto, estructura inválida, ZIP corrupto), THE sistema DEBE abortar inmediatamente y reportar el error específico.
4. IF una etapa posterior falla, THE sistema DEBE hacer rollback de la BD (TRUNCATE todas las tablas) y reportar el error.
5. THE restauración DEBE respetar el orden de foreign keys: Organizations → Users → VLANs → Devices → Workstations → Configs → etc.
6. THE passwords de usuarios DEBEN restaurarse tal cual (hashes bcrypt intactos).
7. ALL tokens, API keys, y secretos almacenados en BD DEBEN restaurarse íntegramente.
8. THE restore DEBE funcionar independientemente del nombre del bucket S3 o región de la nueva cuenta.

### Requirement 7: Estado de Restauración (Polling)

**User Story:** Como usuario en la pantalla de setup, quiero ver el progreso de la restauración en tiempo real, para saber en qué etapa está y cuándo terminará.

#### Criterios de Aceptación

1. THE backend DEBE exponer un endpoint público (sin auth) que retorne el estado del restore: `idle`, `uploading`, `restoring`, `completed`, `failed`.
2. WHEN el estado es `restoring`, THE respuesta DEBE incluir: etapa actual, porcentaje de progreso, y descripción de la etapa.
3. THE frontend DEBE hacer polling cada 3 segundos mientras el estado sea `uploading` o `restoring`.
4. WHEN el estado cambia a `completed`, THE frontend DEBE redirigir al login automáticamente después de 3 segundos.
5. WHEN el estado cambia a `failed`, THE frontend DEBE mostrar el mensaje de error y un botón para reintentar.
6. THE estado del restore se DEBE persistir en S3 (`backups/restore_status.json`) ya que la BD puede no estar disponible durante el proceso.

### Requirement 8: Formato del Backup — BD

**User Story:** Como sistema, debo exportar la BD en un formato portable y autodescriptivo que permita restauración en cualquier instancia PostgreSQL compatible.

#### Criterios de Aceptación

1. THE DB_ZIP DEBE contener:
   a. Un archivo `manifest.json` con metadata: versión del schema, fecha de generación, número de registros por tabla, versión de Alembic migration.
   b. Un archivo JSON por cada tabla, nombrado como `{table_name}.json`.
   c. Cada archivo JSON DEBE ser un array de objetos con las columnas como keys.
2. THE formatos de datos DEBEN ser:
   a. UUIDs como strings.
   b. Timestamps en formato ISO 8601.
   c. JSON columns como objetos (no strings escapados).
   d. Enums como strings con su valor.
   e. Booleans como true/false.
   f. Nulls como null.
3. THE manifest DEBE incluir la versión de migración Alembic para validar compatibilidad al restaurar.
4. IF al restaurar la versión de migración no coincide, THE sistema DEBE abortar con un mensaje claro indicando incompatibilidad de schema.

### Requirement 9: Formato del Backup — Imágenes

**User Story:** Como sistema, debo exportar las imágenes de mapas de VLANs en una estructura que permita su restauración en cualquier bucket S3.

#### Criterios de Aceptación

1. THE Images_ZIP DEBE contener las imágenes en la estructura: `vlan-images/{vlan_id}.jpg` (replicando el path de S3).
2. THE Images_ZIP SOLO DEBE incluir imágenes que están referenciadas por un registro VLAN activo en la BD (que tiene `location_image_url` no nulo).
3. THE Images_ZIP DEBE incluir un archivo `manifest.json` con: lista de archivos incluidos, tamaño total, cantidad de imágenes, mapeo vlan_id → filename.
4. IF una imagen referenciada en BD no existe en S3 al momento del export, THE sistema DEBE registrar una advertencia en el manifest pero continuar con las demás.

### Requirement 10: Seguridad

**User Story:** Como operador del sistema, quiero que los backups sean manejados de forma segura, para proteger datos sensibles de la organización.

#### Criterios de Aceptación

1. THE archivos ZIP DEBEN cifrarse con AES-256 cuando se proporciona un password (formato estándar ZIP compatible con herramientas como 7-Zip/WinZip).
2. IF no se proporciona password, THE ZIPs se generan sin cifrado.
3. THE presigned URLs de descarga DEBEN expirar en 1 hora máximo.
4. THE presigned URLs de upload para restore DEBEN expirar en 30 minutos.
5. THE endpoint de restore SOLO DEBE funcionar cuando la BD está vacía (user_count == 0), excepto el endpoint de status que es público.
6. THE archivos de backup en S3 DEBEN almacenarse bajo un prefijo dedicado (`backups/`) en el bucket de artifacts.
7. AFTER una restauración exitosa, THE archivos temporales subidos DEBEN eliminarse de S3.
