#!/bin/bash
set -e

echo "=========================================="
echo "AlwaysPrint Backend - Iniciando"
echo "Build Tag: ${BUILD_TAG:-dev}"
echo "=========================================="

# Esperar a que PostgreSQL esté disponible
echo "Verificando conexión a base de datos..."

# Extraer host y puerto de DATABASE_URL si DB_HOST no está definido
if [ -z "$DB_HOST" ] && [ -n "$DATABASE_URL" ]; then
    # Parsear DATABASE_URL: postgresql://user:pass@host:port/dbname
    DB_HOST=$(echo "$DATABASE_URL" | sed -n 's|.*@\([^:/]*\).*|\1|p')
    DB_PORT=$(echo "$DATABASE_URL" | sed -n 's|.*@[^:]*:\([0-9]*\).*|\1|p')
    DB_USER=$(echo "$DATABASE_URL" | sed -n 's|.*://\([^:]*\):.*|\1|p')
fi

max_retries=30
retry_count=0

until pg_isready -h "${DB_HOST:-localhost}" -p "${DB_PORT:-5432}" -U "${DB_USER:-postgres}" > /dev/null 2>&1; do
    retry_count=$((retry_count + 1))
    if [ $retry_count -ge $max_retries ]; then
        echo "ERROR: No se pudo conectar a la base de datos después de $max_retries intentos"
        exit 1
    fi
    echo "Esperando a que PostgreSQL esté disponible... (intento $retry_count/$max_retries)"
    sleep 2
done

echo "✓ Conexión a base de datos establecida"

# Ejecutar migraciones de Alembic
echo ""
echo "Ejecutando migraciones de base de datos..."

# Verificar si la BD tiene una revisión que ya no existe en el código
# o si el schema está desactualizado (columnas faltantes por migración consolidada modificada)
current_rev=$(alembic current 2>&1 || true)
needs_recreate=false

if echo "$current_rev" | grep -q "Can't locate revision"; then
    echo "⚠ Revisión obsoleta detectada en la BD."
    needs_recreate=true
fi

# Verificar si la tabla organizations tiene la columna target_version
# (detecta cuando la migración consolidada fue modificada después de aplicarse)
if [ "$needs_recreate" = "false" ]; then
    column_check=$(python -c "
from app.core.database import engine
from sqlalchemy import text, inspect
insp = inspect(engine)
if insp.has_table('organizations'):
    cols = [c['name'] for c in insp.get_columns('organizations')]
    if 'target_version' not in cols:
        print('MISSING')
    else:
        print('OK')
else:
    print('OK')
" 2>/dev/null || echo "OK")
    if [ "$column_check" = "MISSING" ]; then
        echo "⚠ Schema desactualizado (columnas faltantes). Recreando..."
        needs_recreate=true
    fi
fi

if [ "$needs_recreate" = "true" ]; then
    echo "Recreando esquema desde cero..."
    python -c "
from app.core.database import engine
from sqlalchemy import text
with engine.connect() as conn:
    conn.execute(text('DROP SCHEMA public CASCADE'))
    conn.execute(text('CREATE SCHEMA public'))
    conn.commit()
print('Schema recreado')
" 2>/dev/null || true
    echo "✓ Schema limpio. Aplicando migración consolidada..."
fi

alembic upgrade head

if [ $? -eq 0 ]; then
    echo "✓ Migraciones aplicadas exitosamente"
else
    echo "ERROR: Fallo al aplicar migraciones"
    exit 1
fi

echo ""
echo "=========================================="
echo "Iniciando servidor uvicorn..."
echo "=========================================="
echo ""

# Ejecutar el comando pasado como argumentos (uvicorn)
exec "$@"
