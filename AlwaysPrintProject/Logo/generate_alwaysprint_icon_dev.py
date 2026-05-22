#!/usr/bin/env python3
"""
Generate the AlwaysPrint DEV icon SVG.

Modifica el ícono de producción para entorno dev:
- Cuerpo de la impresora en tonos naranja/ámbar (en vez de gris/blanco)
- Badge "DEV" naranja en la esquina inferior derecha

Uso:
    python generate_alwaysprint_icon_dev.py -o alwaysprint_icon_dev.svg --preview-png alwaysprint_icon_dev.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

# Importar la función de generación del ícono base
from generate_alwaysprint_icon import build_svg, write_png_preview


# Badge "DEV" — rectángulo naranja redondeado con texto blanco en esquina inferior derecha
DEV_BADGE = """
  <!-- Badge DEV -->
  <g transform="translate(0, 0)">
    <!-- Sombra del badge -->
    <rect x="698" y="868" width="280" height="120" rx="24"
          fill="#000000" opacity="0.25" transform="translate(4, 4)"/>
    <!-- Fondo naranja -->
    <rect x="698" y="868" width="280" height="120" rx="24"
          fill="#FF6B00"/>
    <!-- Borde más claro -->
    <rect x="698" y="868" width="280" height="120" rx="24"
          fill="none" stroke="#FFB366" stroke-width="4" opacity="0.7"/>
    <!-- Texto DEV -->
    <text x="838" y="948" font-family="Arial, Helvetica, sans-serif"
          font-size="82" font-weight="bold" fill="#FFFFFF"
          text-anchor="middle" dominant-baseline="middle">DEV</text>
  </g>
"""

# Reemplazos de color para convertir la impresora gris a naranja/ámbar
COLOR_REPLACEMENTS = [
    # bodyGrad: gris claro → naranja claro
    ('#EFF0F6', '#FFE8D0'),
    ('#E6E6F0', '#FFD9B3'),
    # bodyEdgeGrad: gris medio → naranja medio
    ('#D7DAE2', '#FFB366'),
    ('#A5A5AA', '#E68A2E'),
    ('#6B717B', '#B35C00'),
    # rearGrad: gris oscuro → naranja oscuro
    ('#6A6F7C', '#CC6600'),
    ('#32323C', '#7A3D00'),
    # bodyBottomShade: gris → naranja oscuro
    ('#7B828C', '#B35C00'),
    ('#3F4650', '#663300'),
]


def build_dev_svg() -> str:
    """Genera el SVG del ícono dev: impresora naranja + badge DEV."""
    base_svg = build_svg()

    # Aplicar reemplazos de color al cuerpo de la impresora
    for old_color, new_color in COLOR_REPLACEMENTS:
        base_svg = base_svg.replace(old_color, new_color)

    # Insertar el badge justo antes del cierre </svg>
    return base_svg.replace("</svg>", f"{DEV_BADGE}\n</svg>")


def write_svg(output_path: Path) -> Path:
    svg = build_dev_svg()
    output_path.write_text(svg, encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the AlwaysPrint DEV SVG icon (orange printer + DEV badge)."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("alwaysprint_icon_dev.svg"),
        help="Output SVG path. Default: alwaysprint_icon_dev.svg",
    )
    parser.add_argument(
        "--preview-png",
        type=Path,
        default=None,
        help="Optional PNG preview path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    svg_path = write_svg(args.output)
    print(f"SVG (DEV) written to: {svg_path}")

    if args.preview_png is not None:
        png_path = write_png_preview(svg_path, args.preview_png)
        print(f"PNG preview (DEV) written to: {png_path}")


if __name__ == "__main__":
    main()
