# Flujo de Autorización de IPs Públicas

## Estado: ✅ IMPLEMENTADO

---

## Resumen

Se ha implementado un sistema de autorización de IPs públicas que permite que los clientes Windows se conecten desde IPs desconocidas, registrándolas automáticamente como "pendientes de autorización" para que un administrador las apruebe posteriormente.

---

## Flujo Completo

### 1. Cliente Intenta Conectarse

```
Cliente Windows → WebSocket ws://backend:8000/ws/workstation
  ↓
Envía mensaje de registro:
{
  "type": "register",
  "ip_private": "192.168.1.100",
  "hostname": "DESKTOP-ABC123",
  "os_serial": "XXXXX-XXXXX",
  "current_user": "usuario@dominio.com"
}
```

### 2. Backend Detecta IP Pública

```
Backend detecta IP pública del cliente: 200.48.225.10
  ↓
Busca en tabla public_ips:
  - ¿Existe la IP?
    - NO → Crear registro con is_authorized=False
    - SÍ → ¿Está autorizada?
      - SÍ → Permitir conexión
      - NO → Rechazar conexión
```

### 3. Respuesta al Cliente

**Si IP NO autorizada:**
```
WebSocket cierra con código 1008:
"IP pública 200.48.225.10 no está autorizada. 
Un administrador debe autorizar esta IP antes de que puedas conectarte. 
La IP ha sido registrada y está pendiente de autorización."
```

**Si IP autorizada:**
```
WebSocket acepta conexión
  ↓
Registra workstation en base de datos
  ↓
Envía configuración efectiva
  ↓
Mantiene conexión bidireccional
```

### 4. Administrador Autoriza IP

**Dashboard → Organizaciones → IPs Pendientes**

```
GET /api/v1/accounts/public-ips/pending
  ↓
Muestra lista de IPs pendientes:
  - IP: 200.48.225.10
  - Primera vez vista: 2026-05-10 01:30:00
  - Descripción: "Detectada automáticamente..."
  
Administrador selecciona:
  - Cuenta a asignar: BBVA
  - Descripción: "Oficina Principal Lima"
  
POST /api/v1/accounts/public-ips/{ip_id}/authorize
{
  "account_id": "uuid-de-bbva",
  "description": "Oficina Principal Lima"
}
  ↓
IP actualizada:
  - is_authorized = true
  - account_id = uuid-de-bbva
  - authorized_at = 2026-05-10 01:35:00
```

### 5. Cliente Reintenta Conexión

```
Cliente intenta conectarse nuevamente
  ↓
Backend verifica IP pública: 200.48.225.10
  ↓
IP está autorizada → Permite conexión
  ↓
Workstation registrada exitosamente
  ↓
Aparece en Dashboard → Estaciones
```

---

## Cambios en Base de Datos

### Modelo `PublicIP` Actualizado

```python
class PublicIP(Base):
    id = Column(GUID, primary_key=True)
    account_id = Column(GUID, nullable=True)  # NULL hasta autorizar
    ip_address = Column(String(45), unique=True, nullable=False)
    description = Column(String(500), nullable=True)
    
    # Nuevos campos
    is_authorized = Column(Boolean, default=False, index=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    authorized_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
```

### Migración Aplicada

```bash
alembic upgrade head
# Aplicada: 003_add_public_ip_auth
```

---

## Endpoints Nuevos

### 1. Listar IPs Pendientes

```http
GET /api/v1/accounts/public-ips/pending
Authorization: Bearer {admin_token}

Response 200:
[
  {
    "id": "uuid",
    "ip_address": "200.48.225.10",
    "description": "Detectada automáticamente el 2026-05-10 01:30:00",
    "first_seen": "2026-05-10T01:30:00Z",
    "created_at": "2026-05-10T01:30:00Z"
  }
]
```

### 2. Autorizar IP

```http
POST /api/v1/accounts/public-ips/{ip_id}/authorize
Authorization: Bearer {admin_token}
Content-Type: application/json

{
  "account_id": "uuid-de-cuenta",
  "description": "Oficina Principal Lima"
}

Response 200:
{
  "id": "uuid",
  "ip_address": "200.48.225.10",
  "account_id": "uuid-de-cuenta",
  "description": "Oficina Principal Lima",
  "is_authorized": true,
  "first_seen": "2026-05-10T01:30:00Z",
  "authorized_at": "2026-05-10T01:35:00Z",
  "created_at": "2026-05-10T01:30:00Z"
}
```

### 3. Rechazar IP

```http
DELETE /api/v1/accounts/public-ips/{ip_id}/reject
Authorization: Bearer {admin_token}

Response 204: No Content
```

---

## Servicio `WorkstationService` Actualizado

### Método `register_or_queue_public_ip()`

