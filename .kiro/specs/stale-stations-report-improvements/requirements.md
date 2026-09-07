# Requirements Document

## Introduction

Este documento define los requisitos para corregir y mejorar el reporte de **Estaciones IP Inactivas** (stale IP workstations) en el frontend de AlwaysPrint Cloud. El reporte lista, por IP privada, las estaciones que tuvieron actividad real de conexión pero que no se han conectado en más de N días.

El problema central es un **bug de datos**: la columna "Días inactiva" siempre muestra `0d` porque el backend calcula la antigüedad usando la columna real de actividad `last_seen` (migración 036), pero el schema de respuesta `WorkstationResponse` no expone `last_seen`. El frontend, al no recibir ese campo, recurre a `updated_at`, que se actualiza con cualquier cambio de registro (`onupdate=datetime.utcnow`) y por lo tanto es prácticamente "ahora", dejando la antigüedad en cero.

La solución raíz (conforme a la regla de análisis de impacto) es **exponer `last_seen` de forma aditiva** en el backend y en el tipo del frontend, y usar `last_seen` tanto para calcular los días de inactividad como para la columna "Última conexión". La lógica de la consulta del backend ya es correcta y **no debe modificarse ni debilitarse**.

Además de la corrección del bug, este documento cubre mejoras de claridad, de presentación de fechas con hora, de accesibilidad de la paginación, de ordenamiento de columnas y de pulido visual general del reporte.

Todo texto visible al usuario debe ser dinámico vía next-intl, agregando cada clave en `es.json` y `en.json` bajo el namespace `config`. Se preserva el aislamiento por inquilino (tenant isolation): el operador solo ve su propia organización; el administrador puede filtrar por organización.

## Glossary

- **Reporte_Estaciones_Inactivas**: Componente de frontend `StaleWorkstationsSection` que lista las estaciones IP inactivas en la página de configuración.
- **Backend_Estaciones**: Endpoint `GET /workstations/stale` (`list_stale_workstations`) que devuelve la lista paginada de estaciones inactivas.
- **Schema_Workstation**: Modelo de respuesta `WorkstationResponse` del backend que serializa una estación hacia el frontend.
- **Tipo_Workstation**: Interfaz TypeScript `Workstation` del frontend.
- **last_seen**: Columna de base de datos (migración 036) que registra la última vez real que una estación estuvo en línea. Es no nula.
- **updated_at**: Columna de base de datos que se actualiza con cualquier cambio de registro (`onupdate=datetime.utcnow`); NO refleja la última conexión real.
- **created_at**: Columna de base de datos con la fecha de registro (primer alta) de la estación.
- **min_hours**: Filtro de "actividad mínima": la estación debe haber estado activa al menos N horas (`last_seen - created_at`) antes de quedar inactiva, para descartar registros efímeros que nunca se usaron realmente.
- **Días_Inactiva**: Número entero de días transcurridos desde `last_seen` hasta el momento actual.
- **FAB_Info**: Botón flotante circular de información (floating action button) que se superpone al final del contenido de la página.
- **Operador**: Usuario con rol `OPERATOR`, que solo puede ver estaciones de su propia organización.
- **Administrador**: Usuario con rol `ADMIN`, que puede ver todas las organizaciones o filtrar por una.
- **sort_by**: Parámetro de consulta del Backend_Estaciones que indica la columna por la que se ordena el dataset completo. Valores admitidos: `ip`, `hostname`, `current_user`, `organizacion`, `created_at`, `last_seen`, `dias_inactiva`.
- **sort_dir**: Parámetro de consulta del Backend_Estaciones que indica la dirección de ordenamiento. Valores admitidos: `asc` (ascendente) y `desc` (descendente).
- **Ordenamiento server-side**: Ordenamiento aplicado por el Backend_Estaciones sobre el dataset completo (antes de la paginación offset/limit), no limitado a la página visible en el frontend.
- **Zona_Horaria_Organizacion**: Zona horaria propia de la organización, expuesta en el campo `timezone` de la organización, usada para presentar los timestamps almacenados en UTC. Para BBVA es UTC-5.
- **Umbral_Critico_Inactividad**: Umbral fijo de 180 días de inactividad a partir del cual una estación se resalta visualmente como crítica (Días_Inactiva ≥ 180).

