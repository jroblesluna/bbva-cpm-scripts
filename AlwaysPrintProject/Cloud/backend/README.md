# AlwaysPrint Cloud Management - Backend

**Versión**: 1.0.0  
**Framework**: FastAPI  
**Python**: 3.12+

---

## 📋 Descripción

Backend de AlwaysPrint Cloud Management, sistema de gestión centralizada para estaciones Windows que ejecutan AlwaysPrint Service y Tray Client.

### Características Principales

- ✅ **API REST** con 40+ endpoints
- ✅ **WebSocket** para comunicación en tiempo real (operadores y workstations)
- ✅ **Multi-cuenta** con aislamiento estricto por `account_id`
- ✅ **Autenticación JWT** con roles (Admin, Operador)
- ✅ **Configuración jerárquica** (Global → VLAN → Workstation)
- ✅ **Password reset** vía AWS SES (token 1h)
- ✅ **Auditoría completa** de operaciones
- ✅ **Rate limiting** y headers de seguridad
- ✅ **Documentación automática** (Swagger/OpenAPI)

---

## 🚀 Inicio Rápido

### Requisitos Previos

- Python 3.12 o superior
- PostgreSQL 14+ (o SQLite para desarrollo)
- Redis (opcional, para rate limiting en producción)

### Instalación

```bash
# Crear entorno conda
conda create -n alwaysprint python=3.12
conda activate alwaysprint

# Instalar dependencias
pip install -r requirements.txt

# Configurar variables de entorno
cp .env.example .env
# Editar .env con la configuración local

# Aplicar migraciones
alembic upgrade head
```

**Nota**: Si encuentras problemas, consulta `docs/TROUBLESHOOTING.md`

### Acceso

- **API**: http://localhost:8000
- **Documentación**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

---

## 📁 Estructura del Proyecto

```
backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── endpoints/       # Endpoints REST (8 módulos)
│   │       ├── websocket/       # Endpoints WebSocket
│   │       └── router.py        # Router principal
│   ├── core/
│   │   ├── config.py           # Configuración
│   │   ├── database.py         # Conexión a DB
│   │   └── security.py         # JWT y permisos
│   ├── middleware/
│   │   ├── rate_limit.py       # Rate limiting
│   │   └── security_headers.py # Headers de seguridad
│   ├── models/                 # Modelos SQLAlchemy (8 modelos)
│   ├── schemas/                # Schemas Pydantic (64 schemas)
│   ├── services/               # Lógica de negocio (5 servicios)
│   └── main.py                 # Punto de entrada
├── alembic/
│   └── versions/               # Migraciones de DB
├── docs/
│   └── TLS_SSL_SETUP.md       # Guía de configuración TLS
├── tests/                      # Tests (por implementar)
├── .env.example               # Ejemplo de variables de entorno
├── alembic.ini                # Configuración de Alembic
├── requirements.txt           # Dependencias Python
└── README.md                  # Este archivo
```

---

## 🔧 Configuración

### Variables de Entorno

Crear archivo `.env` en la raíz del backend:

```env
# === GENERAL ===
PROJECT_NAME=AlwaysPrint Cloud Management
VERSION=1.0.0
API_V1_STR=/api/v1

# === BASE DE DATOS ===
# SQLite (desarrollo)
DATABASE_URL=sqlite:///./alwaysprint.db

# PostgreSQL (producción)
# DATABASE_URL=postgresql://user:password@localhost:5432/alwaysprint

# === SEGURIDAD ===
SECRET_KEY=CHANGE_THIS_IN_PRODUCTION_TO_A_SECURE_RANDOM_STRING
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# === CORS ===
CORS_ORIGINS=http://localhost:3000,http://localhost:8000

# === REDIS (OPCIONAL) ===
# REDIS_URL=redis://localhost:6379/0

# === LOGGING ===
LOG_LEVEL=INFO
LOG_FILE=logs/alwaysprint.log

# === WEBSOCKET ===
WS_PING_INTERVAL=30
WS_PING_TIMEOUT=60
WS_MAX_CONNECTIONS=5000

# === RATE LIMITING ===
RATE_LIMIT_LOGIN=5
RATE_LIMIT_API=100
```

### Generar SECRET_KEY

```python
import secrets
print(secrets.token_urlsafe(32))
```

---

## 📊 Base de Datos

### Migraciones con Alembic

```bash
# Crear nueva migración
alembic revision --autogenerate -m "descripción del cambio"

# Aplicar migraciones
alembic upgrade head

# Revertir última migración
alembic downgrade -1

# Ver historial
alembic history

# Ver estado actual
alembic current
```

