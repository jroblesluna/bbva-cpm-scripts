---
inclusion: fileMatch
fileMatchPattern: "**/alembic/versions/*.py"
---

# Migraciones Alembic

Al crear una nueva migración en `alembic/versions/`:

## ⚠️ REGLA CRÍTICA — Longitud del `revision` id ≤ 32 caracteres

**El `revision` id NUNCA debe exceder 32 caracteres.** La columna `alembic_version.version_num` es `VARCHAR(32)`. Si el `revision` id supera los 32 chars, `alembic upgrade head` ejecuta el DDL pero falla al registrar la versión con:

```
psycopg2.errors.StringDataRightTruncation: value too long for type character varying(32)
[SQL: UPDATE alembic_version SET version_num='...']
```

La transacción hace rollback, el `docker-entrypoint.sh` sale con `exit 1` y el contenedor queda en loop `Restarting`. **El backend NO levanta.** (GitHub Actions puede reportar el deploy como "success" porque solo buildea/pushea la imagen; el fallo ocurre después, en el entrypoint del contenedor.)

**Antes de crear o renombrar una migración, contar los caracteres del `revision` id y confirmar que son ≤ 32.** El nombre del archivo puede ser más largo, pero el valor de la variable `revision` (y el `Revision ID:` del docstring, que debe coincidir) NO.

- ✅ `revision = '038_billing_closure_reports'` (27 chars)
- ❌ `revision = '038_create_billing_closure_reports'` (34 chars → rompe el arranque)

Regla práctica: mantené la descripción corta (2-4 palabras). Prefijo `NNN_` (4 chars) + descripción ≤ 27 chars. Si el nombre natural es largo, abreviá (`create_` suele sobrar: `038_billing_closure_reports` en vez de `038_create_billing_closure_reports`).

**Validación obligatoria** (revision id e id del docstring deben coincidir y ambos ≤ 32):

```bash
# Longitud del revision id de un archivo de migración (debe imprimir un número ≤ 32)
rev=$(grep -m1 "^revision" alembic/versions/NNN_tu_migracion.py | sed -E "s/.*= *['\"]([^'\"]+)['\"].*/\1/"); echo "${#rev} -> $rev"
```

Incidente de referencia: la migración `038` se creó con `revision = '038_create_billing_closure_reports'` (34 chars) y tumbó DEV (restart loop). El fix fue renombrarla a `038_billing_closure_reports` (27 chars) sin tocar `down_revision` ni el DDL. Todas las migraciones previas del repo son ≤ 30 chars.

## Reglas generales

1. **`revision`**: Usar formato `{NNN}_{descripcion_snake_case}` (ej: `024_extend_place_id_length`), SIEMPRE ≤ 32 caracteres (ver regla crítica arriba). El `Revision ID:` del docstring debe ser idéntico al valor de la variable `revision`.
2. **`down_revision`**: SIEMPRE usar el nombre COMPLETO de la revisión anterior, NO solo el número.
   - ✅ `down_revision = '023_normalize_config_hash'`
   - ❌ `down_revision = '023'`
3. **Verificar cadena completa**: Antes de crear una migración, ejecutar `ls alembic/versions/ | sort` para ver TODAS las migraciones existentes y determinar el número secuencial correcto y el `revision` de la ÚLTIMA. No asumir que el número que encontraste es el último.
4. **Secuencia**: Los archivos se nombran con prefijo numérico secuencial (`020_`, `021_`, `022_`, ...). El `down_revision` SIEMPRE apunta al `revision` de la migración inmediatamente anterior en la cadena (la de mayor número).

## Checklist antes de commitear una migración

1. ¿El `revision` id tiene ≤ 32 caracteres? (contarlos)
2. ¿El `Revision ID:` del docstring coincide EXACTAMENTE con la variable `revision`?
3. ¿El `down_revision` apunta al `revision` COMPLETO de la migración inmediatamente anterior (mayor número)?
4. ¿Corriste `ls alembic/versions/ | sort` para confirmar que tu `NNN` es el siguiente y que la anterior es la que referencia `down_revision`?
5. ¿`alembic heads` devuelve un ÚNICO head (tu nueva migración) y `alembic history` muestra la cadena sin ramas?
