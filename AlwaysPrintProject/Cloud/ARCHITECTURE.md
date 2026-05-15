# AlwaysPrint Cloud Manager - Arquitectura

## Descripción General

**AlwaysPrint Cloud Manager (APCM)** es una plataforma SaaS multi-cuenta para la gestión centralizada de workstations Windows que utilizan el sistema AlwaysPrint para gestión de impresión corporativa.

**Versión**: 1.2.0  
**Última actualización**: 11 de mayo de 2026

---

## Arquitectura del Sistema Completo

```
┌─────────────────────────────────────────────────────────────┐
│                    CLIENTE: BBVA                             │
│  Workstations Windows                                        │
│                                                              │
│  Cada workstation ejecuta:                                  │
│  ├─ AlwaysPrintService.exe (LocalSystem, sin Internet)     │
│  └─ AlwaysPrintTray.exe (Usuario, con Internet vía proxy)  │
│                                                              │
│  AlwaysPrintTray se comunica con la nube                   │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          │ HTTPS (vía Proxy Corporativo)
                          │ Autenticación: IP pública autorizada
                          │
┌─────────────────────────▼─────────────────────────────────────┐
│              AWS us-west-2 (APCM)                              │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  EC2 t3.micro (Amazon Linux 2023)                      │  │
│  │  Elastic IP estática                                   │  │
│  │  Nginx (reverse proxy + Let's Encrypt SSL)             │  │
│  │                                                         │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐  │  │
│  │  │ Backend      │  │ Frontend     │  │ Redis       │  │  │
│  │  │ FastAPI :8000│  │ Next.js :3000│  │ :6379       │  │  │
│  │  └──────┬───────┘  └──────────────┘  └─────────────┘  │  │
│  │         │ (Docker Compose bridge network)               │  │
│  └─────────┼──────────────────────────────────────────────┘  │
│            │                                                   │
│  ┌─────────▼──────────────────────────────────────────────┐  │
│  │  RDS PostgreSQL 16 (db.t3.micro, subnet privada)       │  │
│  │  Solo accesible desde el EC2 (security group)          │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌─────────────────┐  ┌─────────────────────────────────┐   │
│  │  ECR            │  │  Secrets Manager                │   │
│  │  (imágenes      │  │  db_password, secret_key,       │   │
│  │  backend/front) │  │  ssh_private_key, database_url  │   │
│  └─────────────────┘  └─────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────┘

URL pública: https://alwaysprint.apps.iol.pe
```

---

## Componentes

### 1. Backend (FastAPI)

**Ubicación**: `AlwaysPrintProject/Cloud/backend/`  
**Tecnología**: Python 3.12, FastAPI, SQLAlchemy, Alembic  
**Puerto**: 8000 (desarrollo y producción interna)

**Responsabilidades**:
- API REST para dispositivos (AlwaysPrintTray)
- API REST para administradores (Dashboard)
- WebSocket en tiempo real para workstations y operadores
- Autenticación JWT para administradores
- Autorización por IP pública para workstations
- Multi-cuenta con `account_id` en todas las tablas

**Estructura**:
```
backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── endpoints/
│   │       │   ├── accounts.py     # CRUD de cuentas (superadmin)
│   │       │   ├── audit.py        # Logs de auditoría
│   │       │   ├── auth.py         # Login JWT + password reset
│   │       │   ├── config.py       # Configuración global/workstation
│   │       │   ├── messages.py     # Mensajes a workstations
│   │       │   ├── setup.py        # Setup inicial (primer admin)
│   │       │   ├── users.py        # Gestión de usuarios admin
│   │       │   ├── vlans.py        # Gestión de VLANs
│   │       │   └── workstations.py # Registro/heartbeat/estado
│   │       ├── websocket/
│   │       │   ├── operator.py     # WS para dashboard (operador)
│   │       │   └── workstation.py  # WS para AlwaysPrintTray
│   │       └── router.py
│   ├── core/
│   │   ├── config.py               # Configuración (env vars, Pydantic Settings)
│   │   ├── database.py             # Engine SQLAlchemy (NullPool en Alembic)
│   │   └── security.py             # JWT, hashing
│   ├── middleware/
│   │   ├── rate_limit.py           # Rate limiting por IP/ruta
│   │   └── security_headers.py     # Headers de seguridad HTTP
│   ├── models/
│   │   ├── account.py              # Account + PublicIP
│   │   ├── audit.py                # AuditLog
│   │   ├── config.py               # GlobalConfig + VLANConfig + WorkstationConfig
│   │   ├── message.py              # Message (broadcast a workstations)
│   │   ├── user.py                 # User (password_reset_token, password_reset_expires)
│   │   ├── vlan.py                 # VLAN
│   │   └── workstation.py          # Workstation + License
│   ├── schemas/                    # Schemas Pydantic
│   ├── services/
│   │   ├── audit.py
│   │   ├── auth.py
│   │   ├── config.py
│   │   ├── email.py                # Envío vía AWS SES (fallback a log si SES_ENABLED=false)
│   │   ├── message.py
│   │   ├── websocket_manager.py    # ConnectionManager singleton (1 worker requerido)
│   │   └── workstation.py
│   └── main.py
├── alembic/                        # Migraciones (cadena lineal)
│   └── versions/
│       ├── 001_initial_migration.py
│       ├── d4a203945821_add_full_name_to_users.py
│       ├── 002_add_timezone_fields.py
│       ├── 003_add_public_ip_authorization.py
│       └── 004_add_password_reset_token.py  ← última
└── requirements.txt
```

### 2. Frontend (Next.js)

**Ubicación**: `AlwaysPrintProject/Cloud/frontend/`  
**Tecnología**: Next.js 15, React 18, TypeScript, Tailwind CSS  
**Puerto**: 3000 (desarrollo y producción interna)

**Responsabilidades**:
- Dashboard web para administradores
- Visualización y gestión de workstations en tiempo real (WebSocket)
- Configuración global y por workstation
- Gestión de VLANs, mensajes, auditoría
- Panel de administración de cuentas y usuarios

**Estructura**:
```
frontend/src/
├── app/
│   ├── dashboard/
│   │   ├── page.tsx                # Dashboard principal (resumen)
│   │   ├── workstations/           # Lista y estado de workstations
│   │   ├── config/                 # Configuración global/workstation
│   │   ├── messages/               # Mensajes a workstations
│   │   ├── vlans/                  # Gestión de VLANs
│   │   ├── audit/                  # Logs de auditoría
│   │   ├── admin/
│   │   │   ├── accounts/           # CRUD de cuentas (superadmin)
│   │   │   ├── users/              # Gestión de usuarios
│   │   │   └── pending-ips/        # IPs pendientes de autorización
│   │   └── layout.tsx
│   ├── login/
│   ├── setup/                      # Setup inicial
│   └── not-found.tsx
├── components/
│   ├── providers/                  # QueryProvider (React Query)
│   └── ui/                         # Componentes shadcn/ui
├── hooks/
│   ├── useAuth.ts
│   ├── useUserTimezone.ts
│   ├── useWebSocket.ts
│   └── useWorkstations.ts
├── lib/
│   ├── api.ts                      # Cliente HTTP
│   ├── dateUtils.ts                # Manejo de fechas/zonas horarias
│   ├── utils.ts
│   └── websocket.ts                # Cliente WebSocket
└── types/                          # Tipos TypeScript
    ├── account.ts, audit.ts, config.ts
    ├── message.ts, user.ts, vlan.ts
    ├── websocket.ts, workstation.ts
```

### 3. Base de Datos (PostgreSQL 16)

**Modelo Multi-Cuenta**: Shared Schema  
**Aislamiento**: Todas las queries filtradas por `account_id`

**Tablas principales**:
- `accounts` — Cuentas cliente (BBVA, Ripley, etc.)
- `public_ips` — IPs públicas autorizadas por cuenta (mecanismo de auth de workstations)
- `workstations` — Estaciones de trabajo (identificadas por `ip_private`)
- `licenses` — Licencias de workstation (serial = MD5(ip_private)[últimos 8 chars])
- `vlans` — VLANs por cuenta
- `users` — Administradores por cuenta
- `global_configs` — Configuración global por cuenta
- `workstation_configs` — Configuración específica por workstation
- `messages` — Mensajes broadcast a workstations
- `audit_logs` — Auditoría de acciones

### 4. AWS SES

Servicio de email transaccional para el flujo de recuperación de contraseña.

- **Identidad verificada**: dominio `apps.iol.pe`
- **Desde**: `noreply@alwaysprint.apps.iol.pe`
- **Integración**: boto3 en `app/services/email.py`
- **Credenciales**: vía IAM role del EC2 (política `ses:SendEmail` / `ses:SendRawEmail`)
- **Desarrollo local**: `SES_ENABLED=false` imprime el enlace en logs sin enviar email

### 5. Redis

Desplegado como container Docker junto al backend. Usado para caché de configuración y soporte de rate limiting.  
URL interna: `redis://redis:6379/0`

---

## Flujo de Comunicación

### 1. Autenticación de Workstations (por IP pública)

```
AlwaysPrintTray intenta conectarse
    │
    │ HTTPS — sin API key
    │ Backend extrae IP pública del request
    │
    ├─ IP no registrada → crea PublicIP(is_authorized=False, account_id=NULL)
    │   Admin ve en /admin/pending-ips y la asigna a una cuenta
    │
    └─ IP autorizada → extrae account_id de public_ips
           │
           ▼
       Backend procesa la solicitud con el account_id correspondiente
```

### 2. Workstation → Nube (Estado / Heartbeat)

```
AlwaysPrintService (LocalSystem, sin Internet)
    │ Named Pipe (IPC local)
    ▼
AlwaysPrintTray (Usuario, con Internet)
    │ HTTPS (vía Proxy Corporativo)
    │ Identificada por IP pública autorizada
    ▼
Backend FastAPI
    ├─ Middleware: extrae account_id de la IP pública
    ├─ Actualiza workstation (ip_private, hostname, is_online, etc.)
    ▼
PostgreSQL (filtered by account_id)
```

### 3. Comunicación en Tiempo Real (WebSocket)

```
AlwaysPrintTray  ←──── wss://alwaysprint.apps.iol.pe/ws/workstation/{id}
                         │
                  WebSocket Manager (in-memory, por proceso)
                         │
Dashboard Admin  ←──── wss://alwaysprint.apps.iol.pe/ws/operator/{token}
```

### 4. Nube → Workstation (Configuración / Mensajes)

```
Admin actúa en Dashboard
    │ HTTPS — Bearer JWT
    ▼
Backend actualiza config o crea mensaje en BD
    │
    ▼
WebSocket push inmediato a AlwaysPrintTray
    │ Named Pipe
    ▼
AlwaysPrintService aplica configuración
```

---

## Autenticación

### Para Administradores (Dashboard)

- Método: JWT en header `Authorization: Bearer <token>`
- Endpoint: `POST /api/v1/auth/login`
- Token incluye `user_id` y `account_id`
- Setup inicial vía `POST /api/v1/setup` (crea primer superadmin)

### Para Workstations (AlwaysPrintTray)

- No usa API keys
- Autenticación basada en IP pública del request
- La IP debe estar en la tabla `public_ips` con `is_authorized=True`
- El `account_id` se deriva de la IP autorizada
- IPs nuevas quedan en estado pendiente hasta que un admin las autoriza

---

## Infraestructura (Terraform — AWS us-west-2)

### Módulos

| Módulo | Recursos |
|--------|----------|
| `networking` | VPC, 2 subnets públicas, 2 subnets DB (privadas), IGW, route tables, Security Groups (EC2 y RDS) |
| `ec2` | EC2 t3.micro (AL2023), Elastic IP, IAM role (ECR + Secrets Manager), Key pair SSH, volumen gp3 20GB cifrado |
| `rds` | RDS PostgreSQL 16 db.t3.micro, 20GB gp3, cifrado, en subnets privadas |
| `ecr` | 2 repositorios ECR (backend, frontend), retención 10 tags |
| `secrets` | Secrets Manager: db_password, secret_key, ssh_private_key |
| `main` | Secret `database_url` compuesto, wires todos los módulos |

### Stack de producción en EC2

```
Nginx (puerto 80/443, Let's Encrypt SSL)
  ├── /api/*   → localhost:8000 (backend)
  ├── /ws/*    → localhost:8000 (WebSocket upgrade)
  └── /*       → localhost:3000 (frontend)

Docker Compose (bridge network "app", puertos mapeados al host):
  ├── backend  (imagen ECR, uvicorn 1 worker — singleton WebSocket)
  ├── frontend (imagen ECR, Next.js)
  └── redis    (redis:7-alpine, caché interna)
```

### CI/CD

Manejado por GitHub Actions. Al hacer push a `main`:
1. Build y push de la imagen Docker a ECR
2. `aws ssm send-command` ejecuta `/opt/alwaysprint/deploy.sh [backend|frontend]` en el EC2
3. El script hace pull de ECR y reinicia solo el servicio afectado

No se usa SSH — el acceso al EC2 es exclusivamente vía **SSM Session Manager** (sin puerto 22).

### Dominio y SSL

- **Dominio**: `apps.iol.pe` (zona `apps.iol.pe` — DNS en Hostinger, no Route53)
- **SSL**: Let's Encrypt (Certbot + nginx), renovación automática vía cron
- **IP**: Elastic IP estática `34.213.90.95` (no cambia al reiniciar el EC2)

### Variables clave (terraform.tfvars)

| Variable | Valor |
|----------|-------|
| `aws_region` | `us-west-2` |
| `ec2_instance_type` | `t3.micro` |
| `db_instance_class` | `db.t3.micro` |
| `zone_name` | `apps.iol.pe` |
| `subdomain` | `alwaysprint` |
| `backend_port` | `8000` |
| `frontend_port` | `3000` |

---

## Seguridad

### Comunicación

- HTTPS/TLS 1.3 vía Let's Encrypt en producción
- Proxy corporativo soportado (detección automática del cliente)
- WebSocket sobre WSS

### Backend

- Rate limiting por IP/ruta (`rate_limit.py`)
- Security headers HTTP (`security_headers.py`)
- Passwords con bcrypt
- JWT con expiración configurable (`ACCESS_TOKEN_EXPIRE_MINUTES`)
- Secrets sensibles en AWS Secrets Manager (nunca en env vars planas)
- RDS accesible solo desde el security group del EC2

### IP Authorization Flow

1. Workstation desconocida → `PublicIP` creada con `is_authorized=False`
2. Admin ve IPs pendientes en dashboard (`/admin/pending-ips`)
3. Admin asigna la IP a una cuenta → `is_authorized=True`, `account_id` asignado
4. Siguiente request de esa IP queda autorizado automáticamente

---

## Despliegue

### Desarrollo local

```bash
# Backend
cd AlwaysPrintProject/Cloud/backend
conda activate alwaysprint
uvicorn app.main:app --reload

# Frontend
cd AlwaysPrintProject/Cloud/frontend
npm run dev
```

### Producción (Terraform + GitHub Actions)

```bash
# Provisionar infraestructura (primera vez o cambios)
cd AlwaysPrintProject/Cloud/terraform
./setup.sh plan    # revisa cambios
./setup.sh apply   # aplica — gestiona la clave SSH automáticamente

# Acceso interactivo al servidor (SSM, sin SSH)
aws ssm start-session --target i-0177ed8ad554ffc08 --profile Antonio-Robles-425642439683

# Recuperar clave SSH (solo para emergencias)
aws secretsmanager get-secret-value \
  --secret-id /alwaysprint/prod/ssh_private_key \
  --query SecretString --output text > alwaysprint.pem
chmod 400 alwaysprint.pem
```

El CI/CD (GitHub Actions) construye las imágenes, las sube a ECR y ejecuta `deploy.sh` en el EC2 vía **SSM send-command** (sin SSH).

---

## Estado actual del proyecto

### Implementado
- Backend FastAPI completo con todos los endpoints
- WebSocket en tiempo real (workstations y operadores)
- Frontend Next.js con dashboard completo
- Autenticación JWT (admins) + autorización por IP (workstations)
- Password reset completo vía AWS SES (token 1h, páginas forgot/reset)
- Multi-cuenta con aislamiento por `account_id`
- Gestión de VLANs, mensajes, configuración, auditoría
- Infraestructura AWS completa vía Terraform (EC2, RDS, ECR, SES, Secrets Manager)
- CI/CD via GitHub Actions

### Pendiente
- Integración completa con AlwaysPrintTray (cliente Windows)
- Alertas automáticas (workstation offline > X min)
- Analytics y reportes avanzados
- SSO (SAML/OAuth)

---

## Referencias

- [Backend README](backend/README.md)
- [Frontend README](frontend/README.md)
- [CHANGELOG](CHANGELOG.md)

---

## Contacto

**Robles.AI**  
Email: antonio@robles.ai  
Teléfono: +1 408 590 0153  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados  
Producto de la familia de automatización Robles.AI  
Prohibida la utilización sin autorización de Inversiones On Line SAC