### Modelos de Datos

El sistema incluye 8 modelos principales:

1. **User**: Usuarios del sistema (Admin, Operador)
2. **Account**: Cuentas multi-tenant
3. **PublicIP**: IPs públicas para identificación de cuentas
4. **Workstation**: Estaciones Windows
5. **License**: Licencias de workstations
6. **VLAN**: Segmentos de red
7. **Config**: Configuración jerárquica (Global, VLAN, Workstation)
8. **Message**: Mensajes a workstations
9. **AuditLog**: Registro de auditoría

---

## 🔐 Autenticación y Autorización

### Roles

- **Admin**: Acceso completo a todas las cuentas
- **Operador**: Acceso solo a su cuenta asignada

### Flujo de Autenticación

1. **Login**: `POST /api/v1/auth/login`
   ```json
   {
     "email": "user@example.com",
     "password": "password123"
   }
   ```

2. **Respuesta**:
   ```json
   {
     "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
     "token_type": "bearer",
     "expires_in": 3600
   }
   ```

3. **Usar Token**:
   ```
   Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
   ```

### Crear Usuario Admin Inicial

```python
# Ejecutar en Python shell
from app.core.database import SessionLocal
from app.services.auth import AuthService
from app.models.user import UserRole

db = SessionLocal()
auth_service = AuthService()

# Crear admin
admin = auth_service.create_user(
    db=db,
    email="admin@example.com",
    password="admin123",
    full_name="Administrador",
    role=UserRole.ADMIN,
    account_id=None
)

db.close()
```

---

## 🌐 API REST

### Endpoints Principales

#### Autenticación (`/api/v1/auth/`)
- `POST /login` - Login de usuario
- `POST /logout` - Logout
- `GET /me` - Usuario actual
- `POST /password-reset` - Solicitar reset (envía email con token vía SES)
- `POST /password-reset/confirm` - Confirmar reset con token (expira en 1h)

#### Cuentas (`/api/v1/accounts/`) - Solo Admin
- `GET /` - Listar cuentas
- `POST /` - Crear cuenta
- `GET /{id}` - Obtener cuenta
- `PUT /{id}` - Actualizar cuenta
- `DELETE /{id}` - Eliminar cuenta
- `POST /{id}/public-ips` - Agregar IP pública

#### Usuarios (`/api/v1/users/`)
- `GET /` - Listar usuarios
- `POST /` - Crear usuario
- `GET /{id}` - Obtener usuario
- `PUT /{id}` - Actualizar usuario
- `DELETE /{id}` - Eliminar usuario
- `PUT /{id}/password` - Cambiar contraseña

#### Workstations (`/api/v1/workstations/`)
- `GET /` - Listar workstations (con filtros)
- `GET /stats` - Estadísticas
- `GET /{id}` - Obtener workstation
- `PUT /{id}` - Actualizar workstation
- `GET /{id}/config` - Configuración efectiva
- `PUT /{id}/config` - Actualizar configuración
- `DELETE /{id}/config` - Eliminar override

#### VLANs (`/api/v1/vlans/`)
- `GET /` - Listar VLANs
- `POST /` - Crear VLAN
- `GET /{id}` - Obtener VLAN
- `PUT /{id}` - Actualizar VLAN
- `DELETE /{id}` - Eliminar VLAN
- `GET /{id}/workstations` - Workstations de VLAN
- `GET /{id}/config` - Configuración de VLAN

#### Configuración (`/api/v1/config/`)
- `GET /global` - Configuración global
- `PUT /global` - Actualizar configuración global

#### Mensajes (`/api/v1/messages/`)
- `GET /` - Listar mensajes
- `POST /` - Enviar mensaje
- `GET /stats` - Estadísticas
- `GET /{id}` - Obtener mensaje

#### Auditoría (`/api/v1/audit/`)
- `GET /` - Buscar logs
- `GET /stats` - Estadísticas
- `GET /recent` - Actividad reciente
- `GET /{id}` - Obtener log

### Documentación Interactiva

Acceder a http://localhost:8000/docs para:
- Ver todos los endpoints
- Probar endpoints directamente
- Ver schemas de request/response
- Autenticarse con JWT

---

## 🔌 WebSocket

### Endpoint para Tray Clients

**URL**: `ws://localhost:8000/ws/workstation`

