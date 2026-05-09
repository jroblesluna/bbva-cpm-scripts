# AlwaysPrint Cloud Manager - Backend

Backend FastAPI para la gestión centralizada del sistema de impresión AlwaysPrint.

## Requisitos

- **Conda** (Miniconda o Anaconda) - [Descargar aquí](https://docs.conda.io/en/latest/miniconda.html)

O alternativamente:
- **Python 3.11 o 3.12** + pip actualizado

⚠️ **Nota**: Se recomienda usar Conda para evitar problemas de compatibilidad en Windows.

## Instalación Rápida

### Opción 1: Con Conda (Recomendado)

#### Windows
```bash
# Ejecutar script automático
setup-conda.bat
```

#### Linux/Mac
```bash
# Dar permisos de ejecución
chmod +x setup-conda.sh

# Ejecutar script automático
./setup-conda.sh
```

#### Manual con Conda
```bash
# Crear entorno con Python 3.12
conda env create -f environment.yml

# Activar entorno
conda activate alwaysprint

# Configurar variables de entorno
copy .env.example .env  # Windows
# cp .env.example .env  # Linux/Mac

# Inicializar base de datos
alembic upgrade head

# Ejecutar servidor
uvicorn app.main:app --reload
```

### Opción 2: Con pip/venv

⚠️ Requiere Python 3.11 o 3.12 instalado

#### Windows

```bash
# 1. Crear entorno virtual
python -m venv venv

# 2. Activar entorno virtual
venv\Scripts\activate

# 3. Actualizar pip
python -m pip install --upgrade pip

# 4. Instalar dependencias
pip install -r requirements.txt

# 5. Configurar variables de entorno
copy .env.example .env

# 6. Inicializar base de datos
alembic upgrade head

# 7. Ejecutar servidor
uvicorn app.main:app --reload
```

#### Linux/Mac

```bash
# 1. Crear entorno virtual
python3 -m venv venv

# 2. Activar entorno virtual
source venv/bin/activate

# 3. Actualizar pip
python -m pip install --upgrade pip

# 4. Instalar dependencias
pip install -r requirements.txt

# 5. Configurar variables de entorno
cp .env.example .env

# 6. Inicializar base de datos
alembic upgrade head

# 7. Ejecutar servidor
uvicorn app.main:app --reload
```

## Base de Datos

Por defecto usa **SQLite** (archivo `alwaysprint.db`), ideal para desarrollo.

Para producción con PostgreSQL:
1. Instalar: `pip install psycopg2-binary`
2. Configurar `DATABASE_URL` en `.env`

## Estructura del Proyecto

```
backend/
├── app/
│   ├── api/          # Endpoints REST y WebSocket
│   ├── core/         # Configuración y base de datos
│   ├── models/       # Modelos SQLAlchemy
│   ├── schemas/      # Esquemas Pydantic
│   ├── services/     # Lógica de negocio
│   └── main.py       # Punto de entrada
├── alembic/          # Migraciones de BD
├── tests/            # Tests unitarios e integración
└── requirements.txt  # Dependencias Python
```

## Comandos Útiles

```bash
# Ejecutar tests
pytest

# Crear nueva migración
alembic revision --autogenerate -m "descripción"

# Aplicar migraciones
alembic upgrade head

# Revertir última migración
alembic downgrade -1

# Ver estado de migraciones
alembic current

# Formatear código (si instalaste black)
black app/

# Linter (si instalaste ruff)
ruff check app/
```

## API Documentation

Una vez ejecutado el servidor, accede a:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Solución de Problemas

### Error: "conda: command not found"
- **Causa**: Conda no está instalado o no está en el PATH
- **Solución**: Instalar Miniconda desde https://docs.conda.io/en/latest/miniconda.html

### Error: "Failed to build pydantic-core"
- **Causa**: Python 3.14 es muy nuevo
- **Solución**: Usar Python 3.11 o 3.12

### Error: "Failed to build psycopg2-binary"
- **Causa**: Falta compilador C en Windows
- **Solución**: El proyecto usa SQLite por defecto, no necesitas PostgreSQL para desarrollo

### Error: "ModuleNotFoundError"
- **Causa**: Entorno virtual no activado
- **Solución**: Ejecutar `venv\Scripts\activate` (Windows) o `source venv/bin/activate` (Linux/Mac)

## Tecnologías

- **Framework**: FastAPI (moderno, rápido, estándar)
- **ORM**: SQLAlchemy (estándar de facto en Python)
- **Migraciones**: Alembic (herramienta oficial de SQLAlchemy)
- **Base de Datos**: SQLite (desarrollo) / PostgreSQL (producción)
- **Autenticación**: JWT con bcrypt (estándar de seguridad)
- **Validación**: Pydantic (incluido con FastAPI)
