# LpdServiceMonitor

Servicio de Windows (C# .NET 8 Worker Service) que **monitoriza el servicio LPDSVC** y lo levanta automáticamente si detecta que está detenido.  
Incluye ventana de reintentos, “cooldown” tras ráfaga de fallos, *flag* de mantenimiento y registro en **Event Log**.

Windows service that **watches LPDSVC** and restarts it when stopped.  
It applies retry windows, burst cooldown, a maintenance flag, and logs to **Event Log**.

---

## 📁 Estructura (todo en la **raíz**)

~~~text
.
├─ appsettings.json
├─ build.ps1
├─ LpdServiceMonitor.csproj
├─ Product.wxs
├─ Program.cs
├─ app.ico                 # (opcional) Icono usado por ARP en el MSI
├─ dist/                   # (salida de publish; se crea al construir)
└─ LpdServiceMonitor.msi   # (salida de WiX; se crea al construir)
~~~

---

## ⚙️ Configuración

Contenido de `appsettings.json`:

~~~json
{
  "Monitor": {
    "TargetServiceName": "LPDSVC",
    "CheckIntervalMs": 5000,
    "StartTimeoutSeconds": 30,
    "MaxRestartsInWindow": 5,
    "RestartWindowSeconds": 300,
    "CooldownAfterBurstSeconds": 600,
    "MaintenanceFlagPath": "C:\\windows\\temp\\LPDSVCMONITOR.MAINTENANCE.flag"
  }
}
~~~

- **TargetServiceName**: nombre interno del servicio a vigilar (LPDSVC).  
- **MaintenanceFlagPath**: si el archivo existe, el monitor **no** intentará reiniciar.  
- Variables de entorno con prefijo `SM_` pueden *overridear* (ej.: `SM_Monitor__TargetServiceName=XYZ`).

---

## 🧰 Requisitos

- Windows 10/11 o Windows Server compatible con .NET 8.
- [.NET SDK 8](https://dotnet.microsoft.com/download).
- [WiX Toolset 6 (CLI)](https://wixtoolset.org/releases/) instalado como **dotnet tool** (el script lo instala/actualiza).
- PATH debe incluir `%USERPROFILE%\.dotnet\tools` (para `wix`).

---

## 🚀 Construcción y empaquetado (todo en **un comando**)

Ejecuta el script desde PowerShell **como administrador**:

~~~powershell
.\build.ps1
~~~

Qué hace el script:

1) Limpia artefactos (`bin`, `obj`, `dist`, `.wix`, etc.).  
2) Instala/actualiza `wix` (dotnet tool) y registra la extensión `WixToolset.Util.wixext`.  
3) Publica el ejecutable **self-contained**, `win-x64`, **single-file** a `.\dist`.  
4) Compila el **MSI** con WiX usando `Product.wxs` → `.\LpdServiceMonitor.msi`.

Al finalizar verás: `Listo. Salida: .\LpdServiceMonitor.msi`.

---

## 🖥️ Instalación / Desinstalación

Instalar de forma silenciosa con log:

~~~powershell
msiexec /i .\LpdServiceMonitor.msi /qn /L*v install.log
~~~

Desinstalar:

~~~powershell
msiexec /x .\LpdServiceMonitor.msi /qn /L*v uninstall.log
~~~

> El MSI instala en `C:\Program Files\RoblesAI\LPD Service Monitor\` y crea el servicio  
> **LpdServiceMonitor** (inicia automático, cuenta `LocalSystem`).

Comprobar estado:

~~~powershell
Get-Service LpdServiceMonitor
Get-Service LPDSVC
~~~

---

## 🧾 Archivos clave (resumen)

- **Program.cs**: host de Worker Service, EventLog, carga de `appsettings.json`, lógica de monitor.  
- **LpdServiceMonitor.csproj**: .NET 8, `UseWindowsService`, copiado de `appsettings.json` en publish.  
- **Product.wxs**: definición WiX (1 sólo componente), instala servicio `LpdServiceMonitor`, política de recuperación, ARP metadata, icono `app.ico`.  
- **build.ps1**: orquesta publish y build del MSI (con extensiones WiX registradas de forma local).  

---

## 🪵 Logs

- **Event Viewer → Windows Logs → Application**  
  Source: `LpdServiceMonitor`.  
- Si ejecutas desde consola (UserInteractive), también emite a stdout.

---

## 🧰 Overrides rápidos

- Pausar reinicios:
  - Crear archivo: `C:\windows\temp\LPDSVCMONITOR.MAINTENANCE.flag`
- Cambiar el servicio objetivo sin editar JSON:
  - `setx SM_Monitor__TargetServiceName "OtroServicio"`

> Reinicia el servicio **LpdServiceMonitor** tras cambiar variables/archivo para aplicar.

---

## ❗ Solución de problemas

- **El MSI falla con 1603 / “Service does not exist” en ServiceConfig**  
  Asegúrate de que `Product.wxs` tiene **un único** `Component` con:
  - `<File ... KeyPath="yes" />` (el EXE publicado en `.\dist`)  
  - `<ServiceInstall/>` y `<ServiceControl/>` dentro **del mismo componente**  
  - `<util:ServiceConfig ServiceName="LpdServiceMonitor" .../>` con el **mismo Name**
- **No aparece `wix` en PATH**  
  Abre una nueva consola o añade `%USERPROFILE%\.dotnet\tools` al PATH del usuario.
- **El servicio objetivo (LPDSVC) no existe**  
  El monitor se detendrá por seguridad. Instala/activa el rol de **Servicio LPD**.

---

## 📜 Licencia / Contacto

(c) 2025 **Robles.AI** — antonio@robles.ai  
Uso interno / demostración. Ajusta a tus políticas antes de producción.