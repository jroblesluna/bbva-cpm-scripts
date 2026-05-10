# Guía de Desarrollo - AlwaysPrint Cloud

Guía completa para desarrolladores que trabajan en AlwaysPrint Cloud Manager.

## 📋 Tabla de Contenidos

- [Configuración del Entorno](#configuración-del-entorno)
- [Estructura del Código](#estructura-del-código)
- [Convenciones de Código](#convenciones-de-código)
- [Flujos de Trabajo](#flujos-de-trabajo)
- [Testing](#testing)
- [Debugging](#debugging)
- [Base de Datos](#base-de-datos)
- [API](#api)
- [Frontend](#frontend)
- [Deployment](#deployment)

---

## 🛠️ Configuración del Entorno

### Backend (Python/FastAPI)

#### Requisitos

- Python 3.12+
- Conda (recomendado) o venv
- PostgreSQL 14+ (producción) o SQLite (desarrollo)

#### Setup

```bash
cd backend

# Crear entorno conda
conda create -n alwaysprint python=3.12
conda activate alwaysprint

# Instalar dependencias
pip install -r requirements.txt

# Configurar .env
cp .env.example .env
```

#### Variables de Entorno (.env)

```bash
# Base de datos
DATABASE_URL=sqlite:///./alwaysprint.db  # Desarrollo
# DATABASE_URL=postgresql://user:pass@localhost:5432/alwaysprint  # Producción

# Seguridad
SECRET_KEY=dev-secret-key-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# CORS
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# Aplicación
PROJECT_NAME=AlwaysPrint Cloud Manager
VERSION=1.0.0
ENVIRONMENT=development
```

#### Inicializar Base de Datos

```bash
# Crear migración inicial
alembic upgrade head

# Crear usuario admin (opcional)
# Usar endpoint /api/v1/setup/initialize desde el frontend
```

#### Ejecutar Servidor

```bash
# Modo desarrollo (con reload)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Modo producción
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Frontend (Next.js/TypeScript)

#### Requisitos

- Node.js 18+
- npm o yarn

#### Setup

```bash
cd frontend

# Instalar dependencias
npm install

# Configurar .env.local
cp .env.example .env.local
```

#### Variables de Entorno (.env.local)

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
```

#### Ejecutar Servidor

```bash
# Modo desarrollo
npm run dev

# Build de producción
npm run build
npm start
```

---

## 📁 Estructura del Código

### Backend

```
backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── api.py              # Router principal
│   │       └── endpoints/          # Endpoints por entidad
│   │           ├── auth.py         # Autenticación
│   │           ├── users.py        # Gestión de usuarios
│   │           ├── accounts.py     # Gestión de organizaciones
│   │           ├── workstations.py # Gestión de workstations
│   │           ├── vlans.py        # Gestión de VLANs
│   │           ├── messages.py     # Mensajería
│   │           ├── audit.py        # Auditoría
│   │           └── config.py       # Configuración
│   │
│   ├── core/
│   │   ├── config.py               # Configuración de la app
│   │   ├── database.py             # Conexión a BD
│   │   └── security.py             # JWT, bcrypt, dependencias
│   │
│   ├── models/                     # Modelos SQLAlchemy
│   │   ├── user.py
│   │   ├── account.py
│   │   ├── workstation.py
│   │   ├── vlan.py
│   │   ├── message.py
│   │   ├── audit_log.py
│   │   └── config.py
│   │
│   ├── schemas/                    # Schemas Pydantic
│   │   ├── user.py
│   │   ├── account.py
│   │   ├── workstation.py
│   │   ├── vlan.py
│   │   ├── message.py
│   │   ├── audit.py
│   │   └── config.py
│   │
│   ├── services/                   # Lógica de negocio
│   │   ├── audit_service.py        # Servicio de auditoría
│   │   └── ip_authorization.py     # Autorización de IPs
│   │
│   └── main.py                     # Punto de entrada
│
├── alembic/                        # Migraciones
│   ├── versions/                   # Archivos de migración
│   └── env.py
│
└── tests/                          # Tests pytest
    ├── conftest.py                 # Fixtures
    ├── test_auth.py
    ├── test_users.py
    └── ...
```

### Frontend

```
frontend/
├── src/
│   ├── app/                        # Next.js 15 App Router
│   │   ├── layout.tsx              # Layout principal
│   │   ├── page.tsx                # Página de inicio
│   │   ├── login/                  # Autenticación
│   │   ├── setup/                  # Setup inicial
│   │   └── dashboard/              # Dashboard
│   │       ├── page.tsx            # Dashboard principal
│   │       ├── workstations/       # Gestión de workstations
│   │       ├── vlans/              # Gestión de VLANs
│   │       ├── messages/           # Mensajería
│   │       ├── audit/              # Auditoría
│   │       ├── config/             # Configuración
│   │       └── admin/              # Administración
│   │           ├── accounts/       # Gestión de organizaciones
│   │           ├── users/          # Gestión de usuarios
│   │           └── pending-ips/    # Autorización de IPs
│   │
│   ├── components/
│   │   └── ui/                     # Componentes UI (shadcn/ui)
│   │       ├── button.tsx
│   │       ├── card.tsx
│   │       ├── input.tsx
│   │       └── ...
│   │
│   ├── hooks/                      # Custom hooks
│   │   ├── useAuth.ts              # Autenticación
│   │   ├── useWebSocket.ts         # WebSocket (futuro)
│   │   └── useWorkstations.ts      # Workstations
│   │
│   ├── lib/
│   │   ├── api.ts                  # Cliente API (axios)
│   │   └── utils.ts                # Utilidades
│   │
│   └── types/                      # Tipos TypeScript
│       ├── index.ts                # Exportaciones
│       ├── user.ts
│       ├── account.ts
│       ├── workstation.ts
│       ├── vlan.ts
│       ├── message.ts
│       ├── audit.ts
│       └── config.ts
│
└── public/                         # Archivos estáticos
```

---

## 📝 Convenciones de Código

### Backend (Python)

#### Estilo

- **PEP 8** para estilo de código
- **Type hints** en todas las funciones
- **Docstrings** en español para funciones públicas
- **Nombres en inglés** para variables y funciones

```python
from typing import List, Optional
from sqlalchemy.orm import Session

def get_users(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    account_id: Optional[str] = None
) -> List[User]:
    """
    Obtener lista de usuarios con paginación.
    
    Args:
        db: Sesión de base de datos
        skip: Número de registros a saltar
        limit: Número máximo de registros
        account_id: Filtrar por cuenta (opcional)
    
    Returns:
        Lista de usuarios
    """
    query = db.query(User)
    if account_id:
        query = query.filter(User.account_id == account_id)
    return query.offset(skip).limit(limit).all()
```

#### Modelos SQLAlchemy

```python
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
import uuid
from datetime import datetime

class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # admin, operator
    account_id = Column(String, ForeignKey("accounts.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relaciones
    account = relationship("Account", back_populates="users")
```

#### Schemas Pydantic

```python
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    role: str

class UserCreate(UserBase):
    password: str = Field(..., min_length=8)
    account_id: Optional[str] = None

class UserResponse(UserBase):
    id: str
    account_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True
```

#### Endpoints

```python
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

router = APIRouter()

@router.get("/", response_model=List[UserResponse])
def list_users(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Listar usuarios (solo Admin).
    """
    users = get_users(db, skip=skip, limit=limit)
    return users
```

### Frontend (TypeScript/React)

#### Estilo

- **TypeScript estricto** (no `any` sin justificación)
- **Componentes funcionales** con hooks
- **Nombres en inglés** para componentes y funciones
- **Comentarios en español** para lógica compleja

```typescript
import { useState, useEffect } from 'react'
import { User } from '@/types'
import { api } from '@/lib/api'

interface UserListProps {
  accountId?: string
}

export function UserList({ accountId }: UserListProps) {
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  
  useEffect(() => {
    const loadUsers = async () => {
      try {
        setLoading(true)
        const data = await api.users.list({ account_id: accountId })
        setUsers(data.items)
      } catch (err) {
        setError('Error al cargar usuarios')
      } finally {
        setLoading(false)
      }
    }
    
    loadUsers()
  }, [accountId])
  
  if (loading) return <div>Cargando...</div>
  if (error) return <div>Error: {error}</div>
  
  return (
    <div>
      {users.map(user => (
        <div key={user.id}>{user.full_name}</div>
      ))}
    </div>
  )
}
```

#### Tipos TypeScript

```typescript
// types/user.ts
export interface User {
  id: string
  email: string
  full_name: string
  role: 'admin' | 'operator'
  account_id: string | null
  created_at: string
  updated_at: string
}

export interface UserCreate {
  email: string
  full_name: string
  password: string
  role: 'admin' | 'operator'
  account_id?: string
}

export interface UserListResponse {
  items: User[]
  total: number
  skip: number
  limit: number
}
```

---

## 🔄 Flujos de Trabajo

### Autenticación

1. Usuario envía credenciales a `/api/v1/auth/login`
2. Backend valida credenciales y genera JWT
3. Frontend almacena token en localStorage
4. Frontend incluye token en header `Authorization: Bearer <token>`
5. Backend valida token en cada request protegido

### Autorización de IPs Públicas

1. Workstation intenta conectar desde IP pública
2. Backend verifica si IP está autorizada para la organización
3. Si no está autorizada, crea registro en `pending_public_ips`
4. Admin ve IP pendiente en dashboard
5. Admin autoriza o rechaza IP
6. Workstation puede conectar si IP fue autorizada

### Gestión de Workstations

1. Workstation se registra con `/api/v1/workstations/register`
2. Backend crea registro y asigna a VLAN según IP
3. Workstation reporta estado periódicamente con `/api/v1/workstations/{id}/heartbeat`
4. Operador puede ver estado en dashboard
5. Operador puede enviar mensajes/comandos
6. Workstation recibe y ejecuta comandos

---

## 🧪 Testing

### Backend

```bash
cd backend

# Ejecutar todos los tests
pytest

# Test específico
pytest tests/test_auth.py

# Con cobertura
pytest --cov=app --cov-report=html

# Modo verbose
pytest -v

# Solo tests marcados
pytest -m "not slow"
```

#### Estructura de Tests

```python
# tests/conftest.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.database import Base
from app.main import app

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient
    return TestClient(app)

# tests/test_auth.py
def test_login_success(client, db):
    # Crear usuario de prueba
    response = client.post("/api/v1/setup/initialize", json={
        "email": "admin@test.com",
        "password": "password123",
        "full_name": "Admin Test"
    })
    
    # Login
    response = client.post("/api/v1/auth/login", json={
        "email": "admin@test.com",
        "password": "password123"
    })
    
    assert response.status_code == 200
    assert "access_token" in response.json()
```

### Frontend

```bash
cd frontend

# Ejecutar tests
npm run test

# Modo watch
npm run test:watch

# Build de producción (verifica TypeScript)
npm run build
```

---

## 🐛 Debugging

### Backend

#### Logs

```python
import logging

logger = logging.getLogger(__name__)

@router.post("/")
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    logger.info(f"Creating user: {user.email}")
    try:
        # ...
        logger.info(f"User created successfully: {new_user.id}")
        return new_user
    except Exception as e:
        logger.error(f"Error creating user: {str(e)}")
        raise
```

#### Debugger (VS Code)

```json
// .vscode/launch.json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: FastAPI",
      "type": "python",
      "request": "launch",
      "module": "uvicorn",
      "args": [
        "app.main:app",
        "--reload",
        "--host",
        "0.0.0.0",
        "--port",
        "8000"
      ],
      "jinja": true
    }
  ]
}
```

### Frontend

#### Console Logs

```typescript
console.log('User data:', user)
console.error('Error loading users:', error)
console.warn('Token expiring soon')
```

#### React DevTools

- Instalar extensión React DevTools
- Inspeccionar componentes y estado
- Ver props y hooks

---

## 💾 Base de Datos

### Migraciones con Alembic

```bash
# Crear nueva migración
alembic revision --autogenerate -m "Add new column"

# Aplicar migraciones
alembic upgrade head

# Revertir última migración
alembic downgrade -1

# Ver historial
alembic history

# Ver SQL sin ejecutar
alembic upgrade head --sql
```

### Modelo de Datos

Ver [ARCHITECTURE.md](./ARCHITECTURE.md) para diagrama completo del modelo de datos.

---

## 🚀 Deployment

### Docker

```bash
# Backend
cd backend
docker build -t alwaysprint-backend .
docker run -p 8000:8000 alwaysprint-backend

# Frontend
cd frontend
docker build -t alwaysprint-frontend .
docker run -p 3000:3000 alwaysprint-frontend
```

### Terraform (AWS)

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

Ver [README.md](./README.md) para más detalles de deployment.

---

## 📚 Recursos Adicionales

- **FastAPI**: https://fastapi.tiangolo.com/
- **Next.js**: https://nextjs.org/docs
- **SQLAlchemy**: https://docs.sqlalchemy.org/
- **Pydantic**: https://docs.pydantic.dev/
- **TypeScript**: https://www.typescriptlang.org/docs/
- **shadcn/ui**: https://ui.shadcn.com/

---

**Última actualización:** 2026-01-10
