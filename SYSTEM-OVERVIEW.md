# AlwaysPrint - Visión General del Sistema

Documentación ejecutiva del ecosistema completo AlwaysPrint.

**Fecha**: 8 de mayo de 2026  
**Versión**: 1.0

---

## 🎯 Descripción del Ecosistema

**AlwaysPrint** es un ecosistema de software empresarial para gestión de impresión corporativa, compuesto por:

1. **AlwaysPrint** (Cliente Windows) - Software instalado en workstations
2. **AlwaysPrint Cloud Manager** (Plataforma SaaS) - Gestión centralizada en la nube (opcional)

---

## 📦 Productos

### 1. AlwaysPrint (Cliente Windows)

**Ubicación**: `AlwaysPrintProject/Client/`  
**Tecnología**: C# .NET Framework 4.8  
**Plataforma**: Windows 10/11

**Componentes**:
- `AlwaysPrintService.exe` - Servicio Windows (LocalSystem, sin Internet)
- `AlwaysPrintTray.exe` - Aplicación de bandeja del sistema (Usuario, con Internet)
- `AlwaysPrint.msi` - Instalador WiX

**Funciones**:
- Monitoreo de colas de impresión Windows
- Gestión de redirección de puertos LPR
- Configuración local vía Registry
- Comunicación con Cloud Manager (opcional, vía Tray)

**Documentación**: [README](AlwaysPrintProject/Client/README.md)

---

### 2. AlwaysPrint Cloud Manager (Plataforma SaaS)

**Ubicación**: `AlwaysPrintProject/Cloud/`  
**Tecnología**: Python (FastAPI) + TypeScript (Next.js)  
**Plataforma**: Cloud (AWS/Azure/GCP)

**Componentes**:
- Backend FastAPI - API REST
- Frontend Next.js - Dashboard Web
- PostgreSQL - Base de datos multi-tenant

**Funciones**:
- Gestión centralizada de workstations
- Monitoreo en tiempo real (heartbeat cada 60s)
- Configuración remota
- Analytics y reportes
- Multi-tenancy (múltiples clientes)

**Documentación**: [README](AlwaysPrintProject/Cloud/README.md) | [Arquitectura](AlwaysPrintProject/Cloud/ARCHITECTURE.md)

---

## 🏗️ Arquitectura del Sistema Completo

```
┌─────────────────────────────────────────────────────────────┐
│                    CLIENTE: BBVA                             │
│  500 Workstations Windows 11                                │
│                                                              │
│  Cada workstation ejecuta:                                  │
│  ┌────────────────────────────────────────────────────┐    │
│  │  AlwaysPrintService.exe                            │    │
│  │  - LocalSystem (sin Internet)                      │    │
│  │  - Gestiona impresión local                        │    │
│  │  - Expone Named Pipe                               │    │
│  └────────────────┬───────────────────────────────────┘    │
│                   │ Named Pipe (IPC)                        │
│  ┌────────────────▼───────────────────────────────────┐    │
│  │  AlwaysPrintTray.exe                               │    │
│  │  - Usuario (con Internet vía proxy)                │    │
│  │  - Interfaz de usuario                             │    │
│  │  - Cliente HTTP para Cloud Manager                 │    │
│  └────────────────┬───────────────────────────────────┘    │
└───────────────────┼─────────────────────────────────────────┘
                    │
┌───────────────────┼─────────────────────────────────────────┐
│                    CLIENTE: Santander                        │
│  300 Workstations                                           │
└───────────────────┼─────────────────────────────────────────┘
                    │
                    │ HTTPS (vía Proxy Corporativo)
                    │ Authentication: API Key
                    │
┌───────────────────▼─────────────────────────────────────────┐
│              TU NUBE (Robles.AI)                             │
│              ALWAYSPRINT CLOUD MANAGER                       │
│              (SaaS Multi-Tenant)                             │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │  Backend FastAPI                                   │    │
│  │  https://api.alwaysprint.tudominio.com             │    │
│  │                                                     │    │
│  │  Endpoints para Dispositivos:                      │    │
│  │  - POST /api/v1/workstations/register              │    │
│  │  - POST /api/v1/workstations/{id}/heartbeat        │    │
│  │  - POST /api/v1/workstations/{id}/telemetry        │    │
│  │  - GET  /api/v1/workstations/{id}/config           │    │
│  │                                                     │    │
│  │  Endpoints para Administradores:                   │    │
│  │  - POST /api/v1/auth/login                         │    │
│  │  - GET  /api/v1/admin/workstations                 │    │
│  │  - PUT  /api/v1/admin/workstations/{id}/config     │    │
│  │  - GET  /api/v1/admin/analytics                    │    │
│  └────────────────────────┬───────────────────────────┘    │
│                           │                                 │
│  ┌────────────────────────▼───────────────────────────┐    │
│  │  Frontend Next.js                                  │    │
│  │  https://bbva.alwaysprint.tudominio.com            │    │
│  │  https://santander.alwaysprint.tudominio.com       │    │
│  │                                                     │    │
│  │  Dashboard Web para Administradores                │    │
│  └────────────────────────────────────────────────────┘    │
│                           │                                 │
│                    ┌──────▼──────┐                         │
│                    │  PostgreSQL │                         │
│                    │  Multi-Tenant│                        │
│                    └─────────────┘                         │
└──────────────────────────────────────────────────────────────┘
```

