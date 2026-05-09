# AlwaysPrint Project

Sistema de contingencia complementario para gestión de impresión corporativa con arquitectura cliente-servidor.

**Versión**: 1.0.0  
**Última actualización**: 8 de mayo de 2026

---

## 📋 Descripción

**AlwaysPrint Project** es un sistema de contingencia que complementa el sistema de producción estándar (Lexmark CPM + CUPS), proporcionando:

1. **Mecanismo de contingencia** - Cuando el sistema principal no está disponible
2. **Gestión centralizada** - Monitoreo y configuración remota de workstations
3. **Visibilidad operacional** - Analytics y reportes complementarios

**Componentes**:

1. **Client** - Software Windows instalado en workstations como contingencia
2. **Cloud Manager** - Plataforma SaaS multi-tenant para gestión centralizada (opcional)

**Relación con el sistema de producción**:
- ✅ **COMPLEMENTA** el sistema Lexmark CPM + CUPS (no lo reemplaza)
- ✅ **COEXISTE** con el sistema de producción en las workstations
- ✅ **ACTIVA** como contingencia cuando el sistema principal falla
- ✅ **PROPORCIONA** gestión centralizada y monitoreo adicional

---

## 🏗️ Estructura del Proyecto

```
AlwaysPrintProject/
├── Cloud/                      # Plataforma SaaS (Backend + Frontend)
│   ├── backend/               # FastAPI (Python 3.12)
│   ├── frontend/              # Next.js 15 (TypeScript)
│   ├── docker-compose.yml     # Orquestación de servicios
│   ├── ARCHITECTURE.md        # Arquitectura detallada
│   └── README.md              # Documentación Cloud Manager
│
├── Client/                     # Software Windows (C# .NET 4.8)
│   ├── AlwaysPrint.Shared/    # Biblioteca compartida
│   ├── AlwaysPrintService/    # Servicio Windows
│   ├── AlwaysPrintTray/       # Aplicación de bandeja
│   ├── CustomActions/         # Custom actions para MSI
│   ├── Installer/             # Scripts de instalación
│   ├── dist/                  # Binarios compilados
│   ├── AlwaysPrint.sln        # Solución Visual Studio
│   ├── Product.wxs            # Definición instalador WiX
│   ├── build.ps1              # Script de compilación
│   └── README.md              # Documentación Client
│
└── README.md                   # Este archivo
```

---

## 🚀 Quick Start

### Cloud Manager (Plataforma SaaS)

```bash
cd Cloud

# Backend
cd backend
conda env create -f environment.yml
conda activate alwaysprint
alembic upgrade head
uvicorn app.main:app --reload

# Frontend (en otra terminal)
cd frontend
npm install
npm run dev
```

Ver [Cloud/README.md](Cloud/README.md) para más detalles.

### Client (Software Windows)

```powershell
cd Client

# Compilar y crear MSI
.\build.ps1

# Instalar
msiexec /i AlwaysPrint.msi /qn /L*v install.log
```

Ver [Client/README.md](Client/README.md) para más detalles.

---

## 🔄 Arquitectura del Sistema Completo

```
┌─────────────────────────────────────────────────────────────┐
│                    WORKSTATION WINDOWS                       │
│  AlwaysPrint Client (Service + Tray)                        │
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
│  └────────────────────────┬───────────────────────────────┘  │
│                           │                                   │
│  ┌────────────────────────▼───────────────────────────────┐  │
│  │  Frontend (Next.js)                                    │  │
│  │  - Dashboard web para administradores                  │  │
│  └────────────────────────────────────────────────────────┘  │
│                           │                                   │
│                    ┌──────▼──────┐                           │
│                    │  PostgreSQL │                           │
│                    └─────────────┘                           │
└───────────────────────────────────────────────────────────────┘
```

---

## 📚 Documentación

### General
- [SYSTEM-OVERVIEW.md](../SYSTEM-OVERVIEW.md) - Visión general del ecosistema completo

### Cloud Manager
- [Cloud/README.md](Cloud/README.md) - Instalación y configuración
- [Cloud/ARCHITECTURE.md](Cloud/ARCHITECTURE.md) - Arquitectura detallada
- [Cloud/backend/README.md](Cloud/backend/README.md) - Backend FastAPI
- [Cloud/frontend/README.md](Cloud/frontend/README.md) - Frontend Next.js