```python
def register_or_queue_public_ip(db, public_ip) -> tuple[Optional[Account], bool]:
    """
    Registra una IP pública o la pone en cola de autorización.
    
    Returns:
        (account, is_authorized)
        - account: Account si está autorizada, None si pendiente
        - is_authorized: True si autorizada, False si pendiente
    """
```

### Método `register_workstation()` Actualizado

```python
def register_workstation(...) -> tuple[Optional[Workstation], bool, str]:
    """
    Returns:
        (workstation, is_new, status)
        - workstation: Workstation o None si IP no autorizada
        - is_new: True si es nueva
        - status: "authorized", "pending", "inactive_account"
    """
```

---

## WebSocket Actualizado

### Manejo de Estados

```python
workstation, is_new, status = workstation_service.register_workstation(...)

if status == "pending":
    await websocket.close(
        code=1008,
        reason="IP pública no autorizada. Pendiente de autorización."
    )
    return

elif status == "inactive_account":
    await websocket.close(
        code=1008,
        reason="La cuenta asociada está desactivada."
    )
    return

elif status == "authorized":
    # Continuar con conexión normal
    workstation_id = str(workstation.id)
    await connection_manager.connect_workstation(...)
```

---

## Schemas Pydantic Nuevos

### `PublicIPPendingResponse`

```python
class PublicIPPendingResponse(BaseModel):
    id: UUID
    ip_address: str
    description: Optional[str]
    first_seen: datetime
    created_at: datetime
```

### `PublicIPAuthorizeRequest`

```python
class PublicIPAuthorizeRequest(BaseModel):
    account_id: UUID
    description: Optional[str]
```

### `PublicIPResponse` Actualizado

```python
class PublicIPResponse(BaseModel):
    id: UUID
    account_id: Optional[UUID]  # Puede ser NULL si pendiente
    ip_address: str
    description: Optional[str]
    is_authorized: bool
    first_seen: datetime
    authorized_at: Optional[datetime]
    created_at: datetime
```

---

## Auditoría

Todas las acciones de autorización/rechazo se registran en `audit_logs`:

```python
audit_service.log_action(
    action_type="update",
    entity_type="PublicIP",
    entity_id=str(public_ip.id),
    user_id=str(current_user.id),
    account_id=str(account_id),
    old_values={"is_authorized": False, "account_id": None},
    new_values={"is_authorized": True, "account_id": str(account_id)}
)
```

---

## Frontend (Pendiente)

### Página de IPs Pendientes

**Ruta:** `/dashboard/admin/pending-ips`

**Componentes:**
- Lista de IPs pendientes con fecha de primera detección
- Botón "Autorizar" que abre modal para seleccionar cuenta
- Botón "Rechazar" para eliminar la IP
- Filtros por fecha
- Búsqueda por IP

**Funcionalidades:**
- Ver IPs pendientes en tiempo real
- Autorizar asignando a una cuenta
- Rechazar y eliminar
- Ver historial de autorizaciones en auditoría

---

## Testing

### Casos de Prueba

1. **Cliente con IP nueva:**
   - ✅ IP se registra como pendiente
   - ✅ Cliente recibe mensaje de rechazo
   - ✅ IP aparece en lista de pendientes

2. **Administrador autoriza IP:**
   - ✅ IP se marca como autorizada
   - ✅ Se asigna a cuenta
   - ✅ Se registra en auditoría

3. **Cliente reintenta con IP autorizada:**
   - ✅ Conexión aceptada
   - ✅ Workstation registrada
   - ✅ Aparece en dashboard

4. **Administrador rechaza IP:**
   - ✅ IP eliminada de base de datos
   - ✅ Se registra en auditoría

---

## Archivos Modificados

### Backend

1. `app/models/account.py` - Modelo PublicIP actualizado
2. `alembic/versions/003_add_public_ip_authorization.py` - Migración
3. `app/services/workstation.py` - Lógica de autorización
4. `app/api/v1/websocket/workstation.py` - Manejo de estados
5. `app/api/v1/endpoints/accounts.py` - Endpoints de autorización
6. `app/schemas/account.py` - Schemas nuevos

### Frontend (Pendiente)

- Página de IPs pendientes
- Componentes de autorización
- Integración con API

---

## Próximos Pasos

1. **Frontend:**
   - [ ] Crear página `/dashboard/admin/pending-ips`
   - [ ] Componente de lista de IPs pendientes
   - [ ] Modal de autorización
   - [ ] Notificaciones en tiempo real

2. **Mejoras:**
   - [ ] Notificación automática a admins cuando hay IP nueva
   - [ ] Dashboard widget con contador de IPs pendientes
   - [ ] Historial de intentos de conexión por IP
   - [ ] Geolocalización de IPs (opcional)

---

**Fecha de Implementación**: 2026-05-10  
**Estado**: Backend 100% completo, Frontend pendiente
