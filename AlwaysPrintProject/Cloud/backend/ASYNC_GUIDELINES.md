# Guía de Uso de Async/Await en FastAPI con SQLAlchemy

**Fecha**: 10 de mayo de 2026  
**Estado**: Reglas obligatorias para todos los endpoints

---

## ❌ NO Usar `async def` Cuando:

1. **Usas SQLAlchemy síncrono** (que es nuestro caso)
   ```python
   # ❌ INCORRECTO
   @router.get("/users/")
   async def list_users(db: Session = Depends(get_db)):
       users = db.query(User).all()  # SQLAlchemy síncrono
       return users
   ```

2. **Llamas a servicios síncronos**
   ```python
   # ❌ INCORRECTO
   @router.post("/users/")
   async def create_user(data: UserCreate, db: Session = Depends(get_db)):
       audit_service = AuditService()
       audit_service.log_create(...)  # Método síncrono
   ```

3. **No hay operaciones I/O asíncronas**
   ```python
   # ❌ INCORRECTO
   @router.get("/stats")
   async def get_stats(db: Session = Depends(get_db)):
       count = db.query(User).count()  # Operación síncrona
       return {"count": count}
   ```

---

## ✅ SÍ Usar `async def` Cuando:

1. **WebSockets** (siempre async)
   ```python
   # ✅ CORRECTO
   @router.websocket("/ws/workstation")
   async def workstation_websocket(websocket: WebSocket):
       await websocket.accept()
       await websocket.send_json({"status": "connected"})
   ```

2. **Usas SQLAlchemy async** (AsyncSession)
   ```python
   # ✅ CORRECTO (si usáramos AsyncSession)
   @router.get("/users/")
   async def list_users(db: AsyncSession = Depends(get_async_db)):
       result = await db.execute(select(User))
       users = result.scalars().all()
       return users
   ```

3. **Llamas a APIs externas con httpx/aiohttp**
   ```python
   # ✅ CORRECTO
   @router.get("/external-data")
   async def get_external_data():
       async with httpx.AsyncClient() as client:
           response = await client.get("https://api.example.com/data")
           return response.json()
   ```

---

## 📋 Regla General para Este Proyecto

**Usamos SQLAlchemy SÍNCRONO**, por lo tanto:

### ✅ Endpoints Normales: `def` (sin async)
```python
@router.get("/users/")
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return users
```

### ✅ WebSockets: `async def`
```python
@router.websocket("/ws/workstation")
async def workstation_websocket(websocket: WebSocket):
    await websocket.accept()
```

---

## 🔧 Cómo Corregir Endpoints Incorrectos

### Antes (Incorrecto):
```python
@router.get("/users/")
async def list_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    
    audit_service = AuditService()
    await audit_service.log_action(...)  # ❌ await en método síncrono
    
    return users
```

### Después (Correcto):
```python
@router.get("/users/")
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    
    audit_service = AuditService()
    audit_service.log_action(...)  # ✅ Sin await
    
    return users
```

---

## 🚨 Problemas Comunes

### 1. Usar `await` con métodos síncronos
```python
# ❌ INCORRECTO
async def my_endpoint():
    result = await db.query(User).all()  # db.query() no es awaitable
```

### 2. Mezclar async/sync incorrectamente
```python
# ❌ INCORRECTO
async def my_endpoint():
    users = db.query(User).all()  # Operación síncrona en función async
    await some_async_function()   # Operación async
```

### 3. Servicios que no existen
```python
# ❌ INCORRECTO
async def my_endpoint():
    service = WorkstationService()  # Este servicio no existe
    result = await service.get_data()
```

---

## 📝 Checklist para Nuevos Endpoints

Antes de crear un endpoint, pregúntate:

- [ ] ¿Uso SQLAlchemy síncrono? → `def` (sin async)
- [ ] ¿Es un WebSocket? → `async def`
- [ ] ¿Llamo a servicios síncronos? → `def` (sin async)
- [ ] ¿Todos los métodos que llamo son síncronos? → `def` (sin async)
- [ ] ¿Uso `await` en algún lugar? → Verifica que sea realmente async

---

## 🎯 Estado Actual del Proyecto

### ✅ Archivos Corregidos
- `app/api/v1/endpoints/auth.py` - Todos los endpoints son `def`
- `app/api/v1/endpoints/users.py` - Todos los endpoints son `def`
- `app/api/v1/endpoints/accounts.py` - Todos los endpoints son `def`
- `app/api/v1/endpoints/workstations.py` - Parcialmente corregido

### ⏳ Archivos Pendientes de Corrección
- `app/api/v1/endpoints/vlans.py` - Todos los endpoints usan `async def` incorrectamente
- `app/api/v1/endpoints/messages.py` - Todos los endpoints usan `async def` incorrectamente
- `app/api/v1/endpoints/config.py` - Todos los endpoints usan `async def` incorrectamente
- `app/api/v1/endpoints/audit.py` - Todos los endpoints usan `async def` incorrectamente

### ✅ Archivos Correctos (WebSockets)
- `app/api/v1/websocket/workstation.py` - Correcto (WebSocket debe ser async)
- `app/api/v1/websocket/operator.py` - Correcto (WebSocket debe ser async)

---

## 📚 Referencias

- [FastAPI Async/Await](https://fastapi.tiangolo.com/async/)
- [SQLAlchemy Async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Python Async/Await](https://docs.python.org/3/library/asyncio.html)

---

**Robles.AI**  
Email: antonio@robles.ai  
Teléfono: +1 408 590 0153  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados
