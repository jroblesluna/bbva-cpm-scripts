# Análisis Completo del Proyecto — Sistemas de Impresión Corporativa BBVA

**Fecha**: Mayo 2026  
**Versión del documento**: 1.0  
**Propósito**: Documento base para generar presentaciones, documentación técnica y comercial.

---

## 1. Resumen Ejecutivo

### Problema
BBVA utiliza Lexmark Cloud Print Manager (CPM) como sistema de impresión corporativa. Cuando CPM falla, las workstations quedan sin capacidad de impresión hasta que se restaure el servicio manualmente.

### Solución
**AlwaysPrint** es un sistema de contingencia que coexiste con Lexmark CPM en las workstations Windows. Detecta automáticamente fallas de CPM y redirige el tráfico de impresión directamente a las impresoras físicas (bypass completo), garantizando continuidad operativa.

### Componentes del Proyecto

| Sistema | Rol | Estado |
|---------|-----|--------|
| Lexmark CPM (Producción) | Impresión corporativa principal | ✅ Producción activa |
| AlwaysPrint Client (Contingencia) | Detección de fallas + redirección | ⏳ ~85% completo |
| AlwaysPrint Cloud Manager | Gestión centralizada SaaS | ✅ Funcional |

---

## 2. Usuarios y Roles del Sistema

### 2.1 Usuario Final (Empleado BBVA)
- **Interacción**: Imprime normalmente desde cualquier aplicación Windows
- **Experiencia en producción**: Transparente, no nota el sistema
- **Experiencia en contingencia**: Recibe notificación balloon tip de que se activó contingencia
- **Interfaz**: Icono en bandeja del sistema (AlwaysPrintTray) con menú contextual
  - About (versión, estado)
  - Configuration (ver configuración activa)
  - My Printers (impresoras disponibles)
  - Check Updates (verificar actualizaciones)

### 2.2 Administrador de TI (Operador)
- **Interfaz**: Dashboard web (Cloud Manager)
- **Funciones**:
  - Monitorear estado de workstations en tiempo real
  - Ver qué estaciones están en contingencia
  - Enviar comandos remotos (restart service, restart tray, check update)
  - Forzar contingencia individual o masiva
  - Configurar checks de conectividad
  - Gestionar VLANs y agrupaciones
  - Ver telemetría y métricas de impresión
  - Descargar logs remotos de workstations
  - Análisis de logs con IA (LLM)
  - Enviar mensajes a workstations

### 2.3 Superadministrador (Multi-tenant)
- **Interfaz**: Dashboard web (sección Admin)
- **Funciones**:
  - CRUD de organizaciones (BBVA, Ripley, etc.)
  - Gestión de usuarios administradores
  - Autorización de IPs públicas
  - Gestión de configuraciones de acciones (.alwaysconfig)
  - Gestión de actualizaciones automáticas
  - Configuración de modelos LLM por organización

### 2.4 Workstation (Actor automatizado)
- **Interacción**: Comunicación automática con Cloud Manager
- **Funciones**:
  - Registro automático por IP pública
  - Heartbeat periódico (estado online/offline)
  - Reporte de telemetría (trabajos de impresión)
  - Descarga de configuración
  - Auto-actualización del cliente
  - Reporte de checks de conectividad

---

## 3. Arquitectura del Sistema

### 3.1 Diagrama de Arquitectura General

```
┌─────────────────────────────────────────────────────────────────────┐
│                    WORKSTATION WINDOWS (x N estaciones)              │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  PRODUCCIÓN: Lexmark CPM Client                              │   │
│  │  • Cola LexmarkBBVA (driver Lexmark Universal v2 XL)        │   │
│  │  • Puertos internos 9167, 9443                              │   │
│  │  • LPD Service (puerto 515)                                 │   │
│  │  • LpdServiceMonitor (watchdog)                             │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                              │                                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  CONTINGENCIA: AlwaysPrint                                   │   │
│  │  • AlwaysPrintService.exe (LocalSystem, sin Internet)       │   │
│  │  • AlwaysPrintTray.exe (sesión usuario, con Internet)       │   │
│  │  • Comunicación IPC: Named Pipe (\\.\pipe\AlwaysPrintService)│   │
│  └──────────────────────────┬──────────────────────────────────┘   │
└─────────────────────────────┼───────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
┌──────────────────┐ ┌───────────────┐ ┌──────────────────────────┐
│ Servidor Linux   │ │ Impresora     │ │ AWS Cloud (us-west-2)    │
│ SUSE 12 (BBVA)  │ │ Física        │ │                          │
│ • CUPS           │ │ (IP:puerto)   │ │ EC2 + RDS + ECR + S3    │
│ • Filtros custom │ │ Bypass directo│ │ • Backend FastAPI        │
│ • Tea4Cups (PDF) │ │ en contingencia│ │ • Frontend Next.js      │
│ • Puerto 515     │ │               │ │ • PostgreSQL 16          │
└──────────────────┘ └───────────────┘ │ • Redis                  │
                                        │ • Nginx + SSL            │
                                        └──────────────────────────┘
```

