# AGENTS.md

Este archivo proporciona contexto para agentes de IA (Codex, etc.) que trabajen en este repositorio.

## Descripción del Proyecto

Este repositorio contiene **DOS SISTEMAS COMPLEMENTARIOS** para gestión de impresión corporativa BBVA:

### 1. Sistema de Producción (Principal) - Lexmark Cloud Print Manager (CPM)

**El sistema de producción es Lexmark Cloud Print Manager en modo Híbrido**, gestionado por BBVA.

**Componente Principal**: Lexmark CPM Client en workstations Windows  
**Infraestructura**: Servidor Linux SUSE 12 con CUPS y filtros personalizados (BBVA, siempre operativo)  
**Ubicación**: `Linux Server/` y `Workstations/`  
**Estado**: ✅ Producción activa  
**Tecnología**: Lexmark CPM (Hybrid Mode), Bash, CUPS, LPD

**Flujo de Producción**:
```
Usuario → Cola LexmarkBBVA (Windows) → Lexmark CPM Client → 
Servidor Linux CUPS → Filtros personalizados → Impresora física
```

### 2. Sistema de Contingencia (Complementario) - AlwaysPrint

**Mecanismo de contingencia que se activa cuando Lexmark CPM falla.** Redirige el tráfico de las colas Windows directamente a las impresoras (IP:puerto estándar), haciendo bypass del servidor Linux.

**Ubicación**: `AlwaysPrintProject/`  
**Estado**: ⏳ En desarrollo (80% completo)  
**Tecnología**: C# .NET 4.8 (Client), Python 3.12 (Backend), TypeScript (Frontend)

**Flujo de Contingencia** (cuando CPM falla):
```
Usuario → Cola Windows → AlwaysPrint detecta falla → 
Redirige tráfico → IP impresora:puerto estándar (bypass CPM/Linux)
```

**IMPORTANTE**: 
- AlwaysPrint NO reemplaza el sistema de producción
- Ambos sistemas COEXISTEN en las workstations
- El servidor Linux (BBVA) está siempre operativo, pero no se usa en contingencia
- La contingencia hace bypass completo del flujo CPM/Linux

## Reglas de Idioma

**Todos los textos, comentarios y mensajes de log deben estar en español.** Esto incluye:

### Sistema de Producción (Lexmark CPM)
- Comentarios en scripts Bash (`.cpm`, `_pro`, `.sh`)
- Mensajes de log (funciones `log`, `echo >> logfile`)
- Mensajes de error (`die`, `echo [ERROR]`)
- Comentarios en archivos `.bat` y `.ps1` de `Workstations/`

### Sistema de Contingencia (AlwaysPrint)
- Comentarios en código C# (`AlwaysPrintProject/Client/`)
- Mensajes de log en AlwaysPrintLogger
- Mensajes de error y excepciones
- Comentarios en código Python (`AlwaysPrintProject/Cloud/backend/`)
- Comentarios en código TypeScript (`AlwaysPrintProject/Cloud/frontend/`)
- Strings de interfaz de usuario (UI)

## Archivos Principales a Modificar

### Sistema de Producción (Lexmark CPM)

| Archivo | Propósito |
|---|---|
| `Linux Server/root/bin/filtro_nacarpr_pro.cpm` | Filtro producción CPM — versión actual |
| `Linux Server/root/bin/filtro_contingencia_pro` | Filtro contingencia LPD directo — versión actual |
| `Linux Server/root/bin/filtro_winhostuser` | Receptor de mapeados hostname→IP desde Windows |
| `Workstations/Startup/update_winhostuser.bat` | Envío de mapeado desde Windows al inicio |
| `Workstations/Client Installer/configuration.json` | Configuración del cliente CPM |

### Sistema de Contingencia (AlwaysPrint)

| Archivo | Propósito |
|---|---|
| `AlwaysPrintProject/Client/AlwaysPrintService/AlwaysPrintWindowsService.cs` | Servicio Windows principal |
| `AlwaysPrintProject/Client/AlwaysPrintTray/MainWindow.xaml.cs` | Aplicación de bandeja (UI) |
| `AlwaysPrintProject/Client/AlwaysPrint.Shared/Configuration/AppConfiguration.cs` | Configuración compartida |
| `AlwaysPrintProject/Client/AlwaysPrint.Shared/Logging/AlwaysPrintLogger.cs` | Sistema de logging |
| `AlwaysPrintProject/Cloud/backend/app/main.py` | Backend FastAPI principal |
| `AlwaysPrintProject/Cloud/frontend/src/app/dashboard/page.tsx` | Dashboard principal |

### Sistema de Configuración de Acciones (AlwaysPrint)

| Archivo | Propósito |
|---|---|
| `AlwaysPrintProject/Client/AlwaysPrintService/Actions/ActionEngine.cs` | Motor de ejecución de acciones |
| `AlwaysPrintProject/Client/AlwaysPrintService/Actions/AdminActions.cs` | 9 funciones administrativas |
| `AlwaysPrintProject/Client/AlwaysPrint.Shared/Configuration/ActionConfig.cs` | Schemas de configuración |
| `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/ConfigManager.cs` | Gestión de descarga de configs + rotación de certificados |
| `AlwaysPrintProject/Client/CPM_Compliant.alwaysconfig` | Ejemplo de configuración |
| `AlwaysPrintProject/Cloud/backend/app/models/action_config.py` | Modelo de BD |
| `AlwaysPrintProject/Cloud/backend/app/api/v1/endpoints/action_config.py` | API REST (8 endpoints) |
| `AlwaysPrintProject/Cloud/frontend/src/app/dashboard/admin/action-configs/page.tsx` | UI de gestión |
| `AlwaysPrintProject/ACTION_CONFIG_IMPLEMENTATION.md` | Documentación técnica completa |

