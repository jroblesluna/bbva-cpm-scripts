# Guía de Instalación y Actualización - AlwaysPrint

## Comandos Correctos

### ✅ Instalar o Actualizar

```cmd
msiexec /i AlwaysPrint.msi /qn
```

**Funciona para**:
- Primera instalación
- Actualizar de cualquier versión anterior
- Reinstalar la misma versión (reparar)
- **Downgrade** a versión más antigua

### ✅ Desinstalar

```cmd
msiexec /x AlwaysPrint.msi /qn
```

**Funciona con cualquier MSI** de AlwaysPrint, no importa la versión.

### Con Logs

```cmd
REM Instalar con log
msiexec /i AlwaysPrint.msi /qn /L*v install.log

REM Desinstalar con log
msiexec /x AlwaysPrint.msi /qn /L*v uninstall.log
```

## ✅ Por Qué Funciona

**ProductCode Fijo**: `C7A4B5D6-A200-4E00-8F00-0BBA00000001`

Todos los MSIs de AlwaysPrint comparten el mismo ProductCode, por lo que:
- Windows Installer los reconoce como el mismo producto
- Cualquier MSI puede instalar, actualizar o desinstalar
- No importa qué versión esté instalada o qué versión tenga el MSI

**Versión**: Cambia en cada build (`1.26.426.1000`, `1.26.426.1100`, etc.)
- Solo se usa para mostrar en Panel de Control
- No afecta la instalación/desinstalación

## ❌ NO HAY Comandos Incorrectos

Con ProductCode fijo, **todos los comandos estándar de msiexec funcionan**:

```cmd
REM ✅ Instalar
msiexec /i AlwaysPrint.msi /qn

REM ✅ Desinstalar
msiexec /x AlwaysPrint.msi /qn

REM ✅ Reparar
msiexec /f AlwaysPrint.msi /qn

REM ✅ Con interfaz gráfica
msiexec /i AlwaysPrint.msi
```

Todos funcionan porque el ProductCode es fijo en todos los MSIs.

## Flujo de Trabajo Típico

### Desarrollo: Actualizar a nueva versión

```cmd
REM 1. Construir nueva versión
.\build.ps1

REM 2. Instalar (desinstala automáticamente la anterior)
install.bat

REM 3. Verificar que el servicio está corriendo
sc query AlwaysPrintService
```

### Producción: Desplegar actualización

```cmd
REM En cada estación de trabajo:
REM 1. Copiar el nuevo MSI y install.bat
REM 2. Ejecutar instalación (actualiza automáticamente)
install.bat
```

### Limpiar instalación completamente

```cmd
REM 1. Desinstalar
install.bat /uninstall

REM 2. Verificar que el servicio fue eliminado
sc query AlwaysPrintService

REM 3. Limpiar datos residuales (opcional)
rmdir /s /q "C:\ProgramData\AlwaysPrint"
reg delete "HKLM\SOFTWARE\Robles.AI\AlwaysPrint" /f

REM 4. Instalar versión limpia
install.bat
```

## Verificación Post-Instalación

```powershell
# Verificar servicio
Get-Service AlwaysPrintService | Format-List Name, Status, StartType

# Verificar archivos instalados
Get-ChildItem "C:\Program Files (x86)\Robles.AI\AlwaysPrint"

# Verificar configuración en registro
Get-ItemProperty "HKLM:\SOFTWARE\Robles.AI\AlwaysPrint"

# Verificar logs
Get-ChildItem "C:\ProgramData\AlwaysPrint\logs"
```

## Solución de Problemas

### "Este producto no está instalado" al desinstalar

**Causa**: Estás intentando desinstalar con un MSI que tiene un ProductCode diferente al instalado.

**Solución**: Usa `.\uninstall.ps1` en lugar de `msiexec /x AlwaysPrint.msi`

### La actualización no desinstala la versión anterior

**Causa**: La versión nueva no es mayor que la instalada, o hay un problema con el UpgradeCode.

**Verificación**:
```powershell
# Ver versión instalada
$product = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*" | 
           Where-Object { $_.DisplayName -eq "AlwaysPrint" }
Write-Host "Versión instalada: $($product.DisplayVersion)"

# Ver versión del nuevo MSI (requiere WiX)
wix msi info AlwaysPrint.msi
```

**Solución**: Asegúrate de que la nueva versión es mayor (ej: `1.26.426.1225` > `1.26.426.1224`)

### El servicio no inicia después de actualizar

**Verificación**:
```powershell
# Ver estado del servicio
Get-Service AlwaysPrintService | Format-List *

# Ver logs del servicio
Get-Content "C:\ProgramData\AlwaysPrint\logs\AlwaysPrint_$(Get-Date -Format 'yyyyMMdd').log" -Tail 50

# Ver Event Log de Windows
Get-EventLog -LogName Application -Source AlwaysPrint -Newest 10
```

**Solución común**: Reiniciar el servicio manualmente
```powershell
Restart-Service AlwaysPrintService
```

## Notas Técnicas

### Sistema de Versionado

- **Formato**: `1.YY.MMDD.HHMM`
- **Ejemplo**: `1.26.426.1225` = 26 de abril de 2026, 12:25
- **Resolución**: 1 minuto (suficiente para builds de producción)

### Identificadores WiX

- **ProductCode**: Generado automáticamente en cada build (diferente para cada versión)
- **UpgradeCode**: `C7A4B5D6-A100-4E00-8F00-0BBA00000001` (FIJO - nunca cambiar)
- **ComponentGuid**: Fijos en `Product.wxs`

### MajorUpgrade y Comportamiento de Windows Installer

Con `MajorUpgrade`, Windows Installer:
- Usa el **UpgradeCode** (fijo) para detectar versiones anteriores
- Compara las **versiones** para determinar si es upgrade o downgrade
- Desinstala automáticamente la versión anterior antes de instalar la nueva
- Cada build tiene un **ProductCode** único (generado por WiX)

**Ejemplo de flujo**:
1. Instalas versión `1.26.426.1000` → Windows registra ProductCode-A + versión
2. Instalas versión `1.26.426.1100` → Windows detecta mismo UpgradeCode, versión mayor → UPGRADE
   - Desinstala ProductCode-A
   - Instala ProductCode-B (nuevo)
3. Intentas instalar `1.26.426.900` → Windows detecta mismo UpgradeCode, versión menor → DOWNGRADE (bloqueado)

**Para desinstalar**: Usa `.\uninstall.ps1` que busca el ProductCode actual en el registro.
