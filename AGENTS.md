# AGENTS.md

Este archivo proporciona contexto para agentes de IA (Codex, etc.) que trabajen en este repositorio.

## Descripción del Proyecto

Sistema de gestión de impresión híbrido Linux-Windows para BBVA, basado en **Lexmark Cloud Print Manager (CPM)**. Consiste en filtros CUPS personalizados en un servidor Linux SUSE 12 que enrutan trabajos de impresión hacia estaciones Windows mediante LPD.

## Reglas de Idioma

**Todos los textos, comentarios y mensajes de log deben estar en español.** Esto incluye:
- Comentarios en scripts Bash (`.cpm`, `_pro`, `.sh`)
- Mensajes de log (funciones `log`, `echo >> logfile`)
- Mensajes de error (`die`, `echo [ERROR]`)
- Comentarios en archivos `.bat` y `.ps1`

## Archivos Principales a Modificar

| Archivo | Propósito |
|---|---|
| `Linux Server/root/bin/filtro_nacarpr_pro.cpm` | Filtro producción CPM — versión actual |
| `Linux Server/root/bin/filtro_contingencia_pro` | Filtro contingencia LPD directo — versión actual |
| `Linux Server/root/bin/filtro_winhostuser` | Receptor de mapeados hostname→IP desde Windows |
| `Workstations/Startup/update_winhostuser.bat` | Envío de mapeado desde Windows al inicio |
| `Workstations/Client Installer/configuration.json` | Configuración del cliente CPM |

Los archivos sin sufijo `_pro` (`filtro_nacarpr.cpm`, `filtro_contingencia`) son versiones legacy. No modificar salvo corrección crítica de compatibilidad.

## Variables de Entorno CUPS Relevantes

Los filtros CUPS reciben estos argumentos posicionales:
- `$1` = SPOOLID (ID del job)
- `$2` = usuario que imprime
- `$3` = nombre del job
- `$4` = número de copias
- `$5` = opciones
- `$6` = ruta al archivo de spool (vacío = leer desde stdin)

La variable `$DEVICE_URI` es seteada por CUPS con la URI del dispositivo de la cola.

## Lógica de Nomenclatura

Un `PUESTO` tiene el formato `w0###0SpXX` (10 chars) donde:
- posiciones 2-4: código de agencia
- posición 6: identificador servidor Linux
- posiciones 8-9: número de puesto (XX)

El host Windows correspondiente sigue el mismo patrón con prefijo `w10` o `w11`.

## Archivos de Datos en Producción

Estos archivos **no están en el repositorio**, existen solo en el servidor Linux:
- `/var/lib/lexmark/win_hostname_user.txt` — BD de mapeados (formato: `host|usuario|ip`)
- `/var/lib/lexmark/lexmark_filtro.config` — parámetros de comportamiento
- `/var/lib/lexmark/lexmark.log` — log principal
- `/var/lib/lexmark/lexmark_winhostuser.log` — log de mapeados

## Convenciones de Código

- Los filtros `_pro` usan funciones `log()` y `die()` con timestamps
- Toda limpieza de archivos temporales se hace con `trap cleanup EXIT INT TERM`
- Las secciones del código se separan con comentarios `# === NOMBRE DE SECCIÓN ===`
- El número de versión se define como `VERSION="vYYYYMMDDhhmm"` en la línea 4
- Actualizar `VERSION` en cada modificación siguiendo el formato de fecha

## Qué NO Hacer

- No convertir los filtros a otro lenguaje (deben ser bash para compatibilidad SUSE 12)
- No usar `bashisms` incompatibles con bash 4.x de SUSE 12
- No eliminar los archivos legacy (`filtro_nacarpr.cpm`, `filtro_contingencia`) sin instrucción explícita
- No modificar las cabeceras `@PJL` sin conocimiento del protocolo PJL/Lexmark
- No cambiar el nombre de la cola LPD de Windows (`LexmarkBBVA`) sin actualizar `configuration.json`