### Sistema de Firma Digital y Certificados (AlwaysPrint)

| Archivo | Propósito |
|---|---|
| `AlwaysPrintProject/Client/AlwaysPrint.Shared/Security/SignatureVerifier.cs` | Verificación ECDSA + descarga/rotación de certificados |
| `AlwaysPrintProject/Client/AlwaysPrintService/Pipe/MessageDispatcher.cs` | Despacha mensajes IPC incluyendo `UpdateCertVersion` |
| `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/PushMessageHandler.cs` | Maneja push de `cert_rotated` desde Cloud |
| `AlwaysPrintProject/Cloud/backend/app/api/v1/endpoints/organizations.py` | Endpoint de rotación de certificado ECDSA |
| `AlwaysPrintProject/Cloud/backend/app/services/state_map_service.py` | Propaga `ecdsa_cert_hash` en state map |

### Sistema de Backup/Restore (AlwaysPrint Cloud)

| Archivo | Propósito |
|---|---|
| `AlwaysPrintProject/Cloud/backend/app/api/v1/endpoints/backup.py` | Endpoints de backup con tablas opcionales |
| `AlwaysPrintProject/Cloud/backend/app/api/v1/endpoints/restore.py` | Endpoints de restore con streaming |
| `AlwaysPrintProject/Cloud/backend/app/services/backup_service.py` | Servicio de backup (SigV4, tablas selectivas) |
| `AlwaysPrintProject/Cloud/backend/app/services/restore_service.py` | Servicio de restore (streaming, prevención OOM) |
| `AlwaysPrintProject/Cloud/frontend/src/components/admin/BackupSection.tsx` | UI de backup con selección de tablas |
| `AlwaysPrintProject/Cloud/frontend/src/lib/backupZipValidation.ts` | Validación de ZIP antes de restore |

## Variables de Entorno CUPS Relevantes

**Aplica solo al Sistema de Producción (Lexmark CPM)**

Los filtros CUPS reciben estos argumentos posicionales:
- `$1` = SPOOLID (ID del job)
- `$2` = usuario que imprime
- `$3` = nombre del job
- `$4` = número de copias
- `$5` = opciones
- `$6` = ruta al archivo de spool (vacío = leer desde stdin)

La variable `$DEVICE_URI` es seteada por CUPS con la URI del dispositivo de la cola.

## Lógica de Nomenclatura

**Aplica solo al Sistema de Producción (Lexmark CPM)**

> **IMPORTANTE — Existen DOS nomenclaturas relacionadas por una transformación
> que hace el filtro. No confundirlas.**

### 1) `PUESTO` — cola CUPS de entrada / `Where` del finger (10 chars, prefijo `w0`)

Es el nombre de la cola donde llega el job (obtenido de `lpstat`) y el mismo valor
que muestra el `finger` en la columna `Where` (ej. `w035401p19.nacarpe.i`).
Estructura `w0 ### 0 S p XX` (10 chars):

```
w 0 3 5 4 0 1 p 1 9      Ejemplo: w035401p19
0 1 2 3 4 5 6 7 8 9               agencia=354, SERVLIN=1, puesto=19
```

El filtro extrae (índices 0-based sobre `$PUESTO`):
- `AGENCIA="${PUESTO:2:3}"` — posiciones 2-4: código de agencia (3 dígitos)
- `SERVLIN="${PUESTO:6:1}"` — posición 6: servidor de agencia (1 dígito)
- `POSXX="${PUESTO:8:2}"` — posiciones 8-9: número de puesto (2 dígitos)

### 2) Hostname Windows — clave del mapfile y de la cola dinámica (11 chars, prefijo `w1`)

Es el nombre físico de la máquina Windows en agencias y coincide con la clave del
`win_hostname_user.txt` y con la cola dinámica que crea el filtro. Estructura
`w1 [0/1] ### 0 S p XX` (11 chars):

```
w 1 0 3 5 4 0 1 p 1 9      Ejemplo: w1035401p19
0 1 2 3 4 5 6 7 8 9 10              agencia=354, SERVLIN=1, puesto=19
```

- posición 2: `0` (w10, Windows 10) o `1` (w11, Windows 11) según la imagen.
- Sufijo alfabético opcional (`w1035401p01a`, 12 chars) → **siempre se trunca a 11**.

### Transformación PUESTO → Hostname Windows (la hace `filtro_nacarpr`)

El filtro construye el hostname Windows insertando `1` tras la `w` y un `0` extra:

```
WINHOST="w10${AGENCIA}0${SERVLIN}p${YY2}"

PUESTO   w035401p19  (10, w0)  ──►  WINHOST  w1035401p19  (11, w1)
             │                             (con fallback a w11 si no hay match)
    AGENCIA=354  SERVLIN=1  PUESTO=19
```

