# Migraciones de Base de Datos con Alembic

Este directorio contiene las migraciones de base de datos para el sistema AlwaysPrint Cloud Management.

## Estructura

```
alembic/
├── versions/              # Archivos de migración
│   └── 001_initial_migration.py
├── env.py                 # Configuración del entorno de Alembic
├── script.py.mako         # Template para nuevas migraciones
└── README.md              # Este archivo
```

## Comandos Básicos

### Ver estado actual
```bash
alembic current
```

### Ver historial de migraciones
```bash
alembic history --verbose
```

### Aplicar todas las migraciones pendientes
```bash
alembic upgrade head
```

### Aplicar una migración específica
```bash
alembic upgrade 001
```

### Revertir la última migración
```bash
alembic downgrade -1
```

### Revertir todas las migraciones
```bash
alembic downgrade base
```

### Generar nueva migración automáticamente
```bash
alembic revision --autogenerate -m "Descripción del cambio"
```

### Generar nueva migración manualmente
```bash
alembic revision -m "Descripción del cambio"
```

## Migraciones Existentes

Cadena actual (en orden de aplicación):

```
001_initial_migration
  └── d4a203945821_add_full_name_to_users
        └── 002_add_timezone_fields
              └── 003_add_public_ip_authorization
                    └── 004_add_password_reset_token  ← HEAD
```

### 001_initial_migration.py
**Descripción:** Migración inicial que crea toda la estructura de base de datos

**Incluye:**
- Tablas principales: `accounts`, `public_ips`, `users`, `workstations`, `licenses`,
  `vlans`, `global_configs`, `vlan_configs`, `workstation_configs`, `messages`, `audit_logs`
- Índices para optimización de consultas
- Triggers para `updated_at` automático (PostgreSQL)

### d4a203945821_add_full_name_to_users.py
Agrega columna `full_name` a la tabla `users`.

### 002_add_timezone_fields.py
Agrega campos de zona horaria a workstations.

### 003_add_public_ip_authorization.py
Agrega campos de autorización a `public_ips` (`is_authorized`, `account_id`).

### 004_add_password_reset_token.py
Agrega `password_reset_token` (String 255, indexado) y `password_reset_expires` (DateTime)
a la tabla `users` para el flujo de recuperación de contraseña vía AWS SES.

## Flujo de Trabajo

### 1. Desarrollo Local (SQLite)

```bash
# Configurar base de datos en .env
DATABASE_URL=sqlite:///./alwaysprint.db

# Aplicar migraciones
alembic upgrade head

# Verificar
python scripts/verify_migration.py
```

### 2. Producción (PostgreSQL)

```bash
# Configurar base de datos en .env o variable de entorno
export DATABASE_URL="postgresql://user:password@localhost:5432/alwaysprint"

# Aplicar migraciones
alembic upgrade head

# Verificar
python scripts/verify_migration.py
```

### 3. Crear Nueva Migración

```bash
# Opción 1: Autogenerar (recomendado)
alembic revision --autogenerate -m "Agregar campo X a tabla Y"

# Opción 2: Manual
alembic revision -m "Agregar campo X a tabla Y"

# Editar el archivo generado en alembic/versions/
# Implementar upgrade() y downgrade()

# Aplicar la migración
alembic upgrade head

# Verificar
python scripts/verify_migration.py
```

## Buenas Prácticas

### 1. Siempre revisar migraciones autogeneradas
Revisar el archivo generado antes de aplicarlo para asegurar que los cambios son correctos.

### 2. Implementar downgrade()
Implementar la función `downgrade()` para poder revertir cambios si es necesario.

### 3. Probar en desarrollo primero
Aplicar y probar las migraciones en SQLite antes de aplicarlas en PostgreSQL de producción.

### 4. Backup antes de migrar en producción
```bash
# PostgreSQL
pg_dump -U user -d alwaysprint > backup_$(date +%Y%m%d_%H%M%S).sql

# Aplicar migración
alembic upgrade head

# Si algo sale mal, restaurar
psql -U user -d alwaysprint < backup_YYYYMMDD_HHMMSS.sql
```

### 5. Usar transacciones
Alembic usa transacciones por defecto. Si una migración falla, se revierte automáticamente.

### 6. Documentar cambios complejos
Para migraciones complejas, documentar:
- Qué cambia
- Por qué cambia
- Cómo afecta a la aplicación
- Pasos de rollback si es necesario

## Compatibilidad Multi-Base de Datos

El sistema soporta SQLite, PostgreSQL y SQL Server. Las migraciones deben ser compatibles con todos.

### Características específicas de PostgreSQL

Algunas características solo funcionan en PostgreSQL:
- Triggers automáticos para `updated_at`
- Funciones auxiliares (`calculate_license_serial`, `detect_vlan_for_ip`)
- Tipos UUID nativos
- Tipos ENUM nativos
- Operadores de red (CIDR, INET)

Para SQLite y SQL Server, estas características se implementan en la capa de aplicación.

### Verificar compatibilidad

```python
# En la migración, verificar el tipo de base de datos
connection = op.get_bind()

if connection.dialect.name == 'postgresql':
    # Código específico de PostgreSQL
    op.execute("CREATE FUNCTION ...")
elif connection.dialect.name == 'sqlite':
    # Código específico de SQLite
    pass
elif connection.dialect.name == 'mssql':
    # Código específico de SQL Server
    pass
```

## Troubleshooting

### Error: "Can't locate revision identified by 'XXX'"
```bash
# Verificar estado
alembic current

# Ver historial
alembic history

# Si la base de datos está vacía, aplicar desde el inicio
alembic upgrade head
```

### Error: "Target database is not up to date"
```bash
# Ver qué migraciones faltan
alembic history

# Aplicar migraciones pendientes
alembic upgrade head
```

### Error: "FAILED: Can't locate revision identified by 'head'"
```bash
# Verificar que existe al menos una migración
ls alembic/versions/

# Si no hay migraciones, crear la inicial
alembic revision --autogenerate -m "Migración inicial"
```

### Error al autogenerar: "No changes detected"
```bash
# Verificar que los modelos están importados en env.py
# Verificar que Base.metadata está configurado correctamente
# Verificar que la base de datos está vacía o en el estado correcto
```

## Scripts de Utilidad

### verify_migration.py
Verifica que la migración se aplicó correctamente:
```bash
python scripts/verify_migration.py
```

Verifica:
- ✅ Todas las tablas existen
- ✅ Todos los índices existen
- ✅ Todas las foreign keys existen
- ✅ Funciones auxiliares funcionan (PostgreSQL)
- ✅ Triggers funcionan (PostgreSQL)

## Referencias

- **Documentación de Alembic**: https://alembic.sqlalchemy.org/
- **Tutorial de Alembic**: https://alembic.sqlalchemy.org/en/latest/tutorial.html
- **Autogenerate**: https://alembic.sqlalchemy.org/en/latest/autogenerate.html
- **Cookbook**: https://alembic.sqlalchemy.org/en/latest/cookbook.html

## Soporte

Para problemas con migraciones:
1. Revisar logs de Alembic
2. Ejecutar `python scripts/verify_migration.py`
3. Revisar documentación en `docs/MIGRATION_001_DETAILS.md`
4. Consultar con el equipo de desarrollo