### 3.2 Diagrama de Flujo — Modo Producción (Normal)

```
Usuario imprime
    │
    ▼
Cola LexmarkBBVA (Windows)
    │
    ▼
Lexmark CPM Client (puertos 9167/9443)
    │
    ▼
Servidor Linux SUSE 12 (CUPS)
    │
    ├─► filtro_nacarpr_pro.cpm
    │     • Extrae puesto/usuario del mapfile
    │     • Construye cabecera PJL
    │     • Crea/actualiza cola CUPS dinámica
    │     • Envía a impresora vía LPD
    │
    └─► Tea4Cups (opcional)
          • Genera PDF del trabajo
          • Accesible vía web interna
```

### 3.3 Diagrama de Flujo — Modo Contingencia (Falla CPM)

```
AlwaysPrintService detecta falla CPM
    │
    ▼
Activa modo contingencia
    │
    ├─► Redirige tráfico de cola Windows → IP:puerto impresora
    │   (bypass completo de CPM y servidor Linux)
    │
    ├─► Notifica a AlwaysPrintTray vía Named Pipe
    │     • Tray muestra balloon tip al usuario
    │     • Tray reporta contingencia a Cloud Manager
    │
    └─► Cloud Manager registra evento
          • Dashboard muestra alerta
          • Operador puede intervenir remotamente
```

### 3.4 Diagrama de Comunicación Client ↔ Cloud

```
┌─────────────────────────────────────────────────────────────┐
│                    WORKSTATION                                │
│                                                              │
│  AlwaysPrintService (LocalSystem)                           │
│       │                                                      │
│       │ Named Pipe IPC (bidireccional)                      │
│       │ • TrayInitialized (handshake)                       │
│       │ • ReportTelemetry (Service→Tray)                    │
│       │ • UpdateConfiguration (Tray→Service)                │
│       │ • ActionConfigChanged (Service→Tray)                │
│       │ • InstallUpdate (Tray→Service)                      │
│       ▼                                                      │
│  AlwaysPrintTray (sesión usuario)                           │
│       │                                                      │
└───────┼──────────────────────────────────────────────────────┘
        │
        │ HTTPS/WSS (vía Proxy Corporativo)
        │ Auth: IP pública autorizada
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  CLOUD MANAGER (AWS)                                         │
│                                                              │
│  Nginx (SSL/TLS 1.3)                                        │
│       │                                                      │
│       ├─► REST API (/api/v1/*)                              │
│       │     • Registro de workstation                       │
│       │     • Heartbeat / telemetría                        │
│       │     • Descarga de configuración                     │
│       │     • Check de actualizaciones                      │
│       │                                                      │
│       ├─► WebSocket (/ws/workstation/{id})                  │
│       │     • Estado en tiempo real                         │
│       │     • Comandos remotos (push)                       │
│       │     • Configuración push                            │
│       │                                                      │
│       └─► WebSocket (/ws/operator/{token})                  │
│             • Dashboard tiempo real                          │
│             • Notificaciones de eventos                     │
└─────────────────────────────────────────────────────────────┘
```

### 3.5 Diagrama de Infraestructura AWS

