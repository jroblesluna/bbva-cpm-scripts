# Análisis del Proyecto AlwaysPrint

**Fecha**: Mayo 2026  
**Versión del documento**: 2.0  
**Propósito**: Documento base para generar presentaciones, documentación técnica y comercial.

---

## 1. Resumen Ejecutivo

### Problema

BBVA utiliza Lexmark Cloud Print Manager (CPM) como sistema de impresión corporativa. Cuando CPM falla — ya sea por caída del módulo de Lexmark, cruces en las sesiones de los usuarios que impiden enviar correctamente la impresión, u otros motivos — las estaciones de trabajo (PC individual) quedan sin capacidad de impresión hasta que se restaure el servicio o un personal capacitado configure manualmente la solución.

### Solución

**AlwaysPrint** es un sistema de contingencia que coexiste con Lexmark CPM en las workstations Windows (10/11). Evita y soluciona cruces de sesiones, detecta automáticamente caídas de CPM y redirige el tráfico de impresión directamente a las impresoras físicas de contingencia, garantizando continuidad operativa.

### Componentes del Proyecto

| Componente | Rol |
|---|---|
| AlwaysPrint Client (Windows) | Monitoreo, detección de fallas y redirección de impresión |
| AlwaysPrint Cloud Manager | Gestión centralizada SaaS (configuración, monitoreo, acciones remotas) |

---

## 2. Usuarios y Roles del Sistema

### 2.1 Usuario Final (Empleado BBVA)
- **Interacción**: Imprime normalmente desde cualquier aplicación Windows
- **Experiencia en producción**: Transparente, no nota el sistema
- **Experiencia en contingencia**: Recibe notificación balloon tip de que se activó contingencia
- **Interfaz**: Icono en bandeja del sistema (AlwaysPrintTray) con menú contextual
  - About (versión, estado, usuario)
  - Configuration (ver configuración activa)
  - My Printers (impresoras disponibles en VLAN y gestionar las favoritas)
  - Check Updates (verificar actualizaciones)

### 2.2 Administrador TI (por Organización)
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
  - Autorización de IPs públicas
  - Gestión de configuraciones de acciones (.alwaysconfig)

### 2.3 Administrador Global (Admin)
- **Interfaz**: Dashboard web (sección Admin)
- **Funciones**:
  - CRUD de organizaciones (BBVA, Ripley, etc.)
  - Gestión de usuarios (operarios, administradores)
  - Gestión de actualizaciones automáticas
  - Configuración de modelos LLM por organización
  - Funciones de administrador TI

### 2.4 Workstation (PC de trabajo)
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

### 3.1 Arquitectura General

```
┌─────────────────────────────────────────────────────────────────────┐
│                    WORKSTATION WINDOWS (x N estaciones)              │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  AlwaysPrint Client                                          │   │
│  │  • AlwaysPrintService.exe (LocalSystem, sin Internet)       │   │
│  │  • AlwaysPrintTray.exe (sesión usuario, con Internet)       │   │
│  │  • Comunicación IPC: Named Pipe (\\.\pipe\AlwaysPrintService)│   │
│  │                                                              │   │
│  │  Funciones:                                                  │   │
│  │  • Detecta falla CPM → redirige a IP:puerto impresora      │   │
│  │  • Ejecuta acciones administrativas remotas                 │   │
│  │  • Reporta telemetría y estado al Cloud                     │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
└─────────────────────────────┼───────────────────────────────────────┘
                              │
                              │ HTTPS/WSS (vía Proxy Corporativo)
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ALWAYSPRINT CLOUD MANAGER (AWS us-west-2)                          │
│                                                                      │
│  EC2 + RDS + ECR + S3                                               │
│  • Backend FastAPI (Python 3.12)                                    │
│  • Frontend Next.js 15 (TypeScript)                                 │
│  • PostgreSQL 16 + Redis 7                                          │
│  • Nginx + SSL/TLS 1.3                                              │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 Flujo de Contingencia

```
AlwaysPrintService detecta falla CPM
    │
    ▼
Activa modo contingencia
    │
    ├─► Redirige tráfico de cola Windows → IP:puerto impresora
    │   (bypass completo de CPM)
    │
    ├─► Notifica a AlwaysPrintTray vía Named Pipe
    │     • Tray muestra balloon tip al usuario
    │     • Tray reporta contingencia a Cloud Manager
    │
    └─► Cloud Manager registra evento
          • Dashboard muestra alerta
          • Administrador TI puede intervenir remotamente
```

### 3.3 Comunicación Client ↔ Cloud

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
│       │                                                      │
│       └─► WebSocket (/ws/operator/{token})                  │
│             • Dashboard tiempo real                          │
│             • Notificaciones de eventos                     │
└─────────────────────────────────────────────────────────────┘
```

### 3.4 Infraestructura AWS

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

## 4. Stack Tecnológico

### 4.1 Cliente Windows

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

### 4.4 DevOps / Infraestructura

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

### 5.1 AlwaysPrintService (Servicio Windows)

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

### 5.2 AlwaysPrintTray (Aplicación de bandeja)

| # | Funcionalidad | Descripción |
|---|--------------|-------------|
| 1 | Icono de bandeja | NotifyIcon con menú contextual |
| 2 | Conexión WebSocket | Comunicación tiempo real con Cloud |
| 3 | Registro automático | Se registra en Cloud por IP pública |
| 4 | Sincronización de config | Descarga configuración de organización y específica |
| 5 | Telemetría | Envío periódico de métricas al Cloud |
| 6 | Checks de conectividad | HTTP, TCP, Ping, DNS configurables |
| 7 | Auto-actualización | Descarga MSI + solicita instalación al Service |
| 8 | Descarga de .alwaysconfig | Verifica hash, descarga si difiere |
| 9 | Notificaciones | Balloon tips al usuario |
| 10 | Gestión offline | Almacena datos cuando no hay conexión |
| 11 | Localización | Soporte multi-idioma (es/en) |

### 5.3 Acciones Administrativas Remotas

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

### 5.4 Cloud Manager — Backend (API REST)

#### Endpoints por Módulo

| Módulo | Prefix | Endpoints principales |
|--------|--------|----------------------|
| Auth | `/api/v1/auth` | Login, refresh token, password reset |
| Setup | `/api/v1/setup` | Creación primer administrador global |
| Organizations | `/api/v1/organizations` | CRUD orgs, IPs públicas, auto-update config |
| Users | `/api/v1/users` | CRUD usuarios admin por organización |
| Workstations | `/api/v1/workstations` | Registro, listado, stats, comandos, delete, logs |
| VLANs | `/api/v1/vlans` | CRUD VLANs por organización |
| Config | `/api/v1/config` | Configuración de organización y por workstation |
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
| 2 | Auth JWT | Tokens con expiración, roles (ADMIN=Admin Global, OPERATOR=Admin TI, READONLY=Solo lectura) |
| 3 | Auth por IP | Workstations autenticadas por IP pública autorizada |
| 4 | WebSocket | Tiempo real para workstations y administradores |
| 5 | Rate limiting | Por IP y por ruta |
| 6 | Security headers | HSTS, X-Frame-Options, CSP |
| 7 | Auditoría | Log de todas las acciones administrativas |
| 8 | Email (SES) | Password reset, notificaciones |
| 9 | Health check | Con métricas de pool de conexiones |
| 10 | Análisis con IA | Logs analizados por LLM (AWS Bedrock / OpenAI) |

### 5.5 Cloud Manager — Frontend (Dashboard Web)

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
| Organizaciones | `/dashboard/admin/organizations` | CRUD organizaciones (administrador global) |
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

### 6.1 Diagrama Entidad-Relación

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
         ├── GlobalConfig (1:1 con Organization) — Config de organización
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
| User | email, role (ADMIN=Admin Global, OPERATOR=Admin TI, READONLY), password_hash | Admins del dashboard |
| ActionConfig | scope (org/vlan/workstation), config_json, config_hash (SHA256 8 chars), is_active | Herencia jerárquica |
| Device | name, ip_address, port, is_active | Impresoras físicas |
| GlobalConfig | JSON de configuración de organización | Heredada a workstations |

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

### 8.3 Entornos

| Entorno | URL | AWS Account | Trigger |
|---------|-----|-------------|---------|
| DEV | alwaysprint.dev.iol.pe | 040982755196 | Push a main |
| PROD | alwaysprint.apps.iol.pe | 425642439683 | Push a main (workflows separados) |

---

## 9. Sistema de Configuración de Acciones (.alwaysconfig)

### 9.1 Descripción

Sistema que permite definir y ejecutar acciones administrativas en workstations de forma centralizada. Las configuraciones se definen en archivos `.alwaysconfig` (JSON) y se descargan automáticamente.

### 9.2 Flujo de Operación

1. **Admin sube config** → Frontend valida JSON → Backend guarda con hash
2. **Workstation conecta** → Tray verifica hash local vs Cloud
3. **Si difiere** → Descarga nueva config → Guarda en `active.alwaysconfig`
4. **Notifica Service** → Named Pipe mensaje `ActionConfigChanged`
5. **Service recarga** → ActionEngine ejecuta trigger `OnConfigChange`

### 9.3 Triggers Soportados

| Trigger | Descripción |
|---------|-------------|
| `OnServiceStart` | Al iniciar el servicio |
| `OnTrayLaunched` | Después de inicializar Tray |
| `OnConfigChange` | Al recibir nueva configuración |
| `OnUserLogon` | Al iniciar sesión usuario |
| `OnUserLogoff` | Al cerrar sesión usuario |

### 9.4 Características Avanzadas

- **Variables**: Almacenar resultados de acciones (`store_result_in`)
- **Templates**: Reemplazo de variables `{{variable}}` en parámetros
- **Condicionales**: Evaluación de condiciones (equals, not_equals, contains, etc.)
- **Iteración**: Iterar sobre listas de usuarios (`iterate_users`)
- **Herencia jerárquica**: Scope org → vlan → workstation
- **Hash Verification**: SHA256 (8 chars) para integridad

### 9.5 Ejemplo de Configuración

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
                "parameters": { "service_name": "LPDSVC" }
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
                "parameters": { "service_name": "LPDSVC" }
              }
            ]
          }
        }
      ]
    }
  ]
}
```

---

## 10. Diagramas Recomendados para Documentación

### Para Presentación Ejecutiva

| # | Diagrama | Propósito |
|---|----------|-----------|
| 1 | Arquitectura de alto nivel | Mostrar Client + Cloud + flujo |
| 2 | Flujo normal vs contingencia | Comparar ambos modos |
| 3 | Mapa de valor (problema → solución → beneficio) | Presentación comercial |

### Diagramas Técnicos

| # | Diagrama | Propósito |
|---|----------|-----------|
| 4 | Infraestructura AWS | VPC, subnets, EC2, RDS, servicios |
| 5 | Modelo de datos (ER) | Relaciones entre entidades |
| 6 | Secuencia: registro de workstation | Flujo de auth por IP |
| 7 | Secuencia: activación de contingencia | Detección de falla → redirección |
| 8 | Secuencia: descarga de .alwaysconfig | Hash check → descarga → ejecución |
| 9 | Componentes del cliente Windows | Service ↔ Tray ↔ Cloud |
| 10 | Pipeline CI/CD | Build → Push → Deploy |

### Diagramas de UX/UI

| # | Diagrama | Propósito |
|---|----------|-----------|
| 11 | Wireframes del dashboard | Layout de páginas principales |
| 12 | Flujo de usuario admin | Navegación entre secciones |
| 13 | Flujo de usuario final | Experiencia en bandeja del sistema |
| 14 | Mapa de navegación del frontend | Sitemap del dashboard |
