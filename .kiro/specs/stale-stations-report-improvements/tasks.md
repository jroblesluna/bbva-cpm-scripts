# Implementation Plan

## Overview

Este plan implementa la corrección del bug de "Días inactiva" (exponer `last_seen` de forma aditiva) y las mejoras del reporte de Estaciones IP Inactivas: ordenamiento server-side, presentación de fecha+hora en la zona horaria de la organización, paginación no tapada por el FAB, resaltado crítico (≥180 días) e internacionalización.

El orden es incremental y test-driven: primero el backend (schema `last_seen` → endpoint con `sort_by`/`sort_dir` + `joinedload`), luego el frontend (tipo → API client → componente), después i18n, y finalmente las pruebas de frontend. Todos los cambios de esquema/tipo son aditivos; no hay migración de base de datos (la columna `last_seen` ya existe, migración 036).

## Tasks

- [x] 1. Exponer `last_seen` en el schema de respuesta del backend
  - [x] 1.1 Añadir `last_seen: datetime` a `WorkstationResponse`
    - Editar `AlwaysPrintProject/Cloud/backend/app/schemas/workstation.py`
    - Agregar el campo `last_seen: datetime` a la clase `WorkstationResponse` de forma aditiva (junto a `created_at`/`updated_at`), poblado automáticamente vía `from_attributes=True`
    - Conservar TODOS los campos existentes sin renombrar ni eliminar (incluido `updated_at`)
    - _Requisitos: 1.1, 1.2, 1.4_

  - [x] 1.2 Escribir prueba de ejemplo: `last_seen` presente en cada item
    - En la suite de tests del backend (pytest), verificar que cada item de la respuesta de `GET /workstations/stale` incluye `last_seen` con valor no nulo
    - _Requisitos: 1.1, 1.2_

- [x] 2. Añadir ordenamiento server-side al endpoint `list_stale_workstations`
  - [x] 2.1 Definir los Enums `StaleSortBy` y `StaleSortDir`
    - Editar `AlwaysPrintProject/Cloud/backend/app/api/v1/endpoints/workstations.py`
    - Definir `class StaleSortBy(str, Enum)` con valores `ip`, `hostname`, `current_user`, `organizacion`, `created_at`, `last_seen`, `dias_inactiva`
    - Definir `class StaleSortDir(str, Enum)` con valores `asc`, `desc`
    - _Requisitos: 8.7, 8.8_

  - [x] 2.2 Agregar params `sort_by`/`sort_dir`, mapeo de columnas y `order_by` antes de paginar
    - En `list_stale_workstations` (~línea 1588), agregar `sort_by: StaleSortBy = Query(StaleSortBy.last_seen)` y `sort_dir: StaleSortDir = Query(StaleSortDir.asc)`
    - Mapear `sort_by` → columna SQLAlchemy: `ip`→`Workstation.ip_private`, `hostname`→`Workstation.hostname`, `current_user`→`Workstation.current_user`, `organizacion`→`Organization.name` (requiere `outerjoin(Organization)`), `created_at`→`Workstation.created_at`, `last_seen`→`Workstation.last_seen`, `dias_inactiva`→`Workstation.last_seen` con dirección INVERTIDA (días DESC ≡ last_seen ASC)
    - Añadir `joinedload(Workstation.organization)` a la consulta base para que viaje `timezone` y evitar N+1
    - Aplicar `order_by(order_expr)` ANTES de `.offset(...).limit(...)`; calcular `total` con `count()` sobre el conjunto filtrado (independiente del sort)
    - NO modificar los filtros `and_(...)` (`last_seen - created_at > min_hours*3600` Y `last_seen < now - days`) ni el tenant isolation
    - Con default (`last_seen`/`asc`) preservar el comportamiento actual
    - _Requisitos: 1.3, 8.7, 8.8, 8.9, 8.10, 8.11, 8.12, 9.1, 9.2, 9.3, 9.4_

  - [x] 2.3 Escribir pruebas de ejemplo de ordenamiento y filtros
    - Ordenar por cada columna (`ip`, `hostname`, `current_user`, `organizacion`, `created_at`, `last_seen`, `dias_inactiva`) en `asc` y `desc` produce el orden esperado
    - Sin params `sort_by`/`sort_dir` → orden `last_seen` ascendente
    - El ordenamiento se aplica antes de paginar: dos páginas consecutivas no se solapan y son coherentes
    - Tenant isolation preservado bajo cualquier sort (operador y admin filtrado); filtros `days`/`min_hours` intactos
    - _Requisitos: 8.1, 8.2, 8.3, 8.4, 8.9, 8.10, 9.1, 9.2, 9.3, 9.4_

  - [x] 2.4 Property test: el ordenamiento no altera el conjunto filtrado
    - Con Hypothesis (≥100 iteraciones), generar conjuntos de estaciones filtradas y cualquier `sort_by`/`sort_dir`; la unión de páginas es igual (como conjunto) al conjunto filtrado
    - **Property 1: El ordenamiento no altera el conjunto filtrado**
    - Tag: `Feature: stale-stations-report-improvements, Property 1: El ordenamiento no altera el conjunto filtrado`
    - _Requisitos: 8.10, 8.12, 9.3, 9.4_

  - [x] 2.5 Property test: `dias_inactiva` DESC ≡ `last_seen` ASC
    - Con Hypothesis (≥100 iteraciones), verificar que `sort_by=dias_inactiva`/`desc` produce el mismo orden que `sort_by=last_seen`/`asc` (y viceversa)
    - **Property 2: dias_inactiva DESC equivale a last_seen ASC**
    - Tag: `Feature: stale-stations-report-improvements, Property 2: dias_inactiva DESC equivale a last_seen ASC`
    - _Requisitos: 8.11_

  - [x] 2.6 Property test: `total` y paginación consistentes con el filtro
    - Con Hypothesis (≥100 iteraciones), verificar que `total` = |conjunto filtrado| y la concatenación de páginas no repite ni omite elementos, para cualquier tamaño de página e independiente del sort
    - **Property 3: total y paginacion consistentes con el filtro**
    - Tag: `Feature: stale-stations-report-improvements, Property 3: total y paginacion consistentes con el filtro`
    - _Requisitos: 8.10_

  - [x] 2.7 Property test: aislamiento por inquilino bajo cualquier orden
    - Con Hypothesis (≥100 iteraciones), bajo cualquier `sort_by`/`sort_dir`, toda estación devuelta respeta el aislamiento por inquilino (operador y admin filtrado)
    - **Property 4: aislamiento por inquilino bajo cualquier orden**
    - Tag: `Feature: stale-stations-report-improvements, Property 4: aislamiento por inquilino bajo cualquier orden`
    - _Requisitos: 9.1, 9.2_

- [x] 3. Checkpoint - Backend
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Exponer `last_seen` en el frontend (tipo y API client)
  - [x] 4.1 Añadir `last_seen: string` a la interfaz `Workstation`
    - Editar `AlwaysPrintProject/Cloud/frontend/src/types/workstation.ts`
    - Agregar la propiedad `last_seen: string` (cadena ISO de fecha-hora) de forma aditiva; conservar las propiedades existentes sin renombrar ni eliminar
    - _Requisitos: 2.1, 2.2_

  - [x] 4.2 Añadir `sort_by`/`sort_dir` opcionales a `workstationsApi.listStale`
    - Editar `AlwaysPrintProject/Cloud/frontend/src/lib/api.ts` (~línea 657)
    - Agregar params opcionales `sort_by?: 'ip' | 'hostname' | 'current_user' | 'organizacion' | 'created_at' | 'last_seen' | 'dias_inactiva'` y `sort_dir?: 'asc' | 'desc'`, y propagarlos como query params
    - _Requisitos: 8.7, 8.8, 8.13_

- [x] 5. Actualizar `StaleWorkstationsSection` (datos, formateo, sort, UI)
  - [x] 5.1 Corregir "Días inactiva" y "Última conexión" para usar `last_seen`
    - Editar `AlwaysPrintProject/Cloud/frontend/src/components/config/StaleWorkstationsSection.tsx`
    - Hacer que `daysAgo` reciba `ws.last_seen` (no `updated_at`) para calcular "Días inactiva" en cards y tabla
    - Hacer que "Última conexión" use `ws.last_seen` (no `updated_at`) en cards y tabla
    - _Requisitos: 3.1, 3.2, 3.3, 3.4, 4.1, 4.2_

  - [x] 5.2 Añadir `formatDateTimeInOrgTz` y aplicar fecha+hora en zona de la organización
    - En el mismo componente, crear `formatDateTimeInOrgTz(dateStr, timeZone)` con `Intl.DateTimeFormat` (`timeZone: ws.organization?.timezone ?? 'UTC'`), interpretando el timestamp del backend como UTC (añadir `'Z'` si falta), mostrando fecha y hora (year/month/day/hour/minute)
    - Usarla en "Registrada" (`created_at`) y "Última conexión" (`last_seen`), tanto en cards (footer) como en tabla; nunca la zona del navegador
    - _Requisitos: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 5.3 Implementar estado y control de ordenamiento server-side
    - Añadir estado `sortBy` (default `'last_seen'`) y `sortDir` (default `'asc'`) con tipos estrictos
    - Implementar `handleSort(col)`: si es la misma columna, togglear dirección; si es otra, fijar columna con `asc`; en ambos casos resetear `page` a 1
    - Incluir `sortBy`/`sortDir` en las dependencias del efecto que llama a `listStale` y enviarlos al backend
    - _Requisitos: 8.2, 8.3, 8.4, 8.13, 8.14_

  - [x] 5.4 Hacer clicables los encabezados de tabla con indicador de dirección
    - Convertir los encabezados de columnas ordenables (IP, hostname, usuario, organización, registrada, última conexión, días inactiva) en clicables que invocan `handleSort`
    - Mostrar indicador de dirección con icono asc/desc de `lucide-react`; reflejar la columna y dirección activas según `sortBy`/`sortDir`; textos vía i18n
    - _Requisitos: 8.1, 8.5, 8.6, 8.14_

  - [x] 5.5 Corregir paginación tapada por el FAB de info
    - Reservar espacio inferior en el contenedor del reporte (p. ej. `pb-24`) y elevar el bloque de paginación (`relative z-10`) para que no quede cubierto por el FAB y siga clicable al hacer scroll al final
    - _Requisitos: 7.1, 7.2, 7.3_

  - [x] 5.6 Resaltado crítico de estaciones ≥ 180 días
    - Definir `CRITICAL_INACTIVE_DAYS = 180`; cuando `inactive >= CRITICAL_INACTIVE_DAYS`, aplicar estilo crítico (rojo) al Badge de "Días inactiva"
    - _Requisitos: 11.2_

  - [x] 5.7 Tooltip/ayuda para "Actividad mínima (horas)" y tipado estricto
    - Añadir etiqueta y texto de ayuda (tooltip) para el filtro de actividad mínima, explicando que descarta estaciones activas menos de N horas (`last_seen - created_at`), con texto i18n
    - Asegurar tipado estricto (sin `any`) y que todos los textos visibles provengan de `useTranslations('config')`
    - _Requisitos: 5.1, 5.2, 5.3, 10.1, 10.3, 11.1, 11.3_

- [x] 6. Añadir claves i18n nuevas (namespace `config`)
  - [x] 6.1 Agregar claves en `es.json` y `en.json`
    - Editar `AlwaysPrintProject/Cloud/frontend/messages/es.json` y `AlwaysPrintProject/Cloud/frontend/messages/en.json`
    - Bajo el namespace `config`, agregar claves nuevas (ayuda de actividad mínima `staleMinHoursHelp`, indicadores de sort `staleSortAsc`/`staleSortDesc`, `staleSortedBy`, etc.) con idéntica estructura en ambos archivos; reutilizar las claves de encabezado de columna existentes
    - _Requisitos: 5.3, 8.6, 10.1, 10.2_

- [x] 7. Pruebas de frontend
  - [x] 7.1 Pruebas de "Días inactiva" y "Última conexión"
    - Jest + Testing Library: `daysAgo` se calcula desde `ws.last_seen` (una estación con `last_seen` de hace 200 días muestra `200d`); "Última conexión" muestra `last_seen` en cards y tabla
    - _Requisitos: 3.1, 3.2, 4.1, 4.2_

  - [x] 7.2 Prueba de formateo en zona horaria de la organización
    - Verificar que `formatDateTimeInOrgTz` convierte a la zona de la organización (ej. UTC-5 para BBVA) en cards (footer) y tabla, no a la del navegador
    - _Requisitos: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 7.3 Pruebas de ordenamiento e indicador de columna activa
    - Cambiar columna/dirección dispara refetch con `sort_by`/`sort_dir` y resetea `page` a 1; el indicador de columna activa refleja `sortBy`/`sortDir`
    - _Requisitos: 8.5, 8.13, 8.14_

  - [x] 7.4 Prueba de paginación no tapada por el FAB
    - Verificar que los controles de paginación permanecen visibles y clicables al hacer scroll al final
    - _Requisitos: 7.1, 7.2, 7.3_

  - [x] 7.5 Prueba de resaltado crítico y de i18n/tipado
    - El resaltado crítico se aplica cuando `daysInactive >= 180`; todos los textos visibles provienen de `next-intl` (sin strings hardcodeados) y no se usa `any`
    - _Requisitos: 10.1, 10.3, 11.2, 11.3_

  - [x] 7.6 Property test: `formatDateTimeInOrgTz` idempotente por zona
    - Con fast-check: para cualquier timestamp UTC y zona de organización, dos llamadas iguales rinden la misma cadena y el resultado es independiente de la zona del navegador
    - **Property 5: conversion de timezone idempotente por zona**
    - Tag: `Feature: stale-stations-report-improvements, Property 5: conversion de timezone idempotente por zona`
    - _Requisitos: 6.4, 6.5, 6.6_

- [x] 8. Checkpoint final
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Las tareas marcadas con `*` son opcionales (pruebas) y pueden omitirse para un MVP más rápido.
- Todos los cambios de schema/tipo son aditivos; no hay migración de base de datos (`last_seen` ya existe, migración 036).
- Las pruebas de propiedades usan Hypothesis (backend) y fast-check (frontend) con ≥100 iteraciones y los tags exactos del diseño.
- Los checkpoints garantizan validación incremental (backend antes de frontend).

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "4.1", "4.2"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["2.3", "2.4", "2.5", "2.6", "2.7", "5.1"] },
    { "id": 4, "tasks": ["5.2", "5.3"] },
    { "id": 5, "tasks": ["5.4", "5.5", "5.6", "5.7"] },
    { "id": 6, "tasks": ["6.1"] },
    { "id": 7, "tasks": ["7.1", "7.2", "7.3", "7.4", "7.5", "7.6"] }
  ]
}
```