Búsqueda en el mapfile (regex): `^w10${AGENCIA}0[0-9]p${YY2}[A-Za-z]?\|`,
con fallback a `^w11${AGENCIA}...`. El `[0-9]` en posición 7 tolera que el
`SERVLIN` real del hostname difiera del extraído del PUESTO.

> **Nota sobre el mapfile real:** el tercer campo (IP) puede faltar en algunas
> entradas (ej. `w1035401p01a|o0354p13`). El usuario puede ser personal
> (`P008967`) o genérico de oficina (`o0354p04` = `o` + agencia + `p` + puesto).

### Decisión Agencia vs Sede Central (`update_winhostuser.bat`)

El `.bat` decide qué hostname registrar en el mapfile según `%COMPUTERNAME%`:

| Caso | Condición | Hostname enviado al mapfile |
|---|---|---|
| **Agencia** | `%COMPUTERNAME%` cumple `W1######P##` (con sufijo opcional) | El propio hostname, truncado a 11 chars |
| **Sede Central** | Cualquier otro (`P017241`, `P017241A`, `XP12345`, `DESKTOP-*`, `W11PRUEBAOF3`) | `VMHOST` derivado de la MAC del VMX |

En Sede Central el nombre físico de Windows equivale al usuario (`P######` /
`XP#####`) y no coincide con ninguna cola CUPS. El `VMHOST` se deriva de la MAC
del archivo VMX (`ethernet0.address`):

```
MAC "00:50:56:YX:XX:ZZ" -> w10<XXX>0<Y>p<ZZ>
Ej.  "00:50:56:19:10:22" -> w1091001p22
     XXX (agencia) = 9,1,0  |  Y (SERVLIN) = 1  |  ZZ (puesto) = 22
```

**Limitación conocida:** una workstation VirtAplic **sin** archivo VMX no puede
derivar `VMHOST`. El script emite `[ADVERTENCIA]` y usa `%COMPUTERNAME%` como
fallback (no hará match). Pendiente: identificar la fuente del nombre de VM en
`virtconf.txt`.

### Rol del `finger`

`finger` solo identifica el **usuario LDAP** con sesión activa en el puesto
(cruzando su salida contra `$PUESTO`). No resuelve IP ni hostname de la VM.
Salida típica: `PE.017241 | PE.P017241 | w1091001p22.nacarpe.igrupobbva`
(login LDAP | hostname Windows físico | FQDN de la VM = PUESTO/cola CUPS).

## Archivos de Datos en Producción

**Aplica solo al Sistema de Producción (Lexmark CPM)**

Estos archivos **no están en el repositorio**, existen solo en el servidor Linux:
- `/var/lib/lexmark/win_hostname_user.txt` — BD de mapeados (formato: `host|usuario|ip`)
- `/var/lib/lexmark/lexmark_filtro.config` — parámetros de comportamiento
- `/var/lib/lexmark/lexmark.log` — log principal
- `/var/lib/lexmark/lexmark_winhostuser.log` — log de mapeados

## Convenciones de Código

### Sistema de Producción (Lexmark CPM - Bash)
- Los filtros `_pro` usan funciones `log()` y `die()` con timestamps
- Toda limpieza de archivos temporales se hace con `trap cleanup EXIT INT TERM`
- Las secciones del código se separan con comentarios `# === NOMBRE DE SECCIÓN ===`
- El número de versión se define como `VERSION="vYYYYMMDDhhmm"` en la línea 4
- Actualizar `VERSION` en cada modificación siguiendo el formato de fecha

### Sistema de Producción (Windows - Batch `.bat`)
- Usar **un solo** `setlocal EnableExtensions EnableDelayedExpansion`. NUNCA dos
  `setlocal` seguidos: el segundo sin `EnableDelayedExpansion` desactiva la
  expansión `!VAR!` y deja variables vacías (causó un `del` sobre el directorio
  actual con comodín).
- Dentro de bloques `if (...)`/`for (...)`, leer variables asignadas en el mismo
  bloque con `!VAR!` (delayed), no `%VAR%`.
- Borrado de temporales **fail-safe**: validar `if defined VAR` + `if exist` y
  usar `del /F /Q` (nunca `del "%VAR%"` sin validar — si `VAR` está vacío borra
  el directorio actual).
- Flag `DEBUG` (por defecto `1`) + subrutina `:dbg` para trazas `[DBG]`. Los
  mensajes `[ERROR]` y `[ADVERTENCIA]` se muestran siempre, independientes del flag.
- Comentarios y mensajes en español.

### Sistema de Contingencia (AlwaysPrint - C#)
- Usar `AlwaysPrintLogger` para todos los logs (no `Console.WriteLine`)
- Cada log debe tener un Event ID único (ver `AlwaysPrintLogger.cs`)
- Usar `try-catch` con logging de excepciones
- Validar configuración antes de usar (`AppConfiguration.Validate()`)
- Named Pipe: usar `PipeConstants.PIPE_NAME` (no hardcodear)
- Mensajes IPC: usar clases de `Payloads.cs` (no strings crudos)
- **Configuración de Acciones**: Usar `ActionEngine` para ejecutar acciones, no implementar lógica directamente
- **Firma Digital**: Siempre verificar con `SignatureVerifier.VerifyConfig()` antes de ejecutar configs descargadas
- **Operaciones privilegiadas (Registry HKLM)**: Delegar al Service via Named Pipe (Tray no tiene permisos)
- **OnDemand partial-failure**: ActionEngine trackea acciones fallidas y retorna descripciones individuales (no solo true/false)
- **Notificaciones de contingencia**: Deduplicar comparando contra estado persistido en Registry (no notificar si no cambió)
- **Imports**: Siempre usar `from app.core.database import Base` (no `app.db.base_class`)

