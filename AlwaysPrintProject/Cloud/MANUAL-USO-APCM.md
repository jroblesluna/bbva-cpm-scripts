# APCM — Manual de Uso
### AlwaysPrint Cloud Manager

> Panel web de administración para monitorear y gestionar todas las workstations AlwaysPrint en tiempo real.

---

## Roles de usuario

Hay tres niveles de acceso. Todo lo que un rol puede hacer, los roles superiores también pueden.

| Rol | Puede hacer |
|-----|------------|
| **Admin** | Todo: gestionar cuentas, usuarios, configuración global, IPs |
| **Operator** | Ver y gestionar workstations, enviar mensajes, ver telemetría y auditoría |
| **ReadOnly** | Solo visualizar. No puede modificar nada |

---

## Primeros pasos — Setup inicial

Si el sistema nunca se ha inicializado, al entrar a APCM verás la pantalla de **Setup**.

1. Abre `/setup` en el navegador
2. Completa los datos del primer administrador (nombre, email, contraseña)
3. Al confirmar, el sistema queda listo y te redirige al login

> Esto solo ocurre una vez. Una vez configurado, `/setup` queda deshabilitado.

---

## Login y recuperación de contraseña

### Iniciar sesión
1. Ve a `/login`
2. Ingresa tu email y contraseña
3. Si el login es exitoso, entras al Dashboard

### Olvidé mi contraseña
1. En la pantalla de login, haz clic en **"Olvidé mi contraseña"**
2. Ingresa tu email → recibirás un correo con un enlace de reset
3. Abre el enlace y establece una nueva contraseña

---

## Dashboard principal

Es la primera pantalla que ves al entrar. Muestra el estado global de tu cuenta en tiempo real.

```
┌─────────────────────────────────────────────────────────┐
│  📊 Resumen                                              │
│                                                          │
│  Total workstations: 150                                │
│  🟢 Online: 142   ⚫ Offline: 6   ⚠️ Contingencia: 2   │
└─────────────────────────────────────────────────────────┘
```

Los números se actualizan solos por WebSocket. No hace falta recargar la página.

---

## Workstations

Sección: **Dashboard → Workstations**

### ¿Qué ves aquí?
Lista de todos los PCs que tienen AlwaysPrint instalado y registrado en tu cuenta.

| Columna | Qué significa |
|---------|--------------|
| IP privada | IP del PC dentro de la red BBVA |
| Hostname | Nombre del equipo en Windows |
| Usuario actual | Usuario de Windows con sesión activa |
| Estado | 🟢 Online / ⚫ Offline |
| Contingencia | ⚠️ Activa / — Normal |
| Última conexión | Cuándo fue la última vez que el Tray se conectó |

### Estados posibles de una workstation

```
🟢 Online, sin contingencia   → Todo funciona. CPM activo.
⚠️ Online, contingencia       → CPM falló. AlwaysPrint está redirigiendo directo.
⚫ Offline                     → El Tray no está conectado (PC apagado o sin internet).
```

### Ver detalle de una workstation
Haz clic en cualquier fila. Verás:
- Información del equipo (IP, hostname, serial de OS, usuario)
- Estado en tiempo real
- Historial de telemetría
- Historial de checks de conectividad
- Configuración aplicada

### Configuración individual
Desde el detalle de la workstation puedes establecer una configuración específica para ese PC. Esta **sobreescribe** la configuración de la VLAN y la global.

Parámetros configurables:
- Intervalo de telemetría (minutos)
- Intervalo de checks de conectividad
- IP de impresora para contingencia
- Otros parámetros del cliente

---

## VLANs

Sección: **Dashboard → VLANs**

Las VLANs sirven para agrupar workstations y aplicarles configuración de forma masiva.

### Jerarquía de configuración
```
Configuración Global
        │
        ▼  (puede sobrescribir)
Configuración de VLAN
        │
        ▼  (puede sobrescribir)
Configuración de Workstation  ← tiene la prioridad más alta
```

Si una workstation tiene su propia configuración, esa gana sobre la de la VLAN. Si no tiene, hereda de la VLAN. Si la VLAN tampoco tiene, hereda de la global.

### Crear una VLAN
1. Clic en **"Nueva VLAN"**
2. Pon nombre y descripción (ej: "Piso 3 - Edificio Lima")
3. Asigna workstations a esa VLAN desde el detalle de cada workstation
4. Opcionalmente, define una configuración específica para esta VLAN

---

## Mensajes

Sección: **Dashboard → Mensajes**

Permite enviar mensajes de texto a las workstations. El `AlwaysPrintTray` los recibe y los muestra como notificación en el escritorio del usuario.

### Tipos de envío

| Tipo | Destinatario |
|------|-------------|
| **Broadcast a cuenta** | Todos los PCs online de tu cuenta |
| **Por VLAN** | Todos los PCs online de una VLAN específica |
| **Por workstation** | Un PC específico |

### Cómo enviar un mensaje
1. Selecciona el tipo de destino
2. Si es VLAN o workstation específica, selecciona cuál
3. Escribe el mensaje
4. Clic en **Enviar**

El panel muestra si el mensaje fue entregado y cuándo.

> Los mensajes solo llegan a PCs que estén **online** en ese momento. Si el PC está offline, el mensaje no se encola para después.

---

## Telemetría

Sección: **Dashboard → Telemetría**

Muestra el historial de snapshots que los Trays reportan periódicamente (cada 5 min por defecto).

### ¿Qué datos se reportan?