---

## 🔄 Flujo de Comunicación

### 1. Registro Inicial

```
1. Admin instala AlwaysPrint.msi en workstation
2. Instalador configura:
   - CloudEnabled = 1
   - CloudApiUrl = https://api.alwaysprint.com
   - CloudApiKey = org_bbva_xxxxxxxx (Organization API Key)
3. AlwaysPrintService se inicia y lanza AlwaysPrintTray
4. AlwaysPrintTray lee configuración cloud del Registry
5. Tray envía POST /api/v1/workstations/register
   Headers: X-API-Key: org_bbva_xxxxxxxx
6. Backend crea workstation y devuelve:
   - workstation_id: 123
   - api_key: ws_xxxxxxxx (Workstation API Key)
7. Tray guarda workstation_id y api_key en Registry
8. Tray inicia HeartbeatManager
```

### 2. Operación Normal

```
Cada 60 segundos:
  AlwaysPrintTray → POST /api/v1/workstations/123/heartbeat
  Headers: X-API-Key: ws_xxxxxxxx
  Backend actualiza last_seen y status = "online"

Cuando ocurre evento:
  AlwaysPrintService detecta evento (ej: cola activa)
  Service → Tray (Named Pipe): ReportTelemetry
  Tray → POST /api/v1/workstations/123/telemetry
  Backend almacena telemetría

Cada 5 minutos:
  Tray → GET /api/v1/workstations/123/config
  Si hay cambios:
    Tray → Service (Named Pipe): CloudConfigurationReceived
    Service aplica nueva configuración
```

### 3. Gestión desde Dashboard

```
Admin abre https://bbva.alwaysprint.com
Admin hace login (JWT)
Frontend muestra:
  - 500 workstations
  - 480 online, 20 offline
  - Gráficos de actividad

Admin cambia configuración de workstation 123
Frontend → PUT /api/v1/admin/workstations/123/config
Backend actualiza configuración en BD

En próximo polling (5 min):
  Tray → GET /api/v1/workstations/123/config
  Tray recibe nueva configuración
  Tray → Service: Aplicar cambios
```

---

## 🔐 Seguridad

### Autenticación en Dos Niveles

**1. Organization API Key** (Registro inicial):
- Formato: `org_bbva_xxxxxxxxxxxxxxxx`
- Uso: Solo para registrar nuevas workstations
- Almacenado en: `HKLM\SOFTWARE\Robles.AI\AlwaysPrint\CloudApiKey`
- Permisos: Crear workstations

**2. Workstation API Key** (Operaciones):
- Formato: `ws_xxxxxxxxxxxxxxxx`
- Uso: Heartbeat, telemetría, obtener config
- Almacenado en: `HKCU\SOFTWARE\Robles.AI\AlwaysPrint\Cloud\ApiKey`
- Permisos: Solo acceso a datos de esa workstation

**3. JWT** (Administradores):
- Uso: Dashboard web
- Almacenado en: localStorage del navegador
- Permisos: Según rol (admin, operator, viewer)

### Tenant Isolation