### Sistema de Contingencia (AlwaysPrint - Python/TypeScript)
- Backend: usar structured logging con timestamps
- Backend: todas las queries deben filtrar por `organization_id` (tenant isolation)
- Backend: usar Pydantic schemas para validación
- Backend: **CRÍTICO** - Importar Base desde `app.core.database`, no desde `app.db`
- Backend: registro de workstations busca por `ip_private` primero, luego fallback por `os_serial` (evita duplicados por cambio de IP/DHCP)
- Backend: presigned URLs S3 deben usar endpoint regional explícito (`s3.<region>.amazonaws.com`) + SigV4
- Frontend: usar TypeScript estricto (no `any`)
- Frontend: componentes reutilizables en `components/ui/`
- Frontend: componentes shadcn/ui deben importar desde `@radix-ui/react-*`

## Qué NO Hacer

### Sistema de Producción (Lexmark CPM)
- No convertir los filtros a otro lenguaje (deben ser bash para compatibilidad SUSE 12)
- No usar `bashisms` incompatibles con bash 4.x de SUSE 12
- No modificar las cabeceras `@PJL` sin conocimiento del protocolo PJL/Lexmark
- No cambiar el nombre de la cola LPD de Windows (`LexmarkBBVA`) sin actualizar `configuration.json`
- **No usar doble `setlocal`** en los `.bat` (rompe la delayed expansion)
- **No ejecutar `del "%VAR%"` sin validar** que la variable esté definida y el archivo exista (riesgo de borrado con comodín en el directorio actual)
- No enviar `%COMPUTERNAME%` como hostname en Sede Central — debe usarse el `VMHOST` derivado de la MAC (ver "Lógica de Nomenclatura")
- No cambiar la validación de longitud de hostname en `filtro_winhostuser` (11-12 → 11) sin verificar que las colas CUPS siguen siendo de 11 chars

### Sistema de Contingencia (AlwaysPrint)
- No usar `Console.WriteLine` en lugar de `AlwaysPrintLogger`
- No hardcodear rutas, nombres de pipe, o configuración (usar `AppConfiguration`)
- No cambiar `ProductCode` en `Product.wxs` (debe ser fijo para actualizaciones)
- No modificar la arquitectura Service↔Tray sin entender el flujo completo
- No eliminar tenant isolation en queries del backend (filtrado por `organization_id`)
- No usar `any` en TypeScript (usar tipos específicos)
- **No importar Base desde `app.db`** - siempre usar `app.core.database`
- No crear archivos en `src/lib/` sin verificar `.gitignore` (puede ser ignorado)
- No modificar el sistema de acciones sin leer `ACTION_CONFIG_IMPLEMENTATION.md`
- **No eliminar verificación de firma ECDSA** — fail-closed es obligatorio
- **No escribir en HKLM desde el Tray** — siempre delegar al Service via Named Pipe
- **No cargar backups completos en memoria** durante restore — usar streaming
- **No usar SigV2** para presigned URLs de S3 — solo SigV4

### Ambos Sistemas
- No asumir que AlwaysPrint reemplaza Lexmark CPM (son complementarios)
- No modificar un sistema sin verificar impacto en el otro
- No cambiar estructura de carpetas sin actualizar toda la documentación


## Estructura del Repositorio

```
.
├── AlwaysPrintProject/            # Sistema de contingencia (complementario)
│   ├── Cloud/                     # Plataforma SaaS
│   │   ├── backend/              # FastAPI (Python 3.12)
│   │   ├── frontend/             # Next.js 15 (TypeScript)
│   │   ├── ARCHITECTURE.md       # Arquitectura detallada
│   │   └── README.md
│   ├── Client/                    # Software Windows
│   │   ├── AlwaysPrint.Shared/   # Biblioteca compartida
│   │   ├── AlwaysPrintService/   # Servicio Windows
│   │   ├── AlwaysPrintTray/      # Aplicación de bandeja
│   │   ├── AlwaysPrint.sln       # Solución Visual Studio
│   │   └── README.md
│   └── README.md
│
├── Linux Server/                  # Servidor CUPS (BBVA, siempre operativo)
│   └── root/bin/
│       ├── filtro_nacarpr_pro.cpm      # Filtro producción CPM
│       ├── filtro_contingencia_pro     # Filtro contingencia LPD
│       ├── filtro_winhostuser          # Receptor de mapping
│       └── Lexmark.Cups.ppd.gz         # PPD base
│
├── Workstations/                  # Componentes Windows (CPM + contingencia)
│   ├── Client Installer/          # Instalador Lexmark CPM (producción)
│   ├── SetupLPD/                  # Scripts LPD/LPR
│   ├── Startup/                   # Scripts de inicio
│   └── LpdServiceMonitor/         # Monitor de servicio LPD
│
├── AGENTS.md                      # Este archivo
└── README.md                      # Documentación principal
```

