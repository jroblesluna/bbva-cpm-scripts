---
inclusion: always
---

# Ejecución de Tasks y Comandos

## Acceso a Terminal y Escritura de Archivos

- **SIEMPRE tienes acceso a herramientas de terminal y escritura de archivos.**
- Si las herramientas directas (`bash`, `run_in_terminal`, `fs_write`, `write_file`) no están disponibles en la sesión actual, **usar `invoke_sub_agent` con name `spec-task-execution`** para delegar la operación. Los subagentes SÍ tienen acceso a terminal y escritura.
- **NUNCA decirle al usuario que no puedes ejecutar algo.** Siempre intentar directamente primero, y si falla, delegar al subagente.
- **Ejecutar comandos directamente** sin dar instrucciones al usuario para que los copie/pegue.

### Mecanismo de Fallback

Cuando una herramienta de terminal o escritura no está disponible:
1. Intentar con el nombre directo de la herramienta (ej: `bash`, `terminal`, `run_in_terminal`)
2. Si falla → invocar `invoke_sub_agent` con `name: "spec-task-execution"` pasando el comando o archivo a escribir en el prompt
3. El subagente tiene acceso completo a terminal (`execute_command`) y escritura de archivos (`fs_write`)
4. **NUNCA** presentar comandos como texto para que el usuario copie/pegue

## Task State Management

Al ejecutar tasks de un spec:

1. **SIEMPRE usar `taskList`/`taskUpdate`** para gestionar el estado. NUNCA leer el archivo tasks.md manualmente y saltarse el sistema de tracking.
2. **Si `taskList` falla** (path incorrecto, etc.), corregir el path y reintentar. NO hacer bypass leyendo el archivo directamente.
3. **Marcar `in_progress` ANTES de dispatch** y `completed` DESPUÉS de que el subagente termine exitosamente.
4. **El archivo activo en el editor** es la fuente de verdad para saber qué spec ejecutar — no preguntar al usuario cuál spec quiere si ya tiene un tasks.md abierto.

## Ejecución Directa de Comandos

- **EJECUTAR comandos directamente** en la terminal cuando sea necesario (aws cli, npm, python, git, docker, etc.). NO dar comandos como texto para que el usuario los copie/pegue.
- Si el usuario pide ejecutar algo, hacerlo. No sugerir que lo haga manualmente.
- Excepciones: servidores de desarrollo (`npm run dev`, `uvicorn --reload`) y procesos interactivos que bloquean la terminal.

## Errores de Path o Contexto

- Si una herramienta falla por path incorrecto, usar `file_search` o el contexto del editor activo para encontrar el path correcto y reintentar inmediatamente.
- NO pedir al usuario que confirme paths que puedes resolver tú mismo.