**Mensajes Workstation → Backend**:
- `register`: Registro inicial
- `pong`: Respuesta a ping
- `status_update`: Actualización de estado
- `config_change_report`: Reporte de cambio de config
- `command_result`: Resultado de comando

**Mensajes Backend → Workstation**:
- `ping`: Verificación de conexión (cada 30s)
- `config_change`: Notificación de cambio de config
- `command`: Comando a ejecutar
- `notification`: Notificación para el usuario

### Endpoint para Frontend

**URL**: `ws://localhost:8000/ws/operator?token=<JWT>`

**Mensajes Backend → Operator**:
- `workstation_connected`: Workstation conectada
- `workstation_disconnected`: Workstation desconectada
- `contingency_toggle`: Cambio de estado de contingencia
- `message_delivered`: Mensaje entregado
- `command_result`: Resultado de comando
- `connection_stats`: Estadísticas de conexiones

---

## 🛡️ Seguridad

### Rate Limiting

- **Login**: 5 intentos por minuto
- **API General**: 100 peticiones por minuto

Headers de respuesta:
- `X-RateLimit-Limit`: Límite máximo
- `X-RateLimit-Remaining`: Peticiones restantes
- `X-RateLimit-Reset`: Timestamp de reset

### Headers de Seguridad

Todos los responses incluyen:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Content-Security-Policy: default-src 'self'`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), microphone=(), camera=()`

### TLS/SSL

Ver `docs/TLS_SSL_SETUP.md` para configuración en producción.

---

## 🧪 Testing

```bash
# Instalar dependencias de testing
pip install pytest pytest-asyncio pytest-cov httpx

# Ejecutar tests
pytest

# Con cobertura
pytest --cov=app --cov-report=html

# Tests específicos
pytest tests/test_auth.py
```

---

## 📈 Monitoreo

### Health Check

```bash
curl http://localhost:8000/health
```

### WebSocket Status

```bash
curl http://localhost:8000/ws/status
```

### Logs

```bash
# Ver logs en tiempo real
tail -f logs/alwaysprint.log

# Buscar errores
grep ERROR logs/alwaysprint.log
```

---

## 🚀 Deployment

### Producción (Docker Compose en EC2)

El deployment en producción es automático vía GitHub Actions. Al hacer push a `main`:
1. Build de imagen Docker y push a ECR
2. `aws ssm send-command` ejecuta `deploy.sh backend` en el EC2

**Importante**: Producción usa **siempre 1 worker** — el `ConnectionManager` de WebSocket
es un singleton en memoria. Múltiples workers rompen el broadcast entre conexiones.

```bash
# En el EC2 (vía sesión SSM)
cd /opt/alwaysprint
docker compose restart backend

# Ver logs
docker logs alwaysprint-backend-1 --tail 50 -f
```

### Docker (imagen de producción)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# 1 worker — requerido por WebSocket singleton
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

---

## 🐛 Troubleshooting

### Error: "Database is locked" (SQLite)

**Causa**: SQLite no soporta concurrencia alta  
**Solución**: Usar PostgreSQL en producción

### Error: "Too Many Connections"

**Causa**: Pool de conexiones agotado  
**Solución**: Aumentar `DB_POOL_SIZE` en configuración

### Error: "WebSocket connection failed"

**Causa**: Proxy no configurado correctamente  
**Solución**: Verificar headers `Upgrade` y `Connection` en Nginx

### Error: "Rate limit exceeded"

**Causa**: Demasiadas peticiones desde misma IP  
**Solución**: Esperar o aumentar límites en configuración

---

## 📚 Documentación Adicional

- **Arquitectura**: `../ARCHITECTURE.md`
- **TLS/SSL Setup**: `docs/TLS_SSL_SETUP.md`
- **Troubleshooting**: `docs/TROUBLESHOOTING.md`
- **API Specification**: http://localhost:8000/docs
- **Changelog**: `CHANGELOG.md`

---

## 🤝 Contribución

1. Fork el repositorio
2. Crear branch de feature (`git checkout -b feature/nueva-funcionalidad`)
3. Commit cambios (`git commit -am 'Agregar nueva funcionalidad'`)
4. Push al branch (`git push origin feature/nueva-funcionalidad`)
5. Crear Pull Request

---

## 📞 Soporte

**Robles.AI**  
Email: antonio@robles.ai  
Teléfono: +1 408 590 0153  
Web: https://robles.ai

---

## 📄 Licencia

© 2026 Inversiones On Line SAC - Todos los derechos reservados  
Producto de la familia de automatización Robles.AI  
Prohibida la utilización sin autorización de Inversiones On Line SAC
