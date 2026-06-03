---
título: Manual de Usuario — AlwaysPrint Cloud Manager
versión: 1.0.0
fecha: Mayo 2026
producto: AlwaysPrint Cloud Manager (Web)
empresa: Inversiones On Line SAC — Robles.AI
clasificación: Confidencial — Uso interno
---

# Manual de Usuario — AlwaysPrint Cloud Manager

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

1. [¿Qué es AlwaysPrint Cloud Manager?](#1-qué-es-alwaysprint-cloud-manager)
2. [Acceso al sistema](#2-acceso-al-sistema)
3. [Inicio rápido](#3-inicio-rápido)
4. [Navegación del dashboard](#4-navegación-del-dashboard)
5. [Monitoreo diario](#5-monitoreo-diario)
6. [Gestión de workstations](#6-gestión-de-workstations)
7. [Gestión de redes y dispositivos](#7-gestión-de-redes-y-dispositivos)
8. [Configuración centralizada](#8-configuración-centralizada)
9. [Acciones administrativas remotas](#9-acciones-administrativas-remotas)
10. [Contingencia de impresión](#10-contingencia-de-impresión)
11. [Documentación](#11-documentación)
12. [Administración avanzada](#12-administración-avanzada)
13. [Seguridad y roles](#13-seguridad-y-roles)
14. [Solución de problemas](#14-solución-de-problemas)
15. [Preguntas frecuentes](#15-preguntas-frecuentes)
16. [Glosario](#16-glosario)
17. [Soporte y contacto](#17-soporte-y-contacto)

---

## Convenciones del Documento

| Icono | Significado |
|-------|-------------|
| ℹ️ | Información adicional |
| ⚠️ | Advertencia — requiere atención |
| ✅ | Acción completada o confirmación |
| 💡 | Consejo o buena práctica |

---

## 1. ¿Qué es AlwaysPrint Cloud Manager?

AlwaysPrint Cloud Manager es la **plataforma web de gestión centralizada** para el sistema de contingencia de impresión AlwaysPrint. Permite a los administradores de TI:

- Monitorear en tiempo real el estado de todas las workstations
- Configurar parámetros de impresión de forma centralizada
- Gestionar contingencias (activar/desactivar redirección de impresión)
- Ejecutar acciones administrativas remotas en las estaciones
- Analizar telemetría y logs de impresión
- Administrar organizaciones, usuarios y dispositivos

**Acceso**: https://alwaysprint.apps.iol.pe

**Requisitos**: Navegador moderno (Chrome, Edge, Firefox o Safari, versión 90+).

---

## 2. Acceso al sistema

### 2.1 Iniciar sesión

1. Abrir https://alwaysprint.apps.iol.pe/login
2. Ingresar email y contraseña
3. Click en "Iniciar sesión"

### 2.2 Recuperar contraseña

1. En la página de login, click en "¿Olvidaste tu contraseña?"
2. Ingresar el email registrado
3. Revisar la bandeja de entrada (se envía un enlace de recuperación)
4. El enlace es válido por 1 hora
5. Establecer la nueva contraseña

### 2.3 Roles de usuario

| Rol | Qué puede hacer |
|-----|-----------------|
| **Administrador Global** | Acceso completo: configuración, organizaciones, usuarios, acciones remotas |
| **Operador TI** | Monitoreo, workstations, VLANs, dispositivos, comandos remotos dentro de su organización |

---

## 3. Inicio rápido

### 3.1 Primera vez (Setup inicial)

Si es la primera vez que se accede al sistema y no hay usuarios creados:

1. Navegar a https://alwaysprint.apps.iol.pe/setup
2. Crear el primer usuario administrador (email + contraseña)
3. Asignar nombre a la organización
4. El sistema redirige al login

### 3.2 Autorizar la primera workstation

Una vez instalado AlwaysPrint Client en un equipo:

1. La workstation intenta conectarse → su IP pública queda como "pendiente"
2. En el dashboard: ir a **Administración → IPs Pendientes**
3. Localizar la IP nueva y asignarla a la organización
4. La workstation se conecta automáticamente en minutos

### 3.3 Flujo resumido

```
Setup → Login → Autorizar IPs → Workstations visibles → Configurar → Monitorear
```

---

## 4. Navegación del dashboard

### 4.1 Estructura de la interfaz

```
┌─────────────────────────────────────────────────────────────┐
│  BARRA SUPERIOR                                              │
│  Logo | Organización | Idioma (ES/EN) | Usuario ▼           │
├──────────────┬──────────────────────────────────────────────┤
│  MENÚ        │  CONTENIDO PRINCIPAL                         │
│  LATERAL     │                                               │
│              │  (varía según la sección seleccionada)        │
│  Operación   │                                               │
│  ──────────  │                                               │
│  Dashboard   │                                               │
│  Workstations│                                               │
│  VLANs       │                                               │
│  Dispositivos│                                               │
│  Configuración│                                              │
│  Mensajes    │                                               │
│  Telemetría  │                                               │
│  Conectividad│                                               │
│  Auditoría   │                                               │
│  Documentación│                                              │
│              │                                               │
│  Admin       │                                               │
│  ──────────  │                                               │
│  Organizaciones│                                             │
│  Usuarios    │                                               │
│  IPs Pendientes│                                             │
│  Action Configs│                                             │
│  Actualizaciones│                                            │
└──────────────┴──────────────────────────────────────────────┘
```

### 4.2 Secciones de administración

| Sección | Función |
|---------|---------|
| **Dashboard** | Resumen general: estadísticas, alertas, estado global |
| **Organizaciones** | Crear y gestionar organizaciones (solo Admin) |
| **VLANs** | Agrupaciones de red (por piso, sede, etc.) |
| **Workstations** | Lista de equipos, estado, comandos remotos |
| **IPs Pendientes** | Autorizar IPs públicas de workstations nuevas (solo Admin) |
| **Dispositivos** | Impresoras registradas y su estado |

### 4.3 Secciones de monitoreo y operaciones

| Sección | Función |
|---------|---------|
| **Telemetría** | Métricas de impresión y uso de las workstations |
| **Conectividad** | Resultados de las verificaciones de red ejecutadas por las workstations |
| **Auditoría** | Registro histórico de todas las acciones realizadas en la plataforma |
| **Mensajes** | Envío de notificaciones a workstations |
| **Documentación** | Repositorio de documentos PDF para consulta y descarga |

### 4.4 Secciones de sistema (solo Administrador Global)

| Sección | Función |
|---------|---------|
| **Usuarios** | Crear y gestionar cuentas de administradores y operadores |
| **Actualizaciones** | Gestionar versiones del cliente Windows |
| **Configuración** | Parámetros globales de la organización |

### 4.4 Elementos comunes de la interfaz

- **Vista dual**: Todas las listas ofrecen vista de tarjetas y vista de tabla
- **Filtros**: Búsqueda por texto, filtros por estado, organización, VLAN
- **Paginación**: Controles "Anterior / Siguiente" con indicador de registros
- **Actualización automática**: Los datos se refrescan cada 10 segundos

---

## 5. Monitoreo diario

### 5.1 Dashboard principal

Al ingresar, el dashboard muestra:

| Elemento | Información |
|----------|-------------|
| Total workstations | Cantidad de equipos registrados |
| Online | Equipos conectados y reportando |
| Offline | Equipos sin comunicación |
| En contingencia | Equipos con redirección activa |
| IPs pendientes | Equipos nuevos que requieren autorización |

💡 **Rutina diaria recomendada**: Verificar que no hay workstations offline inesperadas ni contingencias activas sin justificación.

### 5.2 Indicadores de estado

| Indicador | Color | Significado |
|-----------|-------|-------------|
| 🟢 Verde | Online | Equipo conectado y operando normalmente |
| 🔴 Rojo | Offline | Sin comunicación con el equipo |
| 🟡 Amarillo | Contingencia | Impresión redirigida (CPM con falla) |
| ⚪ Gris | Pendiente | IP no autorizada aún |

### 5.3 Auditoría

La sección **Auditoría** registra todas las acciones realizadas en la plataforma:
- Quién realizó la acción
- Qué acción se ejecutó
- Cuándo ocurrió
- Desde qué IP

💡 Revisar la auditoría semanalmente como buena práctica de seguridad.

### 5.4 Telemetría

La sección **Telemetría** muestra métricas de uso de impresión reportadas por las workstations:
- Cantidad de trabajos de impresión procesados
- Estado de las colas de impresión
- Historial de eventos por workstation
- Tendencias de uso por período

Los datos se recopilan automáticamente según el intervalo configurado en la organización.

### 5.5 Conectividad

La sección **Conectividad** muestra los resultados de las verificaciones de red que ejecutan las workstations:
- Estado de cada check configurado (HTTP, TCP, Ping, DNS)
- Última vez que se ejecutó cada verificación
- Historial de fallos de conectividad

Estos resultados permiten identificar problemas de red que podrían afectar la impresión o la comunicación con el Cloud Manager.

---

## 6. Gestión de workstations

### 6.1 Ver workstations

1. Ir a **Workstations** en el menú lateral
2. Usar filtros para buscar por IP, hostname o estado
3. Seleccionar una workstation para ver su detalle

### 6.2 Información de cada workstation

| Campo | Descripción |
|-------|-------------|
| IP privada | Dirección en la red interna |
| Hostname | Nombre del equipo Windows |
| Estado | Online / Offline |
| Contingencia | Activa / Inactiva |
| Versión | Versión del software instalado |
| VLAN | Red asignada |
| Última conexión | Cuándo se comunicó por última vez |
| Usuario actual | Quién tiene sesión activa |

### 6.3 Comandos remotos

Desde el detalle de una workstation, se pueden ejecutar:

| Comando | Efecto |
|---------|--------|
| **Reiniciar servicio** | Reinicia AlwaysPrintService en el equipo |
| **Reiniciar Tray** | Reinicia la aplicación de bandeja |
| **Verificar actualización** | Fuerza la búsqueda de nueva versión |
| **Forzar contingencia** | Activa la redirección de impresión manualmente |
| **Descargar logs** | Obtiene los logs del equipo remotamente |
| **Analizar logs (IA)** | Envía los logs a un modelo de IA para diagnóstico |

### 6.4 Análisis de logs con IA

1. Ir a la workstation deseada
2. Click en "Analizar con IA"
3. El sistema envía los logs al modelo configurado
4. Se recibe un análisis con problemas detectados, causas probables y recomendaciones

ℹ️ Soporta AWS Bedrock y OpenAI. El modelo se configura por organización.

---

## 7. Gestión de redes y dispositivos

### 7.1 VLANs

Las VLANs permiten agrupar workstations por red (piso, sede, segmento). Son necesarias para organizar los equipos y aplicar configuraciones diferenciadas.

**¿Cuándo se crea una VLAN?**

Al autorizar una IP nueva desde **Administración → IPs Pendientes**, el sistema crea automáticamente la VLAN correspondiente si no existe. No es necesario crearla manualmente de antemano.

**Flujo:**
1. Autorizar la IP de la workstation → el sistema crea la VLAN automáticamente (si no existe)
2. La workstation se asigna a la VLAN según su CIDR

**Crear una VLAN:**
1. Ir a **VLANs** → "Crear VLAN"
2. Asignar nombre descriptivo (ej: "Piso 3 — Sede Central")
3. Definir CIDR de la red (ej: 192.168.3.0/24)
4. Guardar

Una vez creada, las workstations cuya IP privada pertenezca a ese rango se asignan automáticamente a la VLAN.

**Utilidad**: Permite aplicar configuración específica por red, visualizar el estado agrupado por ubicación y asignar impresoras de contingencia por zona.

### 7.2 Dispositivos (Impresoras)

Los dispositivos registrados en esta sección son las **impresoras físicas que se utilizan como destino en modo contingencia**. Cuando AlwaysPrint detecta una falla en CPM y activa la redirección, envía los trabajos de impresión directamente a la IP de estas impresoras.

**¿Para qué sirve registrar una impresora?**

Definir la IP y puerto de destino al que se redirigirá la impresión cuando el sistema principal falle. Sin un dispositivo registrado y asignado, la workstation no sabría a dónde enviar los trabajos en contingencia.

**Registrar una impresora:**
1. Ir a **Dispositivos** → "Crear dispositivo"
2. Completar:
   - **Nombre**: Identificador descriptivo (ej: "Impresora Piso 3 — d1")
   - **IP**: Dirección IP de la impresora en la red interna
   - **Puerto**: Puerto de impresión  
   - **VLAN**: Red a la que pertenece la impresora
3. Guardar

**Asignar impresora a workstations:**

Las workstations de una VLAN utilizan los dispositivos registrados en esa misma VLAN como destino de contingencia. Al registrar una impresora y asociarla a una VLAN, todas las workstations de esa red la tendrán disponible como destino de redirección.

💡 Asegúrese de que la IP de la impresora sea accesible desde las workstations de la VLAN.

---

## 8. Configuración centralizada

### 8.1 Jerarquía de configuración

La configuración se aplica en cascada con la siguiente prioridad:

```
Workstation (máxima prioridad)
    ↑ sobrescribe
VLAN
    ↑ sobrescribe
Organización (configuración base)
```

Si una workstation tiene configuración propia, esta prevalece sobre la de su VLAN y la de la organización.

⚠️ **Excepción — Configuración obligatoria (mandatory):** Si la opción "mandatory" está activada a nivel de organización o de VLAN, la configuración de ese nivel se impone y no puede ser sobrescrita por niveles inferiores. Es decir:
- Si la organización marca su configuración como mandatory → ni la VLAN ni la workstation pueden sobrescribirla.
- Si una VLAN marca su configuración como mandatory → las workstations de esa VLAN no pueden sobrescribirla.

### 8.2 Configuración de organización

Accesible desde **Configuración** en el menú lateral. Aplica a todas las workstations de la organización. La configuración se organiza en pestañas:

**Pestaña General**

Datos básicos de identidad y preferencias globales de la organización.

| Parámetro | Descripción |
|-----------|-------------|
| Nombre | Nombre de la organización |
| Descripción | Referencia interna o nota descriptiva |
| Zona horaria | Zona horaria para mostrar fechas correctamente |
| Idioma por defecto | Idioma inicial para nuevos usuarios (Español / English) |
| Organización activa | Habilitar o deshabilitar la organización |
| Modelo LLM para análisis de logs | Proveedor y modelo de IA para análisis inteligente de logs |
| API Key de OpenAI (opcional) | Si se configura, se usa OpenAI en lugar de AWS Bedrock para análisis |

**Pestaña Impresión**

Parámetros que controlan el comportamiento de impresión y la comunicación con las colas corporativas.

| Parámetro | Descripción |
|-----------|-------------|
| Cola corporativa | Nombre de la cola de impresión principal (ej: LexmarkBBVA) |
| Intervalo de polling | Frecuencia con la que las workstations consultan tareas pendientes (1–1440 minutos) |
| Locale | Configuración regional para formato de fechas y números |

**Pestaña Red**

Configuración de red para el descubrimiento del Cloud Manager y la detección de impresoras físicas en la infraestructura.

| Parámetro | Descripción |
|-----------|-------------|
| Dominios de bootstrap | Dominios para descubrimiento del Cloud Manager (ej: apps.iol.pe) |
| IPs de impresoras | Lista de IPs individuales de impresoras a detectar en la red |
| Rangos de búsqueda | Rangos CIDR para escaneo de impresoras (ej: 192.168.1.0/24) |

**Pestaña Conectividad**

Define las verificaciones de red que cada workstation ejecuta periódicamente para reportar el estado de conectividad al Cloud Manager.

| Parámetro | Descripción |
|-----------|-------------|
| Checks de conectividad | Lista de verificaciones de red que las workstations ejecutan periódicamente (hasta 50). Cada check define: ID, tipo (HTTP/TCP/Ping/DNS), destino y timeout |

Tipos de check disponibles:
| Tipo | Campos requeridos | Ejemplo |
|------|-------------------|---------|
| HTTP | URL | https://api.ejemplo.com/health |
| TCP | Host + Puerto (1–65535) | 192.168.1.1:443 |
| Ping | Host | 192.168.1.1 |
| DNS | Hostname | api.ejemplo.com |

**Pestaña Actualizaciones**

Controla cómo y cuándo las workstations reciben nuevas versiones del cliente AlwaysPrint.

| Parámetro | Descripción |
|-----------|-------------|
| Actualización automática | Permitir que las workstations se actualicen automáticamente |
| Versión fijada | Fijar una versión específica del cliente (si no se fija, se usa la última disponible) |
| Re-registro automático | Permitir que las workstations se re-registren automáticamente si pierden conexión |

**Pestaña Acciones**

Gestión de las configuraciones de acciones administrativas remotas que se ejecutan automáticamente en las workstations.

| Parámetro | Descripción |
|-----------|-------------|
| Configuración obligatoria (mandatory) | Si se activa, la configuración de acciones de la organización se impone a todas las workstations sin posibilidad de sobrescritura |
| Configuraciones de acciones | Lista de archivos `.alwaysconfig` subidos. Se pueden activar, desactivar, ver detalle, descargar o eliminar |

**Pestaña IPs Públicas**

Administración de las IPs públicas desde las cuales las workstations de esta organización se conectan al Cloud Manager.

| Parámetro | Descripción |
|-----------|-------------|
| Agregar IP | Registrar una nueva IP pública autorizada (formato IPv4) con descripción opcional |
| IPs registradas | Lista de IPs públicas asignadas a esta organización, con opción de eliminar |

### 8.3 Configuración por VLAN

Accesible desde **VLANs → [seleccionar] → Editar**. Permite ajustar datos y configuración específica de una VLAN.

**Datos de la VLAN**

| Parámetro | Descripción |
|-----------|-------------|
| Nombre | Nombre descriptivo de la VLAN (ej: "Piso 3 — Sede Central") |
| Descripción | Nota adicional o referencia interna |
| Rangos CIDR | Lista de rangos de red que definen la VLAN (ej: 192.168.3.0/24). Se pueden agregar múltiples rangos |
| Impresora predeterminada | Dispositivo de impresión por defecto para las workstations de esta VLAN en modo contingencia |
| Metadata | Pares clave-valor personalizados para información adicional de la VLAN |

ℹ️ Las workstations se asignan automáticamente a la VLAN cuyo rango CIDR coincida con su IP privada reportada.

**Sección Configuración de Acciones**

Permite gestionar acciones administrativas específicas para todas las workstations de esta VLAN (expandible).

| Parámetro | Descripción |
|-----------|-------------|
| Subir configuración | Subir un archivo `.alwaysconfig` específico para esta VLAN |
| Configuración obligatoria (mandatory) | Si se activa, esta configuración se impone a todas las workstations de la VLAN sin posibilidad de sobrescritura a nivel de workstation |
| Configuraciones de acciones | Lista de archivos subidos con opciones de activar, desactivar, ver o eliminar |

⚠️ Si la organización tiene su configuración marcada como obligatoria (mandatory), la configuración a nivel de VLAN no será aplicable. El sistema muestra un aviso indicando que el nivel superior está bloqueando.

### 8.4 Configuración por workstation

Accesible desde **Workstations → [seleccionar] → Editar**. Permite ajustar datos específicos de una workstation individual.

**Datos de la workstation**

| Parámetro | Descripción |
|-----------|-------------|
| Hostname | Nombre del equipo Windows (informativo) |
| OS Serial | Número de serie del sistema operativo (informativo) |
| Usuario actual | Usuario con sesión activa en el equipo (informativo) |
| Organización | Organización a la que pertenece la workstation (selector) |
| Impresora favorita | Impresora preferida por el usuario para contingencia. Si se selecciona, se usa como destino prioritario al redirigir impresión |

ℹ️ La asignación de organización también se realiza automáticamente cuando la workstation se conecta desde una IP pública registrada.

**Sección Configuración de Acciones**

Permite gestionar acciones administrativas específicas para esta workstation (expandible).

| Parámetro | Descripción |
|-----------|-------------|
| Subir configuración | Subir un archivo `.alwaysconfig` específico para esta workstation |
| Configuración obligatoria (mandatory) | Si se activa, esta configuración se aplica sin posibilidad de sobrescritura |
| Configuraciones de acciones | Lista de archivos subidos con opciones de activar, desactivar, ver o eliminar |

⚠️ Si la organización o la VLAN tienen su configuración marcada como obligatoria (mandatory), la configuración a nivel de workstation no será aplicable. El sistema muestra un aviso indicando qué nivel superior está bloqueando.

---

## 9. Acciones administrativas remotas

### 9.1 ¿Qué son?

Son tareas que se ejecutan automáticamente en las workstations ante ciertos eventos (inicio de servicio, cambio de configuración, activación de contingencia, etc.). Se definen en archivos `.alwaysconfig` (formato JSON) y se distribuyen desde el Cloud Manager.

### 9.2 Flujo de trabajo

1. Subir el archivo JSON en la sección de acciones (a nivel de organización, VLAN o workstation)
2. El sistema valida la estructura automáticamente
3. Activar la configuración (solo una puede estar activa por nivel)
4. Las workstations descargan la nueva configuración automáticamente
5. El servicio ejecuta las acciones según los eventos definidos

Las acciones se pueden configurar en tres niveles:

| Nivel | Dónde se configura | Aplica a |
|-------|-------------------|----------|
| Organización | Pestaña Acciones en configuración de organización | Todas las workstations de la organización |
| VLAN | Sección Acciones en edición de VLAN | Todas las workstations de esa VLAN |
| Workstation | Sección Acciones en edición de workstation | Solo esa workstation |

### 9.3 Eventos disponibles (triggers)

| Evento | Cuándo se ejecuta |
|--------|-------------------|
| OnServiceStart | Al iniciar el servicio Windows |
| OnTrayLaunched | Después de que la aplicación de bandeja se conecta |
| OnConfigChange | Al recibir una nueva configuración |
| OnContingencyActivated | Al activar el modo contingencia |
| OnContingencyDeactivated | Al desactivar el modo contingencia |

### 9.4 Acciones disponibles

| Acción | Función |
|--------|---------|
| PropagatePermissions | Propagar permisos de carpeta recursivamente |
| GetLoggedInUsers | Obtener usuarios con sesión activa |
| DeleteFolderContents | Eliminar contenido de carpetas |
| StopService / StartService | Detener o iniciar un servicio Windows |
| KillProcessesByName | Terminar procesos por nombre |
| Conditional | Ejecutar acciones condicionalmente (if/then) |
| StopTray / StartTray | Gestionar la aplicación de bandeja |
| CreateTcpPort / SetTcpPort | Crear o configurar puertos TCP de impresora |
| AssignPortToQueue | Asignar un puerto a una cola de impresión |
| SetDefaultPrinter | Establecer impresora predeterminada |
| RunProcess | Ejecutar un proceso externo |

### 9.5 Verificación de propagación

- Cada configuración tiene un hash SHA256 (8 caracteres) que la identifica
- En el dashboard se puede comparar el hash activo con el que reporta cada workstation
- Si difieren, la workstation aún no descargó la última versión

---

## 10. Contingencia de impresión

### 10.1 ¿Qué es la contingencia?

Cuando el sistema de impresión principal (Lexmark CPM) falla, AlwaysPrint redirige automáticamente el tráfico de impresión directamente a las impresoras físicas, sin pasar por el servidor intermedio.

### 10.2 Contingencia automática

⏳ **Próximamente** — Esta funcionalidad se encuentra en desarrollo.

- Se activará cuando el servicio en la workstation detecte que CPM no responde
- No requerirá intervención del administrador
- Se desactivará automáticamente cuando CPM se recupere
- El dashboard mostrará las workstations afectadas en amarillo

### 10.3 Contingencia forzada

Un administrador puede forzar la contingencia manualmente. Útil para:
- Mantenimiento programado de CPM
- Pruebas del sistema de contingencia
- Degradación de CPM no detectada automáticamente

**A nivel de organización** (todas las workstations):
1. Ir a **Administración → Organizaciones → [editar]**
2. Activar "Contingencia forzada"

**A nivel de VLAN** (todas las workstations de esa red):
1. Ir a **VLANs → [seleccionar] → Editar**
2. Activar "Contingencia forzada"

**A nivel de workstation individual**:
1. Ir a **Workstations → [seleccionar]**
2. Click en "Forzar contingencia"

⚠️ La contingencia forzada hace bypass del sistema de producción. Usar solo cuando sea necesario y documentar el motivo.

---

## 11. Documentación

### 11.1 ¿Qué es?

La sección **Documentación** es un repositorio centralizado de documentos PDF accesible desde el menú lateral del dashboard. Permite a los administradores compartir manuales, guías, procedimientos y cualquier documentación relevante con los operadores de TI de la organización.

### 11.2 Permisos por rol

| Acción | Admin Global | Operador TI |
|--------|:-----------:|:----------:|
| Ver listado de documentos | ✅ | ✅ |
| Descargar documentos (PDF) | ✅ | ✅ |
| Buscar documentos | ✅ | ✅ |
| Subir nuevos documentos | ✅ | — |
| Editar título y descripción | ✅ | — |
| Eliminar documentos | ✅ | — |

### 11.3 Ver documentos

1. Ir a **Documentación** en el menú lateral
2. Se muestra el listado de documentos disponibles
3. Usar la barra de búsqueda para filtrar por título o descripción
4. Alternar entre vista de tarjetas y vista de tabla con los botones de la esquina superior derecha

Cada documento muestra:
- **Título** — nombre descriptivo del documento
- **Descripción** — resumen opcional del contenido
- **Tamaño** — peso del archivo PDF
- **Fecha de creación** — cuándo se subió
- **Autor** — quién subió el documento

### 11.4 Descargar un documento

1. Localizar el documento en el listado
2. Click en el botón de descarga (ícono ⬇)
3. El archivo PDF se abre o descarga según la configuración del navegador

### 11.5 Subir un nuevo documento (solo Admin)

1. Click en **"Crear documento"** (botón superior derecho)
2. Completar el formulario:
   - **Título** (obligatorio): nombre descriptivo del documento
   - **Descripción** (opcional): breve resumen del contenido
   - **Archivo** (obligatorio): seleccionar un archivo PDF
3. Click en **"Crear documento"** para subir

ℹ️ Solo se aceptan archivos en formato PDF.

### 11.6 Editar un documento (solo Admin)

1. Localizar el documento en el listado
2. Click en el botón de edición (ícono lápiz ✏️)
3. Modificar el título o la descripción
4. Click en **"Guardar"**

⚠️ La edición solo permite cambiar título y descripción. Para reemplazar el archivo PDF, eliminar el documento y subir uno nuevo.

### 11.7 Eliminar un documento (solo Admin)

1. Localizar el documento en el listado
2. Click en el botón de eliminar (ícono 🗑️)
3. Confirmar la eliminación en el diálogo

⚠️ Esta acción es irreversible. El archivo se elimina permanentemente del sistema.

### 11.8 Casos de uso típicos

- Compartir manuales de procedimientos de impresión
- Distribuir guías de configuración de workstations
- Publicar documentación de troubleshooting para operadores
- Almacenar políticas y normativas de TI

---

## 12. Administración avanzada

### 12.1 Gestión de organizaciones

Para entornos multi-organización:

1. Ir a **Administración → Organizaciones**
2. Crear organización: nombre, zona horaria, idioma
3. Configurar parámetros: auto-actualización, versión objetivo, modelo de IA

Cada organización tiene aislamiento completo: sus workstations, usuarios, configuración y datos son independientes.

### 12.2 Gestión de usuarios

1. Ir a **Sistema → Usuarios**
2. Crear usuario: email, rol, contraseña temporal
3. El usuario puede acceder al dashboard inmediatamente

| Rol | Permisos |
|-----|----------|
| Administrador Global | Acceso completo + gestión de organizaciones y usuarios |
| Operador TI | Monitoreo, workstations, VLANs, dispositivos y comandos remotos |

### 12.3 Autorización de IPs

Las workstations se identifican ante el Cloud Manager por su IP pública. Cuando una workstation nueva intenta conectarse por primera vez, su IP queda en estado "pendiente" hasta que un administrador la autorice.

**Flujo:**
1. La workstation intenta conectarse → su IP pública queda como "pendiente"
2. Ir a **Administración → IPs Pendientes**
3. Verificar el origen de la IP (confirmar que corresponde a una sede o red conocida)
4. Asignarla a la organización correspondiente
5. La workstation se conecta automáticamente y se crea la VLAN si no existe

⚠️ No autorizar IPs desconocidas sin verificar su origen. Una IP autorizada incorrectamente podría dar acceso a equipos no corporativos.

### 12.4 Gestión de actualizaciones

Permite controlar qué versión del cliente AlwaysPrint se instala en las workstations. Las actualizaciones se distribuyen de forma silenciosa sin intervención del usuario final.

**Configuración:**
1. Ir a **Administración → Organizaciones → [editar] → Pestaña Actualizaciones**
2. Activar "Actualización automática" para permitir que las workstations se actualicen
3. Opcionalmente, fijar una versión específica (si no se fija, se usa la última disponible)

**Consultar versiones disponibles:**
1. Ir a **Sistema → Actualizaciones**
2. Ver la lista de versiones publicadas con fecha y notas

💡 Se recomienda fijar una versión específica en entornos de producción para evitar actualizaciones no planificadas. Una vez validada la nueva versión en un grupo piloto, actualizar la versión fijada para el resto.

### 12.5 Envío de mensajes

Permite enviar notificaciones directamente a los usuarios finales en sus workstations. El mensaje aparece como una notificación emergente (balloon tip) en la bandeja del sistema.

**Casos de uso:**
- Avisar sobre mantenimientos programados
- Informar sobre cambios en el sistema de impresión
- Comunicar instrucciones específicas a un grupo de usuarios

**Enviar un mensaje:**
1. Ir a **Mensajes** → "Crear mensaje"
2. Escribir el contenido del mensaje
3. Seleccionar destino:
   - **Todas las workstations** — broadcast a toda la organización
   - **Una VLAN** — solo las workstations de esa red
   - **Una workstation específica** — solo ese equipo
4. Enviar

ℹ️ Si la workstation está offline al momento del envío, el mensaje se almacena y se entrega cuando se reconecte.

---

## 13. Seguridad y roles

### 13.1 Autenticación

| Método | Aplica a |
|--------|----------|
| Email + contraseña (JWT) | Administradores del dashboard |
| IP pública autorizada | Workstations (sin credenciales de usuario) |

### 13.2 Permisos por rol

| Acción | Admin Global | Operador TI |
|--------|:-----------:|:----------:|
| Ver dashboard y workstations | ✅ | ✅ |
| Enviar comandos remotos | ✅ | ✅ |
| Forzar contingencia | ✅ | ✅ |
| Gestionar VLANs y dispositivos | ✅ | ✅ |
| Ver auditoría | ✅ | ✅ |
| Modificar configuración | ✅ | — |
| Gestionar usuarios | ✅ | — |
| Autorizar IPs | ✅ | — |
| Gestionar action configs | ✅ | — |
| Gestionar documentación (subir/editar/eliminar) | ✅ | — |
| Ver y descargar documentación | ✅ | ✅ |
| Gestionar organizaciones | ✅ | — |

### 13.3 Seguridad de la plataforma

| Capa | Protección |
|------|-----------|
| Comunicación | TLS 1.3 (cifrado en tránsito) |
| Contraseñas | Almacenadas con bcrypt (hash irreversible) |
| Infraestructura | Base de datos en red privada, sin acceso público |
| Auditoría | Registro de todas las acciones administrativas |
| Sesiones | Tokens JWT con expiración automática |

### 13.4 Buenas prácticas

- 💡 Usar contraseñas de al menos 12 caracteres
- 💡 No compartir credenciales entre usuarios
- 💡 Revisar IPs pendientes diariamente
- 💡 Revisar la auditoría semanalmente
- 💡 Desactivar usuarios que ya no requieren acceso

---

## 14. Solución de problemas

### 14.1 Problemas de acceso al dashboard

| Problema | Solución |
|----------|----------|
| No puedo iniciar sesión | Usar "Olvidé mi contraseña" para restablecer |
| Sesión expirada | Volver a iniciar sesión |
| Página en blanco | Limpiar caché del navegador y recargar |
| Error 502 (Bad Gateway) | El backend no responde. Contactar a Robles.AI |

### 14.2 Problemas con workstations

| Problema | Solución |
|----------|----------|
| Workstation no aparece en el dashboard | Verificar en **Administración → IPs Pendientes** si la IP está sin autorizar |
| Workstation aparece como offline | Verificar red del equipo. Intentar "Reiniciar Tray" remotamente |
| Configuración no se aplica | Verificar que el JSON es válido. Esperar a que la workstation se reconecte |
| Contingencia no se activa | Revisar logs del servicio en la workstation (Event Viewer) |

### 14.3 Comandos de diagnóstico (DevOps)

```bash
# Acceso al servidor (sin SSH, vía AWS SSM)
aws ssm start-session --target <INSTANCE_ID> --profile <PROFILE>

# Ver logs del backend
docker logs alwaysprint-backend-1 --tail 100

# Ver logs del frontend
docker logs alwaysprint-frontend-1 --tail 100

# Verificar estado de containers
docker compose ps

# Health check
curl https://alwaysprint.apps.iol.pe/api/v1/health
```

---

## 15. Preguntas frecuentes

**¿Cuántas workstations puedo gestionar?**  
No hay límite definido. El sistema soporta 500+ workstations por organización.

**¿Los datos se actualizan en tiempo real?**  
Sí. Si la conexión en tiempo real se pierde, el dashboard consulta cada 10 segundos automáticamente.

**¿Qué pasa si autorizo una IP incorrecta?**  
Puede revocar la autorización en cualquier momento desde Administración → Organizaciones.

**¿Los mensajes llegan a workstations offline?**  
Se almacenan y se entregan cuando la workstation se reconecta.

**¿El sistema funciona si Cloud Manager está caído?**  
Sí. Las workstations funcionan de forma autónoma. Cloud Manager es para gestión y monitoreo, no para la operación de impresión.

**¿Cómo sé si una workstation tiene la última configuración?**  
Comparar el hash de configuración en el dashboard con el hash reportado por la workstation.

**¿Puedo revertir una configuración de acciones?**  
Sí. Desactivar la configuración actual y activar la anterior. Las workstations descargarán la versión activa.

**¿Puedo gestionar múltiples organizaciones?**  
Sí, si su usuario tiene rol de Administrador Global con acceso multi-organización.

---

## 16. Glosario

| Término | Definición |
|---------|-----------|
| Cloud Manager | Plataforma web de gestión centralizada (este sistema) |
| Workstation | Equipo Windows con AlwaysPrint Client instalado |
| Organización | Entidad que agrupa workstations, usuarios y configuración |
| VLAN | Agrupación lógica de workstations por red |
| Contingencia | Modo en que la impresión se redirige directamente a la impresora |
| CPM | Cloud Print Manager (Lexmark) — sistema de impresión principal |
| Action Config | Archivo de configuración de acciones remotas (.alwaysconfig) |
| Scope | Nivel de aplicación: organización, VLAN o workstation |
| Heartbeat | Señal periódica que indica que una workstation está activa |
| Telemetría | Datos de uso enviados por las workstations |
| Hash | Identificador de versión de configuración (SHA256, 8 caracteres) |
| IP pública | Dirección desde la cual las workstations se conectan a Internet |

---

## 17. Soporte y contacto

### Soporte de primer nivel (Administrador de la organización)

- Verificar estado de workstations en el dashboard
- Autorizar IPs pendientes
- Reiniciar servicios remotamente
- Revisar logs y auditoría

### Soporte de segundo nivel (Robles.AI)

- **Email**: antonio@robles.ai
- **Teléfono**: +1 408 590 0153
- **Web**: https://robles.ai

### Al reportar un problema, incluya:

1. URL donde ocurre el error
2. Captura de pantalla
3. Navegador utilizado
4. Hora del incidente
5. Acciones realizadas antes del error

---



© 2026 Inversiones On Line SAC - Todos los derechos reservados