## Requirements

### Requirement 1: Exponer `last_seen` en la respuesta del backend

**User Story:** Como consumidor del API de estaciones inactivas, quiero que la respuesta incluya el campo `last_seen`, para que el frontend pueda calcular correctamente los días de inactividad y mostrar la última conexión real.

#### Acceptance Criteria

1. THE Schema_Workstation SHALL incluir el campo `last_seen` de tipo fecha-hora en su representación de respuesta.
2. WHEN el Backend_Estaciones serializa una estación, THE Schema_Workstation SHALL poblar `last_seen` con el valor de la columna `last_seen` del modelo.
3. THE Backend_Estaciones SHALL conservar sin cambios la lógica de filtrado existente (`last_seen - created_at > min_hours*3600` Y `last_seen < now - days`) y el ordenamiento por `last_seen` ascendente.
4. THE Schema_Workstation SHALL conservar todos los campos existentes que expone actualmente sin eliminarlos ni renombrarlos.

### Requirement 2: Exponer `last_seen` en el tipo del frontend

**User Story:** Como desarrollador del frontend, quiero que la interfaz `Workstation` incluya `last_seen`, para poder consumir el campo con tipado estricto sin usar `any`.

#### Acceptance Criteria

1. THE Tipo_Workstation SHALL declarar la propiedad `last_seen` como cadena de fecha-hora.
2. THE Tipo_Workstation SHALL conservar sin eliminar ni renombrar las propiedades existentes.

### Requirement 3: Corregir el cálculo de "Días inactiva"

**User Story:** Como operador o administrador, quiero ver la cantidad real de días que una estación lleva inactiva, para poder identificar equipos abandonados y tomar decisiones.

#### Acceptance Criteria

1. WHEN el Reporte_Estaciones_Inactivas calcula Días_Inactiva para una estación, THE Reporte_Estaciones_Inactivas SHALL derivar el valor a partir de `last_seen` y el momento actual.
2. THE Reporte_Estaciones_Inactivas SHALL mostrar Días_Inactiva como el número entero de días completos transcurridos desde `last_seen`.
3. WHERE la vista es de tarjetas (cards), THE Reporte_Estaciones_Inactivas SHALL calcular Días_Inactiva a partir de `last_seen`.
4. WHERE la vista es de tabla, THE Reporte_Estaciones_Inactivas SHALL calcular Días_Inactiva a partir de `last_seen`.

### Requirement 4: Usar `last_seen` en la columna "Última conexión"

**User Story:** Como operador o administrador, quiero que la columna "Última conexión" muestre la última vez que la estación estuvo en línea, para interpretar correctamente el reporte.

#### Acceptance Criteria

1. WHEN el Reporte_Estaciones_Inactivas muestra la columna "Última conexión", THE Reporte_Estaciones_Inactivas SHALL usar el valor de `last_seen`.
2. THE Reporte_Estaciones_Inactivas SHALL usar `last_seen` para "Última conexión" tanto en la vista de tarjetas como en la vista de tabla.

### Requirement 5: Clarificar el filtro "Actividad mínima (horas)"

**User Story:** Como usuario del reporte, quiero entender qué significa el filtro de actividad mínima, para configurarlo con confianza.

#### Acceptance Criteria

1. THE Reporte_Estaciones_Inactivas SHALL mostrar una etiqueta para el filtro de actividad mínima que comunique que representa las horas mínimas de actividad real antes de quedar inactiva.
2. THE Reporte_Estaciones_Inactivas SHALL mostrar un texto de ayuda o tooltip que explique que el filtro descarta estaciones que estuvieron activas menos de N horas (calculado como `last_seen - created_at`).
3. THE Reporte_Estaciones_Inactivas SHALL obtener el texto de la etiqueta y de la ayuda desde el sistema de traducciones (namespace `config`).

