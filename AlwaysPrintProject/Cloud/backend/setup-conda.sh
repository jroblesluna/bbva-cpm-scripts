#!/bin/bash
# Script de instalación con Conda para Linux/Mac
# AlwaysPrint Cloud Manager - Backend

set -e  # Salir si hay error

echo "========================================"
echo "AlwaysPrint Cloud Manager - Setup"
echo "========================================"
echo ""

# Verificar si conda está instalado
if ! command -v conda &> /dev/null; then
    echo "[ERROR] Conda no está instalado o no está en el PATH"
    echo ""
    echo "Por favor instala Miniconda o Anaconda desde:"
    echo "https://docs.conda.io/en/latest/miniconda.html"
    echo ""
    exit 1
fi

echo "[1/5] Verificando Conda..."
conda --version
echo ""

echo "[2/5] Creando entorno conda 'alwaysprint' con Python 3.12..."
if conda env list | grep -q "^alwaysprint "; then
    echo "[INFO] El entorno ya existe. Actualizando..."
    conda env update -f environment.yml --prune
else
    conda env create -f environment.yml
fi
echo ""

echo "[3/5] Activando entorno..."
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate alwaysprint
echo ""

echo "[4/5] Configurando variables de entorno..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Archivo .env creado. Por favor revisa la configuración."
else
    echo "Archivo .env ya existe."
fi
echo ""

echo "[5/5] Inicializando base de datos..."
if ! alembic upgrade head; then
    echo "[WARNING] Error al aplicar migraciones. Verifica la configuración de la base de datos."
fi
echo ""

echo "========================================"
echo "Instalación completada!"
echo "========================================"
echo ""
echo "Para activar el entorno:"
echo "  conda activate alwaysprint"
echo ""
echo "Para ejecutar el servidor:"
echo "  uvicorn app.main:app --reload"
echo ""
echo "Documentación API:"
echo "  http://localhost:8000/docs"
echo ""
