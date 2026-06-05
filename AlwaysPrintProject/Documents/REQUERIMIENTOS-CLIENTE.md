# Requisitos de instalación — Cliente AlwaysPrint para BBVA

---

## 1. Formato de distribución

- Instalador **MSI** (Windows Installer) generado con WiX Toolset 4.x
- Instalación silenciosa: `msiexec /i AlwaysPrint.msi /qn`
- Soporta actualización automática, upgrade y downgrade
- Firmado digitalmente por Robles.AI / Inversiones On Line SAC

---

## 2. Requisitos de sistema operativo

- **Windows 10 x64** (build 1903 o superior) / Windows 11 x64
- .NET Framework 4.8 (incluido nativamente en Windows 10 1903+)
- No requiere instalación de runtime adicional

---

## 3. Requisitos de hardware

| Recurso | Mínimo | Notas |
|---------|--------|-------|
| RAM | 64 MB disponibles | Uso real: ~30 MB (Service 15 MB + Tray 15 MB) |
| Disco | 20 MB | ~10 MB binarios + ~5 MB logs + ~5 MB temporales |
| CPU | Cualquier x64 | Idle <1%, se activa solo por eventos |

---

## 4. Directorios utilizados

| Ruta | Contenido | Permisos |
|------|-----------|----------|
| `C:\Program Files (x86)\Robles.AI\AlwaysPrint\` | Binarios (EXE, DLL) | SYSTEM + Admins: Full; Users: Read/Execute |
| `C:\ProgramData\AlwaysPrint\config\` | Configuración de acciones | SYSTEM: Full; Users: Read |
| `C:\ProgramData\AlwaysPrint\logs\` | Logs diarios (rotación automática) | SYSTEM: Full; Users: Read |
| `%TEMP%\AlwaysPrint\Updates\` | MSI temporal durante auto-actualización | Usuario actual |

---

## 5. Registro de Windows

- Clave principal: `HKLM\SOFTWARE\Robles.AI\AlwaysPrint`
- Contiene: configuración del servicio, URL cloud, semáforos de estado, versión

---

## 6. Servicio Windows

| Propiedad | Valor |
|-----------|-------|
| Nombre | `AlwaysPrintService` |
| Nombre visible | `AlwaysPrint Service` |
| Tipo de inicio | Automático |
| Cuenta de ejecución | LocalSystem |
| Recuperación ante fallo | Reinicio automático (60s delay) |
| Dependencias | Ninguna |

---

## 7. Comunicación de red (Whitelist firewall/proxy)

| Destino | Puerto | Protocolo | Dirección | Uso |
|---------|--------|-----------|-----------|-----|
| `alwaysprint.apps.iol.pe` | 443 | HTTPS | Salida | API REST, telemetría |
| `alwaysprint.apps.iol.pe` | 443 | WSS | Salida | WebSocket (conexión persistente) |
| `alwaysprint-prod-artifacts.s3.us-west-2.amazonaws.com` | 443 | HTTPS | Salida | Descarga de actualizaciones MSI |

- No requiere puertos de entrada (no escucha conexiones externas)
- Compatible con proxy corporativo (detección automática vía WinHTTP/IE settings)
- Soporta proxy con autenticación NTLM/Kerberos

---

## 8. Exclusiones de antivirus / EDR

### Procesos a excluir

| Proceso | Ruta completa | Justificación |
|---------|---------------|---------------|
| `AlwaysPrintService.exe` | `C:\Program Files (x86)\Robles.AI\AlwaysPrint\AlwaysPrintService.exe` | Servicio Windows que gestiona colas de impresión y ejecuta acciones administrativas (crea procesos hijos, modifica registro, gestiona servicios) |
| `AlwaysPrintTray.exe` | `C:\Program Files (x86)\Robles.AI\AlwaysPrint\AlwaysPrintTray.exe` | Aplicación de bandeja del sistema que mantiene conexión WebSocket persistente y descarga configuración/actualizaciones |

### Carpetas a excluir del escaneo en tiempo real

| Carpeta | Justificación |
|---------|---------------|
| `C:\Program Files (x86)\Robles.AI\AlwaysPrint\` | Binarios de la aplicación |
| `C:\ProgramData\AlwaysPrint\` | Configuración, logs y archivos temporales de acciones |
| `%TEMP%\AlwaysPrint\` | MSI temporales durante auto-actualización |

### Comportamientos que pueden disparar falsos positivos

| Comportamiento | Componente | Motivo legítimo |
|----------------|------------|-----------------|
| Crear procesos como otro usuario (`CreateProcessAsUser`) | Service | Ejecuta acciones de impresión en la sesión del usuario logueado |
| Modificar registro `HKLM` | Service | Configuración de puertos TCP de impresión y semáforos de estado |
| Conexión WebSocket persistente (long-lived HTTPS) | Tray | Canal de comunicación bidireccional con la plataforma cloud |
| Terminar procesos de terceros (`TerminateProcess`) | Service | Limpieza periódica de procesos residuales (Clave*.exe) |
| Iniciar/detener servicios Windows | Service | Gestión de servicios de impresión (Spooler, LPDSVC) durante contingencia |
| Descargar y ejecutar MSI | Tray + Service | Sistema de auto-actualización del propio cliente |

### DLLs incluidas

| Archivo | Ruta | Descripción |
|---------|------|-------------|
| `Newtonsoft.Json.dll` | `C:\Program Files (x86)\Robles.AI\AlwaysPrint\Newtonsoft.Json.dll` | Librería JSON (NuGet oficial, ampliamente utilizada) |

---

## 9. Named Pipe (comunicación interna)

- Nombre: `\\.\pipe\AlwaysPrintService`
- Solo comunicación local entre Service y Tray (no expuesto a red)

---

## 10. Coexistencia con software existente

- Compatible con **Lexmark CPM Client** (coexisten sin conflicto)
- No modifica el Spooler ni LPDSVC excepto durante activación/desactivación de contingencia
- No interfiere con otros sistemas de impresión instalados

---

## 11. Requisitos de instalación

- Privilegios de **Administrador local** para instalar (registrar servicio + escribir HKLM)
- No requiere reinicio del equipo
- Instalación típica: <30 segundos
- Desinstalación: `msiexec /x {ProductCode} /qn` (limpia servicio, binarios y registro; preserva logs)

---

© 2026 Inversiones On Line SAC — Producto de la familia de automatización Robles.AI
