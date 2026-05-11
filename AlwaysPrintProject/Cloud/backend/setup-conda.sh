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
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "Archivo .env creado desde .env.example"
        echo "Revisa y actualiza la configuración en .env antes de continuar"
    else
        echo "[WARNING] No se encontró .env.example"
    fi
else
    echo "Archivo .env ya existe."
fi
echo ""

echo "[4/4] Aplicando migraciones de base de datos..."
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
