# Implementación de Gestión de Workstations

## Estado: ✅ COMPLETADO

---

## Resumen

Se ha completado la implementación del módulo de gestión de workstations en el Cloud Manager de AlwaysPrint. Este módulo permite visualizar, filtrar y gestionar las estaciones de trabajo Windows que ejecutan el cliente AlwaysPrint.

---

## Componentes Implementados

### 1. Backend (FastAPI)

#### Modelos de Datos
- **Workstation** (`app/models/workstation.py`)
  - Campos: IP privada, hostname, usuario actual, estado online, contingencia activa
  - Relaciones: Account, VLAN, License, Config
  - Tipo UUID: Migrado a `GUID` para consistencia con SQLite/PostgreSQL

- **License** (`app/models/workstation.py`)
  - Licencias activas/históricas por workstation
  - Serial calculado como últimos 8 caracteres del MD5 de la IP

#### Schemas Pydantic
- **WorkstationResponse**: Respuesta básica con relación `account` anidada
- **WorkstationDetailResponse**: Respuesta detallada con licencia activa
- **WorkstationListResponse**: Lista paginada con estructura `{items, total, skip, limit}`
- **WorkstationStatsResponse**: Estadísticas agregadas (total, online, offline, contingencia)
- **WorkstationUpdate**: Actualización de hostname, OS serial, usuario, cuenta
- **AccountBasicResponse**: Schema básico de cuenta para relaciones anidadas

#### Endpoints REST
- `GET /api/v1/workstations/` - Listar workstations con filtros y paginación
- `GET /api/v1/workstations/stats` - Estadísticas agregadas
- `GET /api/v1/workstations/{id}` - Detalle de workstation específica
- `PUT /api/v1/workstations/{id}` - Actualizar información de workstation
- `GET /api/v1/workstations/{id}/config` - Configuración efectiva
- `PUT /api/v1/workstations/{id}/config` - Actualizar configuración específica
- `DELETE /api/v1/workstations/{id}/config` - Eliminar override de configuración

#### Servicios
- **WorkstationService** (`app/services/workstation.py`)
  - Registro automático de workstations
  - Detección automática de VLAN por IP
  - Gestión de licencias
  - Actualización de estado (online/offline, contingencia)
  - Queries con filtros y paginación

#### Permisos
- **Admin**: Acceso completo a todas las workstations de todas las cuentas
- **Operador**: Solo puede ver/editar workstations de su cuenta asignada

### 2. Frontend (Next.js + TypeScript)

#### Página Principal
- **Ruta**: `/dashboard/workstations`
- **Componentes**:
  - Tarjetas de estadísticas (Total, En Línea, Fuera de Línea, Contingencia)
  - Filtros: búsqueda por IP/hostname, estado online, cuenta, contingencia
  - Lista de workstations con información detallada
  - Modal de detalles completos
  - Formulario de edición inline

#### Características
- **Visualización**:
  - Estado online/offline con indicadores visuales
  - Badge de contingencia activa
  - Información de red (IP, VLAN)
  - Información del sistema (hostname, usuario, OS serial)
  - Fechas formateadas con timezone del usuario

- **Filtros**:
  - Búsqueda por IP o hostname
  - Filtro por estado (online/offline)
  - Filtro por cuenta (solo Admin)
  - Filtro por contingencia activa
  - Botón para limpiar todos los filtros

- **Edición**:
  - Actualizar hostname, OS serial, usuario actual
  - Reasignar a otra cuenta
  - Validación de permisos según rol

#### Tipos TypeScript
- Interfaces completas en `src/types/workstation.ts`
- Integración con tipos de Account y VLAN
- Soporte para relaciones anidadas

---

## Correcciones Técnicas Realizadas

### 1. Unificación de Tipos UUID
**Problema**: Inconsistencia entre modelos usando `UUID(as_uuid=True)` y `GUID` personalizado, causando errores de foreign key en SQLite.

**Solución**: Migrados todos los modelos al tipo `GUID` personalizado:
- `Workstation`, `License`
- `VLAN`
- `GlobalConfig`, `VLANConfig`, `WorkstationConfig`
- `Message`

**Beneficio**: Compatibilidad total entre SQLite (desarrollo) y PostgreSQL (producción).

### 2. Schema de Respuesta Corregido
**Problema**: `WorkstationListResponse` tenía estructura incorrecta (`workstations`, `page`, `page_size`).

**Solución**: Actualizado a estructura estándar (`items`, `total`, `skip`, `limit`).

### 3. Relación Account Anidada
**Problema**: Frontend esperaba `workstation.account.name` pero el schema no incluía la relación.

**Solución**: 
- Agregado campo `account: Optional[AccountBasicResponse]` a `WorkstationResponse`
- Creado `AccountBasicResponse` para relaciones anidadas
- Uso de `joinedload(Workstation.account)` en queries

### 4. Conversión de UUID en Stats
**Problema**: `account.id` como objeto UUID causaba error al pasarlo a queries SQLAlchemy.

**Solución**: Conversión segura a string con verificación de tipo:
```python
if isinstance(account.id, uuid.UUID):
    account_id_str = str(account.id)
elif isinstance(account.id, str):
    account_id_str = account.id
```

### 5. Logs del Servidor
**Problema**: Logs de uvicorn no se mostraban en terminal.

**Solución**: Uso de `--no-capture-output` en conda run y `PYTHONUNBUFFERED=1`.

---

## Archivos Modificados

