# Troubleshooting - AlwaysPrint Backend

**Fecha**: 8 de mayo de 2026

---

## 🔧 Problemas de Instalación

### Error: "Falló la creación del entorno" con Conda

**Síntomas**:
```
[ERROR] Falló la creación del entorno
```

**Causas posibles**:
1. Conflictos de dependencias en conda-forge
2. Versión de conda desactualizada
3. Problemas de red al descargar paquetes

**Soluciones**:

#### Opción 1: Usar el script alternativo con venv

```powershell
# En lugar de setup-conda.ps1, usar:
.\setup-venv.ps1
```

Este script usa `venv` y `pip` directamente, evitando problemas de conda.

#### Opción 2: Instalación manual con conda

```powershell
# 1. Crear entorno básico
conda create -n alwaysprint python=3.12 pip -y

# 2. Activar entorno
conda activate alwaysprint

# 3. Instalar dependencias con pip
pip install -r requirements.txt

# 4. Configurar .env
copy .env.example .env

# 5. Aplicar migraciones
alembic upgrade head
```

#### Opción 3: Actualizar conda

```powershell
# Actualizar conda
conda update -n base conda

# Limpiar caché
conda clean --all

# Intentar de nuevo
.\setup-conda.ps1
```

### Error: "Python no está instalado"

**Síntomas**:
```
[ERROR] Python no está instalado o no está en el PATH
```

**Solución**:

1. Descargar Python 3.12+ desde https://www.python.org/downloads/
2. Durante la instalación, marcar "Add Python to PATH"
3. Reiniciar PowerShell
4. Verificar: `python --version`

### Error: "pip no está instalado"

**Solución**:

```powershell
# Instalar pip
python -m ensurepip --upgrade

# O descargar get-pip.py
curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
python get-pip.py
```

---

## 🗄️ Problemas de Base de Datos

### Error: "Database is locked" (SQLite)

**Síntomas**:
```
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) database is locked
```

**Causa**: SQLite no soporta múltiples escrituras concurrentes

**Soluciones**:

#### Opción 1: Usar PostgreSQL (Recomendado para producción)

```powershell
# Instalar PostgreSQL
# Descargar desde: https://www.postgresql.org/download/windows/

# Actualizar .env
DATABASE_URL=postgresql://user:password@localhost:5432/alwaysprint

# Aplicar migraciones
alembic upgrade head
```

#### Opción 2: Configurar SQLite para desarrollo

En `.env`:
```env
DATABASE_URL=sqlite:///./alwaysprint.db?check_same_thread=False
```

**Nota**: Solo para desarrollo, no usar en producción.

### Error: "No module named 'psycopg2'"

**Síntomas**:
```
ModuleNotFoundError: No module named 'psycopg2'
```

**Solución**:

```powershell
pip install psycopg2-binary
```

### Error: "Connection refused" (PostgreSQL)

**Síntomas**:
```
sqlalchemy.exc.OperationalError: could not connect to server
```

**Verificaciones**:

1. PostgreSQL está corriendo:
   ```powershell
   # Verificar servicio
   Get-Service postgresql*
   
   # Iniciar si está detenido
   Start-Service postgresql-x64-14
   ```

2. Credenciales correctas en `.env`:
   ```env
   DATABASE_URL=postgresql://user:password@localhost:5432/alwaysprint
   ```

3. Base de datos existe:
   ```sql
   -- Conectar a PostgreSQL
   psql -U postgres
   
   -- Crear base de datos
   CREATE DATABASE alwaysprint;
   ```

---

## 🔐 Problemas de Autenticación

### Error: "Token inválido o expirado"

**Síntomas**:
```json
{
  "detail": "Token inválido o expirado"
}
```

**Causas**:
1. Token expirado (después de 24 horas por defecto)
2. SECRET_KEY cambió
3. Token malformado

**Soluciones**:

1. Hacer login nuevamente para obtener nuevo token
2. Verificar que SECRET_KEY no haya cambiado en `.env`
3. Verificar formato del header:
   ```
   Authorization: Bearer <token>
   ```

### Error: "Email o contraseña incorrectos"

**Verificaciones**:

1. Usuario existe en la base de datos
2. Contraseña es correcta
3. Email está en minúsculas

**Crear usuario admin inicial**:

```python
# Ejecutar en Python shell
from app.core.database import SessionLocal
from app.services.auth import AuthService
from app.models.user import UserRole

db = SessionLocal()
auth_service = AuthService()

admin = auth_service.create_user(
    db=db,
    email="admin@example.com",
    password="admin123",
    full_name="Administrador",
    role=UserRole.ADMIN,
    account_id=None
)

db.close()
print(f"Usuario creado: {admin.email}")
```

