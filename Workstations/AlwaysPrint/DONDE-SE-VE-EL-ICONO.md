# Dónde se Visualiza el Icono - AlwaysPrint

## Resumen Visual

El logo de AlwaysPrint (`logo.png` → `logo.ico`) se visualiza en **5 ubicaciones diferentes**:

### ✅ 1. Explorador de Archivos

**Ubicación**: `C:\Program Files (x86)\Robles.AI\AlwaysPrint\`

**Archivos con icono**:
- `AlwaysPrintService.exe` 🖼️
- `AlwaysPrintTray.exe` 🖼️

**Cómo se ve**:
- Vista de iconos: Logo grande
- Vista de lista: Logo pequeño junto al nombre del archivo
- Vista de detalles: Logo pequeño en la columna de nombre

**Configuración**: `<ApplicationIcon>..\logo.ico</ApplicationIcon>` en los `.csproj`

---

### ✅ 2. Administrador de Tareas

**Ubicación**: Ctrl+Shift+Esc → Pestaña "Procesos" o "Detalles"

**Procesos con icono**:
- `AlwaysPrintService.exe` 🖼️
- `AlwaysPrintTray.exe` 🖼️

**Cómo se ve**:
- Logo pequeño junto al nombre del proceso
- Ayuda a identificar visualmente los procesos de AlwaysPrint

**Configuración**: Mismo que Explorador de Archivos (icono del EXE)

---

### ✅ 3. Bandeja del Sistema (System Tray)

**Ubicación**: Esquina inferior derecha de la pantalla, junto al reloj

**Icono**: AlwaysPrintTray 🖼️

**Cómo se ve**:
- Logo pequeño (16x16 o 32x32 pixels según DPI)
- Siempre visible mientras el servicio está activo
- Clic derecho muestra menú contextual

**Configuración**: 
- Recurso embebido en `AlwaysPrintTray.exe`
- Cargado dinámicamente en `TrayApplicationContext.cs`

---

### ✅ 4. Ventana "Acerca de"

**Ubicación**: Clic derecho en icono del Tray → "Acerca de"

**Logo**: Imagen grande en la esquina superior izquierda 🖼️

**Cómo se ve**:
- PictureBox de 80x80 pixels
- Logo a la izquierda, información del producto a la derecha
- Versión, copyright, contacto

**Configuración**:
- Mismo recurso embebido que el Tray
- Convertido a Bitmap en `AboutForm.cs`

---

### ✅ 5. Panel de Control / Configuración

**Ubicación**: 
- Windows 10/11: Configuración → Aplicaciones → Aplicaciones instaladas
- Windows 7/8: Panel de Control → Programas y características

**Programa**: AlwaysPrint 🖼️

**Cómo se ve**:
- Logo junto al nombre "AlwaysPrint"
- Información: Versión, Fabricante (Robles.AI), Tamaño
- Botones: Modificar, Desinstalar

**Configuración**:
```xml
<Icon Id="ProductIcon" SourceFile="logo.ico" />
<Property Id="ARPPRODUCTICON" Value="ProductIcon" />
```

---

## Tabla Resumen

| Ubicación | Tamaño del Icono | Archivo Fuente | Configuración |
|-----------|------------------|----------------|---------------|
| Explorador de Archivos | 16x16, 32x32, 48x48, 256x256 | `logo.ico` | `.csproj` ApplicationIcon |
| Administrador de Tareas | 16x16, 32x32 | `logo.ico` | `.csproj` ApplicationIcon |
| System Tray | 16x16, 32x32 | Recurso embebido | `TrayApplicationContext.cs` |
| Ventana "Acerca de" | 80x80 (escalado) | Recurso embebido | `AboutForm.cs` |
| Panel de Control | 32x32, 48x48 | `logo.ico` | `Product.wxs` ARPPRODUCTICON |

---

## Verificación

### Verificar icono en EXEs

```powershell
# Ver propiedades del archivo en Explorador de Windows
# Clic derecho → Propiedades → Pestaña "General"
# Debe mostrar el logo de AlwaysPrint
```

### Verificar icono en Tray

```powershell
# 1. Instalar AlwaysPrint
msiexec /i AlwaysPrint.msi /qn

# 2. Verificar que el servicio está corriendo
Get-Service AlwaysPrintService

# 3. Buscar el icono en la bandeja del sistema (junto al reloj)
# Debe mostrar el logo de AlwaysPrint
```

### Verificar icono en Panel de Control

```powershell
# Windows 10/11:
# 1. Abrir Configuración (Win+I)
# 2. Ir a Aplicaciones → Aplicaciones instaladas
# 3. Buscar "AlwaysPrint"
# 4. Debe mostrar el logo junto al nombre

# Windows 7/8:
# 1. Abrir Panel de Control
# 2. Ir a Programas y características
# 3. Buscar "AlwaysPrint"
# 4. Debe mostrar el logo en la columna de iconos
```

### Verificar recurso embebido

```powershell
# Listar recursos embebidos en el ensamblado
$assembly = [System.Reflection.Assembly]::LoadFile("$PWD\dist\AlwaysPrintTray.exe")
$assembly.GetManifestResourceNames()

# Debe incluir: AlwaysPrintTray.Resources.logo.ico
```

---

## Actualizar el Logo

### Paso 1: Reemplazar logo.png

1. Reemplaza `Workstations/AlwaysPrint/logo.png` con tu nuevo logo
2. Recomendado: PNG de alta resolución (mínimo 512x512, ideal 1024x1024 o mayor)
3. Fondo transparente (opcional pero recomendado)

### Paso 2: Regenerar logo.ico

```powershell
cd Workstations\AlwaysPrint
.\convert-icon.ps1
```

Este script:
- Lee `logo.png`
- Genera 4 versiones: 16x16, 32x32, 48x48, 256x256
- Crea `logo.ico` con todas las resoluciones
- Usa interpolación de alta calidad

### Paso 3: Recompilar

```powershell
.\build.ps1
```

Esto:
- Compila los EXEs con el nuevo icono
- Embebe el icono en `AlwaysPrintTray.exe`
- Incluye el icono en el MSI para Panel de Control

### Paso 4: Verificar

1. Instalar: `msiexec /i AlwaysPrint.msi /qn`
2. Verificar en las 5 ubicaciones listadas arriba
3. Si el icono no se actualiza en Panel de Control, desinstalar y reinstalar

---

## Notas Técnicas

### Formato ICO Multi-Resolución

El archivo `logo.ico` contiene 4 imágenes en diferentes resoluciones:

- **16x16**: System Tray (DPI normal), listas pequeñas
- **32x32**: System Tray (DPI alto), Panel de Control, Explorador (lista)
- **48x48**: Panel de Control (vista grande), Explorador (iconos medianos)
- **256x256**: Explorador (iconos muy grandes), About (escalado a 80x80)

Windows selecciona automáticamente la resolución más apropiada según:
- DPI del monitor
- Tamaño de visualización solicitado
- Contexto (Tray, Explorador, Panel de Control)

### Caché de Iconos

Windows cachea los iconos. Si actualizas el logo y no se ve el cambio:

**Limpiar caché de iconos**:
```cmd
REM Detener Explorer
taskkill /f /im explorer.exe

REM Eliminar caché de iconos
del /a /q "%localappdata%\IconCache.db"
del /a /f /q "%localappdata%\Microsoft\Windows\Explorer\iconcache*"

REM Reiniciar Explorer
start explorer.exe
```

**O simplemente reiniciar Windows** (más simple y confiable).

### Recursos Embebidos

El icono se embebe en `AlwaysPrintTray.exe` durante la compilación:

**Ventajas**:
- No requiere archivo externo
- No puede ser modificado por el usuario
- Siempre disponible
- Se distribuye automáticamente con el EXE

**Nombre del recurso**: `AlwaysPrintTray.Resources.logo.ico`

Este nombre se forma de:
- `AlwaysPrintTray` = RootNamespace del proyecto
- `Resources` = carpeta virtual (Link en .csproj)
- `logo.ico` = nombre del archivo

---

## Resumen

✅ **5 ubicaciones** donde se visualiza el logo
✅ **Multi-resolución** (16, 32, 48, 256 pixels)
✅ **Actualización simple** (reemplazar PNG, ejecutar script, recompilar)
✅ **Panel de Control** incluido (ARPPRODUCTICON)
✅ **Recurso embebido** para Tray y About
✅ **Icono de aplicación** para EXEs

El logo de AlwaysPrint está completamente integrado en todos los puntos de contacto visual con el usuario. 🎨
