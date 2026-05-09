# AlwaysPrint Cloud Manager - Arquitectura

## Descripción General

**AlwaysPrint Cloud Manager (APCM)** es una plataforma SaaS multi-tenant para la gestión centralizada de workstations Windows que utilizan el sistema AlwaysPrint para gestión de impresión corporativa.

**Versión**: 1.0.0  
**Última actualización**: 8 de mayo de 2026

---

## Arquitectura del Sistema Completo

```
┌─────────────────────────────────────────────────────────────┐
│                    CLIENTE: BBVA                             │
│  500 Workstations Windows 11                                │
│                                                              │
│  Cada workstation ejecuta:                                  │
│  ├─ AlwaysPrintService.exe (LocalSystem, sin Internet)     │
│  └─ AlwaysPrintTray.exe (Usuario, con Internet vía proxy)  │
│                                                              │
│  AlwaysPrintTray se comunica con la nube                   │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────┼───────────────────────────────────┐
│                    CLIENTE: Santander                        │
│  300 Workstations                                           │
└─────────────────────────┼───────────────────────────────────┘
                          │
                          │ HTTPS (vía Proxy Corporativo)
                          │
┌─────────────────────────▼─────────────────────────────────────┐
│              TU NUBE (APCM - Multi-Tenant SaaS)               │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Backend (FastAPI)                                     │  │
│  │  https://api.alwaysprint.tudominio.com                 │  │
│  │                                                         │  │
│  │  Endpoints para Dispositivos (AlwaysPrintTray):        │  │
│  │  ├─ POST /api/v1/workstations/register                 │  │
│  │  ├─ POST /api/v1/workstations/{id}/heartbeat           │  │
│  │  ├─ POST /api/v1/workstations/{id}/telemetry           │  │
│  │  └─ GET  /api/v1/workstations/{id}/config              │  │
│  │                                                         │  │
│  │  Endpoints para Administradores (Dashboard):           │  │
│  │  ├─ POST /api/v1/auth/login                            │  │
│  │  ├─ GET  /api/v1/admin/workstations                    │  │
│  │  ├─ PUT  /api/v1/admin/workstations/{id}/config        │  │
│  │  └─ GET  /api/v1/admin/analytics                       │  │
│  └────────────────────────┬───────────────────────────────┘  │
│                           │                                   │
│  ┌────────────────────────▼───────────────────────────────┐  │
│  │  Frontend (Next.js)                                    │  │
│  │  https://bbva.alwaysprint.tudominio.com                │  │
│  │  https://santander.alwaysprint.tudominio.com           │  │
│  │                                                         │  │
│  │  Dashboard Web para Administradores                    │  │
│  └────────────────────────────────────────────────────────┘  │
│                           │                                   │
│                    ┌──────▼──────┐                           │
│                    │  PostgreSQL │                           │
│                    │  Database   │                           │
│                    │  Multi-Tenant│                          │
│                    └─────────────┘                           │
└───────────────────────────────────────────────────────────────┘
```

---

## Componentes

### 1. Backend (FastAPI)

**Ubicación**: `AlwaysPrintCloudManager/backend/`  
**Tecnología**: Python 3.12, FastAPI, SQLAlchemy, Alembic  
**Puerto**: 8000 (desarrollo), 443 (producción)

**Responsabilidades**:
- API REST para dispositivos (AlwaysPrintTray)
- API REST para administradores (Dashboard)
- Autenticación multi-tenant (API Keys + JWT)
- Tenant isolation (filtrado por organization_id)
- Gestión de base de datos
- WebSocket para comunicación en tiempo real (opcional)

**Estructura**:
```
backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── endpoints/
│   │       │   ├── devices.py      # Endpoints para AlwaysPrintTray
│   │       │   ├── admin.py        # Endpoints para Dashboard
│   │       │   └── auth.py         # Autenticación
│   │       └── router.py
│   ├── core/
│   │   ├── config.py               # Configuración
│   │   ├── database.py             # Conexión a BD
│   │   └── security.py             # JWT, hashing
│   ├── middleware/
│   │   └── tenant.py               # Tenant isolation
│   ├── models/                     # Modelos SQLAlchemy
│   │   ├── organization.py
│   │   ├── workstation.py
│   │   ├── user.py
│   │   └── telemetry.py
│   ├── schemas/                    # Schemas Pydantic
│   └── main.py
├── alembic/                        # Migraciones
└── requirements.txt
```

### 2. Frontend (Next.js)

**Ubicación**: `AlwaysPrintCloudManager/frontend/`  
**Tecnología**: Next.js 15, React 18, TypeScript, Tailwind CSS  
**Puerto**: 3000 (desarrollo), 443 (producción)

**Responsabilidades**:
- Dashboard web para administradores
- Visualización de workstations
- Configuración centralizada
- Analytics y reportes
- Gestión de usuarios
- Multi-tenant (subdominios por cliente)

**Estructura**:
```
frontend/
├── src/
│   ├── app/
│   │   ├── dashboard/
│   │   │   ├── page.tsx            # Dashboard principal
│   │   │   ├── workstations/       # Gestión de workstations
│   │   │   ├── analytics/          # Reportes
│   │   │   └── settings/           # Configuración
│   │   ├── login/
│   │   └── layout.tsx
│   ├── components/
│   │   ├── ui/                     # Componentes shadcn/ui
│   │   └── dashboard/              # Componentes específicos
│   ├── lib/
│   │   ├── api.ts                  # Cliente HTTP
│   │   └── tenant.ts               # Detección de tenant
│   └── types/
└── package.json
```

### 3. Base de Datos (PostgreSQL)

**Modelo Multi-Tenant**: Shared Schema  
**Tenant Isolation**: Todas las queries filtradas por `organization_id`

**Tablas principales**:
- `organizations` - Clientes (BBVA, Santander, etc.)
- `workstations` - Estaciones de trabajo
- `users` - Administradores por organización
- `telemetry` - Métricas y logs
- `organization_configs` - Configuración por cliente
- `audit_logs` - Auditoría de acciones

---

## Flujo de Comunicación

### 1. Workstation → Nube (Reporte de Estado)

```
AlwaysPrintService (LocalSystem, sin Internet)
    │
    │ Named Pipe (IPC local)
    │
    ▼
AlwaysPrintTray (Usuario, con Internet)
    │
    │ HTTPS (vía Proxy Corporativo)
    │ Authentication: X-API-Key
    │
    ▼
Backend FastAPI
    │
    ├─ Middleware: Extrae organization_id del API Key
    ├─ Tenant Isolation: Filtra por organization_id
    │
    ▼
PostgreSQL Database
```

**Ejemplo de Heartbeat**:
```
1. AlwaysPrintService detecta cambio de estado
2. Envía mensaje a AlwaysPrintTray vía Named Pipe
3. AlwaysPrintTray envía HTTPS POST a backend:
   POST /api/v1/workstations/123/heartbeat
   Headers: X-API-Key: ws_abc123...
4. Backend extrae organization_id del API Key
5. Actualiza workstation en BD (filtrado por organization_id)
```

### 2. Nube → Workstation (Configuración/Comandos)

```
Admin cambia configuración en Dashboard
    │
    ▼
Frontend Next.js
    │
    │ HTTPS
    │ Authentication: Bearer JWT
    │
    ▼
Backend FastAPI
    │
    ├─ Middleware: Extrae organization_id del JWT
    ├─ Actualiza configuración en BD
    │
    ▼
AlwaysPrintTray hace polling (cada 5 min)
    │
    │ GET /api/v1/workstations/123/config
    │
    ▼
AlwaysPrintTray recibe nueva configuración
    │
    │ Named Pipe
    │
    ▼
AlwaysPrintService aplica configuración
```

---

## Multi-Tenancy

### Tenant Isolation

**Principio**: Cada organización (cliente) solo puede acceder a sus propios datos.

**Implementación**:
1. Todas las tablas tienen columna `organization_id`
2. Middleware extrae `organization_id` del API Key o JWT
3. Todas las queries filtran por `organization_id`
4. Índices compuestos para performance

**Ejemplo de Query Segura**:
```python
# ❌ INCORRECTO (sin tenant isolation)
workstation = db.query(Workstation).filter(
    Workstation.id == id
).first()

# ✅ CORRECTO (con tenant isolation)
workstation = db.query(Workstation).filter(
    Workstation.id == id,
    Workstation.organization_id == tenant.organization_id
).first()
```

### API Keys en Dos Niveles

**1. Organization API Key**:
- Formato: `org_bbva_xxxxxxxxxxxxxxxx`
- Uso: Registro inicial de workstations
- Permisos: Crear workstations, obtener configuración global

**2. Workstation API Key**:
- Formato: `ws_xxxxxxxxxxxxxxxx`
- Uso: Operaciones de la workstation (heartbeat, telemetría)
- Permisos: Solo acceso a datos de esa workstation específica

### Subdominios por Cliente