| Métrica | Qué mide |
|---------|---------|
| `queue_status` | Estado de la cola LexmarkBBVA (`ok`, `missing`, `error`) |
| `contingency_active` | Si el PC estaba en modo contingencia |
| `jobs_identified` | Cuántos trabajos de impresión se procesaron |
| `avg_release_time_ms` | Tiempo promedio de liberación de un trabajo (ms) |
| `disconnection_count` | Cuántas veces se desconectó del servidor en ese período |

### Vistas disponibles
- **Por workstation**: historial cronológico de una sola máquina
- **Por cuenta**: estadísticas agregadas de todos los PCs

---

## Conectividad

Sección: **Dashboard → Conectividad**

Cada Tray ejecuta checks periódicos de red y los reporta. Aquí puedes ver esos resultados.

### Tipos de checks

| Check | Qué verifica |
|-------|-------------|
| **HTTP** | Que una URL responda con 2xx |
| **TCP** | Que un puerto esté abierto |
| **Ping** | Que un host responda a ICMP |
| **DNS** | Que un dominio se resuelva correctamente |

Los checks se configuran en la sección de **Configuración Global**.

Cada resultado muestra: tipo, éxito/fallo, latencia en ms, y error si aplica.

---

## Configuración Global

Sección: **Dashboard → Configuración**

Es la configuración base que aplica a **todas** las workstations que no tengan configuración de VLAN o individual.

Parámetros típicos:
- Intervalo de telemetría (minutos)
- Intervalo de checks de conectividad
- Checks de conectividad habilitados (URLs, hosts, puertos a verificar)
- Parámetros del comportamiento del cliente

> Cuando guardas un cambio aquí, APCM lo propaga automáticamente por WebSocket a todos los Trays conectados. El cambio aplica en segundos, sin reinicios.

---

## Auditoría

Sección: **Dashboard → Auditoría**

Registro de todas las acciones realizadas en APCM. Útil para saber quién cambió qué y cuándo.

Incluye:
- Logins y logouts
- Cambios de configuración (global, VLAN, workstation)
- Creación/eliminación de usuarios o cuentas
- Envío de mensajes
- Autorización o rechazo de IPs

---

## Gestión de cuentas (solo Admin)

Sección: **Dashboard → Admin → Cuentas**

Si eres Admin del sistema, puedes gestionar múltiples cuentas cliente (ej: BBVA, Ripley, etc.).

Cada cuenta tiene:
- Nombre y datos de contacto
- Sus propios usuarios (Operators y ReadOnly)
- Sus propias workstations

### IPs públicas pendientes

Sección: **Dashboard → Admin → IPs pendientes**

Cuando una workstation se conecta desde una IP pública nueva (no vista antes), APCM la registra como **pendiente de autorización**.

Como Admin puedes:
- **Autorizar** la IP → esa workstation puede conectarse sin restricciones
- **Rechazar** la IP → se bloquea la conexión

---

## Gestión de usuarios (solo Admin)

Sección: **Dashboard → Admin → Usuarios**

Puedes crear, editar y eliminar usuarios del sistema.

Al crear un usuario:
1. Define su rol: `admin`, `operator` o `readonly`
2. Si es `operator` o `readonly`, asígnalo a una cuenta específica
3. El usuario recibe sus credenciales y puede hacer login

Para cambiar la contraseña de un usuario:
- Edita el usuario → campo "Nueva contraseña"
- O el propio usuario puede usar "Olvidé mi contraseña"

---

## Flujo de registro de una workstation nueva

Cuando se instala AlwaysPrint en un PC nuevo y arranca por primera vez:

```
1. AlwaysPrintTray arranca y abre WebSocket con APCM

2. Envía mensaje "register":
   { ip_private, hostname, os_serial, current_user, contingency_active }

3. APCM verifica si ya existe una workstation con esa IP/serial
   ├─ Si existe → actualiza estado (online, usuario actual)
   └─ Si no existe → crea registro nuevo, la asigna a la cuenta

4. APCM responde con "config_update" (configuración actual)

5. El Tray aplica la config y empieza a reportar telemetría
```

Si la IP pública del PC no está autorizada, el paso 3 genera una alerta en la sección **IPs pendientes** para que el Admin la revise.

---

## Tiempo real — ¿Cómo funciona?

APCM mantiene conexiones WebSocket permanentes con cada Tray. Esto permite:

- Ver si un PC se conecta o desconecta **al instante**
- Recibir alertas de contingencia **al instante**
- Propagar cambios de configuración **al instante**
- Ver resultados de telemetría y conectividad **en cuanto llegan**

No hace falta recargar el dashboard. Los cambios aparecen solos.

---

## Preguntas frecuentes

**¿Por qué una workstation aparece Offline si el PC está encendido?**
El PC puede estar encendido pero el Tray no conectado. Puede pasar si:
- El usuario no ha iniciado sesión en Windows
- La workstation no tiene acceso a internet
- El Tray está configurado con `CloudEnabled=0`

**¿Puedo forzar la contingencia desde APCM?**
No. La contingencia es automática: la activa AlwaysPrintService cuando detecta que CPM no está procesando trabajos. APCM solo la visualiza.

**¿Qué pasa si cambio la config global y hay PCs offline?**
Los PCs offline no reciben el cambio en ese momento. Cuando vuelven a conectarse, el Tray solicita la configuración actualizada y la aplica.

**¿Con qué frecuencia se reporta telemetría?**
Por defecto cada 5 minutos. Se puede cambiar en Configuración Global o por workstation/VLAN.

---

*© 2026 Inversiones On Line SAC — Robles.AI*
