# Changelog - AlwaysPrint

## Sistema de Versionado

### Formato Actual: `1.YY.MMDD.HHMM`

**Ejemplo**: `1.26.426.1228` = 26 de abril de 2026, 12:28

**Componentes**:
- **Major**: 1 (fijo)
- **Minor**: YY (últimos 2 dígitos del año) - ej: 26 = 2026
- **Build**: MMDD (mes y día) - ej: 426 = 04/26 (abril 26)
- **Revision**: HHMM (hora y minuto en formato 24h) - ej: 1228 = 12:28

**Nota sobre ceros iniciales**: 
Los componentes se convierten a enteros, por lo que los ceros iniciales se eliminan:
- `0426` → `426` (abril 26)
- `0911` → `911` (09:11 AM)

**Formato de hora**: 24 horas (militar)
- 09:11 AM → `911`
- 21:11 PM → `2111`

**Resolución**: Versión única por minuto (suficiente para builds de desarrollo)

**Límites de Windows Installer**:
Este formato cumple con todos los límites de MSI:
- Major < 256 ✓ (1)
- Minor < 256 ✓ (26)
- Build < 65536 ✓ (426)
- Revision < 65536 ✓ (1228)

### Identificadores Fijos

**UpgradeCode**: `C7A4B5D6-A100-4E00-8F00-0BBA00000001` (FIJO)
- Identifica la familia de productos AlwaysPrint
- Permite que MajorUpgrade detecte versiones anteriores
- Nunca debe cambiar

**ProductCode**: Generado automáticamente en cada build
- Cada MSI tiene un ProductCode único
- Windows Installer usa UpgradeCode (no ProductCode) para detectar upgrades
- Para desinstalar, usa `.\uninstall.ps1` que busca el ProductCode en el registro

**ComponentGuid**: Fijos en `Product.wxs`
- `cmpService`: `C7A4B5D6-B200-4E00-8F00-0BBA00000002`
- `cmpTray`: `C7A4B5D6-C300-4E00-8F00-0BBA00000003`

**Ventajas**:
- ✓ Versión única por minuto
- ✓ Fácil de leer y entender
- ✓ Siempre creciente
- ✓ Todos los componentes <= 65535 (límite de WiX)
- ✓ **MajorUpgrade: cualquier MSI puede actualizar cualquier versión anterior**
- ✓ UpgradeCode fijo permite detección automática de versiones anteriores

**Configuración Windows Installer**:
- `ProductCode`: generado automáticamente en cada build (único por versión)
- `UpgradeCode` fijo: identifica la familia de productos
- `MajorUpgrade`: desinstala automáticamente versiones anteriores
- `AllowSameVersionUpgrades="yes"`: permite reinstalar la misma versión
- ✓ Siempre creciente
- ✓ Todos los componentes <= 65535 (límite de WiX)
- ✓ Permite upgrades automáticos con `msiexec /i AlwaysPrint.msi /qn`

**Configuración WiX**:
- `MajorUpgrade` con `Schedule="afterInstallInitialize"`
- `AllowSameVersionUpgrades="yes"` para permitir reinstalación de la misma versión
- `UpgradeCode` fijo: `C7A4B5D6-A100-4E00-8F00-0BBA00000001`
- `ProductCode` regenerado automáticamente en cada build

## Cambios Recientes

### 2026-04-26

#### ProductCode Fijo (CAMBIO IMPORTANTE)
- **Implementado**: ProductCode fijo `C7A4B5D6-A200-4E00-8F00-0BBA00000001`
- **Beneficio**: Cualquier MSI puede actualizar o desinstalar cualquier versión anterior
- **Ahora funciona**: `msiexec /x AlwaysPrint.msi` para desinstalar con cualquier MSI
- **Versión sigue creciendo**: Cada build tiene versión única basada en fecha/hora
- **Eliminado**: `MajorUpgrade` (ya no necesario con ProductCode fijo)

#### Sistema de Logging Consolidado
- **Eliminado**: Logging duplicado a `service.log` y múltiples archivos
- **Implementado**: Un solo archivo de log por día en `C:\ProgramData\AlwaysPrint\logs\AlwaysPrint_yyyyMMdd.log`
- **Formato**: `[timestamp] [SVC|APP] Event ID: mensaje`
  - `[SVC]` = AlwaysPrintService.exe
  - `[APP]` = AlwaysPrintTray.exe
- **Logger**: `AlwaysPrintLogger` (antes `EventLogWriter`) en `AlwaysPrint.Shared.dll`

#### Archivos Modificados
- `AlwaysPrint.Shared/Logging/AlwaysPrintLogger.cs` - Logger consolidado
- `AlwaysPrintService/AlwaysPrintWindowsService.cs` - Eliminados logs directos
- `AlwaysPrintService/Pipe/PipeServer.cs` - Eliminados logs directos
- `AlwaysPrintService/UserSession/SessionMonitor.cs` - Eliminados logs directos
- `AlwaysPrintService/UserSession/InteractiveProcessLauncher.cs` - Eliminados logs directos
- `AlwaysPrintTray/TrayApplicationContext.cs` - Eliminados logs a `%TEMP%\AlwaysPrintTray.log`
- `AlwaysPrintTray/Pipe/PipeClient.cs` - Eliminados logs directos

#### Sistema de Versionado
- **Implementado**: Versionado basado en fecha/hora `1.yyyy.MMdd.HHmmss`
- **Script de prueba**: `test-versioning.ps1` para verificar unicidad y orden creciente
- **Build script**: `build.ps1` actualizado con nuevo formato

## Comandos Útiles

### Instalación/Actualización

```cmd
REM Opción 1: Script batch (RECOMENDADO - más simple)
install.bat

REM Opción 2: msiexec directo
msiexec /i AlwaysPrint.msi /qn
```

### Desinstalación

```cmd
REM Opción 1: Script batch (RECOMENDADO)
install.bat /uninstall

REM Opción 2: Script PowerShell
.\uninstall.ps1

REM Opción 3: Panel de Control
REM Configuración > Aplicaciones > AlwaysPrint > Desinstalar
```

**IMPORTANTE**: El script `install.bat` es la forma más simple - detecta automáticamente si instalar o desinstalar.

### Build y Testing

```powershell
# Build completo (limpieza + compilación + MSI)
.\build.ps1

# Verificar sistema de versionado
.\test-versioning.ps1

# Test completo de upgrade automático (requiere permisos de administrador)
.\test-upgrade.ps1
```

## Notas Técnicas

### Windows Installer
- El `ProductCode` cambia en cada build (generado por WiX)
- El `UpgradeCode` es fijo y permite detectar versiones anteriores
- `MajorUpgrade` desinstala automáticamente versiones anteriores cuando la nueva versión es mayor
- Con `AllowSameVersionUpgrades="yes"`, también permite reinstalar la misma versión

### Logging
- Los logs rotan automáticamente por día
- No hay límite de tamaño por archivo (considerar implementar rotación por tamaño en el futuro)
- Los mensajes se truncan a 30,000 caracteres para evitar logs excesivamente grandes
- Los errores de logging se ignoran silenciosamente para no afectar la operación del servicio
