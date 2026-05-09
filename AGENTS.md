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

### Sistema de Contingencia (AlwaysPrint - Python/TypeScript)
- Backend: usar structured logging con timestamps
- Backend: todas las queries deben filtrar por `organization_id` (tenant isolation)
- Backend: usar Pydantic schemas para validación
- Frontend: usar TypeScript estricto (no `any`)
- Frontend: componentes reutilizables en `components/ui/`

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
- `AlwaysPrintProject/Client/README.md` - Cliente Windows (compilación, instalación)
- `AlwaysPrintProject/Client/AlwaysPrint.Shared/README.md` - Biblioteca compartida
- `AlwaysPrintProject/Client/AlwaysPrintService/README.md` - Servicio Windows
- `AlwaysPrintProject/Client/AlwaysPrintTray/README.md` - Aplicación de bandeja

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
```


---

**Robles.AI**  
Email: antonio@robles.ai  
Teléfono: +1 408 590 0153  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados  
Producto de la familia de automatización Robles.AI  
Prohibida la utilización sin autorización de Inversiones On Line SAC
