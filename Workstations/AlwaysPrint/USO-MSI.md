# Uso del MSI - AlwaysPrint

## ProductCode Fijo

AlwaysPrint usa un **ProductCode fijo** para permitir que cualquier MSI pueda instalar, actualizar o desinstalar cualquier versión.

**ProductCode**: `C7A4B5D6-A200-4E00-8F00-0BBA00000001` (FIJO - nunca cambia)

## Comandos

### ✅ Instalar o Actualizar

```cmd
msiexec /i AlwaysPrint.msi /qn
```

**Qué hace**:
- Si no hay versión instalada → instala
- Si hay versión anterior → actualiza (reinstala con archivos nuevos)
- Si hay la misma versión → reinstala (útil para reparar)

**Parámetros**:
- `/i` = instalar
- `/qn` = sin interfaz gráfica (silencioso)

**Con log**:
```cmd
msiexec /i AlwaysPrint.msi /qn /L*v install.log
```

### ✅ Desinstalar

```cmd
msiexec /x AlwaysPrint.msi /qn
```

**Qué hace**:
- Busca el ProductCode en el MSI
- Como el ProductCode es fijo, encuentra el producto instalado
- Lo desinstala

**Parámetros**:
- `/x` = desinstalar
- `/qn` = sin interfaz gráfica (silencioso)

**Con log**:
```cmd
msiexec /x AlwaysPrint.msi /qn /L*v uninstall.log
```

**IMPORTANTE**: Funciona con **cualquier MSI** de AlwaysPrint, no importa la versión.

## Ejemplos de Uso

### Escenario 1: Primera instalación

```cmd
REM Tienes: Nada instalado
REM MSI: versión 1.26.426.1000

msiexec /i AlwaysPrint.msi /qn

REM Resultado: Instala versión 1.26.426.1000
```

### Escenario 2: Actualizar versión

```cmd
REM Tienes: versión 1.26.426.1000 instalada
REM MSI: versión 1.26.426.1100

msiexec /i AlwaysPrint.msi /qn

REM Resultado: Actualiza a versión 1.26.426.1100
REM Windows Installer detecta mismo ProductCode, versión mayor → reinstala
```

### Escenario 3: Reinstalar misma versión

```cmd
REM Tienes: versión 1.26.426.1000 instalada
REM MSI: versión 1.26.426.1000

msiexec /i AlwaysPrint.msi /qn

REM Resultado: Reinstala versión 1.26.426.1000
REM Útil para reparar instalación corrupta
```

### Escenario 4: Desinstalar con cualquier MSI

```cmd
REM Tienes: versión 1.26.426.1000 instalada
REM MSI: versión 1.26.426.1200 (no instalada, solo el archivo)

msiexec /x AlwaysPrint.msi /qn

REM Resultado: Desinstala la versión 1.26.426.1000
REM No importa que el MSI sea de otra versión - el ProductCode es el mismo
```

### Escenario 5: Downgrade (instalar versión más antigua)

```cmd
REM Tienes: versión 1.26.426.1200 instalada
REM MSI: versión 1.26.426.1000 (más antigua)

msiexec /i AlwaysPrint.msi /qn

REM Resultado: Reinstala con versión 1.26.426.1000
REM Con ProductCode fijo, Windows Installer permite downgrades
REM (reinstala todos los archivos con la versión del MSI)
```

## Cómo Funciona

### Con ProductCode Fijo

1. **Todos los MSIs tienen el mismo ProductCode**
   - Build 1 → ProductCode: `C7A4B5D6-A200-4E00-8F00-0BBA00000001`
   - Build 2 → ProductCode: `C7A4B5D6-A200-4E00-8F00-0BBA00000001` (mismo)
   - Build 3 → ProductCode: `C7A4B5D6-A200-4E00-8F00-0BBA00000001` (mismo)

2. **Windows Installer reconoce todos como el mismo producto**
   - Al instalar: busca si ya existe ese ProductCode
   - Si existe: reinstala (actualiza archivos)
   - Si no existe: instala nuevo

3. **La versión solo se usa para mostrar en Panel de Control**
   - No afecta la lógica de instalación/desinstalación
   - Cada build tiene versión única: `1.26.426.1000`, `1.26.426.1100`, etc.

### Propiedades Configuradas

En `Product.wxs`:

```xml
<Package ProductCode="C7A4B5D6-A200-4E00-8F00-0BBA00000001"
         Version="$(var.ProductVersion)">
  
  <!-- Permitir reinstalación con archivos actualizados -->
  <Property Id="REINSTALLMODE" Value="amus" />
  
  <!-- Reinstalar todos los componentes -->
  <Property Id="REINSTALL" Value="ALL" />
</Package>
```

**REINSTALLMODE=amus**:
- `a` = reinstalar todos los archivos
- `m` = reescribir entradas de registro
- `u` = reescribir accesos directos
- `s` = reescribir iconos

## Verificación

### Ver versión instalada

```cmd
reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{C7A4B5D6-A200-4E00-8F00-0BBA00000001}" /v DisplayVersion
```

### Ver ProductCode del MSI

```cmd
REM Con WiX instalado:
wix msi info AlwaysPrint.msi

REM Buscar línea: ProductCode: {C7A4B5D6-A200-4E00-8F00-0BBA00000001}
```

### Verificar servicio

```cmd
sc query AlwaysPrintService
```

## Deployment en Producción

### Actualización masiva

```cmd
REM Script para actualizar todas las estaciones:
REM deploy.bat

@echo off
echo Actualizando AlwaysPrint...
msiexec /i \\servidor\share\AlwaysPrint.msi /qn /L*v C:\Temp\alwaysprint_install.log
if %errorlevel% equ 0 (
    echo Actualización completada
) else (
    echo Error en actualización - código: %errorlevel%
)
```

### Desinstalación masiva

```cmd
REM Script para desinstalar de todas las estaciones:
REM remove.bat

@echo off
echo Desinstalando AlwaysPrint...
msiexec /x \\servidor\share\AlwaysPrint.msi /qn /L*v C:\Temp\alwaysprint_uninstall.log
if %errorlevel% equ 0 (
    echo Desinstalación completada
) else (
    echo Error en desinstalación - código: %errorlevel%
)
```

### Group Policy (GPO)

1. Copiar `AlwaysPrint.msi` a un share de red
2. Crear GPO de instalación de software:
   - Computer Configuration → Policies → Software Settings → Software Installation
   - New → Package → seleccionar `AlwaysPrint.msi`
   - Deployment method: **Assigned**
3. Las estaciones instalarán/actualizarán automáticamente al reiniciar

## Solución de Problemas

### Error: "Another version of this product is already installed"

**Causa**: Esto NO debería ocurrir con ProductCode fijo.

**Solución**: Verificar que el ProductCode en `Product.wxs` sea realmente fijo:
```xml
<Package ProductCode="C7A4B5D6-A200-4E00-8F00-0BBA00000001" ...>
```

Si no está, el ProductCode se genera automáticamente y cambia en cada build.

### La actualización no reemplaza los archivos

**Causa**: `REINSTALLMODE` no está configurado correctamente.

**Solución**: Verificar en `Product.wxs`:
```xml
<Property Id="REINSTALLMODE" Value="amus" />
<Property Id="REINSTALL" Value="ALL" />
```

### No puedo desinstalar con el MSI

**Causa**: El ProductCode no es fijo o el MSI está corrupto.

**Solución**: 
1. Verificar ProductCode: `wix msi info AlwaysPrint.msi`
2. Si es diferente al esperado, recompilar con ProductCode fijo
3. Desinstalar manualmente: `msiexec /x {C7A4B5D6-A200-4E00-8F00-0BBA00000001} /qn`

## Resumen

✅ **Instalar/Actualizar**: `msiexec /i AlwaysPrint.msi /qn`
✅ **Desinstalar**: `msiexec /x AlwaysPrint.msi /qn`
✅ **Funciona con cualquier MSI** de AlwaysPrint (ProductCode fijo)
✅ **No requiere scripts adicionales** - solo el MSI
✅ **Permite downgrades** - puedes instalar versión más antigua
✅ **Deployment simple** - copiar MSI y ejecutar msiexec
