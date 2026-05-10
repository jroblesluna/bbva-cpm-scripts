# AlwaysPrint Cloud Manager

Sistema de gestión centralizada para el sistema de contingencia de impresión AlwaysPrint.

## 📋 Descripción

AlwaysPrint Cloud Manager es una plataforma SaaS multi-tenant que permite:

- **Gestión de Workstations**: Monitoreo y control de estaciones Windows con AlwaysPrint Client
- **Gestión de VLANs**: Organización de workstations por segmentos de red
- **Gestión de Organizaciones**: Multi-tenancy con aislamiento completo de datos
- **Mensajería**: Envío de mensajes y comandos a workstations
- **Auditoría**: Registro completo de acciones y eventos del sistema
- **Autorización de IPs**: Control de acceso basado en IPs públicas

## 🏗️ Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│                    ALWAYSPRINT CLOUD                         │
│                                                              │
│  ┌────────────────────┐         ┌────────────────────┐     │
│  │   Frontend         │         │   Backend          │     │
│  │   Next.js 15       │────────▶│   FastAPI          │     │
│  │   TypeScript       │  HTTPS  │   Python 3.12      │     │
│  │   Port 3000        │         │   Port 8000        │     │
│  └────────────────────┘         └────────────────────┘     │
│                                           │                  │
│                                           ▼                  │
│                                  ┌────────────────────┐     │
│                                  │   PostgreSQL       │     │
│                                  │   (Producción)     │     │
│                                  │   SQLite (Dev)     │     │
│                                  └────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
                        │
                        ▼
        ┌───────────────────────────────────┐
        │   AlwaysPrint Clients (Windows)   │
        │   - Reportan estado               │
        │   - Reciben mensajes/comandos     │
        │   - Envían logs                   │
        └───────────────────────────────────┘
```

## 🚀 Inicio Rápido

### Requisitos Previos

- **Backend**: Python 3.12+, Conda (recomendado)
- **Frontend**: Node.js 18+, npm
- **Base de Datos**: SQLite (desarrollo) o PostgreSQL (producción)

### Instalación Local

#### 1. Backend

```bash
cd backend

# Crear entorno conda
conda create -n alwaysprint python=3.12
conda activate alwaysprint

# Instalar dependencias
pip install -r requirements.txt

# Configurar variables de entorno
cp .env.example .env
# Editar .env con tus configuraciones

# Inicializar base de datos
alembic upgrade head

# Ejecutar servidor
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Backend disponible en: http://localhost:8000  
Documentación API: http://localhost:8000/docs

#### 2. Frontend

```bash
cd frontend

# Instalar dependencias
npm install

# Configurar variables de entorno
cp .env.example .env.local
# Editar .env.local con la URL del backend

# Ejecutar servidor de desarrollo
npm run dev
```

Frontend disponible en: http://localhost:3000

#### 3. Inicialización del Sistema

1. Acceder a http://localhost:3000/setup
2. Crear el primer usuario administrador
3. Iniciar sesión en http://localhost:3000/login

## 📁 Estructura del Proyecto

```
AlwaysPrintProject/Cloud/
├── backend/                    # Backend FastAPI
│   ├── app/
│   │   ├── api/               # Endpoints REST
│   │   │   └── v1/
│   │   │       └── endpoints/ # Controladores por entidad
│   │   ├── core/              # Configuración y seguridad
│   │   ├── models/            # Modelos SQLAlchemy
│   │   ├── schemas/           # Schemas Pydantic
│   │   └── services/          # Lógica de negocio
│   ├── alembic/               # Migraciones de BD
│   ├── tests/                 # Tests pytest
│   └── requirements.txt
│
├── frontend/                   # Frontend Next.js
│   ├── src/
│   │   ├── app/               # Páginas Next.js 15 (App Router)
│   │   │   ├── dashboard/     # Dashboard principal
│   │   │   ├── login/         # Autenticación
│   │   │   └── setup/         # Configuración inicial
│   │   ├── components/        # Componentes React
│   │   │   └── ui/            # Componentes UI reutilizables
│   │   ├── hooks/             # Custom hooks
│   │   ├── lib/               # Utilidades y API client
│   │   └── types/             # Tipos TypeScript
│   └── package.json
│
├── terraform/                  # Infraestructura como código
│   ├── modules/               # Módulos reutilizables
│   │   ├── networking/        # VPC, subnets, security groups
│   │   ├── ecr/               # Container registry
│   │   ├── rds/               # PostgreSQL
│   │   └── ec2/               # Instancia EC2 con Docker
│   └── main.tf
│
├── ARCHITECTURE.md            # Arquitectura detallada
├── DEVELOPMENT.md             # Guía de desarrollo
└── README.md                  # Este archivo
```

## 🔑 Características Principales

### Multi-Tenancy

- **Aislamiento completo** de datos por organización
- **Roles de usuario**: Admin (super usuario) y Operator (por organización)
- **Autorización de IPs públicas**: Control de acceso por IP

### Gestión de Workstations

- **Monitoreo en tiempo real** del estado de workstations
- **Configuración remota** de parámetros
- **Activación/desactivación** de modo contingencia
- **Historial de eventos** y cambios

### Mensajería y Comandos

- **Envío de mensajes** a workstations individuales, VLANs o toda la organización
- **Comandos remotos** para operaciones específicas
- **Confirmación de entrega** y resultados

### Auditoría Completa

- **Registro de todas las acciones** de usuarios
- **Eventos del sistema** (conexiones, desconexiones, cambios)
- **Filtrado y búsqueda** avanzada
- **Exportación de logs**

## 🔒 Seguridad

- **Autenticación JWT** con tokens de 24 horas
- **Bcrypt** para hashing de contraseñas
- **CORS configurado** para dominios específicos
- **Autorización basada en roles** (RBAC)
- **Autorización de IPs públicas** para workstations
- **HTTPS/TLS 1.3** en producción
- **Tenant isolation** a nivel de base de datos

## 🧪 Testing

### Backend

```bash
cd backend
pytest                          # Ejecutar todos los tests
pytest tests/test_auth.py       # Test específico
pytest -v                       # Modo verbose
pytest --cov=app                # Con cobertura
```

### Frontend

```bash
cd frontend
npm run test                    # Ejecutar tests
npm run test:watch              # Modo watch
npm run build                   # Verificar build de producción
```

## 📦 Deployment

### Producción con Terraform (AWS)

```bash
cd terraform

# Inicializar Terraform
terraform init

# Planificar cambios
terraform plan

# Aplicar infraestructura
terraform apply

# Obtener outputs (URLs, IPs, etc.)
terraform output
```

La infraestructura incluye:
- VPC con subnets públicas y privadas
- RDS PostgreSQL en subnet privada
- ECR para imágenes Docker
- EC2 con Docker Compose
- Route53 para DNS
- Security Groups configurados

### Variables de Entorno Requeridas

#### Backend (.env)

```bash
# Base de datos
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Seguridad
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# CORS
ALLOWED_ORIGINS=https://alwaysprint.apps.iol.pe

# Aplicación
PROJECT_NAME=AlwaysPrint Cloud Manager
VERSION=1.0.0
```

#### Frontend (.env.local)

```bash
NEXT_PUBLIC_API_URL=https://api.alwaysprint.apps.iol.pe
```

## 📚 Documentación Adicional

- **[ARCHITECTURE.md](./ARCHITECTURE.md)** - Arquitectura detallada del sistema
- **[DEVELOPMENT.md](./DEVELOPMENT.md)** - Guía completa de desarrollo
- **[Backend README](./backend/README.md)** - Documentación específica del backend
- **[Frontend README](./frontend/README.md)** - Documentación específica del frontend

## 🔗 URLs de Producción

- **Frontend**: https://alwaysprint.apps.iol.pe
- **Backend API**: https://api.alwaysprint.apps.iol.pe
- **Documentación API**: https://api.alwaysprint.apps.iol.pe/docs

## 🤝 Contribución

1. Crear rama desde `main`: `git checkout -b feature/nueva-funcionalidad`
2. Hacer cambios y commits descriptivos
3. Ejecutar tests: `pytest` (backend) y `npm run build` (frontend)
4. Push y crear Pull Request
5. Esperar revisión y aprobación

## 📄 Licencia

© 2026 Inversiones On Line SAC - Todos los derechos reservados  
Producto de la familia de automatización Robles.AI

---

**Contacto:**  
Email: antonio@robles.ai  
Teléfono: +1 408 590 0153  
Web: https://robles.ai
