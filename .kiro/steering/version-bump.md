---
inclusion: fileMatch
fileMatchPattern: "**/*.alwaysconfig"
---

# Bumpeo de Versión en AlwaysConfig

Al modificar cualquier archivo `.alwaysconfig`:

1. **SIEMPRE** incrementar el campo `"version"` en el JSON raíz.
2. Usar versionado semántico simple: `major.minor` (ej: `8.0` → `8.1` → `8.2`).
3. Incrementar `minor` para cambios de acciones, parámetros, o lógica.
4. Incrementar `major` solo si se agrega/elimina un trigger o se cambia la estructura base.
5. El bump debe hacerse en el mismo commit que el cambio funcional.
