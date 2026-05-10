# Guía de Pruebas - AlwaysPrint Cloud Manager

## Estado: ✅ LISTO PARA PRUEBAS

---

## Pre-requisitos

### Backend
- ✅ Python 3.12 con conda environment "alwaysprint"
- ✅ Base de datos SQLite con migraciones aplicadas
- ✅ Servidor corriendo en http://localhost:8000

### Frontend
- ✅ Node.js con dependencias instaladas
- ✅ Servidor corriendo en http://localhost:3000

---

## Iniciar Servidores

### Terminal 1: Backend
```bash
cd AlwaysPrintProject/Cloud/backend
conda activate alwaysprint
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Verificar:**
- Debe mostrar: `Application startup complete.`
- Abrir http://localhost:8000/docs para ver API docs

### Terminal 2: Frontend
```bash
cd AlwaysPrintProject/Cloud/frontend
npm run dev
```

**Verificar:**
- Debe mostrar: `Ready on http://localhost:3000`
- Abrir http://localhost:3000

---

## Pruebas Paso a Paso

### 1. Login y Navegación Básica

**Objetivo:** Verificar que el sistema carga correctamente

**Pasos:**
1. Abrir http://localhost:3000
2. Debe redirigir a `/login`
3. Verificar que aparece:
   - Logo de AlwaysPrint (80x80px)
   - Título "AlwaysPrint Cloud Manager"
   - Formulario de login

4. Ingresar credenciales:
   - Email: `antonio@robles.ai`
   - Password: `admin123`

5. Click en "Iniciar sesión"

**Resultado Esperado:**
- ✅ Redirección a `/dashboard`
- ✅ Logo visible en sidebar
- ✅ Menú de navegación completo
- ✅ Usuario "Antonio Robles" visible en sidebar
- ✅ Badge "Administrador"

---

### 2. Dashboard Principal

**Objetivo:** Verificar estadísticas y widgets

**Pasos:**
1. Estar en `/dashboard`
2. Observar las 4 tarjetas principales

**Resultado Esperado:**
- ✅ Estaciones Totales: 0 (aún no hay workstations)
- ✅ Estaciones Online: 0
- ✅ Contingencia Activa: 0
- ✅ **IPs Pendientes: 0** (tarjeta amarilla si hay IPs pendientes)

3. Verificar sección "Enlaces Rápidos"

**Resultado Esperado:**
- ✅ Enlace "Gestionar Estaciones"
- ✅ Enlace "Gestionar VLANs"
- ✅ Enlace "IPs Pendientes" (con badge si hay pendientes)

---

### 3. Gestión de Organizaciones

**Objetivo:** Crear organización para pruebas

**Pasos:**
1. Click en "Organizaciones" en el menú
2. Click en "Crear Organización"
3. Llenar formulario:
   - Nombre: `BBVA`
   - Descripción: `Banco BBVA - Oficinas Perú`
   - Timezone: `America/Lima` (UTC-5)
   - Estado: Activa ✓

4. Click en "Crear"

**Resultado Esperado:**
- ✅ Organización creada exitosamente
- ✅ Aparece en la lista
- ✅ Muestra timezone "America/Lima"
- ✅ Badge "Activa"

---

### 4. Gestión de Usuarios

**Objetivo:** Crear usuario operador

**Pasos:**
1. Click en "Usuarios" en el menú
2. Click en "Crear Usuario"
3. Llenar formulario:
   - Nombre completo: `Juan Pérez`
   - Email: `juan.perez@bbva.com`
   - Contraseña: `operador123`
   - Rol: Operador
   - Organización: BBVA
   - Timezone: (dejar vacío para heredar)
   - Estado: Activo ✓

4. Click en "Crear"

**Resultado Esperado:**
- ✅ Usuario creado exitosamente
- ✅ Aparece en la lista
- ✅ Muestra organización "BBVA"
- ✅ Timezone heredado de BBVA

---

### 5. Verificar Menú de IPs Pendientes

**Objetivo:** Confirmar que la página existe

**Pasos:**
1. Click en "IPs Pendientes" en el menú
2. Debe cargar `/dashboard/admin/pending-ips`

**Resultado Esperado:**
- ✅ Página carga sin errores
- ✅ Título "IPs Públicas Pendientes"
- ✅ 3 tarjetas de estadísticas:
  - Total Pendientes: 0
  - Cuentas Activas: 1 (BBVA)
  - Filtradas: 0
- ✅ Mensaje "No hay IPs pendientes"

---

### 6. Simular Conexión de Cliente (Opcional)

**Objetivo:** Probar flujo completo de autorización

**Nota:** Esta prueba requiere el cliente Windows. Si no está disponible, puedes simular creando una IP pendiente manualmente en la base de datos.

#### Opción A: Con Cliente Windows Real

**Pasos:**
1. Configurar cliente Windows para conectarse a `ws://localhost:8000/ws/workstation`
2. Cliente intenta conectarse
3. Cliente recibe mensaje de rechazo
4. Verificar en dashboard

