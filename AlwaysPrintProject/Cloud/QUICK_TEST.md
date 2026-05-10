# Prueba Rápida del Sistema de Setup

Este documento te guía para probar el sistema de configuración inicial que acabamos de implementar.

## ✅ Problema Resuelto

Los siguientes errores han sido **completamente resueltos**:

1. ✅ `password cannot be longer than 72 bytes` - Incompatibilidad bcrypt 5.x/passlib
2. ✅ `'full_name' is an invalid keyword argument for User` - Campo faltante en modelo
3. ✅ `'str' object has no attribute 'hex'` - Problema de UUID con SQLite

**Soluciones implementadas:**
- Downgrade a bcrypt 4.1.3 + doble hashing (SHA-256 + bcrypt)
- Campo `full_name` agregado al modelo User
- Tipo GUID personalizado compatible con SQLite y PostgreSQL

Ver detalles técnicos en: `AlwaysPrintProject/Cloud/backend/BCRYPT_FIX.md`

---

## 🚀 Pasos para Probar

### 1. Verificar que los servicios estén corriendo

**Backend (Terminal 1):**
```bash
cd AlwaysPrintProject/Cloud/backend
conda activate alwaysprint
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Deberías ver:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [xxxxx] using WatchFiles
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

**Frontend (Terminal 2):**
```bash
cd AlwaysPrintProject/Cloud/frontend
npm run dev
```

Deberías ver:
```
  ▲ Next.js 15.x.x
  - Local:        http://localhost:3000
  - Network:      http://192.168.x.x:3000

 ✓ Starting...
 ✓ Ready in Xms
```

### 2. Verificar el estado del sistema

Abre tu navegador y ve a: http://localhost:3000

**Comportamiento esperado:**
- La página debería redirigirte automáticamente a `/setup`
- Verás un formulario titulado "Configuración Inicial"

### 3. Crear el usuario administrador

Completa el formulario con:
- **Nombre Completo:** Tu nombre (ej: "Antonio Robles")
- **Correo Electrónico:** Tu email (ej: "admin@ejemplo.com")
- **Contraseña:** Una contraseña de 8-72 caracteres (ej: "Admin123!@#$%^&*")
- **Confirmar Contraseña:** La misma contraseña

**Pruebas recomendadas:**
- ✅ Contraseña de 8 caracteres: `Admin123`
- ✅ Contraseña de 16 caracteres: `Admin123!@#$%^&*`
- ✅ Contraseña de 32 caracteres: `Admin123!@#$%^&*0123456789ABC`
- ✅ Contraseña con Unicode: `Contraseña123!ñáéíóú`
- ✅ Contraseña de 72 caracteres (máximo)

Haz clic en **"Crear Usuario Administrador"**

### 4. Verificar la creación exitosa

**Comportamiento esperado:**
1. Verás un mensaje de éxito con un ícono verde ✓
2. El mensaje dirá: "¡Configuración Completada!"
3. Después de 2 segundos, serás redirigido a `/login`

### 5. Iniciar sesión

En la página de login:
- **Email:** El email que usaste en el setup
- **Contraseña:** La contraseña que usaste en el setup

Haz clic en **"Iniciar Sesión"**

**Comportamiento esperado:**
- Serás redirigido al dashboard (`/dashboard`)
- Verás estadísticas del sistema (todas en 0 por ahora)
- El menú lateral mostrará tu nombre y rol (Admin)

---

## 🧪 Pruebas Adicionales

### Verificar que el setup solo funciona una vez

1. Intenta acceder a http://localhost:3000/setup
2. Deberías ser redirigido automáticamente a `/login` o `/dashboard`
3. Esto confirma que el sistema detecta que ya hay un usuario

### Verificar el endpoint de API directamente

**Verificar estado:**
```bash
curl http://127.0.0.1:8000/api/v1/setup/status
```

Respuesta esperada (después de crear el usuario):
```json
{
  "needs_setup": false,
  "message": "El sistema ya está configurado con 1 usuario(s)."
}
```

**Intentar crear otro usuario (debería fallar):**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/setup/initialize \
  -H "Content-Type: application/json" \
  -d '{
    "email": "otro@ejemplo.com",
    "password": "Password123",
    "full_name": "Otro Usuario"
  }'
```

Respuesta esperada:
```json
{
  "detail": "El sistema ya está configurado. No se puede crear otro usuario administrador inicial."
}
```

---

## 🔧 Solución de Problemas

### El backend no inicia

**Error:** `ImportError: cannot import name 'foreign' from 'sqlalchemy'`

**Solución:** Ya está resuelto. El archivo `workstation.py` fue corregido.

### Error de bcrypt

**Error:** `password cannot be longer than 72 bytes`

**Solución:** Ya está resuelto. Ejecuta:
```bash
conda activate alwaysprint
pip install "bcrypt==4.1.3"
```

### El frontend muestra "Verificando configuración" indefinidamente

**Causa:** El backend no está corriendo o hay un error de CORS

**Solución:**
1. Verifica que el backend esté corriendo en http://127.0.0.1:8000
2. Abre la consola del navegador (F12) y busca errores
3. Verifica que `.env.local` tenga: `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000`

### No puedo iniciar sesión después del setup

**Causa:** Posible problema con el token JWT

**Solución:**
1. Abre la consola del navegador (F12)
2. Ve a Application > Local Storage
3. Elimina todas las entradas
4. Recarga la página e intenta de nuevo

---

## 📝 Notas Importantes

1. **Contraseñas soportadas:**
   - Mínimo: 8 caracteres
   - Máximo: 72 caracteres
   - Soporta Unicode (ñ, acentos, emojis, etc.)
   - Soporta caracteres especiales (!@#$%^&*, etc.)

2. **Seguridad:**
   - Las contraseñas se hashean con SHA-256 + bcrypt (cost factor 12)
   - Los tokens JWT expiran en 24 horas
   - El sistema usa tenant isolation (cada cuenta está aislada)

3. **Primer usuario:**
   - Siempre es Admin (rol más alto)
   - No pertenece a ninguna cuenta (account_id = null)
   - Puede crear cuentas y usuarios adicionales

---

## ✅ Checklist de Verificación

- [ ] Backend corriendo en http://127.0.0.1:8000
- [ ] Frontend corriendo en http://localhost:3000
- [ ] Redirección automática a `/setup` funciona
- [ ] Formulario de setup se muestra correctamente
- [ ] Usuario administrador se crea exitosamente
- [ ] Redirección a `/login` después del setup
- [ ] Login funciona con las credenciales creadas
- [ ] Dashboard se muestra correctamente
- [ ] Intento de acceder a `/setup` redirige a `/login` o `/dashboard`

---

**¿Todo funcionó?** ¡Excelente! El sistema de setup está completamente operativo.

**¿Algo falló?** Revisa la sección "Solución de Problemas" o consulta los logs del backend.

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados  
Producto de la familia de automatización Robles.AI  
Contacto: antonio@robles.ai | +1 408 590 0153
