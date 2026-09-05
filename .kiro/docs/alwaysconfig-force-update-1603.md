# Diagnóstico: Force Update MSI falla con error 1603

**Fecha de investigación**: 2026-09-05  
**Versión afectada**: AlwaysPrint `1.26.813.1025` → `1.26.827.1352`  
**Workstation afectada confirmada**: W1015101P01 (IP `118.64.220.41`, BBVA PROD)  
**Alwaysconfig investigado**: CPM_Compliant v14.2  
**Alwaysconfig con fix pendiente de prueba en entorno real**: CPM_Compliant v14.3

---

## Síntoma

- El comando `check_update` remoto y el OnDemand `Forzar Actualización MSI` fallan.
- El log muestra `msiexec finalizado. ExitCode=1603` repetidamente.
- El servicio levanta correctamente después (con la versión vieja), lo que enmascara el fallo.
- Con alwaysconfig v14.2: el dashboard reporta `Success=True` aunque msiexec falló (bug de exit code).
- La versión instalada **no cambia** a pesar de múltiples intentos.

### Log característico (v14.2, fallo enmascarado)

```
[UPD] Event 1020: Ejecutando msiexec /i (silencioso)...
[UPD] Event 1020: msiexec finalizado. ExitCode=1603
[UPD] Event 1091: ERROR - msiexec fallo con codigo 1603.
[UPD] Event 1020: Iniciando servicio...
[UPD] Event 1020: Verificacion 1/10: servicio ACTIVO.
[UPD] Event 1020: Forzar Actualizacion MSI finalizada.
← ActionEngine reporta Success=True aunque falló
```

### Log del msiexec verbose (`AlwaysPrint_update.msi.msiexec.log`)

Línea clave:
```
MSI (s): Warning: Local cached package 'C:\WINDOWS\Installer\4274bf8.msi' is missing.
...
SOURCEMGMT: Source is invalid due to invalid package code
...
Error 1714. The older version of AlwaysPrint cannot be removed. System Error 1612.
Action ended: RemoveExistingProducts. Return value 3.
```

---

## Causa raíz

**Cache de Windows Installer eliminado o corrupto.**

