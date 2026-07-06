---
inclusion: fileMatch
fileMatchPattern: "**/alembic/versions/*.py"
---

# Migraciones Alembic

Al crear una nueva migración en `alembic/versions/`:

1. **`revision`**: Usar formato `{NNN}_{descripcion_snake_case}` (ej: `024_extend_place_id_length`).
2. **`down_revision`**: SIEMPRE usar el nombre COMPLETO de la revisión anterior, NO solo el número.
   - ✅ `down_revision = '023_normalize_config_hash'`
   - ❌ `down_revision = '023'`
3. **Verificar**: Antes de commitear, ejecutar `grep "^revision" alembic/versions/{archivo_anterior}.py` para obtener el nombre exacto y usarlo como `down_revision`.
4. **Secuencia**: Los archivos se nombran con prefijo numérico secuencial (`020_`, `021_`, `022_`, ...). Verificar cuál es el último antes de crear uno nuevo.