**Resultado Esperado:**
- ✅ Widget "IPs Pendientes" muestra 1
- ✅ Tarjeta amarilla en dashboard
- ✅ Badge rojo en "Enlaces Rápidos"

#### Opción B: Simulación Manual (Para Testing)

**Pasos:**
1. Abrir terminal en backend
2. Ejecutar script de prueba:

```bash
cd AlwaysPrintProject/Cloud/backend
conda activate alwaysprint
python -c "
from app.core.database import SessionLocal
from app.models.account import PublicIP
from datetime import datetime

db = SessionLocal()

# Crear IP pendiente de prueba
ip = PublicIP(
    ip_address='200.48.225.10',
    description='Detectada automáticamente el 2026-05-10 02:00:00',
    is_authorized=False,
    account_id=None,
    first_seen=datetime.utcnow(),
    created_at=datetime.utcnow()
)

db.add(ip)
db.commit()
print(f'IP pendiente creada: {ip.ip_address}')
db.close()
"
```

3. Refrescar dashboard (F5)

**Resultado Esperado:**
- ✅ Widget "IPs Pendientes" muestra 1
- ✅ Tarjeta amarilla clickeable
- ✅ Badge "1" en enlaces rápidos

---

### 7. Autorizar IP Pendiente

**Objetivo:** Probar flujo de autorización

**Pre-requisito:** Tener una IP pendiente (de paso 6)

**Pasos:**
1. Click en widget "IPs Pendientes" o menú
2. Debe mostrar la IP `200.48.225.10`
3. Click en botón "Autorizar"
4. En el modal:
   - Seleccionar cuenta: BBVA
   - Descripción: `Oficina Principal Lima`
5. Click en "Autorizar"

**Resultado Esperado:**
- ✅ Modal se cierra
- ✅ IP desaparece de la lista
- ✅ Mensaje de éxito (toast o similar)
- ✅ Widget en dashboard muestra 0
- ✅ Tarjeta vuelve a mostrar VLANs

---

### 8. Verificar IP Autorizada

**Objetivo:** Confirmar que la IP fue autorizada correctamente

**Pasos:**
1. Ir a "Organizaciones"
2. Click en "Editar" en BBVA
3. Scroll hasta sección "IPs Públicas Autorizadas"

**Resultado Esperado:**
- ✅ Aparece IP `200.48.225.10`
- ✅ Descripción: "Oficina Principal Lima"
- ✅ Estado: Autorizada
- ✅ Fecha de autorización visible

---

### 9. Gestión de Workstations

**Objetivo:** Verificar página de workstations

**Pasos:**
1. Click en "Estaciones" en el menú
2. Debe cargar `/dashboard/workstations`

**Resultado Esperado:**
- ✅ Página carga sin errores
- ✅ 4 tarjetas de estadísticas (todas en 0)
- ✅ Filtros disponibles
- ✅ Mensaje "No hay workstations"

**Nota:** Las workstations aparecerán cuando el cliente Windows se conecte exitosamente.

---

### 10. Verificar Timezone

**Objetivo:** Confirmar que las fechas se formatean correctamente

**Pasos:**
1. Ir a "Usuarios"
2. Observar columna "Creado"
3. Debe mostrar formato: `2026-05-10 02:30:45 UTC-5`

**Resultado Esperado:**
- ✅ Formato correcto con timezone
- ✅ Hora ajustada según timezone del usuario
- ✅ Indicador UTC±X visible

---

### 11. Cambiar Timezone

**Objetivo:** Probar cambio de timezone

**Pasos:**
1. Ir a "Usuarios"
2. Click en "Editar" en tu usuario (Antonio Robles)
3. Cambiar timezone a `America/New_York` (UTC-5)
4. Click en "Actualizar"

**Resultado Esperado:**
- ✅ Página se recarga automáticamente
- ✅ Todas las fechas se actualizan al nuevo timezone
- ✅ Formato muestra UTC-5 (o UTC-4 según horario de verano)

---

### 12. Probar Permisos de Operador

**Objetivo:** Verificar restricciones de rol

**Pasos:**
1. Cerrar sesión
2. Iniciar sesión como operador:
   - Email: `juan.perez@bbva.com`
   - Password: `operador123`

**Resultado Esperado:**
- ✅ Login exitoso
- ✅ Badge "Operador" en sidebar
- ✅ Menú NO muestra:
  - Organizaciones
  - Usuarios
  - IPs Pendientes
- ✅ Menú SÍ muestra:
  - Dashboard
  - Estaciones
  - VLANs
  - Configuración
  - Mensajes
  - Auditoría

---

### 13. Rechazar IP Pendiente

**Objetivo:** Probar rechazo de IP

**Pre-requisito:** Crear otra IP pendiente (repetir paso 6B)

