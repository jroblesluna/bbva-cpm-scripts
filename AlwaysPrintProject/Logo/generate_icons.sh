#!/bin/bash
# =============================================================================
# Genera los íconos de AlwaysPrint para Prod y Dev en los 3 formatos (SVG, PNG, ICO)
#
# Uso: ./generate_icons.sh
#
# Salida:
#   prod/alwaysprint_icon.svg
#   prod/alwaysprint_icon.png
#   prod/alwaysprint_icon.ico
#   dev/alwaysprint_icon_dev.svg
#   dev/alwaysprint_icon_dev.png
#   dev/alwaysprint_icon_dev.ico
#
# Requisitos: python3, cairosvg, Pillow
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}=== Generador de íconos AlwaysPrint (Prod + Dev) ===${NC}"
echo ""

# ── Validar dependencias ──────────────────────────────────────────────────────
echo -e "${CYAN}Verificando dependencias...${NC}"

if ! command -v python3 &>/dev/null; then
    echo -e "${RED}✗ python3 no encontrado. Instalar Python 3.${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} python3"

# Verificar cairosvg
if ! python3 -c "import cairosvg" 2>/dev/null; then
    echo -e "${RED}✗ cairosvg no disponible.${NC}"
    echo "  Instalar con: pip install cairosvg"
    echo "  También necesitas la librería cairo del sistema:"
    echo "    macOS:  brew install cairo"
    echo "    Linux:  apt install libcairo2-dev"
    exit 1
fi
echo -e "${GREEN}✓${NC} cairosvg"

# Verificar Pillow
if ! python3 -c "from PIL import Image" 2>/dev/null; then
    echo -e "${RED}✗ Pillow no disponible.${NC}"
    echo "  Instalar con: pip install Pillow"
    exit 1
fi
echo -e "${GREEN}✓${NC} Pillow"

echo ""

# ── Crear carpetas de salida ──────────────────────────────────────────────────
mkdir -p prod dev

# ── Generar Prod ──────────────────────────────────────────────────────────────
echo -e "${CYAN}Generando ícono PROD...${NC}"

python3 generate_alwaysprint_icon.py \
    -o prod/alwaysprint_icon.svg \
    --preview-png prod/alwaysprint_icon.png

# Convertir PNG a ICO con múltiples tamaños
python3 -c "
from PIL import Image
img = Image.open('prod/alwaysprint_icon.png')
sizes = [(16,16), (32,32), (48,48), (256,256)]
img.save('prod/alwaysprint_icon.ico', format='ICO', sizes=sizes)
"

echo -e "${GREEN}✓${NC} prod/alwaysprint_icon.svg"
echo -e "${GREEN}✓${NC} prod/alwaysprint_icon.png"
echo -e "${GREEN}✓${NC} prod/alwaysprint_icon.ico"
echo ""

# ── Generar Dev ───────────────────────────────────────────────────────────────
echo -e "${CYAN}Generando ícono DEV...${NC}"

python3 generate_alwaysprint_icon_dev.py \
    -o dev/alwaysprint_icon_dev.svg \
    --preview-png dev/alwaysprint_icon_dev.png

# Convertir PNG a ICO con múltiples tamaños
python3 -c "
from PIL import Image
img = Image.open('dev/alwaysprint_icon_dev.png')
sizes = [(16,16), (32,32), (48,48), (256,256)]
img.save('dev/alwaysprint_icon_dev.ico', format='ICO', sizes=sizes)
"

echo -e "${GREEN}✓${NC} dev/alwaysprint_icon_dev.svg"
echo -e "${GREEN}✓${NC} dev/alwaysprint_icon_dev.png"
echo -e "${GREEN}✓${NC} dev/alwaysprint_icon_dev.ico"
echo ""

# ── Resumen ───────────────────────────────────────────────────────────────────
echo -e "${CYAN}═══════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✓ Íconos generados correctamente${NC}"
echo -e "${CYAN}═══════════════════════════════════════════${NC}"
echo ""
echo "  prod/"
ls -lh prod/ | grep -v "^total" | awk '{print "    " $NF " (" $5 ")"}'
echo ""
echo "  dev/"
ls -lh dev/ | grep -v "^total" | awk '{print "    " $NF " (" $5 ")"}'
echo ""