```
┌─────────────────────────────────────────────────────────────────┐
│  AWS us-west-2                                                   │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  VPC                                                     │    │
│  │                                                          │    │
│  │  ┌── Subnet Pública ──────────────────────────────┐     │    │
│  │  │                                                 │     │    │
│  │  │  EC2 t3.micro (Amazon Linux 2023)              │     │    │
│  │  │  Elastic IP: 34.213.90.95                      │     │    │
│  │  │  Docker Compose:                               │     │    │
│  │  │    ├─ backend (FastAPI, uvicorn)               │     │    │
│  │  │    ├─ frontend (Next.js 15)                    │     │    │
│  │  │    └─ redis (redis:7-alpine)                   │     │    │
│  │  │  Nginx + Let's Encrypt SSL                     │     │    │
│  │  │                                                 │     │    │
│  │  └─────────────────────────────────────────────────┘     │    │
│  │                                                          │    │
│  │  ┌── Subnet Privada (DB) ─────────────────────────┐     │    │
│  │  │                                                 │     │    │
│  │  │  RDS PostgreSQL 16 (db.t3.micro)               │     │    │
│  │  │  20GB gp3, cifrado                             │     │    │
│  │  │  Solo accesible desde EC2 (Security Group)     │     │    │
│  │  │                                                 │     │    │
│  │  └─────────────────────────────────────────────────┘     │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  Servicios adicionales:                                          │
│  • ECR (2 repos: backend, frontend)                              │
│  • S3 (artefactos MSI del client)                                │
│  • SES (email transaccional)                                     │
│  • Secrets Manager (passwords, SSH keys, database_url)           │
│  • SSM (acceso al servidor, sin SSH)                             │
│                                                                   │
│  Entornos:                                                       │
│  • DEV: Account 040982755196 → alwaysprint.dev.iol.pe           │
│  • PROD: Account 425642439683 → alwaysprint.apps.iol.pe         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Stack Tecnológico Completo

### 4.1 Cliente Windows (AlwaysPrint)

| Categoría | Tecnología | Versión |
|-----------|-----------|---------|
| Lenguaje | C# | 9.0 |
| Framework | .NET Framework | 4.8 |
| UI | WPF + WinForms (NotifyIcon) | — |
| IPC | Named Pipes | — |
| Serialización | Newtonsoft.Json | — |
| Instalador | WiX Toolset | 4.0.5 |
| Build | MSBuild + dotnet CLI | — |
| Target OS | Windows 10/11 | — |

### 4.2 Backend (Cloud Manager)

| Categoría | Tecnología | Versión |
|-----------|-----------|---------|
| Lenguaje | Python | 3.12 |
| Framework | FastAPI | latest |
| ORM | SQLAlchemy | 2.x |
| Migraciones | Alembic | latest |
| BD | PostgreSQL | 16 |
| Cache | Redis | 7 |
| Auth | JWT (python-jose) + bcrypt | — |
| Email | AWS SES (boto3) | — |
| WebSocket | FastAPI WebSocket | — |
| Validación | Pydantic | 2.x |
| Rate Limiting | Custom middleware | — |
| Servidor | Uvicorn (1 worker) | — |

### 4.3 Frontend (Cloud Manager)

| Categoría | Tecnología | Versión |
|-----------|-----------|---------|
| Framework | Next.js (App Router) | 15 |
| Lenguaje | TypeScript | strict |
| UI Library | React | 18 |
| Estilos | Tailwind CSS | 3.x |
| Componentes | shadcn/ui + Radix UI | — |
| State | React Query (TanStack) | — |
| i18n | next-intl | — |
| Iconos | lucide-react | — |
| WebSocket | Cliente custom | — |
| Fechas | date-fns + zonas horarias | — |

### 4.4 Sistema de Producción (Linux)

| Categoría | Tecnología | Versión |
|-----------|-----------|---------|
| OS | SUSE Linux | 12 |
| Shell | Bash | 4.x |
| Impresión | CUPS | — |
| Protocolo | LPD (puerto 515) | — |
| PDF | Tea4Cups | — |
| Servicio | xinetd (cups-lpd) | — |

### 4.5 DevOps / Infraestructura

| Categoría | Tecnología | Detalle |
|-----------|-----------|---------|
| Cloud | AWS | us-west-2 |
| IaC | Terraform | Módulos: networking, ec2, rds, ecr, secrets |
| CI/CD | GitHub Actions | 6 workflows (build + deploy × entorno) |
| Contenedores | Docker + Docker Compose | Bridge network |
| Reverse Proxy | Nginx | + Let's Encrypt SSL |
| Acceso servidor | AWS SSM | Sin SSH (puerto 22 cerrado) |
| Artefactos | S3 + ECR | MSI en S3, imágenes Docker en ECR |
| Secretos | AWS Secrets Manager | db_password, secret_key, ssh_key |
| DNS | Hostinger | Zona apps.iol.pe |

---

## 5. Funcionalidades Detalladas

### 5.1 Cliente Windows — Funcionalidades

#### AlwaysPrintService (Servicio Windows)

| # | Funcionalidad | Descripción |
|---|--------------|-------------|
| 1 | Detección de falla CPM | Monitorea estado del servicio Lexmark CPM |
| 2 | Redirección de tráfico | Redirige cola de impresión a IP:puerto directo |
| 3 | Motor de acciones (ActionEngine) | Ejecuta acciones administrativas configurables |
| 4 | Gestión de sesión | Detecta logon/logoff, lanza Tray en sesión de usuario |
| 5 | Servidor Named Pipe | Comunicación bidireccional con Tray |
| 6 | Telemetría de impresión | Captura datos de trabajos completados |
| 7 | Máquina de estados | Starting → WaitingUser → TrayStarting → Running |
| 8 | Cola de tareas | Gestión de tareas pendientes (TaskQueueManager) |
| 9 | Recarga de configuración | Aplica cambios de .alwaysconfig en caliente |

#### AlwaysPrintTray (Aplicación de bandeja)

| # | Funcionalidad | Descripción |
|---|--------------|-------------|
| 1 | Icono de bandeja | NotifyIcon con menú contextual |
| 2 | Conexión WebSocket | Comunicación tiempo real con Cloud |
| 3 | Registro automático | Se registra en Cloud por IP pública |
| 4 | Sincronización de config | Descarga configuración global y específica |
| 5 | Telemetría | Envío periódico de métricas al Cloud |
| 6 | Checks de conectividad | HTTP, TCP, Ping, DNS configurables |
| 7 | Auto-actualización | Descarga MSI + solicita instalación al Service |
| 8 | Descarga de .alwaysconfig | Verifica hash, descarga si difiere |
| 9 | Notificaciones | Balloon tips al usuario |
| 10 | Gestión offline | Almacena datos cuando no hay conexión |
| 11 | Localización | Soporte multi-idioma (es/en) |

#### Acciones Administrativas Remotas

| # | Acción | Descripción |
|---|--------|-------------|
| 1 | PropagatePermissions | Propagar permisos de carpeta recursivamente |
| 2 | GetLoggedInUsers | Obtener usuarios con sesión activa |
| 3 | DeleteFolderContents | Eliminar contenido de carpetas |
| 4 | StopService / StartService | Gestionar servicios Windows |
| 5 | KillProcessesByName | Matar procesos por nombre |
| 6 | Conditional | Ejecución condicional (if/then/else) |
| 7 | StopTray / StartTray | Gestionar aplicación Tray |
| 8 | DeleteOrphanedFolders | Limpieza de carpetas huérfanas |
| 9 | CreateTcpPort / SetTcpPort | Crear/actualizar puertos TCP de impresora |
| 10 | AssignPortToQueue | Asignar puerto a cola de impresión |
| 11 | PausePrintQueue / UnpausePrintQueue | Pausar/reanudar cola |
| 12 | SetDefaultPrinter | Establecer impresora predeterminada |
| 13 | RunProcess | Ejecutar proceso externo |
| 14 | CheckPrintQueueExists | Verificar existencia de cola |
| 15 | ReadRegistryValue | Leer valor del registro Windows |
| 16 | ReadPrintQueuePort | Leer puerto de cola de impresión |
| 17 | ReadAppSetting / WriteAppSetting | Lectura/escritura de configuración |

### 5.2 Cloud Manager — Backend (API REST)

#### Endpoints por Módulo

| Módulo | Prefix | Endpoints principales |
|--------|--------|----------------------|
| Auth | `/api/v1/auth` | Login, refresh token, password reset |
| Setup | `/api/v1/setup` | Creación primer superadmin |
| Organizations | `/api/v1/organizations` | CRUD orgs, IPs públicas, auto-update config |
| Users | `/api/v1/users` | CRUD usuarios admin por organización |
| Workstations | `/api/v1/workstations` | Registro, listado, stats, comandos, delete, logs |
| VLANs | `/api/v1/vlans` | CRUD VLANs por organización |
| Config | `/api/v1/config` | Configuración global y por workstation |
| Messages | `/api/v1/messages` | Broadcast a workstations |
| Audit | `/api/v1/audit` | Logs de auditoría |
| Telemetry | (sub-router) | Historial y estadísticas por workstation/org |
| Connectivity | (sub-router) | Resultados de checks de conectividad |
| Action Config | (sub-router) | CRUD configuraciones .alwaysconfig |
| Devices | `/api/v1/devices` | CRUD impresoras/dispositivos |
| Updates | (sub-router) | Check y descarga de actualizaciones |
| Log Analysis | (sub-router) | Análisis de logs con LLM (Bedrock/OpenAI) |

#### Funcionalidades Transversales

| # | Funcionalidad | Descripción |
|---|--------------|-------------|
| 1 | Multi-tenancy | Aislamiento por `organization_id` en todas las queries |
| 2 | Auth JWT | Tokens con expiración, roles (ADMIN/OPERATOR/READONLY) |
| 3 | Auth por IP | Workstations autenticadas por IP pública autorizada |
| 4 | WebSocket | Tiempo real para workstations y operadores |
| 5 | Rate limiting | Por IP y por ruta |
| 6 | Security headers | HSTS, X-Frame-Options, CSP |
| 7 | Auditoría | Log de todas las acciones administrativas |
| 8 | Email (SES) | Password reset, notificaciones |
| 9 | Health check | Con métricas de pool de conexiones |
| 10 | Análisis con IA | Logs analizados por LLM (AWS Bedrock / OpenAI) |

### 5.3 Cloud Manager — Frontend (Dashboard Web)

#### Páginas y Funcionalidades

| Página | Ruta | Funcionalidades |
|--------|------|-----------------|
| Dashboard | `/dashboard` | Stats generales, IPs pendientes, distribución por VLAN/cuenta, polling 10s |
| Workstations | `/dashboard/workstations` | Lista cards/tabla, filtros, comandos remotos, contingencia forzada, logs |
| VLANs | `/dashboard/vlans` | CRUD VLANs, asignación de workstations |
| Dispositivos | `/dashboard/devices` | CRUD impresoras, asignación a VLANs |
| Configuración | `/dashboard/config` | Config global y por workstation |
| Mensajes | `/dashboard/messages` | Envío broadcast a workstations |
| Auditoría | `/dashboard/audit` | Logs de acciones con filtros |
| Telemetría | `/dashboard/telemetry` | Métricas de impresión, gráficos |
| Conectividad | `/dashboard/connectivity` | Resultados de checks por workstation |
| Organizaciones | `/dashboard/admin/organizations` | CRUD organizaciones (superadmin) |
| Usuarios | `/dashboard/admin/users` | Gestión de usuarios admin |
| IPs Pendientes | `/dashboard/admin/pending-ips` | Autorización de IPs nuevas |
| Action Configs | `/dashboard/admin/action-configs` | Upload/gestión de .alwaysconfig |
| Actualizaciones | `/dashboard/admin/updates` | Gestión de versiones MSI |
| Login | `/login` | Autenticación JWT |
| Setup | `/setup` | Configuración inicial |
| Forgot Password | `/forgot-password` | Solicitud de reset |
| Reset Password | `/reset-password` | Cambio de contraseña |

#### Características de UX

- Vista dual: tarjetas (mobile) y tabla (desktop)
- Polling automático cada 10 segundos
- WebSocket para actualizaciones en tiempo real
- Soporte multi-idioma (español/inglés) con next-intl
- Responsive design (mobile-first)
- Notificaciones toast
- Paginación server-side
- Filtros avanzados (búsqueda, estado, organización, VLAN)

---

## 6. Modelo de Datos

### 6.1 Diagrama Entidad-Relación (Simplificado)

```
┌──────────────────┐       ┌──────────────────┐
│  Organization    │       │     User         │
│──────────────────│       │──────────────────│
│ id (UUID)        │◄──┐   │ id (UUID)        │
│ name             │   │   │ email            │
│ timezone         │   │   │ role (ENUM)      │
│ language         │   ├───│ organization_id  │
│ forced_contingency│   │   │ password_hash    │
│ auto_update      │   │   └──────────────────┘
│ llm_model_id     │   │
└────────┬─────────┘   │   ┌──────────────────┐
         │             │   │    PublicIP       │
         │             │   │──────────────────│
         │             │   │ id (UUID)        │
         │             ├───│ organization_id  │
         │             │   │ ip_address       │
         │             │   │ is_authorized    │
         │             │   └──────────────────┘
         │             │
         │             │   ┌──────────────────┐
         │             │   │      VLAN        │
         │             │   │──────────────────│
         │             │   │ id (UUID)        │
         │             ├───│ organization_id  │
         │             │   │ name             │
         │             │   │ cidr             │
         │             │   └────────┬─────────┘
         │             │            │
         │             │   ┌────────▼─────────┐
         │             │   │   Workstation    │
         │             │   │──────────────────│
         │             │   │ id (UUID)        │
         │             ├───│ organization_id  │
         │             │   │ vlan_id          │
         │             │   │ ip_private       │
         │             │   │ hostname         │
         │             │   │ is_online        │
         │             │   │ contingency_active│
         │             │   │ tray_version     │
         │             │   └────────┬─────────┘
         │             │            │
         │             │   ┌────────▼─────────┐
         │             │   │    License       │
         │             │   │──────────────────│
         │             │   │ serial_number    │
         │             │   │ workstation_id   │
         │             │   │ is_active        │
         │             │   └──────────────────┘
         │             │
         │             │   ┌──────────────────┐
         │             │   │  ActionConfig    │
         │             │   │──────────────────│
         │             │   │ id (UUID)        │
         │             ├───│ organization_id  │
         │             │   │ scope (ENUM)     │
         │             │   │ vlan_id (opt)    │
         │             │   │ workstation_id   │
         │             │   │ config_json      │
         │             │   │ config_hash      │
         │             │   │ is_active        │
         │             │   └──────────────────┘
         │             │
         │             │   ┌──────────────────┐
         │             │   │    Device        │
         │             │   │──────────────────│
         │             ├───│ organization_id  │
         │                 │ name             │
         │                 │ ip_address       │
         │                 │ port             │
         │                 │ vlan_id          │
         │                 └──────────────────┘
         │
         │  Tablas adicionales:
         ├── GlobalConfig (1:1 con Organization)
         ├── WorkstationConfig (1:1 con Workstation)
         ├── Message (broadcast, target_type/target_id)
         ├── AuditLog (acciones de admin)
         ├── TelemetryLog (métricas de impresión)
         └── ConnectivityResult (checks de red)