## Documentación del Repositorio

### Archivos en la Raíz
- **README.md** - Visión general del repositorio completo (ambos sistemas)
- **AGENTS.md** - Este archivo (reglas para agentes IA)

### Sistema de Producción (Lexmark CPM)
- Ver sección "Manual del Sistema de Producción" en `README.md`
- **Componente principal**: Lexmark CPM Client en Windows
- **Infraestructura**: Servidor Linux SUSE 12 (BBVA, siempre operativo)

### Sistema de Contingencia (AlwaysPrint)
- `AlwaysPrintProject/README.md` - Visión general del proyecto
- `AlwaysPrintProject/Cloud/README.md` - Cloud Manager (instalación, configuración)
- `AlwaysPrintProject/Cloud/ARCHITECTURE.md` - Arquitectura detallada multi-tenant
- `AlwaysPrintProject/Cloud/TROUBLESHOOTING_BACKEND.md` - Guía de diagnóstico de problemas
- `AlwaysPrintProject/Client/README.md` - Cliente Windows (compilación, instalación)
- `AlwaysPrintProject/Client/AlwaysPrint.Shared/README.md` - Biblioteca compartida
- `AlwaysPrintProject/Client/AlwaysPrintService/README.md` - Servicio Windows
- `AlwaysPrintProject/Client/AlwaysPrintTray/README.md` - Aplicación de bandeja
- `AlwaysPrintProject/ACTION_CONFIG_IMPLEMENTATION.md` - Sistema de configuración de acciones (completo)
- `AlwaysPrintProject/IMPLEMENTATION_STATUS.md` - Estado de implementación y métricas
- `AlwaysPrintProject/QUICK_DEPLOY.md` - Guía de despliegue rápido

## Relación Entre Sistemas

**CRÍTICO**: 
- **Sistema de Producción** = Lexmark CPM Client (Windows) + Servidor Linux (BBVA)
- **Sistema de Contingencia** = AlwaysPrint (Windows) que hace bypass de CPM/Linux
- AlwaysPrint NO reemplaza el sistema de producción
- El servidor Linux está siempre operativo (responsabilidad BBVA), pero no se usa en contingencia

**Flujo de Operación**:
1. **Normal (Producción)**: Lexmark CPM Client maneja toda la impresión → Servidor Linux → Impresora
2. **Contingencia**: Si CPM falla, AlwaysPrint redirige tráfico → Directo a IP impresora:puerto estándar (bypass completo)
3. **Monitoreo**: AlwaysPrint siempre reporta estado a Cloud Manager
4. **Coexistencia**: Ambos sistemas instalados simultáneamente en workstations

**Arquitectura en Workstation**:
```
┌─────────────────────────────────────────────────────────────┐
│                    WORKSTATION WINDOWS                       │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │  SISTEMA DE PRODUCCIÓN (Lexmark CPM)               │    │
│  │  • Cola LexmarkBBVA                                │    │
│  │  • Lexmark CPM Client ← COMPONENTE PRINCIPAL       │    │
│  │  • LPD Service (puerto 515)                        │    │
│  └────────────────┬───────────────────────────────────┘    │
│                   │ Tráfico CPM                             │
│                   ↓                                          │
│            Servidor Linux SUSE 12 (BBVA)                    │
│            Siempre operativo                                │
│                   ↓                                          │
│            Impresora física                                 │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │  SISTEMA DE CONTINGENCIA (AlwaysPrint)             │    │
│  │  • AlwaysPrintService (detecta falla CPM)          │    │
│  │  • AlwaysPrintTray (interfaz + cloud)              │    │
│  │  • Redirige tráfico → IP:puerto estándar           │    │
│  │    (bypass CPM/Linux)                              │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## Tecnologías por Sistema

### Sistema de Producción (Lexmark CPM)
- **Servidor**: Linux SUSE 12, Bash 4.x, CUPS, LPD
- **Cliente**: Windows 10/11, Lexmark CPM Client, LPD Service
- **Protocolos**: LPD (puerto 515), PJL

### Sistema de Contingencia (AlwaysPrint)
- **Client**: C# 9, .NET Framework 4.8, WPF, Named Pipes
- **Backend**: Python 3.12, FastAPI, SQLAlchemy, PostgreSQL
- **Frontend**: TypeScript, Next.js 15, React 18, Tailwind CSS
- **Protocolos**: HTTPS/TLS 1.3, REST API, WebSocket (opcional)

## Arquitectura Multi-Worker del Backend (WebSocket Scaling)

**Estado**: ✅ Implementado (Junio 2026)

### Configuración de Despliegue

El backend se ejecuta con **2 uvicorn workers** coordinados vía **Redis pub/sub**:

| Variable | Valor | Propósito |
|----------|-------|-----------|
| `UVICORN_WORKERS` | `2` | Distribuye carga de WS entre 2 event loops |
| `REDIS_URL` | `redis://redis:6379/0` | Coordinación inter-worker (pub/sub + WorkerRegistry) |

Estos valores se fuerzan automáticamente en cada deploy vía `deploy.sh` (no dependen de configuración manual).

### Componentes

