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
**Producto**: AlwaysPrint Client para Windows  
**Empresa**: Inversiones On Line SAC — Robles.AI  
**Clasificación**: Confidencial — Uso interno

---

## Historial de Versiones

| Versión | Fecha | Autor | Descripción del cambio |
|---------|-------|-------|------------------------|
| 1.0.0 | Mayo 2026 | Robles.AI | Versión inicial del manual |
| — | — | — | — |

---

## Tabla de Contenidos

1. [Introducción](#1-introducción)
2. [Descripción General del Sistema](#2-descripción-general-del-sistema)
3. [Requisitos del Sistema](#3-requisitos-del-sistema)
4. [Instalación y Despliegue](#4-instalación-y-despliegue)
5. [Primeros Pasos / Inicio Rápido](#5-primeros-pasos--inicio-rápido)
6. [Interfaz de Usuario](#6-interfaz-de-usuario)
7. [Configuración](#7-configuración)
8. [Uso Diario / Operación Normal](#8-uso-diario--operación-normal)
9. [Funciones Avanzadas](#9-funciones-avanzadas)
10. [Estados del Sistema](#10-estados-del-sistema)
11. [Seguridad y Permisos](#11-seguridad-y-permisos)
12. [Solución de Problemas](#12-solución-de-problemas)
13. [Preguntas Frecuentes](#13-preguntas-frecuentes)
14. [Glosario](#14-glosario)
15. [Soporte y Contacto](#15-soporte-y-contacto)

---

## Convenciones del Documento

| Icono | Significado |
|-------|-------------|
| ℹ️ | Información adicional o nota aclaratoria |
| ⚠️ | Advertencia — acción que requiere precaución |
| 🚫 | Prohibición — acción que NO debe realizarse |
| ✅ | Confirmación o paso completado exitosamente |
| 💡 | Consejo o buena práctica |

---

## 1. Introducción

### 1.1 Propósito del Documento

Este manual describe la instalación, configuración y uso del software **AlwaysPrint Client** en workstations Windows corporativas. Está dirigido a:

- **Usuarios finales** (empleados BBVA) que interactúan con el icono de bandeja
- **Soporte de TI** que instala y configura el software en las estaciones

### 1.2 Alcance

Cubre exclusivamente el componente **Client** (AlwaysPrintService + AlwaysPrintTray) instalado en workstations Windows. Para la gestión centralizada vía web, consultar el *Manual de Usuario — AlwaysPrint Cloud Manager*.

### 1.3 Audiencia

| Perfil | Secciones relevantes |
|--------|---------------------|
| Usuario final | 5, 6, 8, 10, 12, 13 |
| Soporte TI | Todas |
| Administrador de red | 3, 4, 7, 9, 11 |

### 1.4 Relación con el Sistema de Producción

AlwaysPrint Client **coexiste** con Lexmark Cloud Print Manager (CPM) en la misma workstation. No lo reemplaza. Su función es activarse automáticamente cuando CPM presenta fallas, garantizando continuidad de impresión.

---

## 2. Descripción General del Sistema

### 2.1 ¿Qué es AlwaysPrint Client?

AlwaysPrint Client es un software de contingencia para impresión corporativa que:

- Monitorea el estado del sistema de impresión principal (Lexmark CPM)
- Detecta automáticamente fallas de CPM
- Redirige el tráfico de impresión directamente a las impresoras físicas
- Reporta estado y telemetría a la plataforma de gestión centralizada (Cloud Manager)
- Ejecuta acciones administrativas remotas configuradas por TI

### 2.2 Arquitectura del Cliente

```
┌─────────────────────────────────────────────────────────┐
│                 WORKSTATION WINDOWS                       │
│                                                          │
│  ┌─────────────────────────────────────────────────┐    │
│  │  AlwaysPrintService.exe                          │    │
│  │  (Servicio Windows — cuenta LocalSystem)         │    │
│  │                                                   │    │
│  │  • Detección de fallas CPM                       │    │
│  │  • Redirección de tráfico de impresión           │    │
│  │  • Motor de acciones administrativas             │    │
│  │  • Gestión de sesión de usuario                  │    │
│  └──────────────────┬──────────────────────────────┘    │
│                     │ Named Pipe (IPC local)             │
│  ┌──────────────────▼──────────────────────────────┐    │
│  │  AlwaysPrintTray.exe                             │    │
│  │  (Aplicación de bandeja — sesión de usuario)     │    │
│  │                                                   │    │
│  │  • Icono en bandeja del sistema                  │    │
│  │  • Conexión a Cloud Manager                      │    │
│  │  • Sincronización de configuración               │    │
│  │  • Notificaciones al usuario                     │    │
│  │  • Auto-actualización                            │    │
│  └──────────────────────────────────────────────────┘    │
│                                                          │
│  Archivos de configuración:                             │
│  • C:\ProgramData\AlwaysPrint\config\active.alwaysconfig│
│  • C:\ProgramData\AlwaysPrint\config\resources.json     │
└─────────────────────────────────────────────────────────┘
```

### 2.3 Componentes

| Componente | Ejecutable | Cuenta | Función principal |
|-----------|-----------|--------|-------------------|
| Service | AlwaysPrintService.exe | LocalSystem | Monitoreo, contingencia, acciones |
| Tray | AlwaysPrintTray.exe | Usuario actual | UI, comunicación Cloud, notificaciones |

### 2.4 Cómo Encaja en el Ecosistema

```
Impresión normal:  Usuario → Cola LexmarkBBVA → CPM Client → Servidor Linux → Impresora
Contingencia:      Usuario → Cola Windows → AlwaysPrint → Directo a IP impresora
```

---

## 3. Requisitos del Sistema

### 3.1 Requisitos de Hardware

| Recurso | Mínimo | Recomendado |
|---------|--------|-------------|
| RAM | 2 GB libres | 4 GB libres |
| Disco | 50 MB (instalación) | 100 MB (con logs) |
| CPU | x64 | x64 |

### 3.2 Requisitos de Software

| Software | Versión | Obligatorio |
|----------|---------|-------------|
| Windows | 10 / 11 (x64) | ✅ |
| .NET Framework | 4.8 | ✅ |
| Lexmark CPM Client | ≥ 3.6.0 | ✅ (coexistencia) |
| Servicio LPD (LPDSVC) | Habilitado | ✅ |

### 3.3 Requisitos de Red

| Recurso | Puerto/Protocolo | Dirección | Propósito |
|---------|-----------------|-----------|-----------|
| Cloud Manager | HTTPS 443 | Salida (vía proxy) | Telemetría, configuración |
| Cloud Manager | WSS 443 | Salida (vía proxy) | Tiempo real |
| Impresoras | TCP 515 (LPD) o 9100 (RAW) | Salida (red interna) | Impresión en contingencia |
| Proxy corporativo | Según configuración | Salida | Acceso a Internet |

### 3.4 Requisitos de Permisos

| Componente | Cuenta requerida | Motivo |
|-----------|-----------------|--------|
| Instalación MSI | Administrador local | Registro de servicio Windows |
| AlwaysPrintService | LocalSystem (automático) | Gestión de colas, servicios, procesos |
| AlwaysPrintTray | Usuario estándar | Sesión interactiva, acceso a proxy |

---

## 4. Instalación y Despliegue

### 4.1 Instalación Manual

1. Obtener el archivo `AlwaysPrint.msi` (proporcionado por TI o descargado de S3)
2. Ejecutar como administrador:
   ```
   msiexec /i AlwaysPrint.msi /qn
   ```
3. Verificar instalación:
   ```
   Get-Service AlwaysPrintService
   ```

### 4.2 Instalación vía GPO (Despliegue masivo)

<!-- TODO: Documentar procedimiento de despliegue por GPO -->

1. Copiar MSI a carpeta compartida accesible por las workstations
2. Crear GPO de instalación de software (Computer Configuration)
3. Asignar el paquete MSI
4. Las workstations instalarán en el próximo reinicio

### 4.3 Verificación Post-Instalación

| Verificación | Comando / Acción | Resultado esperado |
|-------------|-----------------|-------------------|
| Servicio registrado | `Get-Service AlwaysPrintService` | Status: Running |
| Tray visible | Revisar bandeja del sistema | Icono AlwaysPrint presente |
| Directorio de config | `Test-Path C:\ProgramData\AlwaysPrint\config` | True |
| Logs en Event Viewer | Event Viewer → Application → AlwaysPrintService | Entradas de inicio |

### 4.4 Actualización

El cliente se actualiza automáticamente cuando el administrador publica una nueva versión en Cloud Manager. El proceso es:

1. Tray detecta nueva versión disponible
2. Descarga el MSI en segundo plano
3. Notifica al Service para instalar
4. Service ejecuta la instalación silenciosa
5. Servicio se reinicia con la nueva versión

⚠️ **No es necesario desinstalar la versión anterior.** El MSI maneja la actualización in-place.

### 4.5 Desinstalación

```
msiexec /x AlwaysPrint.msi /qn
```

O desde Panel de Control → Programas y características → AlwaysPrint → Desinstalar.

---

## 5. Primeros Pasos / Inicio Rápido

### 5.1 Para el Usuario Final

Después de la instalación, **no se requiere ninguna acción del usuario**. El sistema funciona de forma transparente:

1. ✅ El servicio se inicia automáticamente con Windows
2. ✅ El icono de bandeja aparece al iniciar sesión
3. ✅ La conexión a Cloud Manager se establece automáticamente
4. ✅ La configuración se descarga sin intervención

💡 **El usuario solo necesita saber**: Si aparece una notificación de contingencia, puede seguir imprimiendo normalmente. El sistema se encarga de redirigir.

### 5.2 Para Soporte TI

Después de instalar en una workstation nueva:

1. Verificar que el servicio está corriendo (`Get-Service AlwaysPrintService`)
2. Verificar que el icono de Tray aparece en la bandeja
3. Esperar ~30 segundos para que se registre en Cloud Manager
4. Verificar en el dashboard web que la workstation aparece como "Online"
5. Si la IP pública es nueva, autorizarla en Cloud Manager → Admin → IPs Pendientes

---

## 6. Interfaz de Usuario

### 6.1 Icono de Bandeja del Sistema

El icono de AlwaysPrint se ubica en la bandeja del sistema (system tray, esquina inferior derecha). Su color/estado indica:

| Estado del icono | Significado |
|-----------------|-------------|
| Normal (color estándar) | Sistema operando correctamente, CPM activo |
| Alerta (color diferenciado) | Contingencia activa — impresión redirigida |
| Gris / Inactivo | Sin conexión a Cloud Manager |

### 6.2 Menú Contextual (Click derecho)

Al hacer click derecho sobre el icono se muestra:

| Opción | Descripción | Disponible para |
|--------|-------------|-----------------|
| **About** | Versión del software, estado de conexión, ID de workstation | Todos |
| **Configuration** | Ver configuración activa (solo lectura) | Todos |
| **My Printers** | Lista de impresoras disponibles y estado | Todos |
| **Check Updates** | Verificar si hay actualizaciones disponibles | Todos |

### 6.3 Notificaciones (Balloon Tips)

El Tray muestra notificaciones emergentes en estos eventos:

| Evento | Mensaje típico | Acción del usuario |
|--------|---------------|-------------------|
| Contingencia activada | "Modo contingencia activo. La impresión continúa normalmente." | Ninguna requerida |
| Contingencia desactivada | "Sistema de impresión restaurado." | Ninguna requerida |
| Actualización disponible | "Nueva versión disponible. Se instalará automáticamente." | Ninguna requerida |
| Error de conexión | "Sin conexión al servidor de gestión." | Contactar TI si persiste |

### 6.4 Ventana "About"

Muestra:
- Nombre del producto y versión instalada
- Estado de conexión a Cloud Manager (Conectado / Desconectado)
- IP privada de la workstation
- Hostname
- Organización asignada
- Última sincronización de configuración

---

## 7. Configuración

### 7.1 Configuración Automática (Recomendado)

La configuración se gestiona centralmente desde Cloud Manager. El Tray descarga automáticamente:

- **Configuración de organización**: Parámetros de la organización
- **Configuración de VLAN**: Parámetros específicos de la red
- **Configuración de workstation**: Parámetros específicos de esta estación
- **Acciones administrativas**: Archivo `.alwaysconfig` con acciones a ejecutar

ℹ️ **No es necesario configurar manualmente** en la mayoría de los casos.

### 7.2 Parámetros de Configuración

| Parámetro | Descripción | Valor por defecto |
|-----------|-------------|-------------------|
| CorporateQueueName | Nombre de la cola de impresión corporativa | LexmarkBBVA |
| BootstrapDomains | Dominios para descubrimiento del Cloud Manager | apps.iol.pe |
| CloudEnabled | Habilitar conexión a Cloud Manager | true |
| TelemetryEnabled | Enviar telemetría de impresión | true |
| TelemetryIntervalSeconds | Intervalo de envío de telemetría | 300 (5 min) |
| ConnectivityChecks | Lista de checks de conectividad | Configurado por TI |

### 7.3 Configuración del Registro Windows

La configuración se almacena en:
```
HKLM\SOFTWARE\AlwaysPrint\
```

⚠️ **No modificar manualmente** a menos que lo indique Soporte TI.

### 7.4 Archivos de Configuración

| Archivo | Ruta | Propósito |
|---------|------|-----------|
| active.alwaysconfig | `C:\ProgramData\AlwaysPrint\config\` | Acciones administrativas activas |
| resources.json | `C:\ProgramData\AlwaysPrint\config\` | Recursos de VLAN, impresoras |

### 7.5 Configuración de Proxy

El Tray detecta automáticamente la configuración de proxy del sistema. Si se requiere configuración manual:

<!-- TODO: Documentar configuración manual de proxy si aplica -->

---

## 8. Uso Diario / Operación Normal

### 8.1 Flujo Normal (CPM Funcionando)

Cuando el sistema de producción (Lexmark CPM) funciona correctamente:

1. El usuario imprime desde cualquier aplicación
2. El trabajo va a la cola LexmarkBBVA → CPM Client → Servidor Linux → Impresora
3. AlwaysPrint permanece en segundo plano, monitoreando
4. El icono de bandeja muestra estado normal
5. La telemetría se envía periódicamente a Cloud Manager

**Acción del usuario**: Ninguna. Imprimir normalmente.

### 8.2 Flujo de Contingencia (CPM con Falla)

Cuando AlwaysPrint detecta una falla en CPM:

1. El Service detecta que CPM no responde
2. Se activa automáticamente el modo contingencia
3. El tráfico de impresión se redirige a la IP directa de la impresora
4. El Tray muestra notificación: "Modo contingencia activo"
5. El usuario puede seguir imprimiendo normalmente
6. Cloud Manager registra el evento y alerta a los administradores

**Acción del usuario**: Ninguna. Seguir imprimiendo. La redirección es transparente.

### 8.3 Restauración (CPM Recuperado)

Cuando CPM se recupera:

1. AlwaysPrint detecta que CPM vuelve a responder
2. Se desactiva el modo contingencia
3. El tráfico vuelve al flujo normal (CPM → Servidor Linux → Impresora)
4. El Tray muestra notificación: "Sistema restaurado"
5. Cloud Manager registra la restauración

**Acción del usuario**: Ninguna. El sistema se restaura automáticamente.

### 8.4 Inicio de Sesión

Al iniciar sesión en Windows:

1. El servicio AlwaysPrintService ya está corriendo (inicio automático)
2. El servicio detecta la sesión interactiva del usuario
3. Lanza AlwaysPrintTray en la sesión del usuario
4. El Tray se conecta al Service vía Named Pipe
5. El Tray establece conexión con Cloud Manager
6. Se sincroniza la configuración

**Acción del usuario**: Ninguna. Todo es automático.

### 8.5 Cierre de Sesión / Cambio de Usuario

Al cerrar sesión:

1. El Tray se cierra automáticamente
2. El Service detecta el logoff
3. El Service pasa a estado "WaitingUser"
4. Cuando otro usuario inicia sesión, se repite el proceso 8.4

---

## 9. Funciones Avanzadas

### 9.1 Modo Contingencia Forzada

Un administrador puede forzar el modo contingencia desde Cloud Manager, incluso si CPM funciona correctamente. Esto es útil para:

- Mantenimiento programado de CPM
- Pruebas del sistema de contingencia
- Situaciones donde CPM funciona pero con degradación

Cuando se activa contingencia forzada:
- El icono de bandeja cambia de estado
- Se muestra notificación al usuario
- La impresión se redirige directamente a la impresora

### 9.2 Acciones Administrativas Remotas

Los administradores pueden configurar acciones que se ejecutan automáticamente en la workstation ante ciertos eventos:

| Evento (Trigger) | Cuándo se ejecuta |
|-------------------|-------------------|
| OnServiceStart | Al iniciar el servicio Windows |
| OnTrayLaunched | Después de que el Tray se conecta |
| OnConfigChange | Al recibir nueva configuración |
| OnContingencyActivated | Al activar contingencia |
| OnContingencyDeactivated | Al desactivar contingencia |

Ejemplos de acciones:
- Propagar permisos de carpetas de impresión
- Limpiar cachés de usuarios inactivos
- Reiniciar servicios relacionados
- Configurar puertos de impresora

ℹ️ Estas acciones son transparentes para el usuario final.

### 9.3 Auto-Actualización

El cliente se actualiza automáticamente:

1. El Tray verifica periódicamente si hay nueva versión
2. Si existe, descarga el MSI en segundo plano
3. Solicita al Service que instale la actualización
4. El Service ejecuta la instalación silenciosa
5. Los servicios se reinician con la nueva versión

⚠️ La actualización puede causar una breve interrupción del icono de bandeja (~10 segundos).

### 9.4 Checks de Conectividad

El Tray ejecuta checks de conectividad configurados por TI:

| Tipo de check | Qué verifica |
|--------------|-------------|
| HTTP | Accesibilidad de una URL (código 200) |
| TCP | Conexión a un host:puerto |
| Ping | Respuesta ICMP de un host |
| DNS | Resolución de un nombre de dominio |

Los resultados se reportan a Cloud Manager para monitoreo centralizado.

---

## 10. Estados del Sistema

### 10.1 Estados del Servicio (AlwaysPrintService)

```
Starting ──► WaitingUser ──► TrayStarting ──► TrayStarted ──► Running
                 ▲                                                │
                 │                                                │
                 └──────────── (logoff usuario) ◄─────────────────┘
                 
Running puede estar en:
  • Modo Normal (CPM activo)
  • Modo Contingencia (CPM con falla)

Stopping ──► Stopped (apagado del sistema o detención manual)
```

| Estado | Significado | Icono de bandeja |
|--------|-------------|-----------------|
| Starting | Servicio iniciándose | No visible aún |
| WaitingUser | Esperando sesión interactiva | No visible |
| TrayStarting | Lanzando aplicación de bandeja | Apareciendo |
| TrayStarted | Tray conectado, sincronizando | Visible, inicializando |
| Running | Operación normal | Visible, estado normal |
| TrayError | Error en comunicación con Tray | Visible con error |
| Stopping | Servicio deteniéndose | Desapareciendo |
| Stopped | Servicio detenido | No visible |

### 10.2 Estados de Contingencia

| Estado | Descripción | Impacto en usuario |
|--------|-------------|-------------------|
| Inactiva | CPM funciona, flujo normal | Ninguno |
| Activa (automática) | CPM falló, redirección activa | Impresión continúa, notificación |
| Activa (forzada) | Admin forzó contingencia | Impresión continúa, notificación |

### 10.3 Estados de Conexión a Cloud

| Estado | Descripción | Consecuencia |
|--------|-------------|-------------|
| Conectado | WebSocket activo con Cloud Manager | Tiempo real, configuración sincronizada |
| Desconectado | Sin conexión a Cloud Manager | Funciona offline, datos se acumulan localmente |
| Pendiente | IP no autorizada en Cloud Manager | Funciona localmente, sin gestión remota |

---

## 11. Seguridad y Permisos

### 11.1 Cuentas y Privilegios

| Componente | Cuenta | Privilegios | Justificación |
|-----------|--------|-------------|---------------|
| AlwaysPrintService | LocalSystem | Máximos (local) | Gestionar servicios, colas, procesos |
| AlwaysPrintTray | Usuario actual | Estándar | Acceso a proxy, sesión interactiva |
| Instalación | Administrador | Elevados | Registro de servicio, escritura en ProgramData |

### 11.2 Comunicación Segura

| Canal | Protocolo | Cifrado |
|-------|-----------|---------|
| Tray → Cloud Manager | HTTPS / WSS | TLS 1.3 |
| Service ↔ Tray | Named Pipe local | No aplica (IPC local) |
| Workstation → Impresora (contingencia) | LPD / RAW | Sin cifrado (red interna) |

### 11.3 Autenticación con Cloud Manager

- **No se usan credenciales de usuario** para la comunicación con Cloud
- La workstation se autentica por su **IP pública**
- La IP debe estar autorizada por un administrador en Cloud Manager
- Si la IP cambia (ej: cambio de sede), requiere re-autorización

### 11.4 Almacenamiento de Datos

| Dato | Ubicación | Acceso |
|------|-----------|--------|
| Configuración | `C:\ProgramData\AlwaysPrint\config\` | Service: R/W, Tray: R |
| Credenciales Cloud | Registro HKCU | Solo usuario actual |
| Logs | Event Viewer (Application) | Administradores |

### 11.5 Consideraciones de Red

- El Tray requiere acceso a Internet (vía proxy corporativo) para comunicarse con Cloud Manager
- El Service NO requiere acceso a Internet
- En contingencia, se requiere acceso directo a la IP de la impresora (red interna)
- El puerto 515 (LPD) o 9100 (RAW) debe estar accesible hacia las impresoras

---

## 12. Solución de Problemas

### 12.1 Problemas Comunes — Usuario Final

| Problema | Causa probable | Solución |
|----------|---------------|----------|
| No aparece el icono de bandeja | Servicio detenido o sesión sin usuario | Reiniciar PC o contactar TI |
| Notificación "Sin conexión" persistente | Proxy no configurado o Cloud Manager inaccesible | Contactar TI |
| No puedo imprimir en contingencia | Impresora no accesible por red | Contactar TI |
| El icono desapareció tras actualización | Reinicio del Tray durante actualización | Esperar 30 segundos, reaparecerá |

### 12.2 Problemas Comunes — Soporte TI

| Problema | Diagnóstico | Solución |
|----------|-------------|----------|
| Servicio no inicia | Event Viewer → Application → AlwaysPrintService | Verificar .NET 4.8, reinstalar MSI |
| Tray no se conecta a Cloud | Verificar proxy, DNS, firewall | Asegurar acceso HTTPS a `*.iol.pe` |
| Workstation no aparece en dashboard | IP pública no autorizada | Autorizar en Admin → IPs Pendientes |
| Configuración no se descarga | Verificar logs del Tray (ConfigManager) | Verificar conectividad, reiniciar Tray |
| Acciones no se ejecutan | Event Viewer → AlwaysPrintService → ActionEngine | Verificar `active.alwaysconfig` existe y es JSON válido |
| Contingencia no se activa | Verificar que el Service detecta la falla | Revisar logs, verificar configuración de detección |

### 12.3 Comandos de Diagnóstico

```powershell
# Verificar estado del servicio
Get-Service AlwaysPrintService

# Ver últimos 50 logs del servicio
Get-EventLog -LogName Application -Source AlwaysPrintService -Newest 50

# Ver últimos 50 logs del Tray
Get-EventLog -LogName Application -Source AlwaysPrintTray -Newest 50

# Verificar archivo de configuración
Test-Path "C:\ProgramData\AlwaysPrint\config\active.alwaysconfig"
Get-Content "C:\ProgramData\AlwaysPrint\config\active.alwaysconfig" | ConvertFrom-Json

# Verificar conectividad con Cloud Manager
Test-NetConnection alwaysprint.apps.iol.pe -Port 443

# Reiniciar servicio
Restart-Service AlwaysPrintService

# Verificar servicio LPD (requerido para contingencia)
Get-Service LPDSVC
```

### 12.4 Logs y Diagnóstico

| Fuente de log | Ubicación | Contenido |
|--------------|-----------|-----------|
| AlwaysPrintService | Event Viewer → Application | Inicio, estados, contingencia, acciones |
| AlwaysPrintTray | Event Viewer → Application | Conexión Cloud, config sync, updates |
| Descarga remota | Cloud Manager → Workstation → Logs | Admin puede descargar logs remotamente |

---

## 13. Preguntas Frecuentes

**P: ¿Necesito hacer algo para que AlwaysPrint funcione?**  
R: No. El software funciona de forma completamente automática después de la instalación.

**P: ¿Puedo seguir imprimiendo si aparece la notificación de contingencia?**  
R: Sí. La notificación solo informa que el sistema de impresión principal falló y AlwaysPrint está redirigiendo. Puede seguir imprimiendo normalmente.

**P: ¿AlwaysPrint reemplaza a Lexmark CPM?**  
R: No. AlwaysPrint es un sistema de contingencia que solo se activa cuando CPM falla. Ambos coexisten.

**P: ¿Qué pasa si no tengo conexión a Internet?**  
R: AlwaysPrint funciona localmente sin Internet. La conexión a Cloud Manager es para gestión y telemetría, no para imprimir.

**P: ¿Puedo desinstalar AlwaysPrint?**  
R: Solo con autorización de TI. La desinstalación elimina la protección de contingencia.

**P: ¿El software consume muchos recursos?**  
R: No. El consumo es mínimo (~20-30 MB RAM, CPU negligible en operación normal).

**P: ¿Cómo sé qué versión tengo instalada?**  
R: Click derecho en el icono de bandeja → About. Muestra la versión actual.

**P: ¿Qué hago si el icono no aparece?**  
R: Espere 1-2 minutos después de iniciar sesión. Si no aparece, contacte a Soporte TI.

---

## 14. Glosario

| Término | Definición |
|---------|-----------|
| AlwaysPrint | Sistema de contingencia de impresión desarrollado por Robles.AI |
| CPM | Cloud Print Manager (Lexmark) — sistema de impresión de producción |
| Contingencia | Modo activado cuando CPM falla; redirige impresión directamente a impresoras |
| Cloud Manager | Plataforma web de gestión centralizada de AlwaysPrint |
| Tray | Aplicación de bandeja del sistema (AlwaysPrintTray.exe) |
| Service | Servicio Windows (AlwaysPrintService.exe) |
| Named Pipe | Canal de comunicación local entre Service y Tray |
| LPD | Line Printer Daemon — protocolo de impresión (puerto 515) |
| RAW | Protocolo de impresión directa (puerto 9100) |
| VLAN | Red de área local virtual — agrupación lógica de workstations |
| MSI | Microsoft Installer — formato del instalador de Windows |
| LocalSystem | Cuenta de servicio Windows con máximos privilegios locales |
| Balloon Tip | Notificación emergente de Windows desde la bandeja del sistema |
| Heartbeat | Señal periódica que indica que la workstation está activa |
| Telemetría | Datos de uso y rendimiento enviados a Cloud Manager |

---

## 15. Soporte y Contacto

### Soporte de Primer Nivel (TI BBVA)
- Verificar estado del servicio y Tray
- Reiniciar servicio si es necesario
- Verificar conectividad de red

### Soporte de Segundo Nivel (Robles.AI)
- **Email**: antonio@robles.ai
- **Teléfono**: +1 408 590 0153
- **Web**: https://robles.ai

### Información para Reportar Incidencias

Al reportar un problema, incluir:
1. Hostname de la workstation
2. IP privada
3. Versión del cliente (About → versión)
4. Captura de pantalla del error (si aplica)
5. Últimos 50 eventos del Event Viewer (Application → AlwaysPrintService)

---

## Apéndices

### Apéndice A: Parámetros del Registro Windows

| Clave | Ruta | Tipo | Descripción |
|-------|------|------|-------------|
| CorporateQueueName | HKLM\SOFTWARE\AlwaysPrint | REG_SZ | Nombre de la cola corporativa |
| CloudApiUrl | HKLM\SOFTWARE\AlwaysPrint | REG_SZ | URL del Cloud Manager |
| TelemetryEnabled | HKLM\SOFTWARE\AlwaysPrint | REG_DWORD | 1=habilitado, 0=deshabilitado |
| TelemetryIntervalSeconds | HKLM\SOFTWARE\AlwaysPrint | REG_DWORD | Intervalo en segundos |

### Apéndice B: Rutas de Archivos

| Archivo | Ruta completa |
|---------|--------------|
| Ejecutable Service | `C:\Program Files\AlwaysPrint\AlwaysPrintService.exe` |
| Ejecutable Tray | `C:\Program Files\AlwaysPrint\AlwaysPrintTray.exe` |
| Config de acciones | `C:\ProgramData\AlwaysPrint\config\active.alwaysconfig` |
| Recursos VLAN | `C:\ProgramData\AlwaysPrint\config\resources.json` |

### Apéndice C: Event IDs Relevantes

<!-- TODO: Completar con Event IDs específicos del AlwaysPrintLogger -->

| Event ID | Fuente | Severidad | Descripción |
|----------|--------|-----------|-------------|
| — | AlwaysPrintService | Information | Servicio iniciado correctamente |
| — | AlwaysPrintService | Warning | Contingencia activada |
| — | AlwaysPrintService | Error | Error en ejecución de acción |
| — | AlwaysPrintTray | Information | Conexión a Cloud establecida |
| — | AlwaysPrintTray | Warning | Desconexión de Cloud Manager |

---

**Robles.AI**  
Email: antonio@robles.ai  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados
