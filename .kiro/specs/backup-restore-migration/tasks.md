# Implementation Plan: Backup & Restore para Migración de Cuenta AWS

## Overview

Implementar sistema completo de backup (export) y restore (import) para migrar AlwaysPrint Cloud Manager entre cuentas AWS. El backup lo genera un Corporate Admin desde la UI, se almacena en S3 como 2 ZIPs cifrados (BD + imágenes), y la restauración se realiza desde la pantalla de setup inicial. Ambos procesos son asíncronos con tracking de progreso en S3.

## Tasks

- [x] 1. Backend: Instalar dependencia y crear servicio de backup
  - [x] 1.1 Agregar `pyzipper` al requirements.txt
    - Agregar `pyzipper>=0.3.6` al archivo de requirements
    - Verificar que se instala correctamente en el entorno
    - _Requirements: 2.2e, 8.1, 10.1_

  - [x] 1.2 Crear `app/services/backup_service.py` — servicio de generación de backup
    - Implementar clase `BackupService` con método `generate(password: Optional[str])`
    - Implementar `_export_table(db, model_class)` que serializa todos los registros a lista de dicts
    - Implementar `_convert_value(value)` para manejar: UUID→str, datetime→ISO8601, Enum→str, JSON→object, None→null
    - Implementar `_create_zip_with_password(files: dict[str, bytes], password: Optional[str])` usando pyzipper AES-256
    - Implementar `_get_active_vlan_images(db)` que consulta VLANs con `location_image_url IS NOT NULL` y extrae paths relativos
    - Implementar `_download_s3_image(relative_path)` para descargar imagen del bucket actual
    - Implementar `_build_manifest(table_counts, alembic_revision)` con metadata del backup
    - Implementar `_update_status(status, stage, progress, error)` que escribe `backups/status.json` en S3
    - Implementar `_cleanup_previous_backup()` que elimina archivos del backup anterior en S3
    - Implementar `_convert_image_url_to_relative(url)` que extrae path relativo de una URL absoluta de S3
    - El generate() debe: actualizar status a generating, exportar BD, descargar imágenes, crear ZIPs, subir a S3, actualizar status a completed
    - Si falla en cualquier punto, actualizar status a failed con mensaje de error
    - _Requirements: 2.2, 3.1, 3.2, 3.4, 8.1, 8.2, 8.3, 9.1, 9.2, 9.3, 9.4_

  - [x] 1.3 Crear `app/services/restore_service.py` — servicio de restauración
    - Implementar clase `RestoreService` con método `restore(password: Optional[str])`
    - Definir `TABLE_ORDER` con las 26+ tablas en orden de dependencias FK
    - Implementar `_validate_zip(zip_bytes, password, expected_files)` que verifica password, estructura e integridad
    - Implementar `_restore_table(db, table_name, records)` que inserta registros con conversión de tipos (str→UUID, ISO→datetime, str→Enum)
    - Implementar `_rebuild_image_urls(db)` que construye URLs absolutas desde paths relativos usando bucket/región actuales
    - Implementar `_upload_images_to_s3(zip_bytes, password)` que extrae imágenes del ZIP y las sube al bucket
    - Implementar `_update_restore_status(status, stage, progress, error)` que escribe `backups/restore_status.json` en S3
    - Implementar `_verify_integrity(db, manifest)` que compara conteos de registros restaurados vs manifest
    - Implementar `_get_alembic_head()` que obtiene la revision actual de Alembic para validar compatibilidad
    - El restore() debe: validar ZIPs, limpiar BD, insertar tabla por tabla, subir imágenes, reconstruir URLs, verificar integridad
    - Si falla después de la limpieza, hacer TRUNCATE de todas las tablas y reportar error
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 7.1, 7.2, 8.3, 8.4_

- [x] 2. Backend: Crear endpoints de backup (admin)
  - [x] 2.1 Crear `app/api/v1/endpoints/backup.py` con dependencia `require_corporate_admin`
    - Reutilizar patrón de `ALLOWED_DOMAINS` y `require_corporate_admin` de ssl.py
    - Implementar endpoint `POST /admin/backup/generate` que acepta `BackupGenerateRequest` (password opcional)
      - Verificar que no hay backup en generación (status != "generating")
      - Lanzar `BackupService.generate()` como asyncio.create_task
      - Retornar 202 Accepted
    - Implementar endpoint `GET /admin/backup/status` que lee `backups/status.json` de S3 y retorna `BackupStatusResponse`
    - Implementar endpoint `GET /admin/backup/download/{file_type}` (file_type: "db" | "images")
      - Generar presigned URL de descarga con expiración de 1 hora
      - Retornar `BackupDownloadResponse` con URL, nombre, tamaño
    - Implementar endpoint `DELETE /admin/backup/delete` que elimina archivos de backup y resetea status a idle
    - Registrar router en `app/api/v1/router.py`
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 4.1, 4.2, 4.3, 4.4, 10.3, 10.6_

- [x] 3. Backend: Crear endpoints de restore (setup)
  - [x] 3.1 Crear `app/api/v1/endpoints/restore.py` con endpoints públicos (solo BD vacía)
    - Implementar guard `require_empty_db(db)` que verifica user_count == 0
    - Implementar endpoint `POST /setup/restore/presigned-urls` 
      - Verificar BD vacía
      - Generar 2 presigned PUT URLs para S3 (`backups/restore-upload/db.zip`, `backups/restore-upload/images.zip`)
      - Expiración de 30 minutos
      - Retornar `RestorePresignedUrlsResponse`
    - Implementar endpoint `POST /setup/restore/start`
      - Verificar BD vacía
      - Verificar que los archivos existen en S3 (`backups/restore-upload/`)
      - Lanzar `RestoreService.restore()` como asyncio.create_task
      - Retornar 202 Accepted
    - Implementar endpoint `GET /setup/restore/status` (público, sin auth)
      - Leer `backups/restore_status.json` de S3
      - Si no existe, retornar `{status: "idle"}`
      - Retornar `RestoreStatusResponse`
    - Registrar router en `app/api/v1/router.py`
    - _Requirements: 5.1, 5.4, 5.5, 5.6, 6.1, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 10.4, 10.5, 10.7_

- [x] 4. Backend: Modificar endpoint de setup existente
  - [x] 4.1 Actualizar `app/api/v1/endpoints/setup.py` — agregar detección de restore en progreso
    - Modificar `GET /setup/status` para que también verifique si hay un restore en progreso (leer restore_status.json de S3)
    - Si restore está en progreso, retornar `needs_setup: false` + campo adicional `restore_in_progress: true`
    - Agregar campo `restore_in_progress` al schema `SetupStatusResponse`
    - _Requirements: 5.6, 7.1_

- [x] 5. Checkpoint Backend — Verificar servicios y endpoints
  - Ejecutar tests unitarios existentes para asegurar que no hay regresiones
  - Verificar que los imports de modelos funcionan correctamente en BackupService
  - Verificar que pyzipper genera ZIPs correctamente con y sin password

- [x] 6. Frontend: Agregar traducciones i18n
  - [x] 6.1 Agregar namespace `backup` en `messages/es.json` y `messages/en.json`
    - Definir keys para: título sección, descripción, campo password, botón generar, estados (idle, generating, completed, failed), etapas de progreso, botones descarga, tamaños de archivo, confirmación de eliminación
    - Definir keys para restore: tab labels, selector de archivos, campo password, botón restaurar, indicador de upload, pantalla de progreso, etapas de restauración, mensajes de error/éxito, indicación de no cerrar ventana
    - Textos en español en `es.json`, en inglés en `en.json`
    - _Requirements: 5.2c (UX), 5.4c (UX)_

- [x] 7. Frontend: Agregar API client
  - [x] 7.1 Agregar interfaces TypeScript y funciones API en `src/lib/api.ts`
    - Definir interfaces: `BackupStatusResponse`, `BackupDownloadResponse`, `RestorePresignedUrlsResponse`, `RestoreStatusResponse`
    - Agregar `backupApi` con métodos: `generate(password?)`, `getStatus()`, `getDownloadUrl(fileType)`, `deleteBackup()`
    - Agregar `restoreApi` con métodos: `getPresignedUrls(dbSize, imagesSize)`, `start(password?)`, `getStatus()`
    - Implementar upload directo a S3 con tracking de progreso (axios PUT con onUploadProgress)
    - _Requirements: 2.1, 3.1, 4.1, 5.4_

- [x] 8. Frontend: Crear componente BackupSection para admin dashboard
  - [x] 8.1 Crear `src/components/admin/BackupSection.tsx`
    - Verificar dominio de email del usuario (ocultar si no es Corporate Admin)
    - Estado idle: mostrar campo password (opcional) + botón "Generar Backup"
    - Estado generating: mostrar barra de progreso + etapa actual + deshabilitar botón
    - Estado completed: mostrar metadata (fecha, tamaño, tiene password) + botones de descarga + botones de generar nuevo / eliminar
    - Estado failed: mostrar error + botón reintentar
    - Implementar polling cada 5 segundos cuando status es "generating"
    - Click en descargar: obtener presigned URL y abrir en nueva pestaña / trigger download
    - _Requirements: 1.1, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 3.1, 3.2, 3.3, 3.5, 4.1, 4.2, 4.3, 4.4_

  - [x] 8.2 Integrar BackupSection en la página admin correspondiente
    - Agregar sección en la página de System Configuration o crear nueva ruta admin `/dashboard/admin/backup`
    - Agregar entrada en navegación admin (solo visible para Corporate Admin)
    - _Requirements: 1.1, 1.4_

- [x] 9. Frontend: Modificar Setup Page para soportar restore
  - [x] 9.1 Modificar `src/app/setup/page.tsx` — agregar tabs y detección de restore en progreso
    - Al cargar, verificar si hay restore en progreso (GET /setup/restore/status)
    - Si restore en progreso → mostrar pantalla de progreso (no tabs)
    - Si BD vacía y no hay restore → mostrar 2 tabs: "Crear Administrador" | "Restaurar Backup"
    - Tab "Crear Administrador": mantener formulario actual sin cambios
    - Tab "Restaurar Backup": nuevo formulario de restore
    - _Requirements: 5.1, 5.2, 5.6_

  - [x] 9.2 Implementar formulario de restore en la tab "Restaurar Backup"
    - Input file para DB_ZIP (aceptar solo .zip)
    - Input file para Images_ZIP (aceptar solo .zip)
    - Campo password (con nota "requerido si los archivos están protegidos")
    - Botón "Restaurar" (disabled si no hay ambos archivos seleccionados)
    - Al click en restaurar:
      1. Obtener presigned URLs del backend
      2. Mostrar indicador "Subiendo archivos — no cierre la ventana"
      3. Upload DB_ZIP a S3 con barra de progreso
      4. Upload Images_ZIP a S3 con barra de progreso
      5. Llamar POST /setup/restore/start
      6. Redirigir a pantalla de progreso de restauración
    - Si error en upload, mostrar mensaje y permitir reintentar
    - _Requirements: 5.3, 5.4, 5.5_

  - [x] 9.3 Implementar pantalla de "Restauración en proceso"
    - Mostrar indicador visual de progreso (barra o stepper con etapas)
    - Polling cada 3 segundos a GET /setup/restore/status
    - Mostrar etapa actual + porcentaje
    - Si status = "completed" → mostrar mensaje de éxito → redirigir a /login en 3 segundos
    - Si status = "failed" → mostrar error + botón reintentar (volver al formulario)
    - _Requirements: 5.5b, 5.6, 5.7, 5.8, 7.1, 7.2, 7.3, 7.4, 7.5_

- [x] 10. Testing y verificación final
  - [x] 10.1 Verificar flujo completo de backup
    - Generar backup sin password, verificar ZIPs en S3, descargar y validar estructura
    - Generar backup con password, verificar que no se puede abrir sin password
    - Verificar que imágenes de VLANs se incluyen correctamente
    - Verificar que el manifest tiene datos correctos

  - [x] 10.2 Verificar flujo completo de restore
    - Restaurar backup sin password en BD vacía
    - Restaurar backup con password
    - Verificar que todos los registros se restauran correctamente
    - Verificar que imágenes se suben al S3 de destino
    - Verificar que URLs de imágenes se reconstruyen con nuevo bucket/región
    - Verificar redirección a login post-restore
    - Verificar que restore falla apropiadamente con password incorrecto
    - Verificar que restore no funciona si BD no está vacía