| Archivo | Rol |
|---------|-----|
| `app/services/websocket_manager.py` | Factory condicional: si REDIS_URL → RedisConnectionManager, else → ConnectionManager |
| `app/services/redis_connection_manager.py` | Gestión WS multi-worker con pub/sub, WorkerRegistry, fallback graceful |
| `app/services/worker_registry.py` | Registra qué workstations están en qué worker (Redis SETs con TTL) |
| `app/core/logging.py` | Structured logging con structlog (worker_id binding) |
| `app/api/v1/endpoints/health.py` | `/health/detailed` — métricas por worker individual |

### Arquitectura de Canales Redis

```
worker:{worker_id}     → Mensajes dirigidos a WS del worker + cmd_response
org:{organization_id}  → Broadcasts a operadores de la org (lazy subscribe)
global:broadcast       → Broadcasts globales a todos los workers
```

### Reglas Críticas de Rendimiento

1. **`broadcast_to_organization` solo envía a operadores**, NO a workstations. Las WS no necesitan recibir broadcasts de telemetría/status — esos son para el frontend.
2. **El listener Redis usa `get_message(timeout=1.0)` blocking**, no polling con sleep. Polling con `timeout=0.001` + sleep saturaba el event loop.
3. **Registros de WS en WorkerRegistry se batchean** (flush cada 1s), no 1 asyncio.Task por connect.
4. **Locks (`async with self._lock`) NO se usan en hot paths** — dict reads/writes son atómicas en asyncio (single-threaded per worker). Solo proteger operaciones multi-step con await intermedio.
5. **`is_workstation_online` retorna True si Redis está activo** — deja que `send_to_workstation` resuelva cross-worker routing.

### Capacidad Probada (Load Test)

| Instancia | Workers | Redis | WS Máximas | Latencia P95 |
|-----------|---------|-------|-----------|--------------|
| t3.small (2 GB) | 2 | Sí | ~3,475 | <200ms |
| t3.small (2 GB) | 1 | No | ~2,000 | Event loop starvation a 2K |
| c7i-flex.large (4 GB) | 2 | Sí | ~6,000+ (estimado) | <200ms |

### Qué NO Hacer

- **No enviar broadcasts a workstations** desde `broadcast_to_organization` — causa O(n²) con N workstations
- **No crear un asyncio.Task por cada `connect_workstation`** — batchear operaciones Redis
- **No usar polling agresivo en el listener** (`timeout=0.001` + sleep) — bloquea registros
- **No poner locks en lectura de dicts** del hot path (ping loop, broadcast, deliver)
- **No remover `RegistrationCache`** de los lint guards — fue eliminado por causar pool exhaustion
- **No cambiar REDIS_URL o UVICORN_WORKERS manualmente** — deploy.sh los restaura

## Comandos Útiles

### Sistema de Producción (Lexmark CPM)
```bash
# Verificar colas CUPS
lpstat -v
lpstat -p -d

# Ver logs
tail -f /var/lib/lexmark/lexmark.log
tail -f /var/lib/lexmark/lexmark_winhostuser.log

# Reinstalar filtro en cola
lpadmin -p w012301p01 -i /root/bin/filtro_nacarpr

# Verificar mapping
cat /var/lib/lexmark/win_hostname_user.txt
```

### Sistema de Contingencia (AlwaysPrint)
```powershell
# Compilar Client
cd AlwaysPrintProject/Client
.\build.ps1

# Ver logs del servicio
Get-EventLog -LogName Application -Source AlwaysPrintService -Newest 50

# Verificar servicios
Get-Service AlwaysPrintService
Get-Service LPDSVC
```

```bash
# Backend (Cloud Manager)
cd AlwaysPrintProject/Cloud/backend
conda activate alwaysprint
uvicorn app.main:app --reload

# Frontend (Cloud Manager)
cd AlwaysPrintProject/Cloud/frontend
npm run dev

# Diagnóstico Backend via SSM (sin SSH)
aws ssm send-command \
  --instance-ids "i-XXXXXXXXX" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["docker logs alwaysprint-backend-1 --tail 100"]'
```

## Sistema de Configuración de Acciones Administrativas

**Estado**: ✅ Implementado y en producción (Mayo 2026)

### Descripción

Sistema que permite a los administradores definir y ejecutar acciones administrativas en workstations Windows de forma centralizada desde la Cloud. Las configuraciones se definen en archivos `.alwaysconfig` (JSON) y se descargan automáticamente a las workstations.

### Componentes Clave

#### Cliente Windows (C#)
- **ActionEngine**: Motor que parsea y ejecuta archivos `.alwaysconfig`
- **AdminActions**: 9 funciones administrativas (PropagatePermissions, GetLoggedInUsers, DeleteFolderContents, StopService, StartService, KillProcessesByName, Conditional, StopTray, StartTray)
- **ConfigManager**: Descarga configuraciones desde Cloud y notifica al Service via Named Pipe
- **ReloadActionConfigTask**: Tarea que recarga configuración cuando hay cambios

#### Backend (Python/FastAPI)
- **Modelo**: `ActionConfig` con tenant isolation (`organization_id`)
- **API**: 8 endpoints REST (6 admin + 2 workstation)
- **Migración**: `20260515151758_add_action_configs_table.py`
- **Almacenamiento**: PostgreSQL con hash SHA256 para integridad

#### Frontend (Next.js/TypeScript)
- **UI**: Página de gestión en `/dashboard/admin/action-configs`
- **Funciones**: Upload, activar/desactivar, ver detalles, eliminar
- **Validación**: JSON en tiempo real con feedback visual

