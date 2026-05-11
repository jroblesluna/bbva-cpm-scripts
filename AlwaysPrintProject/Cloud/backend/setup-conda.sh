#!/bin/bash
# Script de instalación con Conda para Linux/Mac
# AlwaysPrint Cloud Manager - Backend

set -e

echo "========================================"
echo "AlwaysPrint Cloud Manager - Setup"
echo "========================================"
echo ""

# Verificar si conda está instalado
if ! command -v conda &> /dev/null; then
    echo "[ERROR] Conda no está instalado o no está en el PATH"
    echo ""
    echo "Instala Miniconda desde: https://docs.conda.io/en/latest/miniconda.html"
    echo ""
    exit 1
fi

echo "[1/4] Verificando Conda..."
conda --version
echo ""

echo "[2/4] Preparando entorno conda 'alwaysprint' con Python 3.12..."
if conda env list | grep -q "^alwaysprint "; then
    echo "[INFO] El entorno ya existe. Eliminando para recrear..."
    conda env remove -n alwaysprint -y
fi

conda create -n alwaysprint python=3.12 pip -y

if [ $? -ne 0 ]; then
    echo "[ERROR] No se pudo crear el entorno conda"
    exit 1
fi

echo "Instalando dependencias..."
conda run -n alwaysprint pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo "[ERROR] Falló la instalación de dependencias"
    exit 1
fi
echo ""

echo "[3/4] Configurando variables de entorno..."
if [ ! -f .env ]; then
    cat > .env << 'EOF'
DATABASE_URL=sqlite:///./alwaysprint.db
SECRET_KEY=dev-secret-key-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
CORS_ORIGINS=http://localhost:3000
API_V1_STR=/api/v1
REDIS_URL=redis://localhost:6379/0
SES_ENABLED=false
SES_FROM_EMAIL=noreply@alwaysprint.apps.iol.pe
AWS_REGION=us-west-2
FRONTEND_URL=http://localhost:3000
LOG_LEVEL=DEBUG
WS_PING_INTERVAL=30
WS_PING_TIMEOUT=60
RATE_LIMIT_LOGIN=5
RATE_LIMIT_API=100
EOF
    echo "Archivo .env creado con valores de desarrollo."
    echo "Actualiza SECRET_KEY y DATABASE_URL según tu entorno."
else
    echo "Archivo .env ya existe."
fi
echo ""

echo "[4/4] Aplicando migraciones de base de datos..."
# Si usa SQLite y el .db existe en estado inconsistente, borrarlo para empezar limpio
DB_FILE=$(grep "^DATABASE_URL=sqlite" .env 2>/dev/null | grep -oP '(?<=///).*' || true)
if [ -n "$DB_FILE" ] && [ -f "$DB_FILE" ]; then
    echo "[INFO] Eliminando base de datos SQLite existente para setup limpio..."
    rm -f "$DB_FILE"
fi

conda run -n alwaysprint alembic upgrade head || {
    echo "[WARNING] Error al aplicar migraciones."
    echo "Verifica la configuración DATABASE_URL en .env y ejecuta 'alembic upgrade head' manualmente."
}
echo ""

echo "========================================"
echo "Instalación completada!"
echo "========================================"
echo ""
echo "Próximos pasos:"
echo ""
echo "1. Activar el entorno:"
echo "   conda activate alwaysprint"
echo ""
echo "2. Revisar configuración:"
echo "   Edita .env con tu configuración local"
echo ""
echo "3. Ejecutar el servidor:"
echo "   uvicorn app.main:app --reload"
echo ""
echo "4. Documentación API:"
echo "   http://localhost:8000/docs"
echo ""