```

### 6.2 Campos Clave por Entidad

| Entidad | Campos principales | Notas |
|---------|-------------------|-------|
| Organization | name, timezone, language, forced_contingency, auto_update_enabled, target_version, llm_model_id, openai_api_key | Tenant principal |
| PublicIP | ip_address, is_authorized, last_hostname, last_user | Auth de workstations |
| Workstation | ip_private (unique), hostname, is_online, contingency_active, forced_contingency, tray_version, cidr | Identificada por IP privada |
| License | serial_number (MD5 últimos 8 chars de ip_private), is_active | Licenciamiento |
| VLAN | name, cidr | Agrupación de workstations |
| User | email, role (ADMIN/OPERATOR/READONLY), password_hash | Admins del dashboard |
| ActionConfig | scope (org/vlan/workstation), config_json, config_hash (SHA256 8 chars), is_active | Herencia jerárquica |
| Device | name, ip_address, port, is_active | Impresoras físicas |
| GlobalConfig | JSON de configuración por organización | Heredada a workstations |

---

## 7. Seguridad

### 7.1 Autenticación y Autorización

| Mecanismo | Aplica a | Detalle |
|-----------|----------|---------|
| JWT Bearer | Administradores (Dashboard) | Token con user_id + organization_id, expiración configurable |
| IP pública autorizada | Workstations | Sin API key, auth basada en IP del request |
| Roles | Usuarios admin | ADMIN (todo), OPERATOR (su org), READONLY (solo lectura) |
| Password reset | Admins | Token 1h vía AWS SES |
| Tenant isolation | Todas las queries | Filtrado por organization_id obligatorio |

### 7.2 Seguridad de Red

| Capa | Mecanismo |
|------|-----------|
| Transporte | HTTPS/TLS 1.3 (Let's Encrypt) |
| WebSocket | WSS (sobre TLS) |
| BD | RDS en subnet privada, solo accesible desde EC2 |
| Servidor | Sin SSH (puerto 22 cerrado), acceso solo vía SSM |
| Firewall | Security Groups restrictivos |
| Secretos | AWS Secrets Manager (nunca en env vars) |
| Proxy | Soporte de proxy corporativo (detección automática) |

### 7.3 Seguridad de Aplicación

| Mecanismo | Detalle |
|-----------|---------|
| Rate limiting | Por IP y por ruta (middleware custom) |
| Security headers | HSTS, X-Frame-Options, X-Content-Type-Options, CSP |
| Passwords | bcrypt con salt |
| Validación | Pydantic schemas en backend, TypeScript strict en frontend |
| Hash integridad | SHA256 (8 chars) para archivos .alwaysconfig |
| Auditoría | Log de todas las acciones administrativas |
| Service Windows | Ejecuta como LocalSystem (máximos privilegios locales) |

---

## 8. CI/CD y Despliegue

### 8.1 Pipelines de GitHub Actions

```
Push a main
    │
    ├─► Cambios en Client/** → build-client-dev.yml
    │     1. Checkout
    │     2. Setup .NET SDK + .NET Framework 4.8
    │     3. Install WiX CLI v4
    │     4. Generate version (1.YY.MMDD.HHmm)
    │     5. Publish Service + Tray (.NET 4.8)
    │     6. Build MSI (WiX)
    │     7. Upload MSI a S3 (latest + versioned)
    │
    ├─► Cambios en backend/** → deploy-backend-dev.yml
    │     1. Checkout
    │     2. Configure AWS credentials
    │     3. Login ECR
    │     4. Docker build + push (tag: commit SHA 8 chars)
    │     5. SSM send-command → deploy.sh backend
    │     6. Wait for completion (polling 30 intentos × 10s)
    │
    └─► Cambios en frontend/** → deploy-frontend-dev.yml
          1. Checkout
          2. Configure AWS credentials
          3. Login ECR
          4. Copy logo assets (dev/prod)
          5. Docker build + push (con build args: API_URL, WS_URL, APP_NAME)
          6. SSM send-command → deploy.sh frontend
          7. Wait for completion
```

### 8.2 Versionado

| Componente | Formato | Ejemplo |
|-----------|---------|---------|
| Client MSI | `1.YY.MMDD.HHmm` | `1.26.0527.1430` |
| Backend | Git SHA (8 chars) | `a1b2c3d4` |
| Frontend | Git SHA (8 chars) | `a1b2c3d4` |
| Filtros Linux | `vYYYYMMDDhhmm` | `v202603070100` |

### 8.3 Entornos

| Entorno | URL | AWS Account | Trigger |
|---------|-----|-------------|---------|
| DEV | alwaysprint.dev.iol.pe | 040982755196 | Push a main |
| PROD | alwaysprint.apps.iol.pe | 425642439683 | Push a main (workflows separados) |

---

## 9. Diagramas Necesarios para Documentación

### 9.1 Diagramas para Presentación Ejecutiva

| # | Diagrama | Herramienta sugerida | Propósito |
|---|----------|---------------------|-----------|
| 1 | Arquitectura de alto nivel (2 sistemas) | Draw.io / Lucidchart | Mostrar coexistencia CPM + AlwaysPrint |
| 2 | Flujo normal vs contingencia | Draw.io | Comparar ambos modos |
| 3 | Mapa de valor (problema → solución → beneficio) | PowerPoint | Presentación comercial |

### 9.2 Diagramas Técnicos

| # | Diagrama | Tipo | Propósito |
|---|----------|------|-----------|
| 4 | Infraestructura AWS | Diagrama de red | VPC, subnets, EC2, RDS, servicios |
| 5 | Modelo de datos (ER) | ERD | Relaciones entre entidades |
| 6 | Secuencia: registro de workstation | Sequence diagram | Flujo de auth por IP |
| 7 | Secuencia: activación de contingencia | Sequence diagram | Detección de falla → redirección |
| 8 | Secuencia: descarga de .alwaysconfig | Sequence diagram | Hash check → descarga → ejecución |
| 9 | Componentes del cliente Windows | Component diagram | Service ↔ Tray ↔ Cloud |
| 10 | Pipeline CI/CD | Flowchart | Build → Push → Deploy |

### 9.3 Diagramas de UX/UI

| # | Diagrama | Propósito |
|---|----------|-----------|
| 11 | Wireframes del dashboard | Mostrar layout de páginas principales |
| 12 | Flujo de usuario admin | Navegación entre secciones |
| 13 | Flujo de usuario final | Experiencia en bandeja del sistema |
| 14 | Mapa de navegación del frontend | Sitemap del dashboard |

### 9.4 Diagramas de Operación

| # | Diagrama | Propósito |
|---|----------|-----------|
| 15 | Topología de red BBVA | Workstations → Proxy → Cloud |
| 16 | Flujo de impresión completo (producción) | Desde usuario hasta impresora física |
| 17 | Flujo de contingencia completo | Detección → bypass → restauración |
| 18 | Diagrama de estados del servicio | Starting → Running → Contingency |

---

## 10. Software Necesario para Desarrollo

### 10.1 Desarrollo del Cliente Windows

| Software | Propósito | Versión |
|----------|-----------|---------|
| Visual Studio 2022 | IDE principal | Community+ |
| .NET Framework 4.8 Developer Pack | Compilación | 4.8 |
| .NET SDK | dotnet CLI | 8.x |
| WiX Toolset | Generación de MSI | 4.0.5 |
| Git | Control de versiones | latest |

### 10.2 Desarrollo del Backend

| Software | Propósito | Versión |
|----------|-----------|---------|
| Python | Runtime | 3.12 |
| Conda/Miniconda | Gestión de entornos | latest |
| PostgreSQL | BD local (opcional, puede usar SQLite) | 16 |
| Redis | Cache local | 7 |
| Docker Desktop | Contenedores locales | latest |
| Git | Control de versiones | latest |

### 10.3 Desarrollo del Frontend

| Software | Propósito | Versión |
|----------|-----------|---------|
| Node.js | Runtime | 20+ LTS |
| npm | Gestión de paquetes | 10+ |
| Git | Control de versiones | latest |

### 10.4 Infraestructura y DevOps

| Software | Propósito | Versión |
|----------|-----------|---------|
| AWS CLI | Gestión de recursos AWS | v2 |
| Terraform | Infrastructure as Code | latest |
| Docker | Build de imágenes | latest |
| GitHub CLI (gh) | Gestión de PRs | latest |

### 10.5 Herramientas de Documentación

| Software | Propósito |
|----------|-----------|
| Draw.io / Lucidchart | Diagramas de arquitectura |
| Figma / Excalidraw | Wireframes y mockups |
| PowerPoint / Google Slides | Presentaciones ejecutivas |
| Mermaid (en Markdown) | Diagramas embebidos en docs |

---

## 11. Métricas y KPIs del Proyecto

### 11.1 Métricas Técnicas

| Métrica | Valor actual |
|---------|-------------|
| Endpoints REST | ~50+ |
| Modelos de BD | 12+ tablas |
| Páginas frontend | 18+ rutas |
| Acciones administrativas | 17+ tipos |
| Workflows CI/CD | 6 |
| Entornos desplegados | 2 (DEV + PROD) |
| Servicios AWS | 7 (EC2, RDS, ECR, S3, SES, Secrets Manager, SSM) |

### 11.2 KPIs de Negocio (a medir)

| KPI | Descripción | Meta |
|-----|-------------|------|
| Tiempo de detección | Segundos desde falla CPM hasta activación de contingencia | < 30s |
| Tiempo de recuperación | Segundos desde activación hasta primera impresión exitosa | < 60s |
| Disponibilidad | % de tiempo con capacidad de impresión (producción + contingencia) | 99.9% |
| Workstations monitoreadas | Número de estaciones gestionadas simultáneamente | 500+ |
| Latencia de telemetría | Tiempo entre evento y visualización en dashboard | < 5s |

---

## 12. Estado Actual y Pendientes

### 12.1 Implementado ✅

- [x] Sistema de producción CPM completo (filtros Linux, workstations)
- [x] Cliente Windows: Service + Tray + Shared library
- [x] Motor de acciones administrativas (ActionEngine) con 17+ acciones
- [x] Backend FastAPI completo con todos los endpoints
- [x] Frontend Next.js con dashboard completo
- [x] WebSocket en tiempo real
- [x] Autenticación JWT + autorización por IP
- [x] Multi-tenancy con aislamiento por organización
- [x] Sistema de configuración jerárquica (Org → VLAN → Workstation)
- [x] CI/CD completo (6 workflows)
- [x] Infraestructura AWS vía Terraform
- [x] Auto-actualización del cliente
- [x] Telemetría y checks de conectividad
- [x] Password reset vía AWS SES
- [x] Análisis de logs con LLM (Bedrock/OpenAI)
- [x] Gestión de dispositivos/impresoras
- [x] Soporte multi-idioma (es/en)

### 12.2 Pendiente ⏳

- [ ] Integración completa heartbeat Tray ↔ Cloud (parcial)
- [ ] Alertas automáticas (workstation offline > X minutos)
- [ ] SSO (SAML/OAuth) para login corporativo
- [ ] Reportes exportables (PDF/Excel)
- [ ] Pruebas de carga (stress testing)
- [ ] Documentación de usuario final

---

## 13. Documentos a Generar (Próximos Pasos)

Basándose en este análisis, los documentos a producir son:

### 13.1 Documentación Comercial

| # | Documento | Audiencia | Contenido |
|---|-----------|-----------|-----------|
| 1 | Presentación Ejecutiva (PPT) | C-Level, Gerencia TI | Problema, solución, beneficios, ROI |
| 2 | Brochure / One-pager | Decisores | Resumen visual de capacidades |
| 3 | Caso de uso BBVA | Stakeholders | Escenario real, métricas, resultados |

### 13.2 Documentación Técnica

| # | Documento | Audiencia | Contenido |
|---|-----------|-----------|-----------|
| 4 | Guía de Arquitectura | Arquitectos, DevOps | Diagramas detallados, decisiones técnicas |
| 5 | Manual de API | Desarrolladores | OpenAPI/Swagger exportado |
| 6 | Guía de Integración | Equipo cliente | Cómo integrar con infraestructura existente |
| 7 | Runbook de Operaciones | SRE/Ops | Procedimientos de mantenimiento, troubleshooting |

### 13.3 Documentación de Usuario

| # | Documento | Audiencia | Contenido |
|---|-----------|-----------|-----------|
| 8 | Manual de Administrador | Admin TI | Uso del dashboard, configuración |
| 9 | Guía de Usuario Final | Empleados | Qué hacer cuando aparece el icono de contingencia |
| 10 | FAQ | Todos | Preguntas frecuentes |

### 13.4 Documentación de Despliegue

| # | Documento | Audiencia | Contenido |
|---|-----------|-----------|-----------|
| 11 | Guía de Instalación Client | Soporte TI | Instalación MSI, GPO, configuración |
| 12 | Guía de Despliegue Cloud | DevOps | Terraform, Docker, CI/CD |
| 13 | Plan de Disaster Recovery | Ops | Procedimientos de recuperación |

---

## 14. Glosario

| Término | Definición |
|---------|-----------|
| CPM | Cloud Print Manager (Lexmark) — sistema de producción |
| AlwaysPrint | Sistema de contingencia desarrollado por Robles.AI |
| Contingencia | Modo activado cuando CPM falla, bypass directo a impresora |
| VLAN | Agrupación lógica de workstations por red |
| ActionConfig | Archivo .alwaysconfig con acciones administrativas remotas |
| Tenant | Organización cliente (BBVA, Ripley, etc.) en modelo multi-tenant |
| Named Pipe | Mecanismo IPC entre Service y Tray en Windows |
| Tray | Aplicación de bandeja del sistema (AlwaysPrintTray.exe) |
| Service | Servicio Windows (AlwaysPrintService.exe, LocalSystem) |
| SSM | AWS Systems Manager — acceso al servidor sin SSH |
| ECR | Elastic Container Registry — almacén de imágenes Docker |

---

**Robles.AI**  
Email: antonio@robles.ai  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados
