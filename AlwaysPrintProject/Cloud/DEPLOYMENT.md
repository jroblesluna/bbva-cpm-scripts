# Guía de Despliegue - AlwaysPrint Cloud

## 🚀 Flujo de Despliegue Automático

### Backend

```
Push a GitHub (main branch)
       ↓
GitHub Actions detecta cambios en AlwaysPrintProject/Cloud/backend/**
       ↓
Workflow: .github/workflows/deploy-backend.yml
       ↓
1. Build Docker image
2. Push a ECR (tag: {git-sha-8-chars} + latest)
3. Deploy via SSM a EC2
       ↓
EC2 ejecuta: /opt/alwaysprint/deploy.sh backend
       ↓
Docker pull nueva imagen
       ↓
Docker restart contenedor
       ↓
ENTRYPOINT: /docker-entrypoint.sh
       ↓
1. Verifica conexión a PostgreSQL
2. Ejecuta: alembic upgrade head ← MIGRACIONES AUTOMÁTICAS
3. Inicia: uvicorn app.main:app
       ↓
✅ Backend actualizado y migraciones aplicadas
```

### Frontend

```
Push a GitHub (main branch)
       ↓
GitHub Actions detecta cambios en AlwaysPrintProject/Cloud/frontend/**
       ↓
Workflow: .github/workflows/deploy-frontend.yml
       ↓
1. npm run build
2. Deploy a hosting (Vercel/Netlify/S3)
       ↓
✅ Frontend actualizado
```

---

## 🔄 Migraciones de Base de Datos

### ✅ Ahora Automáticas (Actualización Implementada)

**Archivo**: `docker-entrypoint.sh`

```bash
#!/bin/bash
# 1. Espera a que PostgreSQL esté disponible
# 2. Ejecuta: alembic upgrade head
# 3. Inicia uvicorn
```

**Dockerfile actualizado**:
```dockerfile
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 📋 Cadena de Migraciones Actual

```
001_initial_migration
       ↓
002_add_timezone_fields
       ↓
003_add_public_ip_authorization
       ↓
004_add_password_reset_token
       ↓
005_add_language_fields
       ↓
006_add_phase3_config_fields
       ↓
007_add_telemetry_connectivity
       ↓
20260515151758_add_action_configs_table ← NUEVA
       ↓
d4a203945821_add_full_name_to_users
```

**NOTA**: La migración `d4a203945821_add_full_name_to_users` necesita actualizar su `down_revision` a `20260515151758` si fue creada después.

---

## 🛠️ Comandos Manuales (Si es Necesario)

### Verificar Estado de Migraciones

```bash
# En el contenedor Docker
docker exec -it alwaysprint-backend bash
alembic current
alembic history
```

### Aplicar Migraciones Manualmente

```bash
# Si por alguna razón fallan las automáticas
docker exec -it alwaysprint-backend alembic upgrade head
```

### Rollback de Migración

```bash
# Revertir última migración
docker exec -it alwaysprint-backend alembic downgrade -1

# Revertir a una revisión específica
docker exec -it alwaysprint-backend alembic downgrade 007_add_telemetry_connectivity
```

### Crear Nueva Migración

```bash
# En desarrollo local
cd AlwaysPrintProject/Cloud/backend
conda activate alwaysprint
alembic revision -m "descripcion_de_cambio"

# Editar el archivo generado en alembic/versions/
# Actualizar down_revision con la última migración
# Implementar upgrade() y downgrade()
```

---

## ⚠️ Qué Pasa Si Despliegas Sin Migrar

### Escenario: Push sin migración de DB

```
Backend nuevo código → Intenta acceder a action_configs
       ↓
❌ ERROR: relation "action_configs" does not exist
       ↓
Backend se cae en cualquier request a /organizations/{id}/config
       ↓
500 Internal Server Error
```

### Solución Implementada

Con el `docker-entrypoint.sh`, esto **NO puede pasar** porque:

1. El contenedor ejecuta migraciones ANTES de iniciar uvicorn
2. Si las migraciones fallan, el contenedor no inicia
3. El despliegue falla de forma segura (fail-fast)

---

## 🔍 Verificación Post-Despliegue

### 1. Verificar que el Backend Inició

```bash
# Ver logs del contenedor
docker logs alwaysprint-backend --tail 100

# Buscar estas líneas:
# ✓ Conexión a base de datos establecida
# Ejecutando migraciones de base de datos...
# ✓ Migraciones aplicadas exitosamente
# Iniciando servidor uvicorn...
```

### 2. Verificar Migraciones Aplicadas

```bash
# Conectar a PostgreSQL
docker exec -it alwaysprint-postgres psql -U postgres -d alwaysprint

# Verificar tabla alembic_version
SELECT * FROM alembic_version;
# Debe mostrar: 20260515151758 (o posterior)

# Verificar que existe la tabla action_configs
\dt action_configs
# Debe mostrar la tabla

# Ver estructura
\d action_configs
```

### 3. Probar Endpoints

```bash
# Health check
curl https://alwaysprint.apps.iol.pe/api/v1/health

