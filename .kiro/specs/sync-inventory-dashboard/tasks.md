# Implementation Plan: Sync Inventory Dashboard

## Overview

Implementar una sección de sincronización de inventario en la página de System Configuration que permite a los Corporate Admins ejecutar los 6 pasos de `sync_inventory.py` desde la UI web. El backend expone un único endpoint POST que importa directamente las funciones de paso, captura stdout vía `StringIO`, y devuelve el output al frontend. El acceso se restringe por dominio de email tanto en frontend como en backend.

## Tasks

- [x] 1. Backend: Crear endpoint y dependencia de autorización
  - [x] 1.1 Crear `app/api/v1/endpoints/sync_inventory.py` con la dependencia `require_corporate_admin`
    - Crear el archivo `app/api/v1/endpoints/sync_inventory.py`
    - Implementar dependencia `require_corporate_admin` que verifica dominio email (`@robles.ai`, `@sistemas.com.pe`)
    - Devolver HTTP 403 si el dominio no coincide
    - Definir schemas Pydantic `StepResult` y `SyncExecutionResponse`
    - Crear el router con prefijo `/admin/sync-inventory`
    - _Requirements: 1.3, 1.4, 8.1, 8.6_

  - [x] 1.2 Implementar endpoint `POST /execute` con lógica de ejecución de pasos
    - Aceptar parámetros: `step` (1-7), `dry_run` (bool, default True), `organization_id` (UUID), `csv_file` (UploadFile opcional)
    - Validar que la organización existe (404 si no)
    - Validar que el CSV está presente cuando es requerido (steps 1-3 o "all"/step=7) — retornar 422 si falta
    - Parsear CSV y validar columnas requeridas (VLAN_CODE, VLAN_NAME, IP, MODELO, SERIE, UBICACION, DIRECCION, DISTRITO, PROVINCIA, DEPARTAMENTO, TIPO) — retornar 422 si faltan columnas
    - Implementar patrón de captura stdout con `StringIO` para cada paso
    - Para step=7 ("run all"): ejecutar pasos 1-6 secuencialmente, commit independiente por paso, rollback solo del paso que falla
    - Importar y llamar funciones `step1_sync_vlans` a `step6_cleanup_vlan_cidrs` de `app.scripts.sync_inventory`
    - Retornar `SyncExecutionResponse` con lista de `StepResult` y output total
    - _Requirements: 3.2, 3.5, 3.6, 4.1, 4.2, 4.3, 5.2, 8.2, 8.3, 8.4, 8.5_

  - [x] 1.3 Registrar el router en `app/api/v1/router.py`
    - Importar `sync_inventory` desde `app.api.v1.endpoints`
    - Incluir el router con tag `"Sync Inventory"`
    - _Requirements: 8.1_

- [x] 2. Checkpoint - Verificar backend funcional
  - Ensure all tests pass, ask the user if questions arise.
  - Verificar que el endpoint responde correctamente con `curl` o test manual

- [x] 3. Frontend: Agregar traducciones i18n
  - [x] 3.1 Agregar namespace `syncInventory` en `messages/es.json` y `messages/en.json`
    - Definir keys para: título de sección, descripción, labels de cada paso (1-6), descripción de cada paso, botones (Run, Run All, Upload CSV), toggle dry-run y banner, placeholder del área de output, mensajes de error (CSV inválido, CSV requerido, ejecución fallida), label del selector de organización, labels de resumen (creados, actualizados, eliminados, sin cambios, omitidos), estado de ejecución (ejecutando, completado, error)
    - Textos en español en `es.json`, en inglés en `en.json`
    - _Requirements: 9.1, 9.2, 9.3_

- [x] 4. Frontend: Agregar API client y tipos TypeScript
  - [x] 4.1 Agregar interfaces TypeScript para `StepResult` y `SyncExecutionResponse`
    - Definir `StepResult` con campos: `step`, `name`, `success`, `output`, `error?`
    - Definir `SyncExecutionResponse` con campos: `success`, `dry_run`, `steps_executed`, `total_output`
    - Ubicar en `src/lib/api.ts` o archivo de tipos según patrón del proyecto
    - _Requirements: 8.3_

  - [x] 4.2 Agregar `syncInventoryApi` en `src/lib/api.ts`
    - Implementar método `execute` que envía POST multipart/form-data a `/admin/sync-inventory/execute`
    - Construir `FormData` con `step`, `dry_run`, `organization_id` y opcionalmente `csv_file`
    - Configurar timeout de 120000ms (2 minutos) para "run all"
    - Retornar `SyncExecutionResponse`
    - _Requirements: 8.2_