**Producción**:
- `https://bbva.alwaysprint.com` → Dashboard de BBVA
- `https://santander.alwaysprint.com` → Dashboard de Santander
- `https://api.alwaysprint.com` → API única para todos

**Desarrollo**:
- `http://localhost:3000` → Frontend
- `http://localhost:8000` → Backend

---

## Seguridad

### Autenticación

**Para Dispositivos (AlwaysPrintTray)**:
- Método: API Key en header `X-API-Key`
- Validación: Lookup en tabla `workstations`
- Extracción de tenant: `organization_id` de la workstation

**Para Administradores (Dashboard)**:
- Método: JWT en header `Authorization: Bearer <token>`
- Validación: Verificación de firma JWT
- Extracción de tenant: `organization_id` del usuario

### Comunicación

- ✅ HTTPS/TLS 1.3 obligatorio en producción
- ✅ Proxy corporativo soportado (detección automática)
- ✅ Rate limiting por API Key
- ✅ CORS configurado por dominio

### Datos

- ✅ Passwords hasheados con bcrypt
- ✅ API Keys generados con secrets.token_urlsafe()
- ✅ Logs anonimizados (sin PII)
- ✅ Auditoría de todas las acciones de admin

---

## Escalabilidad

### Capacidad por Configuración

| Configuración | Workstations | Clientes | Infraestructura |
|---------------|--------------|----------|-----------------|
| Básica | <5,000 | 1-10 | 1 servidor (4 CPU, 8GB RAM) |
| Estándar | 5,000-50,000 | 10-50 | Load balancer + 2-3 servidores |
| Enterprise | 50,000-200,000 | 50-200 | Kubernetes cluster |
| Global | 200,000+ | 200+ | Multi-region + CDN |

### Optimizaciones

**Base de Datos**:
- Índices compuestos en `(organization_id, ...)` para todas las tablas
- Particionamiento de tabla `telemetry` por `organization_id`
- Connection pooling (20 conexiones por defecto)

**Backend**:
- Caché de configuración con Redis (opcional)
- Async I/O con FastAPI
- Background tasks para procesamiento pesado

**Frontend**:
- Server-Side Rendering (SSR) con Next.js
- Static Generation para páginas públicas
- CDN para assets estáticos

---

## Despliegue

### Desarrollo

```bash
# Backend
cd AlwaysPrintCloudManager/backend
conda activate alwaysprint
uvicorn app.main:app --reload

# Frontend
cd AlwaysPrintCloudManager/frontend
npm run dev
```

### Producción

**Opción 1: Docker Compose**
```bash
cd AlwaysPrintCloudManager
docker-compose up -d
```

**Opción 2: Kubernetes**
```bash
kubectl apply -f k8s/
```

**Opción 3: Cloud Providers**
- AWS: ECS + RDS + CloudFront
- Azure: App Service + Azure Database + CDN
- GCP: Cloud Run + Cloud SQL + Cloud CDN

---

## Monitoreo

### Métricas Clave

**Dispositivos**:
- Total de workstations registradas
- Workstations online/offline
- Heartbeats por minuto
- Latencia de API

**Negocio**:
- Clientes activos
- Workstations por cliente
- Uso de recursos por cliente
- Tasa de crecimiento

### Herramientas

- **Logs**: Structured logging con timestamps
- **Métricas**: Prometheus + Grafana (opcional)
- **Alertas**: Email/Slack cuando workstation offline > 5 min
- **Uptime**: Health checks en `/health`

---

## Roadmap

### Fase 1: MVP (Actual)
- ✅ Backend FastAPI con multi-tenancy
- ✅ Frontend Next.js con dashboard básico
- ✅ Autenticación y tenant isolation
- ⏳ Integración con AlwaysPrintTray

### Fase 2: Producción
- ⏳ WebSocket para comandos en tiempo real
- ⏳ Analytics avanzados
- ⏳ Sistema de alertas
- ⏳ API pública para integraciones

### Fase 3: Enterprise
- ⏳ SSO (SAML, OAuth)
- ⏳ Multi-region deployment
- ⏳ SLA 99.9%
- ⏳ Soporte 24/7

---

## Referencias

- [Backend README](backend/README.md)
- [Frontend README](frontend/README.md)
- [API Documentation](backend/docs/API.md)
- [Deployment Guide](DEPLOYMENT.md)

---

## Contacto

**Robles.AI**  
Email: antonio@robles.ai  
Web: https://robles.ai

© 2026 Robles.AI - Todos los derechos reservados
