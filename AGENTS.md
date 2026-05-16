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
| `AlwaysPrintProject/Client/AlwaysPrintTray/Cloud/ConfigManager.cs` | Gestión de descarga de configs |
| `AlwaysPrintProject/Client/CPM_Compliant.alwaysconfig` | Ejemplo de configuración |
| `AlwaysPrintProject/Cloud/backend/app/models/action_config.py` | Modelo de BD |
| `AlwaysPrintProject/Cloud/backend/app/api/v1/endpoints/action_config.py` | API REST (8 endpoints) |
| `AlwaysPrintProject/Cloud/frontend/src/app/dashboard/admin/action-configs/page.tsx` | UI de gestión |
| `AlwaysPrintProject/ACTION_CONFIG_IMPLEMENTATION.md` | Documentación técnica completa |

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

Un `PUESTO` tiene el formato `w0###0SpXX` (10 chars) donde:
- posiciones 2-4: código de agencia
- posición 6: identificador servidor Linux
- posiciones 8-9: número de puesto (XX)

El host Windows correspondiente sigue el mismo patrón con prefijo `w10` o `w11`.

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

### Sistema de Contingencia (AlwaysPrint - C#)
- Usar `AlwaysPrintLogger` para todos los logs (no `Console.WriteLine`)
- Cada log debe tener un Event ID único (ver `AlwaysPrintLogger.cs`)
- Usar `try-catch` con logging de excepciones
- Validar configuración antes de usar (`AppConfiguration.Validate()`)
- Named Pipe: usar `PipeConstants.PIPE_NAME` (no hardcodear)
- Mensajes IPC: usar clases de `Payloads.cs` (no strings crudos)
- **Configuración de Acciones**: Usar `ActionEngine` para ejecutar acciones, no implementar lógica directamente
- **Imports**: Siempre usar `from app.core.database import Base` (no `app.db.base_class`)

### Sistema de Contingencia (AlwaysPrint - Python/TypeScript)
- Backend: usar structured logging con timestamps
- Backend: todas las queries deben filtrar por `organization_id` (tenant isolation)
- Backend: usar Pydantic schemas para validación
- Backend: **CRÍTICO** - Importar Base desde `app.core.database`, no desde `app.db`
- Frontend: usar TypeScript estricto (no `any`)
- Frontend: componentes reutilizables en `components/ui/`
- Frontend: componentes shadcn/ui deben importar desde `@radix-ui/react-*`

## Qué NO Hacer

### Sistema de Producción (Lexmark CPM)
- No convertir los filtros a otro lenguaje (deben ser bash para compatibilidad SUSE 12)
- No usar `bashisms` incompatibles con bash 4.x de SUSE 12
- No modificar las cabeceras `@PJL` sin conocimiento del protocolo PJL/Lexmark
- No cambiar el nombre de la cola LPD de Windows (`LexmarkBBVA`) sin actualizar `configuration.json`

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


---

**Robles.AI**  
Email: antonio@robles.ai  
Teléfono: +1 408 590 0153  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados  
Producto de la familia de automatización Robles.AI  
Prohibida la utilización sin autorización de Inversiones On Line SAC
