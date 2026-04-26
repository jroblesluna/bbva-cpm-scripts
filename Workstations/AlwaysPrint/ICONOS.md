# Configuración de Iconos - AlwaysPrint

## Archivos de Iconos

### logo.png
- **Ubicación**: `Workstations/AlwaysPrint/logo.png`
- **Formato**: PNG de alta resolución (2048x2048)
- **Uso**: Archivo fuente para generar el icono .ico

### logo.ico
- **Ubicación**: `Workstations/AlwaysPrint/logo.ico`
- **Formato**: ICO multi-resolución
- **Tamaños incluidos**: 16x16, 32x32, 48x48, 256x256 pixels
- **Generación**: Automática desde logo.png mediante `convert-icon.ps1`

## Usos del Icono

### 1. Icono de Aplicación (EXE)

Ambos ejecutables usan logo.ico como icono de aplicación:

**AlwaysPrintService.exe**
- Configurado en `AlwaysPrintService.csproj`:
  ```xml
  <ApplicationIcon>..\logo.ico</ApplicationIcon>
  ```
- Se ve en: Explorador de archivos, Administrador de tareas

**AlwaysPrintTray.exe**
- Configurado en `AlwaysPrintTray.csproj`:
  ```xml
  <ApplicationIcon>..\logo.ico</ApplicationIcon>
  ```
- Se ve en: Explorador de archivos, Administrador de tareas

### 2. Icono del System Tray (NotifyIcon)

El icono en la bandeja del sistema se carga desde el recurso embebido:

**Configuración**:
- Archivo embebido en `AlwaysPrintTray.csproj`:
  ```xml
  <EmbeddedResource Include="..\logo.ico" Link="Resources\logo.ico" />
  ```
- Cargado en `TrayApplicationContext.cs`:
  ```csharp
  private static Icon LoadIconFromResource()
  {
      var assembly = typeof(TrayApplicationContext).Assembly;
      using var stream = assembly.GetManifestResourceStream("AlwaysPrintTray.Resources.logo.ico");
      if (stream != null)
          return new Icon(stream);
      return SystemIcons.Application; // Fallback
  }
  ```

### 3. Logo en About (Acerca de)

El formulario "Acerca de" muestra el logo como imagen:

**Configuración**:
- Mismo recurso embebido que el Tray
- Cargado en `AboutForm.cs`:
  ```csharp
  private static Image? LoadLogoFromResource()
  {
      var assembly = Assembly.GetExecutingAssembly();
      using var stream = assembly.GetManifestResourceStream("AlwaysPrintTray.Resources.logo.ico");
      if (stream != null)
      {
          using var icon = new Icon(stream);
          return icon.ToBitmap();
      }
      return null;
  }
  ```
- Mostrado en un `PictureBox` de 80x80 pixels

## Proceso de Build

### Generación Automática

El script `build.ps1` genera automáticamente `logo.ico` si no existe:

```powershell
if (-not (Test-Path "logo.ico") -and (Test-Path "logo.png")) {
    Write-Host "=== Generando logo.ico desde logo.png ==="
    .\convert-icon.ps1
}
```

### Generación Manual

Si necesitas regenerar el icono manualmente:

```powershell
.\convert-icon.ps1
```

Este script:
1. Lee `logo.png`
2. Genera 4 versiones redimensionadas (16, 32, 48, 256 pixels)
3. Las combina en un archivo `logo.ico` multi-resolución
4. Usa interpolación de alta calidad para mantener la nitidez

## Cambiar el Logo

### Opción 1: Reemplazar logo.png

1. Reemplaza `logo.png` con tu nuevo logo
2. Asegúrate de que sea PNG de alta resolución (recomendado: 1024x1024 o mayor)
3. Ejecuta `.\convert-icon.ps1` para regenerar logo.ico
4. Ejecuta `.\build.ps1` para recompilar

### Opción 2: Reemplazar logo.ico directamente

1. Genera tu propio archivo .ico con múltiples resoluciones
2. Reemplaza `logo.ico`
3. Ejecuta `.\build.ps1` para recompilar

**Importante**: Si reemplazas logo.ico directamente, asegúrate de que incluya múltiples tamaños (16, 32, 48, 256) para que se vea bien en todos los contextos.

## Verificación

### Verificar icono del EXE

```powershell
# Ver propiedades del archivo en Explorador de Windows
# O usar PowerShell:
$shell = New-Object -ComObject Shell.Application
$folder = $shell.Namespace("$PWD\dist")
$item = $folder.ParseName("AlwaysPrintTray.exe")
$item.ExtendedProperty("System.FileDescription")
```

### Verificar recurso embebido

```powershell
# Listar recursos embebidos en el ensamblado
$assembly = [System.Reflection.Assembly]::LoadFile("$PWD\dist\AlwaysPrintTray.exe")
$assembly.GetManifestResourceNames()
# Debe incluir: AlwaysPrintTray.Resources.logo.ico
```

### Verificar en tiempo de ejecución

1. Instala la aplicación: `msiexec /i AlwaysPrint.msi /qn`
2. Verifica el icono en la bandeja del sistema (debe mostrar tu logo)
3. Haz doble clic en el icono para abrir "Acerca de"
4. Verifica que el logo aparece en la esquina superior izquierda

## Solución de Problemas

### El icono no aparece en el Tray

**Causa**: El recurso embebido no se cargó correctamente.

**Solución**:
1. Verifica que `logo.ico` existe en la raíz del proyecto
2. Verifica que `AlwaysPrintTray.csproj` incluye:
   ```xml
   <EmbeddedResource Include="..\logo.ico" Link="Resources\logo.ico" />
   ```
3. Recompila: `.\build.ps1`
4. Verifica los recursos embebidos (ver sección Verificación)

### El icono se ve borroso

**Causa**: El archivo .ico no incluye el tamaño correcto para el contexto.

**Solución**:
1. Regenera logo.ico desde un PNG de alta resolución: `.\convert-icon.ps1`
2. Asegúrate de que logo.png sea al menos 1024x1024 pixels

### El icono no aparece en el About

**Causa**: El método `LoadLogoFromResource()` está fallando silenciosamente.

**Solución**:
1. Verifica los logs en `C:\ProgramData\AlwaysPrint\logs\AlwaysPrint_yyyyMMdd.log`
2. Busca mensajes de error relacionados con la carga del icono
3. Verifica que el recurso está embebido (ver sección Verificación)

## Notas Técnicas

### Formato ICO

El formato ICO permite incluir múltiples imágenes en diferentes resoluciones en un solo archivo. Windows selecciona automáticamente la resolución más apropiada según el contexto:

- **16x16**: Menús, listas pequeñas
- **32x32**: Explorador de archivos (vista lista)
- **48x48**: Explorador de archivos (vista iconos medianos)
- **256x256**: Explorador de archivos (vista iconos grandes), About

### Recursos Embebidos

Los recursos embebidos se incluyen directamente en el ensamblado .exe durante la compilación. Esto tiene ventajas:

- ✓ No requiere archivos externos
- ✓ No puede ser modificado por el usuario
- ✓ Siempre disponible (no puede faltar)
- ✓ Se distribuye automáticamente con el EXE

El nombre del recurso embebido sigue el patrón:
```
<RootNamespace>.<LinkPath>
```

En nuestro caso:
- RootNamespace: `AlwaysPrintTray`
- LinkPath: `Resources\logo.ico`
- Nombre completo: `AlwaysPrintTray.Resources.logo.ico`
