---
título: Manual de Usuario — AlwaysPrint Client
versión: 2.0.0
fecha: Mayo 2026
producto: AlwaysPrint Client (Windows)
empresa: Inversiones On Line SAC — Robles.AI
clasificación: Confidencial — Uso interno BBVA
---

# Manual de Usuario — AlwaysPrint Client

**Versión**: 2.0.0  
**Fecha**: Mayo 2026  
**Clasificación**: Confidencial — Uso interno

---

## Historial de Versiones

| Versión | Fecha | Autor | Descripción |
|---------|-------|-------|-------------|
| 1.0.0 | Mayo 2026 | Robles.AI | Versión inicial |
| 2.0.0 | Mayo 2026 | Robles.AI | Reestructuración completa del manual |

---

## Tabla de Contenidos

1. [Introducción](#1-introducción)
2. [Arquitectura del Sistema](#2-arquitectura-del-sistema)
3. [Requisitos e Instalación](#3-requisitos-e-instalación)
4. [Interfaz de Usuario — Bandeja del Sistema](#4-interfaz-de-usuario--bandeja-del-sistema)
5. [Operación Diaria](#5-operación-diaria)
6. [Ventana "Acerca de"](#6-ventana-acerca-de)
7. [Ventana "Configuración de Valores"](#7-ventana-configuración-de-valores)
8. [Ventana "Mis Impresoras"](#8-ventana-mis-impresoras)
9. [Actualizaciones Automáticas](#9-actualizaciones-automáticas)
10. [Contingencia de Impresión](#10-contingencia-de-impresión)
11. [Integración con Cloud Manager](#11-integración-con-cloud-manager)
12. [Acciones Administrativas Remotas](#12-acciones-administrativas-remotas)
13. [Notificaciones y Alertas](#13-notificaciones-y-alertas)
14. [Información para Soporte TI](#14-información-para-soporte-ti)
15. [Solución de Problemas](#15-solución-de-problemas)
16. [Preguntas Frecuentes](#16-preguntas-frecuentes)
17. [Glosario](#17-glosario)
18. [Soporte y Contacto](#18-soporte-y-contacto)

---

## Convenciones del Documento

| Icono | Significado |
|-------|-------------|
| ℹ️ | Información adicional |
| ⚠️ | Advertencia — requiere atención |
| ✅ | Acción completada o confirmación |
| 💡 | Consejo o buena práctica |

---

## 1. Introducción

### 1.1 ¿Qué es AlwaysPrint Client?

AlwaysPrint Client es un software de **continuidad de impresión** instalado en las workstations Windows corporativas. Su función es garantizar que los usuarios puedan seguir imprimiendo incluso cuando el sistema principal de impresión (Lexmark CPM) presente una falla.

**Características principales:**

- Funciona de forma **completamente automática**. No requiere intervención del usuario final.
- **No reemplaza** el sistema de impresión habitual. Solo se activa cuando este falla.
- Coexiste con Lexmark CPM en el equipo sin conflictos.
- Reporta su estado a AlwaysPrint Cloud Manager para monitoreo centralizado.
- Recibe configuración y acciones administrativas de forma remota.
- Se actualiza automáticamente sin intervención del usuario.

### 1.2 ¿A quién va dirigido este manual?

| Audiencia | Secciones relevantes |
|-----------|---------------------|
| **Usuario final** | Secciones 1–6, 10, 13, 16 |
| **Operador TI** | Todo el manual |
| **Soporte técnico** | Secciones 14–15 especialmente |

### 1.3 Relación con otros sistemas

| Sistema | Relación con AlwaysPrint Client |
|---------|-------------------------------|
| Lexmark CPM | Sistema de impresión principal. AlwaysPrint lo complementa como contingencia |
| AlwaysPrint Cloud Manager | Plataforma web que gestiona, configura y monitorea el Client |
| Servidor Linux CUPS (BBVA) | Infraestructura de producción. No se usa en modo contingencia |

---

## 2. Arquitectura del Sistema

### 2.1 Componentes del Client

AlwaysPrint Client se compone de dos procesos que trabajan en conjunto:

| Componente | Ejecutable | Cuenta | Función |
|-----------|-----------|--------|---------|
| **Service** | AlwaysPrintService.exe | LocalSystem | Monitoreo de impresión, contingencia, ejecución de acciones administrativas, gestión de sesiones |
| **Tray** | AlwaysPrintTray.exe | Usuario actual | Interfaz visual, comunicación con Cloud Manager, notificaciones, actualizaciones |

### 2.2 Comunicación entre componentes

```
┌─────────────────────────────────────────────────────────────┐
│                    WORKSTATION WINDOWS                       │
│                                                              │
│  ┌──────────────────────┐    Named Pipe    ┌─────────────┐ │
│  │  AlwaysPrintService  │◄────────────────►│ AlwaysPrint │ │
│  │  (LocalSystem)       │                  │ Tray (User) │ │
│  │                      │                  │             │ │
│  │  • Monitoreo colas   │                  │ • UI        │ │
│  │  • Contingencia      │                  │ • Cloud     │ │
│  │  • Acciones admin    │                  │ • Updates   │ │
│  │  • Gestión sesiones  │                  │ • Notif.    │ │
│  └──────────────────────┘                  └──────┬──────┘ │
│                                                    │        │
│                                              HTTPS │        │
│                                                    ▼        │
│                                         Cloud Manager       │
│                                         (alwaysprint.       │
│                                          apps.iol.pe)       │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 Flujo de operación

**Modo Normal (impresión habitual):**
```
Usuario imprime → Cola LexmarkBBVA → Lexmark CPM Client → Servidor Linux → Impresora
```
AlwaysPrint permanece en segundo plano, monitoreando silenciosamente.

**Modo Contingencia (falla detectada):**
```
Usuario imprime → Cola de impresión → AlwaysPrint redirige → Directo a IP impresora
```
AlwaysPrint detecta la falla y redirige automáticamente los trabajos a la impresora física.

ℹ️ En ambos modos, el usuario imprime exactamente igual. No cambia nada en su forma de trabajar.

---

## 3. Requisitos e Instalación

### 3.1 Requisitos del sistema

| Requisito | Detalle |
|-----------|---------|
| Sistema operativo | Windows 10 / 11 (x64) |
| .NET Framework | 4.8 |
| Lexmark CPM Client | ≥ 3.6.0 (coexistencia) |
| Servicio LPD (LPDSVC) | Habilitado |
| RAM libre | 2 GB mínimo |
| Disco | 100 MB (instalación + logs) |

### 3.2 Requisitos de red

| Destino | Puerto | Dirección | Propósito |
|---------|--------|-----------|-----------|
| Cloud Manager (*.iol.pe) | HTTPS 443 | Salida (vía proxy) | Telemetría, configuración, actualizaciones |
| Impresoras físicas | TCP 515 (LPD) o 9100 (RAW) | Red interna | Impresión en contingencia |

### 3.3 Instalación

```powershell
# Instalación silenciosa
msiexec /i AlwaysPrint.msi /qn
```

La instalación registra el servicio Windows y configura el Tray para inicio automático con la sesión del usuario.

### 3.4 Verificación post-instalación

| Verificación | Comando | Resultado esperado |
|-------------|---------|-------------------|
| Servicio activo | `Get-Service AlwaysPrintService` | Status: Running |
| Icono visible | Revisar bandeja del sistema | Icono presente |
| Directorio de config | `Test-Path C:\ProgramData\AlwaysPrint\config` | True |
| Registro en Cloud | Dashboard web → Workstations | Workstation "Online" |

### 3.5 Secuencia de inicio

Al iniciar el servicio, se ejecuta la siguiente secuencia:

1. **Verificación de instancia única** — evita duplicados
2. **Limpieza de Trays huérfanos** — elimina procesos residuales
3. **Carga de configuración** — lee valores del registro Windows
4. **Carga de acciones administrativas** — lee `active.alwaysconfig` si existe
5. **Inicialización de cola de tareas** — prepara el sistema de tareas pendientes
6. **Inicio del servidor Named Pipe** — canal de comunicación con el Tray
7. **Espera de sesión de usuario** — detecta login interactivo
8. **Lanzamiento del Tray** — inicia la interfaz en la sesión del usuario
9. **Handshake Tray ↔ Service** — confirma comunicación bidireccional
10. **Ejecución de triggers iniciales** — `OnServiceStart`, `OnTrayLaunched`

### 3.6 Desinstalación

```powershell
msiexec /x AlwaysPrint.msi /qn
```

⚠️ Solo con autorización de TI. La desinstalación elimina la protección de contingencia.

---

## 4. Interfaz de Usuario — Bandeja del Sistema

### 4.1 Icono en la bandeja del sistema

Después de iniciar sesión en Windows, aparece un icono de AlwaysPrint en la bandeja del sistema (esquina inferior derecha, junto al reloj).

| Estado del icono | Significado |
|-----------------|-------------|
| Icono normal | Todo funciona correctamente |
| "AlwaysPrint (sin conexión)" | Sin comunicación con Cloud Manager |
| "AlwaysPrint (pendiente de aprobación)" | IP pública no autorizada aún |
| "AlwaysPrint (sin red detectada)" | No se detectó configuración de red (CIDR) |

### 4.2 Menú contextual (click derecho)

Al hacer click derecho sobre el icono, se muestra el menú con las siguientes opciones:

| Opción | Función | Sección del manual |
|--------|---------|-------------------|
| **Acerca de** | Muestra versión, usuario y datos del equipo | [Sección 6](#6-ventana-acerca-de) |
| **Configuración de Valores** | Muestra y permite editar la configuración | [Sección 7](#7-ventana-configuración-de-valores) |
| **Mis Impresoras** | Lista impresoras disponibles para contingencia | [Sección 8](#8-ventana-mis-impresoras) |
| **Buscar actualizaciones** | Verifica si hay una versión más reciente | [Sección 9](#9-actualizaciones-automáticas) |
| **Salir** | Cierra la aplicación de bandeja | — |

💡 Doble click en el icono abre directamente la ventana "Acerca de".

### 4.3 Notificaciones emergentes (Balloon Tips)

El sistema muestra notificaciones emergentes junto al icono en ciertos eventos:

| Notificación | Significado | Acción requerida |
|-------------|-------------|-----------------|
| "Inicializado correctamente" | Conexión exitosa con el dominio bootstrap | Ninguna |
| "Operando en modo local" | Sin conectividad externa, funciona offline | Si persiste >1h, contactar TI |
| "El servicio no está en ejecución" | El Service no está corriendo | Contactar TI |
| "Conectado a la nube exitosamente" | Conexión con Cloud Manager establecida | Ninguna |
| "Usando configuración guardada" | Offline, usando última config conocida | Ninguna |
| "Conexión con la nube restaurada" | Reconexión exitosa después de una caída | Ninguna |
| "Pendiente de aprobación" | IP pública no autorizada en Cloud Manager | TI debe autorizar la IP |
| "No se pudo detectar la configuración de red" | Problema de red (sin gateway) | Verificar conexión de red |
| "Configuración de red detectada correctamente" | Red recuperada después de fallo | Ninguna |

---

## 5. Operación Diaria

### 5.1 Al iniciar sesión

1. Encienda su equipo e inicie sesión en Windows como de costumbre.
2. El servicio AlwaysPrint detecta la sesión interactiva automáticamente.
3. El Tray se lanza en su sesión (~3 segundos después del login).
4. El icono aparece en la bandeja del sistema.
5. Se ejecuta la secuencia de bootstrap (health check, conexión Cloud).

💡 Si el icono no aparece en los primeros 2 minutos, consulte la [Sección 15](#15-solución-de-problemas).

### 5.2 Al imprimir

Imprima desde cualquier aplicación (Word, Excel, navegador, etc.) como lo hace habitualmente. AlwaysPrint no modifica su flujo de trabajo.

- **Si CPM funciona**: Su impresión sigue la ruta habitual.
- **Si CPM falla**: AlwaysPrint redirige automáticamente. Usted no nota diferencia.

### 5.3 Gestión de sesiones

El servicio gestiona automáticamente los cambios de sesión:

| Evento | Comportamiento |
|--------|---------------|
| Login / Desbloqueo | Detecta sesión → lanza Tray → ejecuta triggers |
| Logoff / Desconexión | Cierra Tray → espera nueva sesión |
| Cambio rápido de usuario | Cierra Tray del usuario anterior → lanza para el nuevo |

### 5.4 Al cerrar sesión o apagar

Cierre sesión o apague normalmente. AlwaysPrint se detiene de forma ordenada y se reiniciará automáticamente en la próxima sesión.

### 5.5 Monitoreo de salud

El Tray ejecuta un ping al Service cada 30 segundos para verificar que sigue activo. Si el Service no responde, se registra una advertencia en los logs.

---

## 6. Ventana "Acerca de"

Accesible desde: **Click derecho → Acerca de** o **Doble click en el icono**.

Muestra información básica del sistema:

| Campo | Descripción |
|-------|-------------|
| Versión | Versión instalada del software (ej: 1.2.0.0) |
| Usuario | Nombre del usuario con sesión activa |
| Iniciado | Fecha y hora en que se inició el proceso Tray |

Información adicional mostrada:
- Logo de AlwaysPrint
- Copyright y empresa (Robles.AI / Inversiones On Line S.A.C.)

💡 Use esta ventana para verificar rápidamente qué versión tiene instalada al reportar un problema.

---

## 7. Ventana "Configuración de Valores"

Accesible desde: **Click derecho → Configuración de Valores**.

⚠️ Requiere conexión activa con el Service. Si no hay conexión, se muestra un mensaje de error.

### 7.1 Parámetros disponibles

La ventana muestra la configuración actual organizada en secciones:

**Sección Principal**

| Parámetro | Descripción | Ejemplo |
|-----------|-------------|---------|
| Cola corporativa | Nombre de la cola de impresión principal | LexmarkBBVA |
| IPs de búsqueda (CSV) | IPs individuales de impresoras a detectar | 192.168.1.10,192.168.1.11 |
| Rangos CIDR (CSV) | Rangos de red para escaneo de impresoras | 192.168.1.0/24 |
| Intervalo de monitoreo (min) | Frecuencia de polling de tareas (1–1440) | 3 |
| Dominios bootstrap (CSV) | Dominios para descubrimiento del Cloud | apps.iol.pe |
| Número de serie licencia | Serial de licencia Robles.AI | — |

**Sección Integración Cloud**

| Parámetro | Descripción |
|-----------|-------------|
| Integración Cloud habilitada | Activa/desactiva la comunicación con Cloud Manager |
| URL del servidor Cloud (APCM) | URL completa del Cloud Manager (ej: https://alwaysprint.apps.iol.pe) |
| Idioma (locale) | Auto / Español / English |

**Sección Actualizaciones**

| Parámetro | Descripción |
|-----------|-------------|
| Habilitar Actualizaciones Automáticas | Permite que el Client se actualice sin intervención |

### 7.2 Guardar cambios

Al hacer click en "Guardar":
1. Se valida la URL del servidor Cloud (debe ser URI absoluta válida)
2. Se envía la configuración al Service vía Named Pipe
3. El Service persiste los valores en el registro de Windows (HKLM)
4. Se confirma con un mensaje de éxito

ℹ️ La configuración también puede ser gestionada de forma centralizada desde Cloud Manager, lo cual sobrescribe los valores locales.

---

## 8. Ventana "Mis Impresoras"

Accesible desde: **Click derecho → Mis Impresoras**.

⚠️ Requiere conexión activa con Cloud Manager. Si no hay conexión o la workstation no está registrada, se muestra un mensaje informativo.

### 8.1 ¿Qué muestra?

Lista las impresoras físicas disponibles para contingencia en la red (VLAN) de la workstation. Estas son las impresoras a las que se redirigirá la impresión cuando el sistema principal falle.

### 8.2 Información mostrada

**Encabezado:**
- Nombre de la VLAN asignada
- Cantidad de impresoras disponibles

**Por cada impresora:**

| Columna | Descripción |
|---------|-------------|
| Nombre | Identificador descriptivo de la impresora |
| IP : Puerto | Dirección IP y puerto de impresión |
| Modelo | Modelo del dispositivo |
| Ubicación | Ubicación física (piso, sala, etc.) |
| Estado | Badge indicando si es Favorita (⭐) o Default (📌) |

### 8.3 Impresora favorita

El usuario puede seleccionar una impresora como **favorita**. En modo contingencia, la impresora favorita se usa como destino prioritario.

**Establecer favorita:**
1. Seleccionar una impresora de la lista
2. Click en "⭐ Establecer favorita"
3. La impresora queda marcada con badge amarillo "⭐ Favorita"

**Quitar favorita:**
1. Seleccionar la impresora marcada como favorita
2. Click en "✕ Quitar favorita"

### 8.4 Impresora por defecto

Si no hay favorita seleccionada, el sistema usa la impresora marcada como **Default** (📌) por el administrador. Esta se asigna a nivel de VLAN desde Cloud Manager.

### 8.5 Prioridad de selección en contingencia

```
1. Impresora favorita (seleccionada por el usuario)
   ↓ si no hay
2. Impresora por defecto de la VLAN (configurada por admin)
   ↓ si no hay
3. Impresora con menor IP de la VLAN
```

---

## 9. Actualizaciones Automáticas

### 9.1 ¿Cómo funcionan?

Las actualizaciones se distribuyen desde Cloud Manager de forma silenciosa. El flujo es:

1. **Verificación periódica** — el Tray consulta al Cloud si hay nueva versión
2. **Descarga del MSI** — si hay actualización, se descarga en segundo plano
3. **Instalación** — el Service ejecuta la instalación del MSI
4. **Reinicio** — el Tray se reinicia automáticamente (~10 segundos)

### 9.2 Requisitos

- Conexión activa con Cloud Manager (registro exitoso)
- Actualización automática habilitada (en configuración)
- Versión disponible en el servidor (publicada por el administrador)

### 9.3 Búsqueda manual

Desde el menú: **Click derecho → Buscar actualizaciones**

| Resultado | Notificación |
|-----------|-------------|
| Hay actualización | "AlwaysPrint se está actualizando a la versión X" |
| No hay actualización | "No hay actualizaciones disponibles. Ya tienes la última versión" |
| Sin conexión Cloud | "No se puede buscar actualizaciones sin conexión a la nube" |
| Error | "No se pudo verificar actualizaciones. Intente más tarde" |

### 9.4 Durante la actualización

- El icono puede desaparecer brevemente (~10 segundos)
- No se interrumpe la impresión en curso
- No es necesario reiniciar el equipo
- El Service coordina la instalación con permisos LocalSystem

### 9.5 Control desde Cloud Manager

El administrador puede:
- Fijar una versión específica para la organización
- Activar/desactivar actualizaciones automáticas
- Enviar comando remoto "check_update" a una workstation específica

---

## 10. Contingencia de Impresión

### 10.1 ¿Qué es la contingencia?

Cuando el sistema de impresión principal (Lexmark CPM) falla, AlwaysPrint redirige automáticamente el tráfico de impresión directamente a las impresoras físicas, sin pasar por el servidor Linux intermedio.

### 10.2 Contingencia automática

⏳ **Próximamente** — Esta funcionalidad se encuentra en desarrollo.

- Se activará cuando el Service detecte que CPM no responde
- No requerirá intervención del administrador
- Se desactivará automáticamente cuando CPM se recupere

### 10.3 Contingencia forzada

Un administrador puede forzar la contingencia desde Cloud Manager. Cuando se recibe la orden:

1. El Tray recibe el comando vía Cloud Manager
2. Notifica al Service vía Named Pipe
3. El Service establece la IP de la impresora de contingencia
4. Se ejecuta el trigger `OnContingencyActivated`
5. La impresión se redirige a la IP de contingencia

### 10.4 Desactivación de contingencia

Cuando se desactiva (manual o automáticamente):

1. Se ejecuta el trigger `OnContingencyDeactivated`
2. La impresión vuelve a la ruta habitual (CPM)

### 10.5 Selección de impresora de contingencia

La impresora destino se determina según la prioridad descrita en la [Sección 8.5](#85-prioridad-de-selección-en-contingencia).

### 10.6 Comportamiento del usuario

⚠️ **Importante**: En modo contingencia, el usuario imprime exactamente igual. No cambia nada en su forma de trabajar. La única diferencia visible es una notificación informativa.

---

## 11. Integración con Cloud Manager

### 11.1 Registro automático

Cuando el Client se instala por primera vez y no tiene configuración Cloud:

1. El Tray inicia el ciclo de **CloudRegistration**
2. Detecta la IP pública y el CIDR de la red local
3. Envía solicitud de registro al Cloud Manager
4. Si la IP no está autorizada → queda en estado "pendiente de aprobación"
5. Un administrador autoriza la IP desde Cloud Manager
6. El Client se registra exitosamente → recibe `workstation_id` y `cloud_api_url`
7. Se activa la integración Cloud completa

### 11.2 Conexión con Cloud Manager

Una vez registrado, el Tray mantiene conexión permanente con Cloud Manager:

| Funcionalidad | Descripción |
|--------------|-------------|
| **Heartbeat** | Señal periódica que indica que la workstation está activa |
| **Telemetría** | Envío de métricas de impresión (jobs procesados, tiempos) |
| **Conectividad** | Ejecución de checks de red configurados |
| **Configuración** | Sincronización de parámetros desde la nube |
| **Comandos remotos** | Recepción y ejecución de comandos del administrador |
| **Acciones** | Descarga de configuraciones de acciones administrativas |

### 11.3 Modo offline (sin conexión)

Si se pierde la conexión con Cloud Manager:

- La impresión **sigue funcionando** normalmente (offline-first)
- Se usa la última configuración guardada localmente
- Se muestra notificación "Usando configuración guardada. Sin conexión a la nube"
- Al reconectarse, se muestra "Conexión con la nube restaurada"

💡 AlwaysPrint está diseñado con principio **offline-first**: la operación de impresión nunca depende de la conectividad con Cloud Manager.

### 11.4 Sincronización de configuración

La configuración se sincroniza desde Cloud Manager según la jerarquía:

```
Organización (base) → VLAN (sobrescribe) → Workstation (máxima prioridad)
```

Parámetros sincronizados:
- Cola corporativa, intervalo de polling, locale
- Dominios bootstrap, IPs y rangos de búsqueda
- Checks de conectividad
- Configuración de telemetría

### 11.5 Recursos de VLAN

El Client descarga un archivo `resources.json` que contiene:
- Ruta de cola remota (`remote_queue_path`)
- Metadata de la VLAN (pares clave-valor personalizados)

Estos valores se usan como variables en las acciones administrativas (templates `{{variable}}`).

---

## 12. Acciones Administrativas Remotas

### 12.1 ¿Qué son?

Son tareas que se ejecutan automáticamente en la workstation ante ciertos eventos. Se definen en archivos `.alwaysconfig` (formato JSON) y se distribuyen desde Cloud Manager.

### 12.2 ¿Cómo llegan a la workstation?

1. El administrador sube un archivo `.alwaysconfig` en Cloud Manager
2. El Tray detecta que hay una nueva configuración (comparando hash SHA256)
3. Descarga el archivo y lo guarda como `active.alwaysconfig`
4. Notifica al Service vía Named Pipe (mensaje `ActionConfigChanged`)
5. El Service recarga la configuración y ejecuta el trigger `OnConfigChange`

### 12.3 Eventos disponibles (triggers)

| Evento | Cuándo se ejecuta |
|--------|-------------------|
| `OnServiceStart` | Al iniciar el servicio Windows |
| `OnTrayLaunched` | Después de que el Tray confirma inicialización |
| `OnConfigChange` | Al recibir una nueva configuración de acciones |
| `OnContingencyActivated` | Al activar el modo contingencia |
| `OnContingencyDeactivated` | Al desactivar el modo contingencia |

### 12.4 Acciones disponibles

| Acción | Función |
|--------|---------|
| **PropagatePermissions** | Propagar permisos de carpeta recursivamente |
| **GetLoggedInUsers** | Obtener usuarios con sesión activa (excluye consola) |
| **DeleteFolderContents** | Eliminar contenido de carpetas con manejo de errores |
| **StopService** | Detener un servicio Windows |
| **StartService** | Iniciar un servicio Windows |
| **KillProcessesByName** | Terminar procesos por nombre, filtrado por usuario |
| **Conditional** | Ejecutar acciones condicionalmente (if/then) |
| **StopTray** | Detener la aplicación de bandeja |
| **StartTray** | Iniciar la aplicación de bandeja |
| **CreateTcpPort** | Crear un puerto TCP de impresora |
| **SetTcpPort** | Configurar un puerto TCP existente |
| **AssignPortToQueue** | Asignar un puerto a una cola de impresión |
| **SetDefaultPrinter** | Establecer impresora predeterminada |
| **RunProcess** | Ejecutar un proceso externo |

### 12.5 Variables y templates

Las acciones soportan variables que se resuelven en tiempo de ejecución:

| Variable | Origen | Ejemplo |
|----------|--------|---------|
| `{{corporate_queue_name}}` | Configuración | LexmarkBBVA |
| `{{contingency_printer_ip}}` | Contingencia activa | 192.168.1.50 |
| `{{remote_queue_path}}` | resources.json | \\\\server\\queue |
| `{{username}}` | Iteración de usuarios | jperez |
| Variables de metadata VLAN | resources.json | Cualquier clave personalizada |

### 12.6 Jerarquía de configuración

La configuración de acciones sigue la misma jerarquía que la configuración general:

```
Organización (base) → VLAN (sobrescribe) → Workstation (máxima prioridad)
```

Si un nivel superior marca su configuración como **mandatory**, los niveles inferiores no pueden sobrescribirla.

### 12.7 Verificación de propagación

- Cada configuración tiene un hash SHA256 (8 caracteres)
- El administrador puede comparar el hash activo en Cloud Manager con el reportado por la workstation
- Si difieren, la workstation aún no descargó la última versión

---

## 13. Notificaciones y Alertas

### 13.1 Tipos de notificaciones

AlwaysPrint usa notificaciones emergentes (balloon tips) en la bandeja del sistema para informar al usuario sobre eventos relevantes.

**Notificaciones informativas (ℹ️)**

| Mensaje | Contexto |
|---------|----------|
| "Inicializado correctamente (dominio)" | Bootstrap exitoso |
| "Conectado a la nube exitosamente" | Primera conexión Cloud |
| "Conexión con la nube restaurada" | Reconexión después de caída |
| "No hay actualizaciones disponibles" | Búsqueda manual sin resultados |
| "Buscando actualizaciones..." | Búsqueda manual en progreso |
| "Configuración de red detectada correctamente" | CIDR recuperado |

**Notificaciones de advertencia (⚠️)**

| Mensaje | Contexto |
|---------|----------|
| "Operando en modo local" | Sin conectividad externa |
| "Usando configuración guardada. Sin conexión a la nube" | Offline con config local |
| "Sin conexión a la nube y sin configuración guardada" | Offline sin config previa |
| "Pendiente de aprobación" | IP no autorizada |
| "No se puede buscar actualizaciones sin conexión a la nube" | Update sin Cloud |

**Notificaciones de error (❌)**

| Mensaje | Contexto |
|---------|----------|
| "El servicio no está en ejecución" | Service detenido |
| "No se pudo detectar la configuración de red (CIDR)" | Sin interfaz con gateway |
| "No se pudo verificar actualizaciones" | Error en búsqueda de updates |

**Notificaciones de actualización**

| Mensaje | Contexto |
|---------|----------|
| "AlwaysPrint se está actualizando a la versión X" | Descarga/instalación en curso |

### 13.2 Duración de las notificaciones

Las notificaciones se muestran durante 3–5 segundos y desaparecen automáticamente. No requieren interacción del usuario.

---

## 14. Información para Soporte TI

### 14.1 Archivos y rutas

| Archivo / Ruta | Propósito |
|----------------|-----------|
| `C:\Program Files\AlwaysPrint\AlwaysPrintService.exe` | Ejecutable del Service |
| `C:\Program Files\AlwaysPrint\AlwaysPrintTray.exe` | Ejecutable del Tray |
| `C:\ProgramData\AlwaysPrint\config\active.alwaysconfig` | Configuración de acciones activa |
| `C:\ProgramData\AlwaysPrint\config\resources.json` | Recursos de VLAN (metadata, impresoras) |
| `HKLM\SOFTWARE\AlwaysPrint\` | Registro Windows (configuración persistente) |

### 14.2 Valores del registro

| Clave | Tipo | Descripción |
|-------|------|-------------|
| CorporateQueueName | REG_SZ | Nombre de la cola corporativa |
| BootstrapDomains | REG_SZ | Dominios para descubrimiento (CSV) |
| PendingTaskPollingMinutes | REG_DWORD | Intervalo de polling |
| CloudEnabled | REG_DWORD | 0=deshabilitado, 1=habilitado |
| CloudApiUrl | REG_SZ | URL del Cloud Manager |
| CloudLocale | REG_SZ | Idioma (es/en/vacío=auto) |
| WorkstationId | REG_SZ | ID asignado por Cloud Manager |
| OrganizationId | REG_SZ | ID de la organización |
| OrganizationName | REG_SZ | Nombre de la organización |

### 14.3 Logs y diagnóstico

Los logs se escriben en el **Event Viewer de Windows** (Visor de Eventos):

| Source | Ubicación | Contenido |
|--------|-----------|-----------|
| AlwaysPrintService | Application | Logs del servicio (inicio, acciones, contingencia) |
| AlwaysPrintTray | Application | Logs del Tray (Cloud, updates, UI) |

**Comandos de diagnóstico:**

```powershell
# Estado del servicio
Get-Service AlwaysPrintService

# Últimos 50 logs del servicio
Get-EventLog -LogName Application -Source AlwaysPrintService -Newest 50

# Últimos 50 logs del Tray
Get-EventLog -LogName Application -Source AlwaysPrintTray -Newest 50

# Verificar configuración de acciones activa
Test-Path "C:\ProgramData\AlwaysPrint\config\active.alwaysconfig"
Get-Content "C:\ProgramData\AlwaysPrint\config\active.alwaysconfig" | ConvertFrom-Json

# Verificar resources.json
Get-Content "C:\ProgramData\AlwaysPrint\config\resources.json" | ConvertFrom-Json

# Conectividad con Cloud Manager
Test-NetConnection alwaysprint.apps.iol.pe -Port 443

# Reiniciar servicio
Restart-Service AlwaysPrintService

# Verificar servicio LPD
Get-Service LPDSVC

# Ver versión instalada
(Get-Item "C:\Program Files\AlwaysPrint\AlwaysPrintService.exe").VersionInfo.FileVersion
```

### 14.4 Event IDs relevantes

El servicio usa Event IDs específicos para facilitar el filtrado:

| Categoría | Descripción |
|-----------|-------------|
| Service Started/Stopped | Inicio y detención del servicio |
| Tray Started/Error/Killed | Ciclo de vida del Tray |
| User Detected/Waiting | Gestión de sesiones |
| Queue Cleared | Limpieza de cola de tareas |
| Duplicate Instance | Detección de instancia duplicada |
| Generic Warning/Error | Advertencias y errores generales |

### 14.5 Root Log

Al iniciar, el Service escribe un bloque de diagnóstico con:
- Organización y workstation ID
- Entorno (DEV/PROD)
- Servidor Cloud
- Versión del software
- Hostname e IP local
- Información de acciones configuradas
- Sistema operativo y zona horaria

---

## 15. Solución de Problemas

### 15.1 Problemas de inicio

| Problema | Diagnóstico | Solución |
|----------|-------------|----------|
| El icono no aparece al iniciar sesión | El servicio puede estar iniciándose | Espere 2 minutos. Si no aparece, reinicie el equipo |
| El servicio no inicia | Event Viewer → Application → AlwaysPrintService | Verificar .NET 4.8 instalado, reinstalar MSI |
| "Instancia duplicada detectada" | Otro proceso AlwaysPrintService corriendo | Reiniciar el equipo |
| Tray no confirma inicialización (timeout 30 min) | Problema de comunicación pipe | Verificar que no hay antivirus bloqueando Named Pipes |

### 15.2 Problemas de conexión Cloud

| Problema | Diagnóstico | Solución |
|----------|-------------|----------|
| "Pendiente de aprobación" persistente | IP pública no autorizada | Admin debe autorizar en Cloud Manager → IPs Pendientes |
| "Sin conexión a la nube" | Problema de red o proxy | Verificar acceso HTTPS a `*.iol.pe` |
| "No se pudo detectar la configuración de red" | Sin interfaz con gateway activo | Verificar conexión de red física |
| Workstation no aparece en dashboard | IP no autorizada o sin conectividad | Verificar en Admin → IPs Pendientes |

### 15.3 Problemas de impresión

| Problema | Diagnóstico | Solución |
|----------|-------------|----------|
| No puedo imprimir (modo normal) | Problema con CPM, no con AlwaysPrint | Verificar servicio Lexmark CPM |
| No puedo imprimir (modo contingencia) | Sin impresora de contingencia configurada | Verificar "Mis Impresoras" tiene dispositivos |
| Contingencia no se activa | Revisar logs del Service | Verificar que hay printer_ip válida |

### 15.4 Problemas de configuración

| Problema | Diagnóstico | Solución |
|----------|-------------|----------|
| Configuración no se descarga | Logs del Tray → "ConfigManager" | Verificar conectividad, reiniciar Tray |
| Acciones no se ejecutan | Event Viewer → "ActionEngine" | Verificar `active.alwaysconfig` existe y es JSON válido |
| Configuración no se aplica desde Cloud | Hash no coincide | Esperar sincronización o reiniciar Tray |

### 15.5 Problemas de actualización

| Problema | Diagnóstico | Solución |
|----------|-------------|----------|
| "No se puede buscar actualizaciones" | Sin conexión Cloud | Verificar registro exitoso en Cloud |
| Actualización falla | Logs del Tray → "AutoUpdate" | Verificar espacio en disco, permisos |
| Versión no cambia después de update | MSI no se instaló correctamente | Verificar logs del Service → "InstallUpdate" |

---

## 16. Preguntas Frecuentes

**¿Necesito hacer algo para que AlwaysPrint funcione?**  
No. El software es completamente automático desde la instalación.

**¿Puedo seguir imprimiendo cuando aparece la notificación de contingencia?**  
Sí. La notificación solo informa que el sistema principal falló y AlwaysPrint está redirigiendo. Siga imprimiendo normalmente.

**¿AlwaysPrint reemplaza al sistema de impresión habitual?**  
No. Es un respaldo que solo se activa cuando el sistema principal (Lexmark CPM) falla.

**¿Funciona sin conexión a Internet?**  
Sí. La impresión funciona localmente (offline-first). La conexión a Internet es solo para gestión, monitoreo y actualizaciones.

**¿Consume muchos recursos de mi equipo?**  
No. El consumo es mínimo (~20-30 MB de RAM, CPU negligible).

**¿Cómo sé qué versión tengo?**  
Click derecho en el icono de bandeja → Acerca de.

**¿Puedo desinstalar AlwaysPrint?**  
Solo con autorización de TI. La desinstalación elimina la protección de contingencia.

**¿Qué hago si el icono no aparece?**  
Espere 2 minutos. Si no aparece, reinicie el equipo. Si persiste, contacte a Soporte TI.

**¿Puedo elegir a qué impresora se redirige en contingencia?**  
Sí. Desde "Mis Impresoras" puede establecer una impresora favorita que se usará como destino prioritario.

**¿Qué pasa si Cloud Manager no está disponible?**  
La impresión sigue funcionando normalmente. Cloud Manager es para gestión y monitoreo, no para la operación de impresión.

**¿Las acciones administrativas pueden afectar mi trabajo?**  
Las acciones están diseñadas para ejecutarse de forma transparente. En casos excepcionales (reinicio de servicios), puede haber una pausa breve en la impresión.

**¿Cómo sé si mi workstation tiene la última configuración?**  
El administrador puede verificar el hash de configuración desde Cloud Manager comparándolo con el reportado por su workstation.

**¿Qué es el "modo local"?**  
Significa que AlwaysPrint opera sin conexión a Cloud Manager, usando la última configuración guardada. La impresión no se ve afectada.

**¿Por qué aparece "pendiente de aprobación"?**  
Su workstation se conecta desde una IP pública que aún no ha sido autorizada por el administrador en Cloud Manager. Contacte a TI.

---

## 17. Glosario

| Término | Definición |
|---------|-----------|
| AlwaysPrint | Software de continuidad de impresión (este sistema) |
| AlwaysPrint Client | Conjunto de Service + Tray instalado en la workstation |
| Service | Proceso Windows que corre como LocalSystem, gestiona contingencia y acciones |
| Tray | Aplicación de bandeja del sistema, interfaz del usuario y comunicación Cloud |
| CPM | Cloud Print Manager (Lexmark) — sistema de impresión principal |
| Contingencia | Modo en que AlwaysPrint redirige la impresión directamente a la impresora |
| Cloud Manager | Plataforma web de gestión centralizada (AlwaysPrint Cloud Manager) |
| Named Pipe | Canal de comunicación entre el Service y el Tray |
| Bootstrap | Secuencia de inicialización que verifica conectividad |
| Heartbeat | Señal periódica que indica que la workstation está activa |
| Action Config | Archivo de configuración de acciones remotas (.alwaysconfig) |
| Trigger | Evento que dispara la ejecución de acciones administrativas |
| Hash | Identificador de versión de configuración (SHA256, 8 caracteres) |
| VLAN | Agrupación lógica de workstations por red |
| Offline-first | Principio de diseño: la operación funciona sin conectividad externa |
| Bandeja del sistema | Área de iconos en la esquina inferior derecha de Windows (junto al reloj) |
| Balloon tip | Notificación emergente que aparece junto al icono de bandeja |
| MSI | Formato de instalador de Windows (Microsoft Installer) |
| CIDR | Notación de rango de red (ej: 192.168.1.0/24) |
| Telemetría | Datos de uso de impresión enviados al Cloud Manager |

---

## 18. Soporte y Contacto

### 18.1 Soporte de primer nivel (TI interno)

Para problemas con la impresión o el icono de AlwaysPrint, contacte a su mesa de ayuda habitual.

**Información a proporcionar:**
1. Nombre del equipo (hostname)
2. Versión de AlwaysPrint (click derecho → Acerca de)
3. Descripción del problema
4. Captura de pantalla (si aplica)
5. ¿Puede imprimir o no?

### 18.2 Soporte de segundo nivel — Robles.AI

- **Email**: antonio@robles.ai
- **Teléfono**: +1 408 590 0153
- **Web**: https://robles.ai

### 18.3 Información requerida para reportar incidentes

| Dato | Cómo obtenerlo |
|------|----------------|
| Hostname | Click derecho → Acerca de |
| Versión | Click derecho → Acerca de |
| Logs del Service | `Get-EventLog -LogName Application -Source AlwaysPrintService -Newest 50` |
| Logs del Tray | `Get-EventLog -LogName Application -Source AlwaysPrintTray -Newest 50` |
| Estado del servicio | `Get-Service AlwaysPrintService` |
| Conectividad | `Test-NetConnection alwaysprint.apps.iol.pe -Port 443` |
| Config de acciones | `Get-Content "C:\ProgramData\AlwaysPrint\config\active.alwaysconfig"` |

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados  
Producto de la familia de automatización Robles.AI  
Prohibida la utilización sin autorización de Inversiones On Line SAC
