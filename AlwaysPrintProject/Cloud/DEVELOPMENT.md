# Guía de Desarrollo — AlwaysPrint Cloud

## Requisitos

- Python 3.12
- Node.js 18+
- Docker (opcional, para levantar PostgreSQL local)
- AWS CLI configurado (para SES en desarrollo)

---

## Backend (FastAPI)

### Setup

```bash
cd AlwaysPrintProject/Cloud/backend

conda create -n alwaysprint python=3.12
conda activate alwaysprint

pip install -r requirements.txt
```

### Variables de entorno (`.env`)

```bash
# Base de datos — SQLite para desarrollo
DATABASE_URL=sqlite:///./alwaysprint.db

# Seguridad
SECRET_KEY=dev-secret-key-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# CORS
CORS_ORIGINS=http://localhost:3000

# SES — deshabilitar en desarrollo local
SES_ENABLED=false
SES_FROM_EMAIL=noreply@alwaysprint.apps.iol.pe
AWS_REGION=us-west-2
FRONTEND_URL=http://localhost:3000

# Logging
LOG_LEVEL=DEBUG
```

> Con `SES_ENABLED=false` el servicio de email imprime el enlace de reset en los logs
> en lugar de enviarlo por correo — útil para desarrollo sin credenciales AWS.

### Migraciones

```bash
# Aplicar todas las migraciones
alembic upgrade head

# Crear nueva migración tras cambiar un modelo
alembic revision --autogenerate -m "descripcion"

# Ver historial
alembic history
```

### Ejecutar

```bash
# Desarrollo (con reload)
uvicorn app.main:app --reload --port 8000
```

> **Producción usa `--workers 1`** — el WebSocket manager es un singleton en memoria;
> múltiples workers rompen el broadcast entre conexiones.

### Documentación de la API

Con el servidor corriendo: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Frontend (Next.js)

### Setup

```bash
cd AlwaysPrintProject/Cloud/frontend

npm install
```

### Variables de entorno (`.env.local`)

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
NEXT_PUBLIC_APP_NAME=AlwaysPrint Cloud Management
```

### Ejecutar

```bash
npm run dev        # desarrollo
npm run build      # build de producción
npm run lint       # linter
```

---

## Infraestructura (Terraform)

```bash
cd AlwaysPrintProject/Cloud/terraform

terraform init
terraform plan
terraform apply
```

Tras el apply, obtener los registros DNS para SES:

```bash
terraform output ses_dns_records
```

Ver [DNS_SETUP.md](./DNS_SETUP.md) para el procedimiento completo de configuración DNS.

---

## Migraciones de base de datos — cadena actual

```
001_initial_migration
  └── d4a203945821_add_full_name_to_users
        └── 002_add_timezone_fields
              └── 003_add_public_ip_authorization
                    └── 004_add_password_reset_token  ← última
```

---

## Estructura real del código

```
backend/app/
├── api/v1/
│   ├── endpoints/
│   │   ├── accounts.py       # CRUD cuentas (superadmin)
│   │   ├── audit.py          # Logs de auditoría
│   │   ├── auth.py           # Login, logout, password reset
│   │   ├── config.py         # Config global y por workstation
│   │   ├── messages.py       # Mensajes a workstations
│   │   ├── setup.py          # Setup inicial (primer admin)
│   │   ├── users.py          # Gestión de usuarios
│   │   ├── vlans.py          # Gestión de VLANs
│   │   └── workstations.py   # Estado y config de workstations
│   └── websocket/
│       ├── operator.py       # WS dashboard
│       └── workstation.py    # WS AlwaysPrintTray
├── core/
│   ├── config.py             # Settings (Pydantic)
│   ├── database.py           # Engine SQLAlchemy
│   └── security.py           # JWT
├── middleware/
│   ├── rate_limit.py
│   └── security_headers.py
├── models/
│   ├── account.py            # Account + PublicIP
│   ├── audit.py
│   ├── config.py             # GlobalConfig + VLANConfig + WorkstationConfig
│   ├── message.py
│   ├── user.py               # User (incluye password_reset_token)
│   ├── vlan.py
│   └── workstation.py        # Workstation + License
├── schemas/                  # Schemas Pydantic
├── services/
│   ├── audit.py
│   ├── auth.py
│   ├── config.py
│   ├── email.py              # Envío via AWS SES
│   ├── message.py
│   ├── websocket_manager.py  # ConnectionManager (singleton)
│   └── workstation.py
└── main.py

frontend/src/
├── app/
│   ├── dashboard/
│   │   ├── workstations/
│   │   ├── config/
│   │   ├── messages/
│   │   ├── vlans/
│   │   ├── audit/
│   │   └── admin/
│   │       ├── accounts/
│   │       ├── users/
│   │       └── pending-ips/
│   ├── login/
│   ├── forgot-password/      # Solicitar reset de contraseña
│   ├── reset-password/       # Confirmar reset con token
│   └── setup/
├── hooks/
│   ├── useAuth.ts
│   ├── useUserTimezone.ts
│   ├── useWebSocket.ts
│   └── useWorkstations.ts
├── lib/
│   ├── api.ts                # Cliente HTTP (axios)
│   ├── dateUtils.ts
│   ├── utils.ts
│   └── websocket.ts          # WebSocketClient (singleton)
└── types/

terraform/
├── main.tf
├── variables.tf
├── outputs.tf
├── terraform.tfvars
└── modules/
    ├── ec2/     # EC2 t3.micro + IAM + EIP
    ├── ecr/     # Repositorios de imágenes
    ├── networking/ # VPC + subnets + security groups
    ├── rds/     # PostgreSQL 16 db.t3.micro
    ├── secrets/ # Secrets Manager (db_password, secret_key, ssh)
    └── ses/     # SES domain identity + DKIM + IAM policy
```

---

## Referencias

- [ARCHITECTURE.md](./ARCHITECTURE.md) — Arquitectura completa del sistema
- [DNS_SETUP.md](./DNS_SETUP.md) — Configuración DNS para SES
- [CHANGELOG.md](./CHANGELOG.md) — Historial de cambios