### Requirement 6: Mostrar fecha y hora en "Registrada" y "Última conexión"

**User Story:** Como usuario del reporte, quiero ver la hora además de la fecha en las columnas de fechas, expresadas en la zona horaria de mi organización, para conocer el momento exacto de registro y de última conexión sin ambigüedad de huso horario.

#### Acceptance Criteria

1. WHEN el Reporte_Estaciones_Inactivas muestra la columna "Registrada", THE Reporte_Estaciones_Inactivas SHALL mostrar la fecha y la hora del valor `created_at`.
2. WHEN el Reporte_Estaciones_Inactivas muestra la columna "Última conexión", THE Reporte_Estaciones_Inactivas SHALL mostrar la fecha y la hora del valor `last_seen`.
3. THE Reporte_Estaciones_Inactivas SHALL aplicar el formato de fecha y hora tanto en la vista de tarjetas (incluido el footer de cada tarjeta) como en la vista de tabla.
4. GIVEN que `created_at` y `last_seen` se almacenan en UTC (naive), WHEN el Reporte_Estaciones_Inactivas presenta cualquiera de esas fechas-hora, THE Reporte_Estaciones_Inactivas SHALL convertir el timestamp desde UTC a la Zona_Horaria_Organizacion (campo `timezone` de la organización) antes de mostrarlo, y no a la zona horaria del navegador.
5. WHERE la organización es BBVA, THE Reporte_Estaciones_Inactivas SHALL presentar las fechas-hora en UTC-5 conforme a la Zona_Horaria_Organizacion.
6. THE Reporte_Estaciones_Inactivas SHALL aplicar la conversión a la Zona_Horaria_Organizacion de forma idéntica en la vista de tarjetas (footer) y en la vista de tabla.

### Requirement 7: Paginación visible y accesible

**User Story:** Como usuario del reporte, quiero poder ver y usar los controles de paginación sin que queden tapados, para navegar entre páginas de resultados.

#### Acceptance Criteria

1. THE Reporte_Estaciones_Inactivas SHALL renderizar el bloque de paginación de forma que no quede superpuesto por el FAB_Info.
2. WHILE el usuario hace scroll hasta el final del contenido, THE Reporte_Estaciones_Inactivas SHALL mantener los controles de paginación visibles y clicables.
3. THE Reporte_Estaciones_Inactivas SHALL reservar espacio inferior suficiente para que el FAB_Info no cubra los controles de paginación.

### Requirement 8: Ordenamiento de columnas en la tabla

**User Story:** Como usuario del reporte, quiero ordenar la tabla por cualquier columna sobre todo el conjunto de resultados (no solo la página visible), para organizar los resultados según mi necesidad de análisis.

#### Acceptance Criteria