- [x] 5. Frontend: Crear componente `SyncInventorySection`
  - [x] 5.1 Crear `src/components/config/SyncInventorySection.tsx` — estructura base y control de acceso
    - Verificar email del usuario contra dominios permitidos — retornar `null` si no es Corporate Admin
    - Implementar estado interno: `selectedOrgId`, `csvFile`, `csvRowCount`, `csvError`, `dryRun` (default true), `selectedStep`, `isExecuting`, `results`
    - Renderizar selector de organización (fetch con `organizationsApi.list()`)
    - Usar `useTranslations('syncInventory')` para todos los textos
    - _Requirements: 1.1, 1.2, 7.1, 7.2, 9.3_

  - [x] 5.2 Implementar área de upload de CSV con validación client-side
    - Aceptar solo archivos `.csv`
    - Al subir, leer headers y validar columnas requeridas (VLAN_CODE, VLAN_NAME, IP, etc.)
    - Si válido: mostrar nombre de archivo y conteo de filas
    - Si inválido: mostrar error con columnas faltantes
    - _Requirements: 2.1, 2.2, 2.3, 2.5_

  - [x] 5.3 Implementar tarjetas de pasos con distinción visual CSV_Steps vs DB_Steps
    - Mostrar 6 tarjetas/botones con labels descriptivos para cada paso
    - Distinguir visualmente pasos CSV (1-3) de pasos DB (4-6) — indicar cuáles requieren CSV
    - Permitir selección de un paso individual
    - Botón "Run All" para ejecutar todos los pasos secuencialmente
    - _Requirements: 3.1, 3.4, 4.1, 4.4_

  - [x] 5.4 Implementar toggle Dry-Run y lógica de ejecución
    - Toggle de dry-run habilitado por defecto
    - Mostrar banner visual cuando dry-run está activo
    - Al ejecutar: deshabilitar botones, mostrar loading indicator
    - Llamar `syncInventoryApi.execute()` con los parámetros seleccionados
    - Si CSV_Step sin CSV → mostrar error sin llamar al backend
    - _Requirements: 2.5, 3.3, 5.1, 5.2, 5.3, 5.4_

  - [x] 5.5 Implementar área de output monospace y manejo de resultados
    - Área scrollable con fuente monospace para mostrar output de ejecución
    - Agrupar output por paso cuando se ejecutan múltiples (Run All)
    - Estilo diferenciado para errores (rojo/badge de error)
    - Badge de success/failure por cada paso completado
    - Manejar errores HTTP (403, 422, 500, timeout) con mensajes apropiados
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [x] 6. Frontend: Integrar componente en la página de configuración
  - [x] 6.1 Importar y renderizar `SyncInventorySection` en `src/app/dashboard/config/page.tsx`
    - Importar `SyncInventorySection` desde `@/components/config/SyncInventorySection`
    - Renderizar debajo del header de la página (antes o en lugar del placeholder actual)
    - El componente maneja su propio control de acceso internamente (retorna null si no es corporate admin)
    - _Requirements: 1.1, 1.2_

- [x] 7. Backend: Escribir tests unitarios
  - [x] 7.1 Test de `require_corporate_admin` — emails permitidos y rechazados
    - Verificar que `@robles.ai` y `@sistemas.com.pe` pasan
    - Verificar que otros dominios reciben 403
    - _Requirements: 1.3, 1.4_

  - [x] 7.2 Test de validación de CSV — columnas faltantes, archivo vacío, archivo válido
    - Verificar 422 con columnas faltantes
    - Verificar parseo correcto con CSV válido
    - _Requirements: 8.4_

  - [x] 7.3 Test de ejecución de pasos — mock de step functions, captura de stdout
    - Verificar que solo el step solicitado se ejecuta
    - Verificar que stdout se captura correctamente
    - Verificar comportamiento de "Run All" (step=7) secuencial
    - Verificar rollback si un paso falla
    - _Requirements: 3.2, 4.2, 4.3, 8.3, 8.5_

- [x] 8. Checkpoint final - Verificar implementación completa
  - Ensure all tests pass, ask the user if questions arise.
  - Verificar: endpoint responde correctamente, componente se renderiza para corporate admin, upload de CSV funciona, dry-run por defecto, output se muestra en monospace, i18n en ambos idiomas

## Notes

- Tasks marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido
- Las funciones de paso ya existen en `app/scripts/sync_inventory.py` — solo se importan y ejecutan
- No se necesitan nuevas tablas de base de datos
- No hay PBT — la feature es CRUD/sync con efectos secundarios en BD, sin invariantes puras
- El patrón de restricción por dominio sigue el mismo enfoque que `RemoteTerminalSection`/`RemoteViewSection`
- El timeout del frontend (120s) es necesario para "Run All" que ejecuta 6 pasos secuenciales
- Cada paso individual tiene commit independiente (misma semántica que el script original)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "3.1"] },
    { "id": 1, "tasks": ["1.2", "4.1"] },
    { "id": 2, "tasks": ["1.3", "4.2"] },
    { "id": 3, "tasks": ["5.1"] },
    { "id": 4, "tasks": ["5.2", "5.3"] },
    { "id": 5, "tasks": ["5.4", "5.5"] },
    { "id": 6, "tasks": ["6.1"] },
    { "id": 7, "tasks": ["7.1", "7.2", "7.3"] }
  ]
}
```
