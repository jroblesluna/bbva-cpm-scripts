# 🔧 Troubleshooting Backend - Bad Gateway 502

## Diagnóstico Rápido

### 1. Verificar Estado del Contenedor

```bash
# SSH al servidor EC2
ssh ec2-user@{servidor-ip}

# Ver contenedores en ejecución
docker ps -a

# Ver logs del contenedor backend
docker logs alwaysprint-backend --tail 100

# Ver logs en tiempo real
docker logs -f alwaysprint-backend
```

### 2. Verificar Migraciones

```bash
# Entrar al contenedor
docker exec -it alwaysprint-backend bash

# Verificar versión actual de la BD
alembic current

# Ver historial de migraciones
alembic history

# Intentar migración manual
alembic upgrade head
```

### 3. Verificar Variables de Entorno

```bash
# Ver variables del contenedor
docker exec alwaysprint-backend env | grep -E "DB_|BUILD_TAG"

# Verificar archivo .env
cat /opt/alwaysprint/.env
```

### 4. Verificar Conectividad a PostgreSQL

```bash
# Desde el host
docker exec alwaysprint-postgres psql -U postgres -d alwaysprint -c "SELECT version();"

# Verificar que el backend puede conectarse
docker exec alwaysprint-backend pg_isready -h alwaysprint-postgres -p 5432 -U postgres
```

### 5. Reiniciar Servicios

```bash
# Reiniciar solo el backend
docker restart alwaysprint-backend

# Ver logs durante el reinicio
docker logs -f alwaysprint-backend

# Si persiste, recrear el contenedor
cd /opt/alwaysprint
docker-compose down backend
docker-compose up -d backend
```

## Errores Comunes

### Error: "No se pudo conectar a la base de datos"

**Causa**: PostgreSQL no está disponible o las credenciales son incorrectas.

**Solución**:
```bash
# Verificar que PostgreSQL está corriendo
docker ps | grep postgres

# Verificar logs de PostgreSQL
docker logs alwaysprint-postgres --tail 50

# Reiniciar PostgreSQL si es necesario
docker restart alwaysprint-postgres
```

### Error: "Fallo al aplicar migraciones"

**Causa**: Conflicto en el historial de migraciones o error en SQL.

**Solución**:
```bash
# Ver el error específico
docker logs alwaysprint-backend | grep -A 20 "ERROR"

# Verificar versión actual
docker exec alwaysprint-backend alembic current

# Si hay conflicto, verificar en la BD
docker exec alwaysprint-postgres psql -U postgres -d alwaysprint \
  -c "SELECT * FROM alembic_version;"

# Opción 1: Marcar migración como aplicada (si ya existe la tabla)
docker exec alwaysprint-backend alembic stamp 20260515151758

# Opción 2: Hacer downgrade y volver a subir
docker exec alwaysprint-backend alembic downgrade -1
docker exec alwaysprint-backend alembic upgrade head
```

### Error: "permission denied: /docker-entrypoint.sh"

**Causa**: El script no tiene permisos de ejecución.

**Solución**:
```bash
# Reconstruir la imagen
cd /opt/alwaysprint
docker-compose build backend
docker-compose up -d backend
```

### Error: "Bad Gateway" persistente

**Causa**: El contenedor se está reiniciando constantemente.

**Solución**:
```bash
# Ver si el contenedor se está reiniciando
docker ps -a | grep alwaysprint-backend

# Ver el número de reinicios
docker inspect alwaysprint-backend | grep -A 5 RestartCount

# Ver el último error
docker logs alwaysprint-backend --tail 200

# Detener el reinicio automático temporalmente
docker update --restart=no alwaysprint-backend

# Intentar iniciar manualmente para ver el error
docker start alwaysprint-backend
docker logs -f alwaysprint-backend
```

## Verificación Post-Fix

```bash
# 1. Verificar que el contenedor está corriendo
docker ps | grep alwaysprint-backend

# 2. Verificar health check
curl http://localhost:8000/api/v1/health

# 3. Verificar desde fuera del servidor
curl https://alwaysprint.apps.iol.pe/api/v1/health

# 4. Verificar logs sin errores
docker logs alwaysprint-backend --tail 50 | grep -i error

# 5. Verificar que las migraciones se aplicaron
docker exec alwaysprint-backend alembic current
# Debe mostrar: 20260515151758 (head)
```

## Rollback de Emergencia

Si el problema persiste y necesitas volver a la versión anterior:

```bash
# 1. Ver tags disponibles en ECR
aws ecr list-images --repository-name alwaysprint-prod-backend \
  --query 'imageIds[*].imageTag' --output table

# 2. Actualizar .env con el tag anterior
cd /opt/alwaysprint
sed -i 's/BUILD_TAG=.*/BUILD_TAG=<tag-anterior>/' .env

# 3. Hacer downgrade de la migración
docker exec alwaysprint-backend alembic downgrade -1

# 4. Reiniciar con la versión anterior
docker-compose down backend
docker-compose up -d backend

# 5. Verificar
curl http://localhost:8000/api/v1/health
```

## Comandos Útiles

```bash
# Ver todas las migraciones aplicadas
docker exec alwaysprint-postgres psql -U postgres -d alwaysprint \
  -c "SELECT * FROM alembic_version;"

# Ver si la tabla action_configs existe
docker exec alwaysprint-postgres psql -U postgres -d alwaysprint \
  -c "\dt action_configs"

# Ver estructura de la tabla
docker exec alwaysprint-postgres psql -U postgres -d alwaysprint \
  -c "\d action_configs"

# Ver logs de nginx (proxy)
docker logs alwaysprint-nginx --tail 100

# Verificar conectividad interna
docker exec alwaysprint-nginx curl http://backend:8000/api/v1/health
```

## Contacto

Si el problema persiste después de seguir estos pasos, contactar a:

**Desarrollador**: antonio@robles.ai  
**Teléfono**: +1 408 590 0153

---

© 2026 Inversiones On Line SAC
