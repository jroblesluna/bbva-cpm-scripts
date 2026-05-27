---
título: Manual de Usuario — AlwaysPrint Client
versión: 1.0.0
fecha: Mayo 2026
producto: AlwaysPrint Client (Windows)
empresa: Inversiones On Line SAC — Robles.AI
clasificación: Confidencial — Uso interno BBVA
---

# Manual de Usuario — AlwaysPrint Client

**Versión**: 1.0.0  
**Fecha**: Mayo 2026  
**Clasificación**: Confidencial — Uso interno

---

## Historial de Versiones

| Versión | Fecha | Autor | Descripción |
|---------|-------|-------|-------------|
| 1.0.0 | Mayo 2026 | Robles.AI | Versión inicial |

---

## Tabla de Contenidos

1. [¿Qué es AlwaysPrint?](#1-qué-es-alwaysprint)
2. [¿Cómo funciona?](#2-cómo-funciona)
3. [Lo que verá en su pantalla](#3-lo-que-verá-en-su-pantalla)
4. [Operación diaria](#4-operación-diaria)
5. [Situaciones frecuentes y qué hacer](#5-situaciones-frecuentes-y-qué-hacer)
6. [Preguntas frecuentes](#6-preguntas-frecuentes)
7. [Información para Soporte TI](#7-información-para-soporte-ti)
8. [Glosario](#8-glosario)
9. [Soporte y contacto](#9-soporte-y-contacto)

---

## Convenciones del Documento

| Icono | Significado |
|-------|-------------|
| ℹ️ | Información adicional |
| ⚠️ | Advertencia — requiere atención |
| ✅ | Acción completada o confirmación |
| 💡 | Consejo o buena práctica |

---

## 1. ¿Qué es AlwaysPrint?

AlwaysPrint es un software de **continuidad de impresión** instalado en su equipo de trabajo. Su función es garantizar que usted pueda seguir imprimiendo incluso cuando el sistema principal de impresión (Lexmark CPM) presente una falla.

**Puntos clave:**

- Funciona de forma **completamente automática**. No requiere intervención del usuario.
- **No reemplaza** el sistema de impresión habitual. Solo se activa cuando este falla.
- Coexiste con Lexmark CPM en su equipo sin conflictos.
- Reporta su estado a un panel de gestión centralizado (Cloud Manager) para que el equipo de TI pueda monitorear la salud de la impresión en toda la organización.

💡 **En resumen**: AlwaysPrint es su red de seguridad para imprimir. Si todo funciona bien, no notará su presencia. Si algo falla, se encarga de que usted siga trabajando sin interrupciones.

---

## 2. ¿Cómo funciona?

El sistema opera en dos modos según el estado de la impresión:

### Modo Normal (impresión habitual)

```
Usted imprime → Cola de impresión → Lexmark CPM → Servidor de impresión → Impresora
```

AlwaysPrint permanece en segundo plano, monitoreando silenciosamente.

### Modo Contingencia (falla detectada)

```
Usted imprime → Cola de impresión → AlwaysPrint redirige → Directo a la impresora
```

AlwaysPrint detecta la falla y redirige automáticamente sus trabajos de impresión a la impresora física, sin pasar por el servidor intermedio.

**Importante**: En ambos modos, usted imprime exactamente igual. No cambia nada en su forma de trabajar.

---

## 3. Lo que verá en su pantalla

### 3.1 Icono en la bandeja del sistema

Después de iniciar sesión en Windows, verá un icono de AlwaysPrint en la bandeja del sistema (esquina inferior derecha de la pantalla, junto al reloj).

| Estado del icono | Significado |
|-----------------|-------------|
| Color normal | Todo funciona correctamente |
| Color de alerta | Contingencia activa — la impresión continúa, pero por ruta alternativa |
| Gris / inactivo | Sin conexión al servidor de gestión (la impresión local no se ve afectada) |

### 3.2 Menú del icono (click derecho)

Al hacer click derecho sobre el icono, verá las siguientes opciones:

| Opción | Qué muestra |
|--------|-------------|
| **About** | Versión instalada, estado de conexión, datos del equipo |
| **Configuration** | Configuración activa (solo lectura) |
| **My Printers** | Impresoras disponibles y su estado |
| **Check Updates** | Verifica si hay una versión más reciente |

### 3.3 Notificaciones

En ciertos eventos, aparecerá una notificación emergente junto al icono:

| Notificación | Significado | ¿Qué debe hacer? |
|-------------|-------------|-------------------|
| "Modo contingencia activo" | El sistema principal falló; AlwaysPrint está redirigiendo la impresión | **Nada.** Siga imprimiendo normalmente |
| "Sistema de impresión restaurado" | El sistema principal se recuperó; todo vuelve a la normalidad | **Nada.** Operación normal |
| "Nueva versión disponible" | Se instalará una actualización automáticamente | **Nada.** Espere unos segundos |
| "Sin conexión al servidor de gestión" | No hay comunicación con Cloud Manager | Si persiste más de 1 hora, contacte a TI |

---

## 4. Operación diaria

### 4.1 Al iniciar sesión

1. Encienda su equipo e inicie sesión en Windows como de costumbre.
2. El icono de AlwaysPrint aparecerá automáticamente en la bandeja del sistema.
3. No se requiere ninguna acción adicional.

💡 Si el icono no aparece en los primeros 2 minutos, consulte la sección [Situaciones frecuentes](#5-situaciones-frecuentes-y-qué-hacer).

### 4.2 Al imprimir

Imprima desde cualquier aplicación (Word, Excel, navegador, etc.) como lo hace habitualmente. AlwaysPrint no modifica su flujo de trabajo.

- **Si CPM funciona**: Su impresión sigue la ruta habitual.
- **Si CPM falla**: AlwaysPrint redirige automáticamente. Usted no nota diferencia.

### 4.3 Al cerrar sesión o apagar el equipo

Cierre sesión o apague normalmente. AlwaysPrint se detiene de forma ordenada y se reiniciará automáticamente en la próxima sesión.

### 4.4 Actualizaciones

Las actualizaciones se instalan automáticamente sin intervención del usuario. Durante la actualización:

- El icono puede desaparecer brevemente (~10 segundos).
- No se interrumpe la impresión en curso.
- No es necesario reiniciar el equipo.

---

## 5. Situaciones frecuentes y qué hacer

| Situación | Causa probable | Acción recomendada |
|-----------|---------------|-------------------|
| El icono no aparece al iniciar sesión | El servicio aún está iniciándose | Espere 2 minutos. Si no aparece, reinicie el equipo |
| Notificación "Sin conexión" persistente | Problema de red o proxy | Contacte a Soporte TI |
| No puedo imprimir (ni en modo normal ni contingencia) | Problema de red hacia la impresora | Contacte a Soporte TI |
| El icono desapareció repentinamente | Actualización en curso | Espere 30 segundos. Reaparecerá automáticamente |
| Notificación de contingencia frecuente | Inestabilidad en el sistema principal | No requiere acción suya. TI está siendo notificado automáticamente |

⚠️ **Regla general**: Si puede imprimir, no hay problema. Si no puede imprimir, contacte a Soporte TI.

---

## 6. Preguntas frecuentes

**¿Necesito hacer algo para que AlwaysPrint funcione?**  
No. El software es completamente automático desde la instalación.

**¿Puedo seguir imprimiendo cuando aparece la notificación de contingencia?**  
Sí. La notificación solo le informa que el sistema principal falló y AlwaysPrint está redirigiendo. Siga imprimiendo normalmente.

**¿AlwaysPrint reemplaza al sistema de impresión habitual?**  
No. Es un respaldo que solo se activa cuando el sistema principal falla.

**¿Funciona sin conexión a Internet?**  
Sí. La impresión funciona localmente. La conexión a Internet es solo para gestión y monitoreo remoto.

**¿Consume muchos recursos de mi equipo?**  
No. El consumo es mínimo (~20-30 MB de RAM, CPU negligible).

**¿Cómo sé qué versión tengo?**  
Click derecho en el icono de bandeja → About.

**¿Puedo desinstalar AlwaysPrint?**  
Solo con autorización de TI. La desinstalación elimina la protección de contingencia.

**¿Qué hago si el icono no aparece?**  
Espere 2 minutos. Si no aparece, reinicie el equipo. Si persiste, contacte a Soporte TI.

---

## 7. Información para Soporte TI

Esta sección está dirigida al personal de soporte técnico que administra las workstations.

### 7.1 Requisitos del sistema

| Requisito | Detalle |
|-----------|---------|
| Sistema operativo | Windows 10 / 11 (x64) |
| .NET Framework | 4.8 |
| Lexmark CPM Client | ≥ 3.6.0 (coexistencia) |
| Servicio LPD (LPDSVC) | Habilitado |
| RAM libre | 2 GB mínimo |
| Disco | 100 MB (instalación + logs) |

### 7.2 Requisitos de red

| Destino | Puerto | Dirección | Propósito |
|---------|--------|-----------|-----------|
| Cloud Manager (*.iol.pe) | HTTPS 443 | Salida (vía proxy) | Telemetría y configuración |
| Impresoras físicas | TCP 515 (LPD) o 9100 (RAW) | Red interna | Impresión en contingencia |

### 7.3 Instalación

```powershell
# Instalación silenciosa
msiexec /i AlwaysPrint.msi /qn

# Verificación
Get-Service AlwaysPrintService
```

### 7.4 Verificación post-instalación

| Verificación | Comando | Resultado esperado |
|-------------|---------|-------------------|
| Servicio activo | `Get-Service AlwaysPrintService` | Status: Running |
| Icono visible | Revisar bandeja del sistema | Icono presente |
| Directorio de config | `Test-Path C:\ProgramData\AlwaysPrint\config` | True |
| Registro en Cloud | Dashboard web → Workstations | Workstation "Online" |

### 7.5 Diagnóstico de problemas

```powershell
# Estado del servicio
Get-Service AlwaysPrintService

# Últimos 50 logs del servicio
Get-EventLog -LogName Application -Source AlwaysPrintService -Newest 50

# Últimos 50 logs del Tray
Get-EventLog -LogName Application -Source AlwaysPrintTray -Newest 50

# Verificar configuración activa
Test-Path "C:\ProgramData\AlwaysPrint\config\active.alwaysconfig"
Get-Content "C:\ProgramData\AlwaysPrint\config\active.alwaysconfig" | ConvertFrom-Json

# Conectividad con Cloud Manager
Test-NetConnection alwaysprint.apps.iol.pe -Port 443

# Reiniciar servicio
Restart-Service AlwaysPrintService

# Verificar servicio LPD
Get-Service LPDSVC
```

### 7.6 Problemas comunes (Soporte TI)

| Problema | Diagnóstico | Solución |
|----------|-------------|----------|
| Servicio no inicia | Event Viewer → Application → AlwaysPrintService | Verificar .NET 4.8, reinstalar MSI |
| Tray no conecta a Cloud | Verificar proxy, DNS, firewall | Asegurar acceso HTTPS a `*.iol.pe` |
| Workstation no aparece en dashboard | IP pública no autorizada | Autorizar en Admin → IPs Pendientes |
| Configuración no se descarga | Logs del Tray (ConfigManager) | Verificar conectividad, reiniciar Tray |
| Acciones no se ejecutan | Event Viewer → ActionEngine | Verificar `active.alwaysconfig` existe y es JSON válido |

### 7.7 Arquitectura de componentes

| Componente | Ejecutable | Cuenta | Función |
|-----------|-----------|--------|---------|
| Service | AlwaysPrintService.exe | LocalSystem | Monitoreo, contingencia, acciones administrativas |
| Tray | AlwaysPrintTray.exe | Usuario actual | Interfaz, comunicación Cloud, notificaciones |

### 7.8 Archivos y rutas

| Archivo | Ruta |
|---------|------|
| Ejecutable Service | `C:\Program Files\AlwaysPrint\AlwaysPrintService.exe` |
| Ejecutable Tray | `C:\Program Files\AlwaysPrint\AlwaysPrintTray.exe` |
| Config de acciones | `C:\ProgramData\AlwaysPrint\config\active.alwaysconfig` |
| Recursos VLAN | `C:\ProgramData\AlwaysPrint\config\resources.json` |
| Registro Windows | `HKLM\SOFTWARE\AlwaysPrint\` |

### 7.9 Desinstalación

```powershell
msiexec /x AlwaysPrint.msi /qn
```

### 7.10 Seguridad

- Comunicación con Cloud Manager cifrada (TLS 1.3).
- Autenticación de workstation por IP pública (sin credenciales de usuario).
- Servicio ejecuta con cuenta LocalSystem (requerido para gestionar colas y servicios).
- Configuración almacenada en `C:\ProgramData\AlwaysPrint\` (acceso restringido).

---

## 8. Glosario

| Término | Definición |
|---------|-----------|
| AlwaysPrint | Software de continuidad de impresión |
| CPM | Cloud Print Manager (Lexmark) — sistema de impresión principal |
| Contingencia | Modo en que AlwaysPrint redirige la impresión directamente a la impresora |
| Cloud Manager | Panel web de gestión centralizada |
| Bandeja del sistema | Área de iconos en la esquina inferior derecha de Windows (junto al reloj) |

---

## 9. Soporte y contacto

### Soporte de primer nivel (TI interno)

Para problemas con la impresión o el icono de AlwaysPrint, contacte a su mesa de ayuda habitual.

### Soporte de segundo nivel (Robles.AI)

- **Email**: antonio@robles.ai
- **Teléfono**: +1 408 590 0153
- **Web**: https://robles.ai

### Al reportar un problema, incluya:

1. Nombre de su equipo (hostname)
2. Versión de AlwaysPrint (click derecho → About)
3. Descripción del problema
4. Captura de pantalla (si aplica)

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados
