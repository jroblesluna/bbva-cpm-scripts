# AlwaysPrint Cloud Manager

Plataforma SaaS multi-tenant para la gestión centralizada de workstations Windows que ejecutan AlwaysPrint.

**Versión**: 1.0.0  
**Última actualización**: 8 de mayo de 2026

---

## Descripción

**AlwaysPrint Cloud Manager (APCM)** es una plataforma cloud que permite monitorear y gestionar centralizadamente miles de workstations Windows desde una interfaz web, con:

- **Multi-Tenancy**: Gestión de múltiples organizaciones cliente (BBVA, Santander, etc.)
- **Monitoreo en Tiempo Real**: Estado de workstations, heartbeat, telemetría
- **Configuración Remota**: Actualización de configuración desde la nube
- **Analytics y Reportes**: Métricas de uso, disponibilidad, errores
- **Escalabilidad**: Soporte para 200,000+ workstations

## Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│                    CLIENTE: BBVA                             │
│  500 Workstations Windows 11                                │
│  Cada workstation ejecuta AlwaysPrint (Service + Tray)     │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          │ HTTPS (vía Proxy Corporativo)
                          │ Authentication: X-API-Key
                          │
┌─────────────────────────▼─────────────────────────────────────┐
│              ALWAYSPRINT CLOUD MANAGER (SaaS)                 │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Backend (FastAPI)                                     │  │
│  │  - API REST para dispositivos y administradores        │  │
│  │  - Multi-tenancy con tenant isolation                  │  │
│  │  - Autenticación: API Keys + JWT                       │  │
│  └────────────────────────┬───────────────────────────────┘  │
│                           │                                   │
│  ┌────────────────────────▼───────────────────────────────┐  │
│  │  Frontend (Next.js)                                    │  │
│  │  - Dashboard web para administradores                  │  │
│  │  - Subdominios por cliente (bbva.alwaysprint.com)     │  │
│  └────────────────────────────────────────────────────────┘  │
│                           │                                   │
│                    ┌──────▼──────┐                           │
│                    │  PostgreSQL │                           │
│                    │  Multi-Tenant│                          │
│                    └─────────────┘                           │
└───────────────────────────────────────────────────────────────┘
```

### Componentes

- **Backend (FastAPI)**: API REST + autenticación multi-tenant
- **Frontend (Next.js 15)**: Dashboard web con subdominios por cliente
- **Base de Datos**: PostgreSQL (producción) / SQLite (desarrollo)
- **Cliente Windows**: AlwaysPrint (Service + Tray) - ver `../Client/`

### Stack Tecnológico

**Backend:**
- Python 3.12
- FastAPI
- SQLAlchemy + Alembic
- JWT + bcrypt

**Frontend:**
- Next.js 15 (App Router)
- TypeScript
- shadcn/ui + Tailwind CSS
- React Query

## Estructura del Proyecto

```
.
├── backend/                    # Backend FastAPI
│   ├── app/                   # Código de la aplicación
│   │   ├── api/              # Endpoints REST y WebSocket
│   │   ├── core/             # Configuración y seguridad
│   │   ├── models/           # Modelos SQLAlchemy
│   │   ├── schemas/          # Schemas Pydantic
│   │   └── services/         # Lógica de negocio
│   ├── alembic/              # Migraciones de BD
│   ├── tests/                # Tests
│   └── requirements.txt      # Dependencias Python
│
├── frontend/                  # Frontend Next.js
│   ├── src/
│   │   ├── app/             # App Router
│   │   ├── components/      # Componentes React
│   │   ├── lib/             # Utilidades
│   │   ├── hooks/           # Custom hooks
│   │   └── types/           # Tipos TypeScript
│   └── package.json         # Dependencias Node.js
│
└── docker-compose.yml        # Orquestación de servicios
```

## Instalación y Configuración

### Requisitos Previos

- **Backend**: Python 3.12+, Conda (recomendado)
- **Frontend**: Node.js 20+, npm
- **Docker** (opcional, para despliegue containerizado)

### Opción 1: Desarrollo Local

#### Backend

```bash
cd backend

# Con Conda (recomendado)
conda env create -f environment.yml
conda activate alwaysprint

# Configurar variables de entorno
cp .env.example .env
# Editar .env con tus configuraciones

# Ejecutar migraciones
alembic upgrade head

# Iniciar servidor
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

El backend estará disponible en http://localhost:8000

Ver [backend/README.md](backend/README.md) para más detalles.

#### Frontend

```bash
cd frontend

# Instalar dependencias
npm install

# Configurar variables de entorno
cp .env.example .env.local
# Editar .env.local con tus configuraciones

# Iniciar servidor de desarrollo
npm run dev
```

El frontend estará disponible en http://localhost:3000

Ver [frontend/README.md](frontend/README.md) para más detalles.

### Opción 2: Docker Compose

```bash
# Construir e iniciar todos los servicios
docker-compose up -d

# Ver logs
docker-compose logs -f

# Detener servicios
docker-compose down
```

Servicios disponibles:
- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- PostgreSQL: localhost:5432

## Multi-Tenancy

### Modelo de Datos

**Shared Schema**: Todas las organizaciones comparten las mismas tablas, con aislamiento por `organization_id`.

```sql
organizations
├─ id, name, slug, plan, api_key

workstations
├─ id, organization_id, hostname, api_key, status

users (admins)
├─ id, organization_id, email, role

telemetry
├─ id, organization_id, workstation_id, metrics
```

### Tenant Isolation

Todas las queries filtran por `organization_id`:

```python
# ✅ CORRECTO
workstation = db.query(Workstation).filter(
    Workstation.id == id,
    Workstation.organization_id == tenant.organization_id
).first()
```

### Subdominios por Cliente

- `https://bbva.alwaysprint.com` → Dashboard de BBVA
- `https://santander.alwaysprint.com` → Dashboard de Santander
- `https://api.alwaysprint.com` → API única para todos

### API Keys en Dos Niveles

**1. Organization API Key**:
- Formato: `org_bbva_xxxxxxxxxxxxxxxx`
- Uso: Registro inicial de workstations
- Almacenado en: Instalador MSI de AlwaysPrint

**2. Workstation API Key**:
- Formato: `ws_xxxxxxxxxxxxxxxx`
- Uso: Heartbeat, telemetría, obtener configuración
- Único por workstation

## Comunicación con Workstations

### Flujo de Registro

```
1. Admin instala AlwaysPrint.msi en workstation
2. Instalador configura:
   - CloudEnabled = 1
   - CloudApiUrl = https://api.alwaysprint.com
   - CloudApiKey = org_bbva_xxxxxxxx
3. AlwaysPrintTray envía POST /api/v1/workstations/register
4. Backend devuelve workstation_id y workstation_api_key
5. Tray guarda credenciales en Registry
6. Tray inicia heartbeat cada 60 segundos
```

### Endpoints para Dispositivos

- `POST /api/v1/workstations/register` - Registro inicial
- `POST /api/v1/workstations/{id}/heartbeat` - Heartbeat (cada 60s)
- `POST /api/v1/workstations/{id}/telemetry` - Envío de métricas
- `GET /api/v1/workstations/{id}/config` - Obtener configuración

### Endpoints para Administradores

- `POST /api/v1/auth/login` - Login con JWT
- `GET /api/v1/admin/workstations` - Lista de workstations
- `PUT /api/v1/admin/workstations/{id}/config` - Actualizar configuración
- `GET /api/v1/admin/analytics` - Métricas y reportes

## Documentación de la API

Una vez iniciado el backend, la documentación interactiva está disponible en:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Escalabilidad

| Workstations | Clientes | Infraestructura |
|--------------|----------|-----------------|
| <5,000 | 1-10 | 1 servidor (4 CPU, 8GB RAM) |
| 5,000-50,000 | 10-50 | Load balancer + 2-3 servidores |
| 50,000-200,000 | 50-200 | Kubernetes cluster |
| 200,000+ | 200+ | Multi-region + CDN |

## Documentación Adicional

- [Arquitectura Detallada](ARCHITECTURE.md) - Arquitectura completa del sistema
- [Backend README](backend/README.md) - Instalación y configuración del backend
- [Frontend README](frontend/README.md) - Instalación y configuración del frontend
- [Cliente Windows](../Client/README.md) - AlwaysPrint (Service + Tray)
- [Visión General del Sistema](../../SYSTEM-OVERVIEW.md) - Ecosistema completo
- [Proyecto Principal](../README.md) - AlwaysPrint Project

---

**Robles.AI**  
Email: antonio@robles.ai  
Teléfono: +1 408 590 0153  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados  
Producto de la familia de automatización Robles.AI  
Prohibida la utilización sin autorización de Inversiones On Line SAC
