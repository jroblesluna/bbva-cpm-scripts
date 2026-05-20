---
inclusion: fileMatch
fileMatchPattern: "**/alembic/**/*.py"
---

# Estándares para Migraciones Alembic

## Restricción Crítica: Longitud de Revision ID

La columna `alembic_version.version_num` en PostgreSQL es `VARCHAR(32)`. Los revision IDs **DEBEN tener máximo 32 caracteres**.

Formato: `NNN_descripcion_corta` donde NNN es el número secuencial.

Ejemplos válidos:
- `001_initial_schema` (18 chars) ✅
- `002_add_cidr_tray_version` (25 chars) ✅
- `006_contingency_ip` (18 chars) ✅

Ejemplos inválidos:
- `006_add_contingency_ip_started_at` (35 chars) ❌ — excede 32

## Estructura de Archivo de Migración

```python
"""Descripción breve de la migración en español

Revision ID: NNN_descripcion_corta
Revises: NNN-1_revision_anterior
Create Date: YYYY-MM-DD HH:MM:SS.000000

Descripción detallada de qué hace la migración.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'NNN_descripcion_corta'
down_revision: Union[str, None] = 'NNN-1_revision_anterior'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Descripción del upgrade en español."""
    pass


def downgrade() -> None:
    """Descripción del downgrade en español."""
    pass
```

## Reglas

1. **Siempre incluir `downgrade()`** — debe revertir exactamente lo que hace `upgrade()`
2. **Usar `server_default`** para columnas Boolean nuevas — evita problemas con filas existentes
3. **Columnas nuevas deben ser `nullable=True`** o tener `server_default` — nunca agregar columnas NOT NULL sin default a tablas con datos
4. **Encadenar correctamente** — `down_revision` debe apuntar al revision ID exacto de la migración anterior
5. **Verificar cadena antes de commit** — ejecutar `alembic history` localmente
6. **Comentarios y docstrings en español**
7. **No usar `autogenerate`** en producción — escribir migraciones manualmente para control total
8. **Enums PostgreSQL: NUNCA usar `enum.create(checkfirst=True)`** — no funciona correctamente en Alembic. Usar SQL raw idempotente:

```python
# CORRECTO: idempotente en PostgreSQL
op.execute("DO $$ BEGIN CREATE TYPE mi_enum AS ENUM ('valor1', 'valor2'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;")
mi_enum = sa.Enum('valor1', 'valor2', name='mi_enum', create_type=False)

# INCORRECTO: falla si el enum ya existe (migración parcial previa)
mi_enum = sa.Enum('valor1', 'valor2', name='mi_enum')
mi_enum.create(op.get_bind(), checkfirst=True)  # ← BUG: checkfirst no funciona en Alembic
```

Para el downgrade de enums:
```python
sa.Enum(name='mi_enum').drop(op.get_bind(), checkfirst=True)
```

9. **En los modelos SQLAlchemy, siempre usar `create_type=False`** en columnas con `SQLEnum`:

```python
# CORRECTO: el modelo no intenta crear el tipo (la migración se encarga)
status = Column(SQLEnum(MiEnum, name='mi_enum', create_type=False), nullable=False)

# INCORRECTO: SQLAlchemy intenta CREATE TYPE al cargar el modelo → falla si ya existe
status = Column(SQLEnum(MiEnum), nullable=False)
```

## Convenciones de Nombres

| Operación | Formato de revision ID |
|---|---|
| Agregar columnas | `NNN_add_campo_tabla` |
| Crear tabla | `NNN_create_tabla` |
| Eliminar columna | `NNN_drop_campo_tabla` |
| Índice | `NNN_idx_tabla_campo` |
| Cambio de tipo | `NNN_alter_campo_tabla` |

## Ejecución Automática

El `docker-entrypoint.sh` ejecuta `alembic upgrade head` al iniciar el contenedor. Si una migración falla, el backend NO arranca. Por eso es crítico que las migraciones sean idempotentes y correctas antes de hacer push.
