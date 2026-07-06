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
3. **Verificar cadena completa**: Antes de crear una migración, ejecutar `ls alembic/versions/ | sort` para ver TODAS las migraciones existentes y determinar el número secuencial correcto y el `revision` de la ÚLTIMA. No asumir que el número que encontraste es el último.
4. **Secuencia**: Los archivos se nombran con prefijo numérico secuencial (`020_`, `021_`, `022_`, ...). El `down_revision` SIEMPRE apunta al `revision` de la migración inmediatamente anterior en la cadena (la de mayor número).