1. THE Reporte_Estaciones_Inactivas SHALL permitir ordenar la tabla por las columnas IP, hostname, usuario, organización, registrada, última conexión y días inactiva.
2. WHEN el usuario selecciona una columna ordenable, THE Reporte_Estaciones_Inactivas SHALL ordenar las filas por el valor de esa columna.
3. WHEN el usuario selecciona una columna que ya está ordenada de forma ascendente, THE Reporte_Estaciones_Inactivas SHALL invertir el orden a descendente.
4. WHEN el usuario selecciona una columna que ya está ordenada de forma descendente, THE Reporte_Estaciones_Inactivas SHALL invertir el orden a ascendente.
5. THE Reporte_Estaciones_Inactivas SHALL indicar visualmente la columna activa de ordenamiento y su dirección.
6. THE Reporte_Estaciones_Inactivas SHALL obtener cualquier texto de encabezado o indicador desde el sistema de traducciones (namespace `config`).
7. THE Backend_Estaciones SHALL aceptar el parámetro de consulta `sort_by` con los valores admitidos `ip`, `hostname`, `current_user`, `organizacion`, `created_at`, `last_seen` y `dias_inactiva`.
8. THE Backend_Estaciones SHALL aceptar el parámetro de consulta `sort_dir` con los valores admitidos `asc` y `desc`.
9. IF la petición no especifica `sort_by` o `sort_dir`, THEN THE Backend_Estaciones SHALL ordenar por `last_seen` de forma ascendente, preservando el comportamiento actual.
10. WHEN el Backend_Estaciones aplica el ordenamiento, THE Backend_Estaciones SHALL ordenar el dataset completo ANTES de aplicar la paginación (offset/limit).
11. WHEN el valor de `sort_by` es `dias_inactiva`, THE Backend_Estaciones SHALL ordenar de forma equivalente a ordenar por `last_seen` en dirección inversa (a mayor Días_Inactiva corresponde un `last_seen` más antiguo).
12. WHILE se aplica el ordenamiento, THE Backend_Estaciones SHALL preservar el aislamiento por inquilino y los filtros `days` y `min_hours` existentes, sin debilitarlos.
13. WHEN el usuario cambia la columna o la dirección de ordenamiento, THE Reporte_Estaciones_Inactivas SHALL enviar los parámetros `sort_by` y `sort_dir` al Backend_Estaciones y volver a la página 1.
14. THE Reporte_Estaciones_Inactivas SHALL reflejar la columna activa y su dirección según los valores de `sort_by` y `sort_dir` enviados al Backend_Estaciones.

### Requirement 9: Preservar el aislamiento por inquilino y los filtros existentes

**User Story:** Como administrador de seguridad, quiero que las mejoras no alteren el aislamiento de datos entre organizaciones ni debiliten el filtrado, para mantener la integridad multi-inquilino.

#### Acceptance Criteria

1. WHILE el usuario tiene rol Operador, THE Backend_Estaciones SHALL devolver únicamente estaciones de la organización del usuario.
2. WHERE el usuario tiene rol Administrador y especifica una organización, THE Backend_Estaciones SHALL devolver únicamente estaciones de esa organización.
3. THE Backend_Estaciones SHALL conservar sin debilitar los filtros de `days` y `min_hours` existentes.
4. IF una estación no cumple los filtros de inactividad, THEN THE Backend_Estaciones SHALL excluirla del resultado.

### Requirement 10: Internacionalización de todos los textos nuevos

**User Story:** Como usuario que cambia de idioma, quiero que todos los textos nuevos del reporte estén traducidos, para usar el sistema en español o inglés sin textos codificados.

#### Acceptance Criteria

1. THE Reporte_Estaciones_Inactivas SHALL obtener todo texto visible al usuario desde el sistema de traducciones (namespace `config`).
2. THE sistema de traducciones SHALL definir cada clave nueva tanto en `es.json` como en `en.json` con la misma estructura de claves.
3. THE Reporte_Estaciones_Inactivas SHALL evitar cadenas de texto codificadas directamente en el JSX para contenido visible al usuario.

### Requirement 11: Pulido visual y de experiencia de usuario

**User Story:** Como usuario del reporte, quiero una presentación más clara y pulida, para leer e interpretar la información con menor esfuerzo.

#### Acceptance Criteria

1. THE Reporte_Estaciones_Inactivas SHALL mantener consistencia visual con el resto de la página de configuración usando los componentes de interfaz existentes.
2. WHERE una estación tiene Días_Inactiva mayor o igual al Umbral_Critico_Inactividad (180 días), THE Reporte_Estaciones_Inactivas SHALL resaltar visualmente el indicador de Días_Inactiva como crítico.
3. THE Reporte_Estaciones_Inactivas SHALL conservar el tipado estricto de TypeScript sin usar `any`.
