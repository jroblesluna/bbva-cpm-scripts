# AlwaysPrint Cloud Manager - Guía de Inicio Rápido

**Fecha**: 9 de mayo de 2026

---

## 🚀 Inicio Rápido (Primera Vez)

### 1. Iniciar el Backend

```powershell
# Ir al directorio backend
cd AlwaysPrintProject\Cloud\backend

# Activar entorno conda
conda activate alwaysprint

# Iniciar servidor
uvicorn app.main:app --reload
```

El backend estará disponible en: http://localhost:8000

### 2. Iniciar el Frontend

Abrir **otra terminal**:

```powershell
# Ir al directorio frontend
cd AlwaysPrintProject\Cloud\frontend

# Instalar dependencias (solo la primera vez)
npm install

# Iniciar servidor de desarrollo
npm run dev
```

El frontend estará disponible en: http://localhost:3000

### 3. Configuración Inicial

1. **Abrir navegador** en http://localhost:3000

2. **Serás redirigido automáticamente** a la pantalla de configuración inicial

3. **Completar el formulario**:
   - Nombre Completo: `Administrador`
   - Correo Electrónico: `admin@ejemplo.com`
   - Contraseña: `admin123` (o la que prefieras, mínimo 8 caracteres)
   - Confirmar Contraseña: `admin123`

4. **Click en "Crear Usuario Administrador"**

5. **Serás redirigido automáticamente** a la página de login

6. **Iniciar sesión** con las credenciales que acabas de crear

7. **¡Listo!** Ya puedes usar el sistema

---

## 🔄 Inicio Rápido (Uso Normal)

Si ya configuraste el sistema anteriormente:

### 1. Iniciar Backend

```powershell
cd AlwaysPrintProject\Cloud\backend
conda activate alwaysprint
uvicorn app.main:app --reload
```

### 2. Iniciar Frontend

```powershell
cd AlwaysPrintProject\Cloud\frontend
npm run dev
```

### 3. Acceder

Abrir http://localhost:3000 y hacer login con tus credenciales.

---

## 📝 Credenciales por Defecto

Si usaste los valores sugeridos en la configuración inicial:

- **Email**: `admin@ejemplo.com`
- **Contraseña**: `admin123`
- **Rol**: Administrador

**⚠️ IMPORTANTE**: Cambia estas credenciales en producción.

---

## 🐛 Solución de Problemas

### Error: "El sistema ya está configurado"

Si intentas acceder a `/setup` pero el sistema ya tiene usuarios, serás redirigido automáticamente a `/login`.

### Error: "Cannot connect to backend"

1. Verifica que el backend esté corriendo en http://localhost:8000
2. Verifica que el archivo `.env.local` del frontend tenga:
   ```env
   NEXT_PUBLIC_API_URL=http://localhost:8000
   ```

### Resetear el Sistema

Si quieres volver a la configuración inicial (⚠️ **ESTO BORRARÁ TODOS LOS DATOS**):

```powershell
# Detener backend y frontend
# Eliminar base de datos
cd AlwaysPrintProject\Cloud\backend
Remove-Item alwaysprint.db

# Recrear base de datos
alembic upgrade head

# Reiniciar backend y frontend
```

---

## 📚 Documentación Adicional

- **Backend API**: http://localhost:8000/docs (Swagger UI)
- **Backend README**: `AlwaysPrintProject/Cloud/backend/README.md`
- **Frontend README**: `AlwaysPrintProject/Cloud/frontend/README.md`
- **Arquitectura**: `AlwaysPrintProject/Cloud/ARCHITECTURE.md`

---

## 📞 Soporte

**Robles.AI**  
Email: antonio@robles.ai  
Teléfono: +1 408 590 0153  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados  
Producto de la familia de automatización Robles.AI  
Prohibida la utilización sin autorización de Inversiones On Line SAC