Todas las queries de base de datos filtran por `organization_id`:

```python
# ✅ CORRECTO
workstation = db.query(Workstation).filter(
    Workstation.id == id,
    Workstation.organization_id == tenant.organization_id
).first()
```

Esto garantiza que:
- BBVA solo ve sus workstations
- Santander solo ve sus workstations
- No hay data leakage entre clientes

---

## 📊 Multi-Tenancy

### Modelo de Datos

**Shared Schema**: Todas las organizaciones comparten las mismas tablas.

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

### Subdominios por Cliente

- `https://bbva.alwaysprint.com` → Dashboard de BBVA
- `https://santander.alwaysprint.com` → Dashboard de Santander
- `https://api.alwaysprint.com` → API única para todos

---

## 📈 Escalabilidad

| Workstations | Clientes | Infraestructura |
|--------------|----------|-----------------|
| <5,000 | 1-10 | 1 servidor (4 CPU, 8GB RAM) |
| 5,000-50,000 | 10-50 | Load balancer + 2-3 servidores |
| 50,000-200,000 | 50-200 | Kubernetes cluster |
| 200,000+ | 200+ | Multi-region + CDN |

---

## 🚀 Estado Actual

### ✅ Completado

**AlwaysPrint (Cliente Windows)**:
- ✅ AlwaysPrintService.exe funcionando
- ✅ AlwaysPrintTray.exe funcionando
- ✅ Instalador MSI con ProductCode fijo
- ✅ Named Pipe para IPC
- ✅ Gestión de impresión local

**AlwaysPrint Cloud Manager**:
- ✅ Backend FastAPI con multi-tenancy
- ✅ Frontend Next.js con dashboard básico
- ✅ Base de datos PostgreSQL/SQLite
- ✅ Autenticación (API Keys + JWT)
- ✅ Tenant isolation

### ⏳ Pendiente

**Integración**:
- ⏳ Agregar CloudApiClient a AlwaysPrintTray
- ⏳ Agregar HeartbeatManager a AlwaysPrintTray
- ⏳ Agregar nuevos MessageTypes al Named Pipe
- ⏳ Implementar endpoints de dispositivos en backend
- ⏳ Testing end-to-end

---

## 📚 Documentación

### AlwaysPrint (Cliente Windows)
- [README](AlwaysPrintProject/Client/README.md) - Documentación completa
- [AlwaysPrint.Shared](AlwaysPrintProject/Client/AlwaysPrint.Shared/README.md) - Biblioteca compartida
- [AlwaysPrintService](AlwaysPrintProject/Client/AlwaysPrintService/README.md) - Servicio Windows
- [AlwaysPrintTray](AlwaysPrintProject/Client/AlwaysPrintTray/README.md) - Aplicación de bandeja

### AlwaysPrint Cloud Manager (SaaS)
- [README](AlwaysPrintProject/Cloud/README.md) - Visión general
- [ARCHITECTURE](AlwaysPrintProject/Cloud/ARCHITECTURE.md) - Arquitectura detallada
- [Backend README](AlwaysPrintProject/Cloud/backend/README.md) - Backend FastAPI
- [Frontend README](AlwaysPrintProject/Cloud/frontend/README.md) - Frontend Next.js

---

## 🎯 Modelo de Negocio

### Plataforma SaaS

**AlwaysPrint Cloud Manager** es una plataforma SaaS multi-tenant que se vende a empresas.

**Pricing Sugerido**:
- $5/mes por workstation
- O planes por tier (1-100, 101-500, 501+ workstations)
- O precio fijo anual para enterprise

**Ejemplo**:
- Cliente con 500 workstations
- $5/mes × 500 = $2,500/mes = $30,000/año

### Instalación en Cliente

1. Cliente se registra en la plataforma
2. Recibe Organization API Key: `org_cliente_xxx`
3. Descarga `AlwaysPrint.msi` desde el portal
4. Instala en workstations con el Organization API Key
5. Workstations se registran automáticamente en la nube
6. Cliente accede a `https://cliente.alwaysprint.com` para gestionar

---

## 📞 Contacto

**Robles.AI**  
Email: antonio@robles.ai  
Web: https://robles.ai

© 2026 Robles.AI - Todos los derechos reservados