### Flujo de Operación

1. **Admin sube config** → Frontend valida JSON → Backend guarda con hash
2. **Workstation conecta** → Tray verifica hash local vs Cloud
3. **Si difiere** → Descarga nueva config → Guarda en `active.alwaysconfig`
4. **Notifica Service** → Named Pipe mensaje `ActionConfigChanged`
5. **Service recarga** → ActionEngine ejecuta trigger `OnConfigChange`
6. **Acciones se ejecutan** → Logs en Event Viewer

### Eventos Soportados (Triggers)

- `OnServiceStart` - Al iniciar el servicio
- `OnTrayLaunched` - Después de inicializar Tray
- `OnConfigChange` - Al recibir nueva configuración
- `OnUserLogon` - Al iniciar sesión usuario (definido, no implementado)
- `OnUserLogoff` - Al cerrar sesión usuario (definido, no implementado)

### Acciones Disponibles

1. **PropagatePermissions** - Propagar permisos de carpeta recursivamente
2. **GetLoggedInUsers** - Obtener usuarios con sesión activa (excluye consola)
3. **DeleteFolderContents** - Eliminar contenido de carpetas con manejo de errores
4. **StopService** / **StartService** - Gestionar servicios Windows
5. **KillProcessesByName** - Matar procesos por nombre, filtrado por usuario
6. **Conditional** - Ejecutar acciones condicionalmente (if/then)
7. **StopTray** / **StartTray** - Gestionar aplicación Tray

### Características Avanzadas

- **Variables**: Almacenar resultados de acciones (`store_result_in`)
- **Templates**: Reemplazo de variables `{{variable}}` en parámetros
- **Condicionales**: Evaluación de condiciones (equals, not_equals, contains, etc.)
- **Iteración**: Iterar sobre listas de usuarios (`iterate_users`)
- **Tenant Isolation**: Todas las queries filtran por `organization_id`
- **Hash Verification**: SHA256 (8 chars) para integridad

### Ejemplo de Configuración

```json
{
  "version": "1.0",
  "name": "CPM_Compliant",
  "triggers": [
    {
      "event": "OnTrayLaunched",
      "actions": [
        {
          "type": "PropagatePermissions",
          "parameters": {
            "path": "C:\\ProgramData\\LPMC\\",
            "recursive": true
          }
        },
        {
          "type": "GetLoggedInUsers",
          "parameters": {
            "exclude_active_console_user": true
          },
          "store_result_in": "inactive_users"
        },
        {
          "type": "Conditional",
          "parameters": {
            "condition": {
              "variable": "inactive_users",
              "operator": "not_empty"
            },
            "actions": [
              {
                "type": "StopService",
                "parameters": {
                  "service_name": "LPDSVC"
                }
              },
              {
                "type": "DeleteFolderContents",
                "parameters": {
                  "path_template": "C:\\Users\\{{username}}\\AppData\\Local\\Lexmark\\",
                  "iterate_users": "inactive_users"
                }
              },
              {
                "type": "StartService",
                "parameters": {
                  "service_name": "LPDSVC"
                }
              }
            ]
          }
        }
      ]
    }
  ]
}
```

### Seguridad

- ✅ Tenant isolation en todas las queries
- ✅ Autenticación JWT para endpoints admin
- ✅ Workstation ID para endpoints de workstation
- ✅ Validación de JSON antes de guardar
- ✅ Hash SHA256 para detectar modificaciones
- ✅ Una configuración activa por organización
- ✅ Service ejecuta con permisos LocalSystem

### Troubleshooting

**Problema**: Configuración no se descarga en workstation
- Verificar logs en Event Viewer: `AlwaysPrintTray` → buscar "ConfigManager"
- Verificar que workstation está registrada en Cloud
- Verificar conectividad: `curl https://alwaysprint.apps.iol.pe/api/v1/health`

**Problema**: Acciones no se ejecutan
- Verificar logs en Event Viewer: `AlwaysPrintService` → buscar "ActionEngine"
- Verificar que archivo `active.alwaysconfig` existe en directorio del servicio
- Verificar sintaxis JSON del archivo de configuración

**Problema**: Backend retorna Bad Gateway (502)
- Ver `AlwaysPrintProject/Cloud/TROUBLESHOOTING_BACKEND.md`
- Verificar logs: `docker logs alwaysprint-backend-1 --tail 100`
- Verificar migraciones: `docker exec alwaysprint-backend-1 alembic current`

### Documentación Completa

Ver `AlwaysPrintProject/ACTION_CONFIG_IMPLEMENTATION.md` para:
- Documentación técnica detallada
- Referencia completa de acciones y parámetros
- Ejemplos de configuraciones
- Guía de troubleshooting
- Métricas y monitoreo

## Sistema de Firma Digital y Rotación de Certificados

**Estado**: ✅ Implementado (Agosto 2026)

### Descripción

Sistema de verificación de integridad y autenticidad para archivos `.alwaysconfig` firmados digitalmente con ECDSA P-256. Los archivos se firman en el backend y se verifican en el cliente Windows antes de ejecutar acciones.

### Componentes

