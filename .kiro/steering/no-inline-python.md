---
inclusion: auto
description: "Evitar python3 -c inline para código multi-línea"
---

# No usar python3 -c para código multi-línea

- NUNCA usar `python3 -c "..."` con código que tenga múltiples statements, imports, loops, o condicionales.
- SIEMPRE escribir el código en un archivo `.py` temporal (ej: `/tmp/script.py`) usando `fs_write` y luego ejecutar con `python3 /tmp/script.py`.
- Excepción: un solo statement simple sin imports adicionales está permitido (ej: `python3 -c "print(2+2)"`).