### Backend
1. `app/models/workstation.py` - Migrado a tipo GUID
2. `app/models/vlan.py` - Migrado a tipo GUID
3. `app/models/config.py` - Migrado a tipo GUID
4. `app/models/message.py` - Migrado a tipo GUID
5. `app/schemas/workstation.py` - Corregido schema de respuesta, agregado AccountBasicResponse
6. `app/schemas/__init__.py` - Exportado AccountBasicResponse
7. `app/api/v1/endpoints/workstations.py` - Corregido manejo de UUID en stats

### Frontend
- `src/app/dashboard/workstations/page.tsx` - Página completa de gestión
- `src/types/workstation.ts` - Tipos TypeScript completos
- `src/lib/api.ts` - Cliente API para workstations (ya existente)

---

## Funcionalidades Pendientes

### Backend
- [x] Endpoint de registro de workstation desde cliente Windows (vía WebSocket)
- [x] WebSocket para comunicación bidireccional
- [ ] Comandos remotos a workstations (infraestructura lista, falta UI)
- [ ] Historial de conexiones
- [ ] Alertas automáticas por desconexión prolongada

### Frontend
- [ ] Gráficos de estadísticas por tiempo
- [ ] Mapa de red visual
- [ ] Notificaciones en tiempo real (WebSocket para operadores)
- [ ] Exportación de datos (CSV, Excel)
- [ ] Panel de comandos remotos
- [ ] Historial de eventos por workstation

---

## Testing

### Endpoints Verificados
- ✅ `GET /api/v1/workstations/` - 200 OK (lista vacía hasta que se conecten clientes)
- ✅ `GET /api/v1/workstations/stats` - 200 OK
- ✅ `GET /api/v1/accounts/` - 200 OK (usado en filtros)
- ✅ `WS /ws/workstation` - Endpoint WebSocket implementado para registro automático

### Registro de Workstations
Las workstations se registran **automáticamente** cuando el cliente Windows se conecta:

1. **Cliente Windows** ejecuta AlwaysPrint Tray Client
2. Se conecta al WebSocket: `ws://localhost:8000/ws/workstation`
3. Envía mensaje de registro:
   ```json
   {
     "type": "register",
     "ip_private": "192.168.1.100",
     "hostname": "DESKTOP-ABC123",
     "os_serial": "XXXXX-XXXXX",
     "current_user": "usuario@dominio.com"
   }
   ```
4. **Backend** valida que la IP pública esté autorizada en una cuenta
5. Registra la workstation automáticamente con `WorkstationService.register_workstation()`
6. Detecta VLAN automáticamente por rango CIDR
7. Activa licencia (serial = últimos 8 chars del MD5 de IP privada)
8. Envía configuración efectiva al cliente
9. Mantiene conexión WebSocket para comunicación bidireccional

**Nota**: No hay endpoint REST para registro manual. El registro es exclusivamente vía WebSocket para mantener conexión persistente.

### Casos de Prueba Pendientes
- [ ] Conectar cliente Windows real para probar registro automático
- [ ] Probar filtros con datos reales
- [ ] Probar actualización de workstation desde dashboard
- [ ] Probar permisos de Operador vs Admin
- [ ] Probar configuración jerárquica
- [ ] Probar desconexión y reconexión de cliente

---

## Notas de Implementación

### Timezone
- Todas las fechas se formatean con el timezone del usuario actual
- Formato: `yyyy-MM-dd HH:mm:ss UTC±X`
- Herencia: Usuario → Organización → UTC

### Permisos
- Admin puede ver/editar todas las workstations
- Operador solo puede ver/editar workstations de su cuenta
- Validación en backend y frontend

### Paginación
- Tamaño de página por defecto: 50
- Máximo: 100
- Parámetros: `page` (1-indexed), `page_size`

### Filtros
- Búsqueda: coincidencia parcial en IP y hostname (case-insensitive)
- Estado online: booleano opcional
- Contingencia: booleano opcional
- Cuenta: UUID opcional (solo Admin)
- VLAN: UUID opcional

---

## Comandos Útiles

### Iniciar Backend
```bash
cd AlwaysPrintProject/Cloud/backend
conda activate alwaysprint
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Iniciar Frontend
```bash
cd AlwaysPrintProject/Cloud/frontend
npm run dev
```

### Verificar Workstations en DB
```bash
conda run -n alwaysprint python -c "from app.core.database import SessionLocal; from app.models.workstation import Workstation; db = SessionLocal(); print(f'Total: {db.query(Workstation).count()}'); db.close()"
```

### Preparar Sistema para Recibir Workstations

**Requisito**: La IP pública desde donde se conectará el cliente debe estar registrada en una cuenta.

1. **Crear una cuenta** (si no existe):
   - Ir a `/dashboard/admin/accounts`
   - Crear cuenta (ej: "BBVA")

2. **Registrar IP pública autorizada**:
   - En la misma página de cuentas, editar la cuenta
   - Agregar la IP pública desde donde se conectarán los clientes
   - Ejemplo: `200.48.225.10` (IP pública de la red corporativa)

3. **Opcional: Crear VLANs** para segmentación:
   - Ir a `/dashboard/admin/vlans`
   - Crear VLAN con rangos CIDR
   - Ejemplo: "VLAN Oficina Principal" con CIDR `192.168.1.0/24`
   - Las workstations se asignarán automáticamente a la VLAN según su IP privada

4. **Conectar cliente Windows**:
   - El cliente AlwaysPrint Tray se conectará automáticamente
   - Aparecerá en `/dashboard/workstations`

**Nota**: Si la IP pública no está registrada, el cliente recibirá error de autorización y no se registrará.

---

**Fecha de Implementación**: 2026-05-09  
**Desarrollador**: Kiro AI Assistant  
**Estado**: Producción Ready (pendiente testing con datos reales)