### Client
- [Client/README.md](Client/README.md) - Instalación y configuración
- [Client/AlwaysPrint.Shared/README.md](Client/AlwaysPrint.Shared/README.md) - Biblioteca compartida
- [Client/AlwaysPrintService/README.md](Client/AlwaysPrintService/README.md) - Servicio Windows
- [Client/AlwaysPrintTray/README.md](Client/AlwaysPrintTray/README.md) - Aplicación de bandeja

---

## 🎯 Características Principales

### Cloud Manager (SaaS)
- ✅ Multi-tenancy con tenant isolation
- ✅ Monitoreo en tiempo real (heartbeat cada 60s)
- ✅ Configuración remota de workstations
- ✅ Analytics y reportes
- ✅ Subdominios por cliente
- ✅ API Keys en dos niveles (Organization + Workstation)
- ✅ Escalable hasta 200,000+ workstations

### Client (Windows)
- ✅ Servicio Windows (LocalSystem, sin Internet)
- ✅ Aplicación de bandeja (Usuario, con Internet)
- ✅ Comunicación vía Named Pipe (IPC local)
- ✅ Gestión automática de sesión (logon/logoff)
- ✅ Integración opcional con Cloud Manager
- ✅ Instalador MSI con ProductCode fijo
- ✅ Modo consola para debugging
- ✅ **Mecanismo de contingencia** para el sistema de producción

---

## 🔄 Integración con Sistema de Producción

### Sistema de Producción (Lexmark CPM + CUPS)
- **Ubicación**: `Linux Server/` y `Workstations/`
- **Función**: Sistema principal de impresión corporativa
- **Estado**: Producción activa

### AlwaysPrint (Contingencia Complementaria)
- **Ubicación**: `AlwaysPrintProject/`
- **Función**: Contingencia + gestión centralizada
- **Estado**: Complementario al sistema principal

**Flujo de Operación**:
```
1. Sistema principal (Lexmark CPM) → Operación normal
2. Si CPM falla → AlwaysPrint Client actúa como contingencia
3. Cloud Manager → Monitoreo continuo de ambos sistemas
4. Dashboard → Visibilidad unificada de toda la infraestructura
```

---

## 🔐 Seguridad

### Cloud Manager
- ✅ HTTPS/TLS 1.3 obligatorio
- ✅ Autenticación: API Keys + JWT
- ✅ Tenant isolation (filtrado por organization_id)
- ✅ Rate limiting por API Key
- ✅ Passwords hasheados con bcrypt

### Client
- ✅ Servicio sin acceso a Internet (LocalSystem)
- ✅ Named Pipe con DACL correcto
- ✅ Validación de configuración
- ✅ Logs estructurados con Event IDs
- ✅ Proxy corporativo soportado

---

## 📈 Escalabilidad

| Workstations | Clientes | Infraestructura |
|--------------|----------|-----------------|
| <5,000 | 1-10 | 1 servidor (4 CPU, 8GB RAM) |
| 5,000-50,000 | 10-50 | Load balancer + 2-3 servidores |
| 50,000-200,000 | 50-200 | Kubernetes cluster |
| 200,000+ | 200+ | Multi-region + CDN |

---

## 🛠️ Tecnologías

### Cloud Manager
- **Backend**: Python 3.12, FastAPI, SQLAlchemy, Alembic, PostgreSQL
- **Frontend**: Next.js 15, TypeScript, React 18, Tailwind CSS, shadcn/ui

### Client
- **Framework**: .NET Framework 4.8
- **Lenguaje**: C# 9
- **Build**: .NET SDK 8+, WiX Toolset v4
- **Plataforma**: Windows 10/11

---

## 📝 Estado del Proyecto

### ✅ Completado
- ✅ Client: Service, Tray, Named Pipe, instalador MSI
- ✅ Cloud Manager: Backend multi-tenant, Frontend dashboard
- ✅ Documentación completa
- ✅ Build system automatizado

### ⏳ En Desarrollo
- ⏳ Integración Cloud en Client (CloudApiClient, HeartbeatManager)
- ⏳ Endpoints de dispositivos en Backend
- ⏳ Testing end-to-end

---

## 📞 Contacto

**Robles.AI**  
Email: antonio@robles.ai  
Teléfono: +1 408 590 0153  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados  
Producto de la familia de automatización Robles.AI  
Prohibida la utilización sin autorización de Inversiones On Line SAC