# Swagger UI
# Abrir en navegador: https://alwaysprint.apps.iol.pe/docs

# Probar endpoint de action configs (requiere autenticación)
curl -H "Authorization: Bearer {token}" \
  https://alwaysprint.apps.iol.pe/api/v1/organizations/1/config
```

---

## 🚨 Troubleshooting

### Problema: Migraciones Fallan al Desplegar

**Síntomas**:
- Contenedor no inicia
- Logs muestran: "ERROR: Fallo al aplicar migraciones"

**Solución**:
```bash
# 1. Ver logs detallados
docker logs alwaysprint-backend

# 2. Conectar a PostgreSQL y verificar estado
docker exec -it alwaysprint-postgres psql -U postgres -d alwaysprint
SELECT * FROM alembic_version;

# 3. Si la migración está a medias, hacer rollback manual
docker exec -it alwaysprint-backend alembic downgrade -1

# 4. Reintentar
docker restart alwaysprint-backend
```

### Problema: Tabla Ya Existe

**Síntomas**:
- Error: "relation 'action_configs' already exists"

**Causa**: La tabla fue creada manualmente o la migración se ejecutó parcialmente

**Solución**:
```bash
# Marcar la migración como aplicada sin ejecutarla
docker exec -it alwaysprint-backend alembic stamp 20260515151758
```

### Problema: Conflicto de Migraciones

**Síntomas**:
- Error: "Multiple head revisions are present"

**Causa**: Dos migraciones tienen el mismo `down_revision`

**Solución**:
```bash
# Ver el árbol de migraciones
docker exec -it alwaysprint-backend alembic branches

# Identificar el conflicto y actualizar down_revision en una de las migraciones
# Luego hacer merge:
docker exec -it alwaysprint-backend alembic merge -m "merge_heads" {rev1} {rev2}
```

---

## 📝 Checklist de Despliegue

### Antes de Push a Main

- [ ] Código compilado localmente sin errores
- [ ] Tests pasando (si existen)
- [ ] Migración creada y probada localmente
- [ ] `down_revision` actualizado correctamente
- [ ] Funciones `upgrade()` y `downgrade()` implementadas
- [ ] Documentación actualizada

### Después de Push a Main

- [ ] GitHub Actions completado exitosamente
- [ ] Backend reiniciado en EC2
- [ ] Logs muestran migraciones aplicadas
- [ ] Health check responde OK
- [ ] Swagger UI accesible
- [ ] Endpoints nuevos funcionan correctamente
- [ ] Frontend actualizado (si aplica)

---

## 🔐 Variables de Entorno Requeridas

### Backend (.env en servidor)

```bash
# Base de datos
DATABASE_URL=postgresql://user:pass@host:5432/dbname
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=secret
DB_NAME=alwaysprint

# Aplicación
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Build
BUILD_TAG=abc12345  # Actualizado automáticamente por deploy
```

### Frontend (.env.local)

```bash
NEXT_PUBLIC_API_URL=https://alwaysprint.apps.iol.pe
NEXTAUTH_URL=https://alwaysprint-frontend.vercel.app
NEXTAUTH_SECRET=your-nextauth-secret
```

---

## 📊 Monitoreo Post-Despliegue

### Métricas a Vigilar

1. **Logs de Aplicación**
   - Errores 500
   - Warnings de migraciones
   - Queries lentas

2. **Métricas de Base de Datos**
   - Conexiones activas
   - Queries por segundo
   - Tamaño de tablas

3. **Métricas de Infraestructura**
   - CPU usage
   - Memory usage
   - Disk I/O

### Comandos de Monitoreo

```bash
# Ver logs en tiempo real
docker logs -f alwaysprint-backend

# Ver uso de recursos
docker stats alwaysprint-backend

# Ver conexiones a PostgreSQL
docker exec -it alwaysprint-postgres psql -U postgres -d alwaysprint \
  -c "SELECT count(*) FROM pg_stat_activity WHERE datname='alwaysprint';"

# Ver tamaño de tabla action_configs
docker exec -it alwaysprint-postgres psql -U postgres -d alwaysprint \
  -c "SELECT pg_size_pretty(pg_total_relation_size('action_configs'));"
```

---

## 🎯 Próximos Pasos

1. **Verificar migración `d4a203945821_add_full_name_to_users`**
   - Si fue creada después de `20260515151758`, actualizar su `down_revision`
   - Si fue creada antes, está bien como está

2. **Probar despliegue en staging** (si existe)
   - Verificar que migraciones se aplican correctamente
   - Probar rollback

3. **Desplegar a producción**
   - Push a main
   - Monitorear logs
   - Verificar funcionalidad

4. **Documentar en CHANGELOG**
   - Nueva feature: Sistema de configuración de acciones
   - Breaking changes: Ninguno
   - Migraciones: Nueva tabla action_configs

---

## 📞 Contacto

**Desarrollador**: Robles.AI  
**Email**: antonio@robles.ai  
**Teléfono**: +1 408 590 0153

---

© 2026 Inversiones On Line SAC
