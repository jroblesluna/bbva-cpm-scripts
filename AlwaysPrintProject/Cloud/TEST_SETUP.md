# Test del Sistema de Setup Automático

**Fecha**: 9 de mayo de 2026

---

## ✅ Checklist de Pruebas

### Backend

- [x] Endpoint `/api/v1/setup/status` creado
- [x] Endpoint `/api/v1/setup/initialize` creado
- [x] Router agregado al router principal
- [x] Modelo Workstation corregido (relación con Message)

### Frontend

- [x] `setupApi` agregado al cliente API
- [x] Página `/setup` creada
- [x] Página principal (`/`) modificada para verificar setup
- [x] Página `/login` modificada para verificar setup
- [x] Hook `useWebSocket` corregido (tipos TypeScript)

---

## 🧪 Pasos de Prueba

### 1. Preparar Base de Datos Limpia

```powershell
# Ir al directorio backend
cd AlwaysPrintProject\Cloud\backend

# Activar entorno
conda activate alwaysprint

# Eliminar base de datos existente (si existe)
Remove-Item alwaysprint.db -ErrorAction SilentlyContinue

# Recrear base de datos
alembic upgrade head
```

### 2. Iniciar Backend

```powershell
# En el mismo directorio backend
uvicorn app.main:app --reload
```

**Verificar**:
- ✓ Backend inicia sin errores
- ✓ Mensaje: `INFO:     Uvicorn running on http://127.0.0.1:8000`

### 3. Probar Endpoint de Setup (Opcional)

Abrir http://127.0.0.1:8000/docs y probar:

1. **GET /api/v1/setup/status**
   - Debería retornar: `{"needs_setup": true, "message": "..."}`

2. **POST /api/v1/setup/initialize** (NO ejecutar aún, lo haremos desde el frontend)

### 4. Iniciar Frontend

Abrir **otra terminal**:

```powershell
# Ir al directorio frontend
cd AlwaysPrintProject\Cloud\frontend

# Iniciar servidor
npm run dev
```

**Verificar**:
- ✓ Frontend inicia sin errores
- ✓ Mensaje: `ready - started server on 0.0.0.0:3000`

### 5. Probar Flujo Completo

#### 5.1 Acceso Inicial

1. Abrir navegador en http://localhost:3000
2. **Verificar**: Muestra "Verificando configuración..."
3. **Verificar**: Redirige automáticamente a http://localhost:3000/setup

#### 5.2 Pantalla de Setup

**Verificar que se muestra**:
- ✓ Título: "Configuración Inicial"
- ✓ Descripción: "Bienvenido a AlwaysPrint Cloud Manager..."
- ✓ Formulario con 4 campos:
  - Nombre Completo
  - Correo Electrónico
  - Contraseña
  - Confirmar Contraseña
- ✓ Botón: "Crear Usuario Administrador"

#### 5.3 Crear Usuario Admin

1. **Completar formulario**:
   - Nombre Completo: `Administrador`
   - Correo Electrónico: `admin@ejemplo.com`
   - Contraseña: `admin123`
   - Confirmar Contraseña: `admin123`

2. **Click en "Crear Usuario Administrador"**

3. **Verificar**:
   - ✓ Botón cambia a "Creando usuario..."
   - ✓ Aparece mensaje de éxito con ícono verde
   - ✓ Mensaje: "¡Configuración Completada!"
   - ✓ Redirige automáticamente a `/login` después de 2 segundos

#### 5.4 Pantalla de Login

**Verificar que se muestra**:
- ✓ Título: "AlwaysPrint Cloud Manager"
- ✓ Formulario de login
- ✓ NO redirige a `/setup` (porque ya hay usuarios)

#### 5.5 Hacer Login

1. **Ingresar credenciales**:
   - Email: `admin@ejemplo.com`
   - Contraseña: `admin123`

2. **Click en "Iniciar sesión"**

3. **Verificar**:
   - ✓ Botón cambia a "Iniciando sesión..."
   - ✓ Redirige a `/dashboard`
   - ✓ Muestra dashboard con estadísticas
   - ✓ Sidebar muestra nombre del usuario: "Administrador"
   - ✓ Badge muestra: "Administrador" (rol)

#### 5.6 Verificar Protección de Setup

1. **Intentar acceder a** http://localhost:3000/setup

2. **Verificar**:
   - ✓ Muestra "Verificando configuración..."
   - ✓ Redirige automáticamente a `/login` o `/dashboard`
   - ✓ NO permite crear otro usuario admin

### 6. Probar Segundo Acceso

1. **Cerrar sesión** (botón en sidebar)
2. **Verificar**: Redirige a `/login`
3. **Cerrar navegador**
4. **Abrir navegador** en http://localhost:3000
5. **Verificar**: Redirige a `/login` (NO a `/setup`)

---

## 🎯 Resultados Esperados

### ✅ Flujo Exitoso

```
Usuario abre http://localhost:3000
    ↓
[Primera vez - Sin usuarios]
    ↓
Redirige a /setup
    ↓
Usuario completa formulario
    ↓
POST /api/v1/setup/initialize
    ↓
Usuario creado en DB
    ↓
Mensaje de éxito
    ↓
Redirige a /login (2 segundos)
    ↓
Usuario hace login
    ↓
Redirige a /dashboard
    ↓
✓ Sistema funcionando
```

### ✅ Flujo con Sistema Configurado

```
Usuario abre http://localhost:3000
    ↓
[Sistema ya configurado]
    ↓
GET /api/v1/setup/status → needs_setup: false
    ↓
Redirige a /login (si no autenticado)
    ↓
Usuario hace login
    ↓
Redirige a /dashboard
```

---

## 🐛 Errores Comunes

### Error: "El sistema ya está configurado"

**Causa**: Ya existe un usuario en la base de datos

**Solución**: 
1. Eliminar `alwaysprint.db`
2. Ejecutar `alembic upgrade head`
3. Reiniciar backend

### Error: "Cannot connect to backend"

**Causa**: Backend no está corriendo

**Solución**: Iniciar backend con `uvicorn app.main:app --reload`

### Error: Página en blanco

**Causa**: Error de JavaScript en el navegador

**Solución**: 
1. Abrir consola del navegador (F12)
2. Ver errores en la pestaña "Console"
3. Reportar el error

---

## 📊 Verificación en Base de Datos

```powershell
# Activar entorno
conda activate alwaysprint

# Abrir Python
python
```

```python
from app.core.database import SessionLocal
from app.models.user import User

db = SessionLocal()
users = db.query(User).all()

print(f"Total de usuarios: {len(users)}")
for user in users:
    print(f"  - {user.email} ({user.role}) - {user.full_name}")

db.close()
exit()
```

**Resultado esperado**:
```
Total de usuarios: 1
  - admin@ejemplo.com (UserRole.ADMIN) - Administrador
```

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
