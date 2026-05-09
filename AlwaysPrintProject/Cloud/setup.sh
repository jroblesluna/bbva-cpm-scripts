#!/bin/bash

# Script de inicialización del proyecto AlwaysPrint Cloud Management
# Este script configura el entorno de desarrollo local

set -e

echo "=========================================="
echo "AlwaysPrint Cloud Management - Setup"
echo "=========================================="
echo ""

# Colores para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Función para imprimir mensajes
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Verificar requisitos
echo "Verificando requisitos previos..."

# Verificar Python
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
    print_success "Python $PYTHON_VERSION encontrado"
else
    print_error "Python 3.11+ no encontrado. Por favor instalar Python."
    exit 1
fi

# Verificar Node.js
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version)
    print_success "Node.js $NODE_VERSION encontrado"
else
    print_error "Node.js 20+ no encontrado. Por favor instalar Node.js."
    exit 1
fi

# Verificar npm
if command -v npm &> /dev/null; then
    NPM_VERSION=$(npm --version)
    print_success "npm $NPM_VERSION encontrado"
else
    print_error "npm no encontrado. Por favor instalar npm."
    exit 1
fi

echo ""
echo "=========================================="
echo "Configurando Backend..."
echo "=========================================="

cd backend

# Crear entorno virtual
if [ ! -d "venv" ]; then
    echo "Creando entorno virtual Python..."
    python3 -m venv venv
    print_success "Entorno virtual creado"
else
    print_warning "Entorno virtual ya existe"
fi

# Activar entorno virtual
echo "Activando entorno virtual..."
source venv/bin/activate

# Instalar dependencias
echo "Instalando dependencias Python..."
pip install --upgrade pip
pip install -r requirements.txt
print_success "Dependencias Python instaladas"

# Crear archivo .env si no existe
if [ ! -f ".env" ]; then
    echo "Creando archivo .env..."
    cp .env.example .env
    print_success "Archivo .env creado (revisar y ajustar configuración)"
else
    print_warning "Archivo .env ya existe"
fi

cd ..

echo ""
echo "=========================================="
echo "Configurando Frontend..."
echo "=========================================="

cd frontend

# Instalar dependencias
echo "Instalando dependencias Node.js..."
npm install
print_success "Dependencias Node.js instaladas"

# Crear archivo .env.local si no existe
if [ ! -f ".env.local" ]; then
    echo "Creando archivo .env.local..."
    cp .env.example .env.local
    print_success "Archivo .env.local creado"
else
    print_warning "Archivo .env.local ya existe"
fi

cd ..

echo ""
echo "=========================================="
echo "Setup completado!"
echo "=========================================="
echo ""
echo "Para iniciar el proyecto:"
echo ""
echo "Backend:"
echo "  cd backend"
echo "  source venv/bin/activate  # Linux/Mac"
echo "  # venv\\Scripts\\activate  # Windows"
echo "  uvicorn app.main:app --reload"
echo ""
echo "Frontend:"
echo "  cd frontend"
echo "  npm run dev"
echo ""
echo "O usar Docker Compose:"
echo "  docker-compose up -d"
echo ""
print_success "¡Listo para desarrollar!"
