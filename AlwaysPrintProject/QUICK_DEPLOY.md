# 🚀 Guía Rápida de Despliegue

## ⚡ Despliegue en 3 Pasos

### 1️⃣ Commit y Push

```bash
git add .
git commit -m "feat: Sistema de configuración de acciones administrativas

- Motor de ejecución de acciones (ActionEngine)
- 9 funciones administrativas implementadas
- API REST completa (8 endpoints)
- UI de gestión en frontend
- Migraciones automáticas en Docker
- Documentación completa

Closes #XXX"

git push origin main
```

### 2️⃣ Esperar GitHub Actions

Monitorear en: https://github.com/{tu-repo}/actions

**Debe completar**:
- ✅ Deploy Backend (build + push ECR + deploy EC2)
- ✅ Deploy Frontend (build + deploy)

**Tiempo estimado**: 5-10 minutos

### 3️⃣ Verificar Despliegue

```bash
# Health check
curl https://alwaysprint.apps.iol.pe/api/v1/health
# Debe retornar: {"status": "healthy", "build_tag": "abc12345"}

# Swagger UI
open https://alwaysprint.apps.iol.pe/docs
# Debe mostrar nuevos endpoints en sección "Configuración de Acciones"

# Frontend
open https://alwaysprint-frontend.vercel.app/dashboard/admin/action-configs
# Debe mostrar página de gestión de configuraciones
```

---

## ✅ Checklist Rápido

### Pre-Push
- [x] Código compila sin errores
- [x] Migración actualizada (`down_revision = '007_add_telemetry_connectivity'`)
- [x] `docker-entrypoint.sh` creado
- [x] Dockerfile actualizado

### Post-Deploy
- [ ] GitHub Actions verde ✅
- [ ] Health check OK
- [ ] Swagger muestra nuevos endpoints
- [ ] Frontend muestra nueva página
- [ ] Logs backend: "✓ Migraciones aplicadas exitosamente"

---

## 🔍 Verificación Rápida de Migraciones

```bash
# SSH a servidor
ssh ec2-user@{tu-servidor}

# Ver logs del contenedor
docker logs alwaysprint-backend --tail 50

# Buscar estas líneas:
# ✓ Conexión a base de datos establecida
# Ejecutando migraciones de base de datos...
# ✓ Migraciones aplicadas exitosamente
# Iniciando servidor uvicorn...

# Verificar tabla en PostgreSQL
docker exec -it alwaysprint-postgres psql -U postgres -d alwaysprint \
  -c "SELECT * FROM alembic_version;"
# Debe mostrar: 20260515151758

# Verificar que existe la tabla
docker exec -it alwaysprint-postgres psql -U postgres -d alwaysprint \
  -c "\dt action_configs"
# Debe mostrar la tabla
```

---

## 🧪 Prueba Rápida End-to-End

### 1. Login en Frontend

```
URL: https://alwaysprint-frontend.vercel.app/login
Usuario: admin@example.com
Password: {tu-password}
```

### 2. Ir a Configuraciones de Acciones

```
URL: /dashboard/admin/action-configs
```

### 3. Subir Configuración de Ejemplo

```
Archivo: AlwaysPrintProject/Client/CPM_Compliant.alwaysconfig
Activar: ✅ Sí
```

### 4. Verificar en Backend

```bash
curl -H "Authorization: Bearer {token}" \
  https://alwaysprint.apps.iol.pe/api/v1/organizations/1/config

# Debe retornar:
{
  "id": 1,
  "organization_id": 1,
  "name": "CPM_Compliant",
  "version": "1.0",
  "config_hash": "a3f5c8d2",
  "is_active": true,
  ...
}
```

### 5. Instalar Cliente Windows (Opcional)

```powershell
# En workstation de prueba
.\AlwaysPrint.msi

# Verificar logs en Event Viewer
# Application → AlwaysPrintService
# Buscar: "ConfigManager: verificando configuración"
```

---

## 🚨 Si Algo Falla

### Backend no inicia

```bash
# Ver logs
docker logs alwaysprint-backend --tail 100

# Si error de migraciones, aplicar manualmente
docker exec -it alwaysprint-backend alembic upgrade head

# Reiniciar
docker restart alwaysprint-backend
```

### Endpoint 404

```bash
# Verificar router
docker exec -it alwaysprint-backend cat app/api/v1/router.py | grep action_config

# Si no aparece, el código no se desplegó
# Verificar GitHub Actions y volver a desplegar
```

### Frontend no muestra página

```bash
# Verificar build
cd AlwaysPrintProject/Cloud/frontend
npm run build

# Verificar archivo existe
ls src/app/dashboard/admin/action-configs/page.tsx

# Re-deploy
git push origin main
```

---

## 📞 Ayuda Rápida

**Logs Backend**: `docker logs alwaysprint-backend`  
**Logs PostgreSQL**: `docker logs alwaysprint-postgres`  
**Swagger UI**: https://alwaysprint.apps.iol.pe/docs  
**GitHub Actions**: https://github.com/{repo}/actions  

**Contacto**: antonio@robles.ai | +1 408 590 0153

---

## 🎉 ¡Listo!

Si todos los checks están ✅, el sistema está desplegado y funcionando.

**Próximo paso**: Probar subiendo una configuración real y verificando que las workstations la descargan automáticamente.

---

© 2026 Inversiones On Line SAC