| Componente | Responsabilidad |
|---|---|
| `SignatureVerifier.cs` | Verificación ECDSA, descarga de certificados, gestión de CertVersion en registry |
| `ConfigManager.cs` | Orquesta descarga de config firmada + verificación + re-sync tras rotación |
| `PushMessageHandler.cs` | Recibe push `cert_rotated` desde Cloud vía WebSocket y ejecuta rotación |
| `MessageDispatcher.cs` (Service) | Despacha `UpdateCertVersion` del Tray al Service para escritura en HKLM |
| `organizations.py` (Backend) | Endpoint de rotación de certificado con propagación de `ecdsa_cert_hash` |
| `state_map_service.py` (Backend) | Persiste `ecdsa_cert_hash` en el state map para distribución a workstations |

### Flujo de Verificación

```
1. Tray descarga config firmada (JSON envolvente: {config, hash, signature, cert_version})
2. SignatureVerifier.VerifyConfig():
   a. Parsea JSON envolvente
   b. Verifica hash SHA256 del config (integridad)
   c. Carga certificado .cer local
   d. Convierte firma DER → IEEE P1363 (compatibilidad Python↔.NET)
   e. Verifica firma ECDSA sobre hashBytes
3. Si válido → ActionEngine ejecuta config
4. Si inválido → rechaza (fail-closed)
```

### Rotación de Certificados

```
1. Admin rota certificado en Cloud → Backend genera nuevo keypair ECDSA P-256
2. Backend publica push `cert_rotated` con nueva URL del .cer y cert_version
3. Tray recibe push → descarga nuevo certificado → guarda en disco local
4. Tray envía `UpdateCertVersion` al Service via Named Pipe (Tray no tiene permisos HKLM)
5. Service escribe CertVersion en HKLM\SOFTWARE\Robles.AI\AlwaysPrint
6. Tray re-sincroniza config inmediatamente (no espera al próximo ciclo periódico)
```

### Reglas Críticas

- **Fail-closed**: Si la firma no verifica → rechazar config, NUNCA ejecutar sin verificación
- **Delegación de privilegios**: Tray (usuario) NO puede escribir en HKLM → delega al Service (LocalSystem)
- **Re-sync post-rotación**: Después de descargar cert nuevo, re-intentar config que pudo haber fallado por cert viejo
- **Conversión DER→P1363**: Python cryptography firma en DER; .NET Framework 4.8 espera IEEE P1363

### Qué NO Hacer

- **No eliminar la verificación de firma** para resolver problemas de compatibilidad (ver regla impact-analysis)
- **No escribir CertVersion desde el Tray** directamente (no tiene permisos HKLM)
- **No ignorar cert_version mismatch** — siempre descargar el certificado actualizado
- **No cachear certificados en memoria** sin verificar versión contra registry

## Sistema de Backup/Restore (Migración entre Cuentas)

**Estado**: ✅ Implementado (Agosto 2026)

### Descripción

Pipeline de backup y restore para migración completa entre instancias AWS (dev↔prod o cuentas diferentes). Soporta backup selectivo de tablas, streaming de restore para prevenir OOM, y validación de ZIP en frontend.

### Características

- ✅ Backup completo o selectivo (tablas opcionales: audit_logs, knowledge_articles)
- ✅ Streaming de extracción en restore (previene OOM-kill en backups grandes)
- ✅ Validación de ZIP en frontend antes de enviar al backend
- ✅ Manejo de circular FK (disable/enable constraints durante restore)
- ✅ SigV4 + endpoint regional explícito para presigned URLs
- ✅ Fail-fast en memoria insuficiente (verifica disponibilidad antes de extraer)
- ✅ CORS habilitado en bucket S3 para presigned URL uploads directos
- ✅ Reconexión forzada de workstations post-restore (evita WS fantasma en dashboard)
- ✅ Rotación automática de certificados ECDSA post-restore

### Archivos Clave

| Archivo | Rol |
|---|---|
| `app/services/backup_service.py` | Genera ZIP con dump de BD + metadata, tablas selectivas |
| `app/services/restore_service.py` | Restore con streaming, prevención OOM, force-disconnect post-restore |
| `app/api/v1/endpoints/backup.py` | API de backup (selección de tablas opcionales) |
| `app/api/v1/endpoints/restore.py` | API de restore con validación |
| `app/services/websocket_manager.py` | `force_disconnect_all()` — cierra WS tras restore |
| `scripts/force_disconnect_org.py` | Script standalone para forzar reconexión de una org |
| `src/lib/backupZipValidation.ts` | Validación client-side del ZIP antes de upload |
| `src/components/admin/BackupSection.tsx` | UI con selección de tablas y progreso |

### Qué NO Hacer

- **No cargar backup completo en memoria** durante restore — usar streaming
- **No ignorar circular FK** — deshabilitarlas antes de INSERT, rehabilitar después
- **No usar SigV2** para presigned URLs — solo SigV4 es compatible con IAM policies actuales
- **No usar endpoint global S3** (`s3.amazonaws.com`) — usar regional (`s3.<region>.amazonaws.com`) para que la firma coincida
- **No omitir force-disconnect post-restore** — las WS con conexión abierta quedarían con IDs huérfanos

---

**Robles.AI**  
Email: antonio@robles.ai  
Teléfono: +1 408 590 0153  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados  
Producto de la familia de automatización Robles.AI  
Prohibida la utilización sin autorización de Inversiones On Line SAC