---

## 🌐 Problemas de Red

### Error: "CORS policy blocked"

**Síntomas**:
```
Access to fetch at 'http://localhost:8000/api/v1/...' from origin 'http://localhost:3000' 
has been blocked by CORS policy
```

**Solución**:

Agregar origen en `.env`:
```env
CORS_ORIGINS=http://localhost:3000,http://localhost:8000,https://app.alwaysprint.com
```

### Error: "Connection refused" al conectar WebSocket

**Verificaciones**:

1. Servidor está corriendo
2. URL correcta: `ws://localhost:8000/ws/workstation`
3. Para HTTPS usar `wss://` en lugar de `ws://`

**Ejemplo de conexión**:

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/workstation');

ws.onopen = () => {
  console.log('Conectado');
  ws.send(JSON.stringify({
    type: 'register',
    ip_private: '192.168.1.100',
    hostname: 'PC-001'
  }));
};
```

---

## 🚀 Problemas de Ejecución

### Error: "Address already in use"

**Síntomas**:
```
ERROR: [Errno 10048] error while attempting to bind on address ('0.0.0.0', 8000)
```

**Causa**: Puerto 8000 ya está en uso

**Soluciones**:

#### Opción 1: Usar otro puerto

```powershell
uvicorn app.main:app --reload --port 8001
```

#### Opción 2: Matar proceso en puerto 8000

```powershell
# Encontrar proceso
netstat -ano | findstr :8000

# Matar proceso (reemplazar PID)
taskkill /PID <PID> /F
```

### Error: "ModuleNotFoundError"

**Síntomas**:
```
ModuleNotFoundError: No module named 'app'
```

**Causa**: Ejecutando desde directorio incorrecto

**Solución**:

```powershell
# Asegurarse de estar en el directorio backend
cd AlwaysPrintProject\Cloud\backend

# Ejecutar servidor
uvicorn app.main:app --reload
```

### Error: "ImportError: cannot import name"

**Causa**: Dependencias no instaladas o versiones incorrectas

**Solución**:

```powershell
# Reinstalar dependencias
pip install -r requirements.txt --upgrade
```

---

## 📝 Problemas de Migraciones

### Error: "Can't locate revision identified by"

**Síntomas**:
```
alembic.util.exc.CommandError: Can't locate revision identified by 'xxxxx'
```

**Causa**: Base de datos y migraciones desincronizadas

**Solución**:

```powershell
# Opción 1: Resetear base de datos (CUIDADO: Borra todos los datos)
# Eliminar archivo SQLite
Remove-Item alwaysprint.db

# O en PostgreSQL
# DROP DATABASE alwaysprint;
# CREATE DATABASE alwaysprint;

# Aplicar migraciones desde cero
alembic upgrade head

# Opción 2: Marcar como aplicada manualmente
alembic stamp head
```

### Error: "Target database is not up to date"

**Solución**:

```powershell
# Aplicar migraciones pendientes
alembic upgrade head

# Ver historial
alembic history

# Ver estado actual
alembic current
```

---

## 🔍 Debugging

### Habilitar logs detallados

En `.env`:
```env
LOG_LEVEL=DEBUG
```

### Ver logs en tiempo real

```powershell
# Si usas archivo de log
Get-Content logs\alwaysprint.log -Wait -Tail 50

# O con uvicorn
uvicorn app.main:app --reload --log-level debug
```

### Verificar configuración

```python
# Ejecutar en Python shell
from app.core.config import settings

print(f"DATABASE_URL: {settings.DATABASE_URL}")
print(f"SECRET_KEY: {settings.SECRET_KEY[:10]}...")
print(f"CORS_ORIGINS: {settings.CORS_ORIGINS}")
```

### Probar conexión a base de datos

```python
from app.core.database import SessionLocal

try:
    db = SessionLocal()
    print("Conexión exitosa")
    db.close()
except Exception as e:
    print(f"Error: {e}")
```

---

## 🆘 Obtener Ayuda

Si ninguna de estas soluciones funciona:

1. **Revisar logs**: `logs/alwaysprint.log`
2. **Verificar configuración**: `.env`
3. **Probar endpoints**: http://localhost:8000/health
4. **Documentación**: http://localhost:8000/docs

### Información útil para reportar problemas

```powershell
# Versión de Python
python --version

# Versiones de paquetes
pip list

# Sistema operativo
systeminfo | findstr /B /C:"OS Name" /C:"OS Version"

# Logs recientes
Get-Content logs\alwaysprint.log -Tail 100
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
