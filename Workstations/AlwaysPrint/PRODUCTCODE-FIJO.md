# ProductCode Fijo - Explicación

## ¿Qué es el ProductCode?

El **ProductCode** es un GUID único que Windows Installer usa para identificar un producto instalado. Es como el "DNI" del software en el sistema.

## Cambio Implementado

### ❌ ANTES (ProductCode dinámico)

Cada build generaba un ProductCode diferente:

```
Build 1 → Version: 1.26.426.1000  ProductCode: {GUID-A}
Build 2 → Version: 1.26.426.1100  ProductCode: {GUID-B}
Build 3 → Version: 1.26.426.1200  ProductCode: {GUID-C}
```

**Problema**: Windows Installer veía cada MSI como un producto diferente.

**Consecuencias**:
- ❌ No podías usar `msiexec /x AlwaysPrint.msi` para desinstalar
- ❌ Tenías que buscar el ProductCode en el registro
- ❌ Cada MSI solo podía desinstalar su propia versión

### ✅ AHORA (ProductCode fijo)

Todos los builds comparten el mismo ProductCode:

```
Build 1 → Version: 1.26.426.1000  ProductCode: {C7A4B5D6-A200-4E00-8F00-0BBA00000001}
Build 2 → Version: 1.26.426.1100  ProductCode: {C7A4B5D6-A200-4E00-8F00-0BBA00000001}
Build 3 → Version: 1.26.426.1200  ProductCode: {C7A4B5D6-A200-4E00-8F00-0BBA00000001}
```

**Solución**: Windows Installer reconoce todos los MSIs como el mismo producto.

**Beneficios**:
- ✅ Puedes usar `msiexec /x AlwaysPrint.msi` con cualquier MSI
- ✅ Cualquier MSI puede actualizar cualquier versión anterior
- ✅ Cualquier MSI puede desinstalar cualquier versión instalada
- ✅ No necesitas buscar el ProductCode en el registro

## ¿Qué sigue cambiando?

### La VERSIÓN sigue creciendo

Cada build tiene una versión única basada en fecha/hora:

```
Build hoy 12:00    → Version: 1.26.426.1200
Build hoy 12:01    → Version: 1.26.426.1201
Build mañana 09:30 → Version: 1.26.427.930
```

Windows Installer usa la versión para:
- Detectar si es un upgrade (versión mayor)
- Detectar si es un downgrade (versión menor)
- Mostrar la versión en Panel de Control

## Ejemplos Prácticos

### Escenario 1: Actualizar versión

```powershell
# Tienes instalada la versión 1.26.426.1000
# Construyes nueva versión 1.26.426.1100

.\build.ps1
msiexec /i AlwaysPrint.msi /qn

# Windows Installer:
# 1. Lee ProductCode del MSI: C7A4B5D6-A200-4E00-8F00-0BBA00000001
# 2. Busca ese ProductCode en el registro → LO ENCUENTRA
# 3. Compara versiones: 1.26.426.1100 > 1.26.426.1000 → UPGRADE
# 4. Desinstala versión 1000 e instala versión 1100
```

### Escenario 2: Desinstalar con cualquier MSI

```powershell
# Tienes instalada la versión 1.26.426.1000
# Tienes un MSI de la versión 1.26.426.1200 (no instalada)

msiexec /x AlwaysPrint.msi /qn

# Windows Installer:
# 1. Lee ProductCode del MSI: C7A4B5D6-A200-4E00-8F00-0BBA00000001
# 2. Busca ese ProductCode en el registro → LO ENCUENTRA (versión 1000)
# 3. Desinstala la versión 1000
# 4. No importa que el MSI sea de la versión 1200
```

### Escenario 3: Reinstalar misma versión

```powershell
# Tienes instalada la versión 1.26.426.1000
# Construyes otra vez (misma versión porque es el mismo minuto)

.\build.ps1
msiexec /i AlwaysPrint.msi /qn

# Windows Installer:
# 1. Lee ProductCode: C7A4B5D6-A200-4E00-8F00-0BBA00000001
# 2. Busca en registro → LO ENCUENTRA
# 3. Compara versiones: 1.26.426.1000 = 1.26.426.1000 → REINSTALL
# 4. Reinstala los archivos (útil para reparar instalación corrupta)
```

### Escenario 4: Intentar downgrade

```powershell
# Tienes instalada la versión 1.26.426.1200
# Intentas instalar versión 1.26.426.1000 (más antigua)

msiexec /i AlwaysPrint_old.msi /qn

# Windows Installer:
# 1. Lee ProductCode: C7A4B5D6-A200-4E00-8F00-0BBA00000001
# 2. Busca en registro → LO ENCUENTRA
# 3. Compara versiones: 1.26.426.1000 < 1.26.426.1200 → DOWNGRADE
# 4. RECHAZA la instalación (por seguridad)
```

## Identificadores en Product.wxs

```xml
<Package Name="AlwaysPrint"
         Version="$(var.ProductVersion)"           <!-- CAMBIA: 1.26.426.1000, 1.26.426.1100, etc. -->
         ProductCode="C7A4B5D6-A200-4E00-8F00-0BBA00000001"  <!-- FIJO -->
         UpgradeCode="C7A4B5D6-A100-4E00-8F00-0BBA00000001"  <!-- FIJO -->
         ...>
```

### Reglas de Oro

1. **ProductCode**: FIJO - nunca cambiar (permite compatibilidad entre versiones)
2. **UpgradeCode**: FIJO - nunca cambiar (identifica la familia de productos)
3. **Version**: CAMBIA - crece con cada build (identifica la versión específica)
4. **ComponentGuid**: FIJO - solo cambiar si cambias el contenido del componente

## Verificación

### Ver ProductCode de un MSI

```powershell
# Opción 1: Con WiX
wix msi info AlwaysPrint.msi

# Opción 2: Con PowerShell (requiere Windows Installer COM)
$installer = New-Object -ComObject WindowsInstaller.Installer
$database = $installer.GetType().InvokeMember("OpenDatabase", "InvokeMethod", $null, $installer, @("AlwaysPrint.msi", 0))
$view = $database.GetType().InvokeMember("OpenView", "InvokeMethod", $null, $database, "SELECT Value FROM Property WHERE Property='ProductCode'")
$view.GetType().InvokeMember("Execute", "InvokeMethod", $null, $view, $null)
$record = $view.GetType().InvokeMember("Fetch", "InvokeMethod", $null, $view, $null)
$productCode = $record.GetType().InvokeMember("StringData", "GetProperty", $null, $record, 1)
Write-Host "ProductCode: $productCode"
```

### Ver ProductCode instalado

```powershell
$product = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*" | 
           Where-Object { $_.DisplayName -eq "AlwaysPrint" }
Write-Host "ProductCode instalado: $($product.PSChildName)"
Write-Host "Versión instalada: $($product.DisplayVersion)"
```

## Conclusión

Con ProductCode fijo:
- ✅ Todos los MSIs son compatibles entre sí
- ✅ Cualquier MSI puede actualizar/desinstalar cualquier versión
- ✅ Simplifica el proceso de deployment
- ✅ La versión sigue siendo única y creciente
- ✅ Windows Installer maneja automáticamente los upgrades