**Pasos:**
1. Iniciar sesión como admin
2. Ir a "IPs Pendientes"
3. Click en "Rechazar" en la IP
4. Confirmar en el diálogo

**Resultado Esperado:**
- ✅ IP eliminada de la lista
- ✅ No aparece en ninguna organización
- ✅ Acción registrada en auditoría

---

### 14. Verificar Auditoría

**Objetivo:** Confirmar que las acciones se registran

**Pasos:**
1. Click en "Auditoría" en el menú
2. Debe mostrar historial de acciones

**Resultado Esperado:**
- ✅ Registro de creación de organización
- ✅ Registro de creación de usuario
- ✅ Registro de autorización de IP
- ✅ Registro de rechazo de IP
- ✅ Fechas con timezone correcto

---

### 15. Verificar Responsividad

**Objetivo:** Probar diseño móvil

**Pasos:**
1. Abrir DevTools (F12)
2. Toggle device toolbar (Ctrl+Shift+M)
3. Seleccionar "iPhone 12 Pro"
4. Navegar por las páginas

**Resultado Esperado:**
- ✅ Sidebar se oculta
- ✅ Menú hamburguesa visible
- ✅ Logo visible en header móvil
- ✅ Tarjetas se apilan verticalmente
- ✅ Tablas son scrolleables horizontalmente

---

## Checklist Final

### Funcionalidades Core
- [ ] Login funciona
- [ ] Dashboard carga correctamente
- [ ] Logo AlwaysPrint visible en todos lados
- [ ] Navegación funciona
- [ ] Logout funciona

### Gestión de Datos
- [ ] Crear organización
- [ ] Editar organización
- [ ] Crear usuario
- [ ] Editar usuario
- [ ] Cambiar timezone

### Autorización de IPs
- [ ] IP pendiente aparece en dashboard
- [ ] Widget muestra contador correcto
- [ ] Página de IPs pendientes funciona
- [ ] Autorizar IP funciona
- [ ] Rechazar IP funciona
- [ ] IP autorizada aparece en organización

### Permisos
- [ ] Admin ve todas las opciones
- [ ] Operador tiene menú limitado
- [ ] Usuario no puede auto-desactivarse
- [ ] Usuario no puede auto-eliminarse

### Timezone
- [ ] Fechas se formatean correctamente
- [ ] Herencia de timezone funciona
- [ ] Cambio de timezone recarga página
- [ ] Formato incluye UTC±X

### UI/UX
- [ ] Diseño responsivo funciona
- [ ] Iconos cargan correctamente
- [ ] Colores y estilos consistentes
- [ ] Mensajes de error claros
- [ ] Loading states visibles

---

## Problemas Comunes y Soluciones

### Backend no inicia
**Síntoma:** Error al ejecutar uvicorn

**Solución:**
```bash
# Verificar environment
conda activate alwaysprint
conda list | grep fastapi

# Reinstalar dependencias si es necesario
pip install -r requirements.txt
```

### Frontend no carga
**Síntoma:** Error "Cannot connect to backend"

**Solución:**
1. Verificar que backend esté corriendo en puerto 8000
2. Abrir http://localhost:8000/docs
3. Verificar CORS en backend

### IPs pendientes no aparecen
**Síntoma:** Widget muestra 0 pero debería haber IPs

**Solución:**
```bash
# Verificar en base de datos
cd AlwaysPrintProject/Cloud/backend
conda activate alwaysprint
python -c "
from app.core.database import SessionLocal
from app.models.account import PublicIP

db = SessionLocal()
pending = db.query(PublicIP).filter_by(is_authorized=False).all()
print(f'IPs pendientes: {len(pending)}')
for ip in pending:
    print(f'  - {ip.ip_address}')
db.close()
"
```

### Fechas en UTC+0
**Síntoma:** Fechas no se formatean con timezone

**Solución:**
1. Verificar que usuario tenga timezone asignado
2. Verificar que organización tenga timezone
3. Refrescar página (F5)

---

## Logs y Debugging

### Ver logs del backend
```bash
# Los logs aparecen en la terminal donde corre uvicorn
# Buscar líneas con ERROR o WARNING
```

### Ver logs del frontend
```bash
# Abrir DevTools (F12) → Console
# Buscar errores en rojo
```

### Ver queries SQL
```bash
# Agregar en backend/.env
SQLALCHEMY_ECHO=true

# Reiniciar backend
# Verás todas las queries SQL en la terminal
```

---

## Siguiente Paso: Pruebas con Cliente Real

Una vez completadas todas las pruebas anteriores, el sistema está listo para:

1. **Conectar cliente Windows real**
2. **Probar flujo completo de registro**
3. **Verificar comunicación bidireccional**
4. **Probar comandos remotos**
5. **Monitorear estado en tiempo real**

---

**Estado:** ✅ Sistema listo para pruebas completas  
**Última actualización:** 2026-05-10  
**Próximo paso:** Ejecutar pruebas paso a paso