Cuando se instala un MSI, Windows Installer guarda una copia del instalador en `C:\WINDOWS\Installer\` (ej: `4274bf8.msi`). El registro apunta a esa copia en:

```
HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\UserData\S-1-5-18\Products\{PACKED_GUID}\InstallProperties → LocalPackage
```

Al intentar instalar una versión nueva con diferente ProductCode, `msiexec /i` ejecuta internamente `RemoveExistingProducts` que necesita ese archivo cacheado para desinstalar la versión anterior. Si el archivo no existe → error 1603.

### Rutas afectadas (3 paths del registry que bloquean la instalación)

```
P1: HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{GUID}
P2: HKLM:\SOFTWARE\Classes\Installer\Products\{PACKED_GUID}
P3: HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\UserData\S-1-5-18\Products\{PACKED_GUID}
```

Donde `{GUID}` es el ProductCode de la versión instalada y `{PACKED_GUID}` es su representación interna de Windows Installer (bytes invertidos por segmento).

### Por qué ocurrió en esta workstation específica

- Instalada el **2026-08-13** con versión `1.26.813.1025` (ProductCode `{97BBA85E-3C5D-4F56-ADEF-E45ED997C491}`)
- En algún momento el archivo `C:\WINDOWS\Installer\4274bf8.msi` fue eliminado (limpieza de disco, política BBVA, o manual)
- Las ~6,000 workstations restantes de BBVA con versión `1.26.813.1124` tienen cache intacto → se actualizan sin problema

---

## Solución manual aplicada en W1015101P01

Se ejecutaron los siguientes comandos remotos desde el dashboard para limpiar el registry y luego se ejecutó el Force Update:

### Paso 1: Verificar los 3 paths del registry
```powershell
powershell -NoProfile -Command "$guid='{97BBA85E-3C5D-4F56-ADEF-E45ED997C491}';$g=$guid-replace'[{}]','';$parts=$g-split'-';$packed=($parts[0][-1..-8]-join'')+($parts[1][-1..-4]-join'')+($parts[2][-1..-4]-join'')+($parts[3]-replace'(.)(.)','$2$1')+($parts[4]-replace'(.)(.)','$2$1');$p1='HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\'+$guid;$p2='HKLM:\SOFTWARE\Classes\Installer\Products\'+$packed;$p3='HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\UserData\S-1-5-18\Products\'+$packed;Write-Output ('P1='+$(if(Test-Path $p1){'EXISTS'}else{'MISSING'}));Write-Output ('P2='+$(if(Test-Path $p2){'EXISTS'}else{'MISSING'}));Write-Output ('P3='+$(if(Test-Path $p3){'EXISTS'}else{'MISSING'}))"
```

### Paso 2: Limpiar los 3 paths
```powershell
powershell -NoProfile -Command "$guid='{97BBA85E-3C5D-4F56-ADEF-E45ED997C491}';$g=$guid-replace'[{}]','';$parts=$g-split'-';$packed=($parts[0][-1..-8]-join'')+($parts[1][-1..-4]-join'')+($parts[2][-1..-4]-join'')+($parts[3]-replace'(.)(.)','$2$1')+($parts[4]-replace'(.)(.)','$2$1');$p1='HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\'+$guid;$p2='HKLM:\SOFTWARE\Classes\Installer\Products\'+$packed;$p3='HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\UserData\S-1-5-18\Products\'+$packed;Remove-Item $p1 -Recurse -Force -ErrorAction SilentlyContinue;Remove-Item $p2 -Recurse -Force -ErrorAction SilentlyContinue;Remove-Item $p3 -Recurse -Force -ErrorAction SilentlyContinue;Write-Output ('P1='+$(if(Test-Path $p1){'AUN_EXISTS'}else{'ELIMINADO'}));Write-Output ('P2='+$(if(Test-Path $p2){'AUN_EXISTS'}else{'ELIMINADO'}));Write-Output ('P3='+$(if(Test-Path $p3){'AUN_EXISTS'}else{'ELIMINADO'}))"
```

### Paso 3: Ejecutar Force Update desde el dashboard
→ msiexec ExitCode=0, versión `1.26.827.1352` instalada exitosamente.

> **NOTA**: El ProductCode `{97BBA85E-...}` y el packed GUID `E58ABB79D5C365F4DAFE4EE59D794C19` son específicos de la versión `1.26.813.1025`. Si en el futuro otra workstation tiene una versión diferente instalada, el GUID será distinto. Siempre calcular dinámicamente (ver los comandos de diagnóstico más abajo).

---

## Alwaysconfig v14.3 — Fix automático (pendiente de prueba en entorno real)

Se desarrolló CPM_Compliant v14.3 que automatiza el proceso anterior dentro del trigger `OnDemand → Forzar Actualización MSI`. El fix **no se ha podido probar en entorno real** con proxy corporativo BBVA.

### Cambios vs v14.2

**1. Retry automático ante 1603**: Si el primer `msiexec /i` devuelve 1603:
   - Genera dinámicamente `ap_clean_msi.ps1` en `C:\ProgramData\AlwaysPrint\config\`
   - El script calcula el GUID y packed GUID del producto instalado desde el registry (sin hardcodear)
   - Elimina los 3 paths del registry de Windows Installer
   - Reintenta `msiexec /i` (segundo intento, log separado en `.retry.log`)
   - El 99.9% de máquinas con cache intacto nunca activa este bloque

**2. Exit code correcto**: El script `.cmd` ahora termina con `exit /b %INSTALL_EXIT%` en lugar del `exit /b` implícito (siempre 0). El ActionEngine recibe `Success=False` cuando falla.

**3. Verificación de versión post-update**: Loga `VersionInfo.FileVersion` del `AlwaysPrintTray.exe` después de confirmar que el servicio está activo.

### Estado del v14.3

- ✅ Código implementado en `AlwaysPrintProject/AlwaysConfig/CPM_Compliant.alwaysconfig`
- ✅ JSON validado
- ✅ Lógica verificada en entorno de laboratorio (DESKTOP-QTJGPTH, sin proxy corporativo)
- ❌ **NO probado con proxy corporativo BBVA** (ZScaler/BlueCoat)
- ❌ **NO probado en escenario completo 1603** en laboratorio (la descarga del MSI falla con 403 en entorno sin proxy porque el endpoint `/updates/pkg` requiere `auto_update_enabled=True` en la organización)

### Por qué no se pudo probar completamente en laboratorio

El Force Update descarga el MSI via `/api/v1/updates/pkg/{org_id}` que devuelve **403 Forbidden** si `auto_update_enabled = False` para la organización. En entorno de laboratorio (red doméstica, sin proxy), al activar `auto_update_enabled`, el Tray recibe un push `check_update` con URL presigned y se actualiza por el flujo nativo (zero-query) antes de que se pueda probar el Force Update. El escenario requiere:

1. Proxy corporativo activo (que bloquea la URL presigned)
2. Workstation con cache de Windows Installer roto
3. `auto_update_enabled = True` en la organización

Las workstations de BBVA en producción tienen exactamente ese entorno.

---

## Diagnóstico dinámico (para futura referencia)

Para cualquier workstation con error 1603, ejecutar estos comandos en orden:

### Identificar versión y ProductCode instalado
```powershell
powershell -NoProfile -Command "$p=Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' | Where-Object{$_.DisplayName -eq 'AlwaysPrint'}; Write-Output ('Version: ' + $p.DisplayVersion); Write-Output ('ProductCode: ' + $p.PSChildName)"
```

### Calcular packed GUID y verificar cache
```powershell
powershell -NoProfile -Command "$p=Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' | Where-Object{$_.DisplayName -eq 'AlwaysPrint'};$g=$p.PSChildName-replace'[{}]','';$t=$g-split'-';$pk=($t[0][-1..-8]-join'')+($t[1][-1..-4]-join'')+($t[2][-1..-4]-join'')+($t[3]-replace'(.)(.)','`$2`$1')+($t[4]-replace'(.)(.)','`$2`$1');$lp=(Get-ItemProperty ('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\UserData\S-1-5-18\Products\'+$pk+'\InstallProperties') -EA SilentlyContinue).LocalPackage;Write-Output ('PackedGUID: '+$pk);Write-Output ('LocalPackage: '+$lp);Write-Output ('Cache existe: '+(Test-Path $lp))"
```

Si `Cache existe: False` → confirma el problema. Aplicar limpieza de los 3 paths.

### Obtener log detallado de msiexec
```
type "C:\ProgramData\AlwaysPrint\Updates\AlwaysPrint_update.msi.msiexec.log"
```
Buscar: `Error 1714`, `missing`, `SOURCEMGMT: Source is invalid`.

---

## Notas adicionales

- **SetTcpPort falla en cada OnTrayLaunched** en estas workstaciones: `ManagementException: Generic failure` al intentar enumerar puertos TCP via WMI. El Spooler recién reiniciado no tiene el WMI provider registrado aún. Es cosmético — la impresión funciona porque el puerto ya existe. No requiere corrección urgente.
- **ConfigurationSync timeout** en W1015101P01 en algunos arranques: `timeout de 30 segundos al descargar configuración`. Posiblemente relacionado con proxy ZScaler en horarios de carga. El Tray continúa con el hash computado local (hash mismatch no bloquea la operación).
- El **flujo zero-query (push-based)** del Tray es más robusto que el Force Update del alwaysconfig para actualizaciones normales. El Force Update es necesario solo cuando el cache está roto o la distribución push no llega.
