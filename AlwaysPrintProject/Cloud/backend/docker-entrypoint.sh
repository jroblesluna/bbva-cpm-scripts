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

# Verificar estado actual de Alembic
current_rev=$(alembic current 2>&1 || true)

if echo "$current_rev" | grep -q "Can't locate revision"; then
    echo "═══════════════════════════════════════════════════════════"
    echo "ERROR CRÍTICO: La BD tiene una revisión que no existe en el código."
    echo "Revisión actual en BD:"
    echo "$current_rev"
    echo ""
    echo "Esto puede ocurrir si se renombró o eliminó una migración."
    echo "SOLUCIÓN MANUAL REQUERIDA:"
    echo "  1. Conectar a la BD: psql \$DATABASE_URL"
    echo "  2. Ver revisión actual: SELECT * FROM alembic_version;"
    echo "  3. Actualizar a la revisión correcta:"
    echo "     UPDATE alembic_version SET version_num = '<revision_correcta>';"
    echo "  4. Reiniciar el contenedor"
    echo ""
    echo "NO se borrarán datos automáticamente. El backend NO arrancará."
    echo "═══════════════════════════════════════════════════════════"
    exit 1
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
