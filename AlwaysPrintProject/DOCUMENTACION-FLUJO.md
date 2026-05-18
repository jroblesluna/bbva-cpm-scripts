# AlwaysPrint — Documentación del Flujo del Sistema

> **¿Para quién es esto?** Para cualquier persona del equipo que necesite entender cómo funciona AlwaysPrint.

---

## ¿Qué problema resuelve AlwaysPrint?

Los empleados de BBVA imprimen a través de **Lexmark CPM**, un software corporativo que enruta los trabajos por un servidor Linux. Cuando ese servidor falla o CPM deja de funcionar, **nadie puede imprimir**.

AlwaysPrint soluciona esto: **detecta el fallo automáticamente y redirige los trabajos directo a la impresora**, sin que el usuario tenga que hacer nada.

---

## Los 7 componentes del sistema

```
┌─────────────────────────────────────────────────────────────────┐
│  INTERNET                                                        │
│                                                                  │
│   ┌─────────────────────────────────┐                           │
│   │  APCM — AlwaysPrint Cloud Mgr   │  Panel web para admins   │
│   │  (Next.js + FastAPI + Postgres) │  NO interviene en impresión│
│   └──────────────┬──────────────────┘                           │
│                  │ WebSocket                                     │
└──────────────────┼──────────────────────────────────────────────┘
                   │
┌──────────────────┼──────────────────────────────────────────────┐
│  RED INTERNA BBVA│                                              │
│                  │                                              │
│  ┌───────────────┴────────────────────────────────────────┐    │
│  │  PC DEL EMPLEADO (Windows 10/11)                        │    │
│  │                                                          │    │
│  │  [1] Cola "LexmarkBBVA"  ← el usuario "imprime" aquí   │    │
│  │            │                                             │    │
│  │            ▼                                             │    │
│  │  [2] Lexmark CPM Client  → envía a Linux (normal)       │    │
│  │                                                          │    │
│  │  [3] AlwaysPrintService  → vigila CPM, actúa si falla   │    │
│  │            │ Named Pipe                                  │    │
│  │  [4] AlwaysPrintTray     → conecta con la nube          │    │
│  └──────────────────────────────────────────────────────────┘    │
│                    │ LPD (puerto 515)                            │
│  ┌─────────────────▼────────────────────────────────────────┐   │
│  │  [5] Servidor Linux (CUPS)  → procesa y enruta           │   │
│  └─────────────────┬────────────────────────────────────────┘   │
│                    │ Red LAN                                     │
│  ┌─────────────────▼────────────────────────────────────────┐   │
│  │  [6] Impresoras físicas (HP, Lexmark, etc.)               │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

| # | Componente | Dónde vive | Rol |
|---|-----------|-----------|-----|
| 1 | **Cola "LexmarkBBVA"** | PC del empleado | Impresora virtual donde el usuario "imprime" |
| 2 | **Lexmark CPM Client** | PC del empleado | Toma trabajos y los envía al servidor Linux |
| 3 | **AlwaysPrintService** | PC del empleado | Vigila CPM; toma el control si CPM falla |
| 4 | **AlwaysPrintTray** | PC del empleado | Iconito en bandeja; puente entre el PC y la nube |
| 5 | **Servidor Linux (SUSE 12)** | Datacenter BBVA | Enruta, agrega cabeceras PJL, registra auditoría |
| 6 | **Impresoras físicas** | Oficinas BBVA | Imprimen el papel |
| 7 | **APCM** | Internet (nube) | Panel de control para administradores de TI |

---

## Flujo normal — Todo funciona bien

> Este es el camino que sigue un trabajo de impresión en condiciones normales.

```
USUARIO                 PC                        LINUX              IMPRESORA
   │                     │                           │                    │
   │  1. Ctrl+P,         │                           │                    │
   │  elige "LexmarkBBVA"│                           │                    │
   │────────────────────>│                           │                    │
   │                     │                           │                    │
   │              2. El trabajo entra                │                    │
   │                 a la cola Windows               │                    │
   │                     │                           │                    │
   │              3. Lexmark CPM                     │                    │
   │                 toma el trabajo                 │                    │
   │                 y lo envía por LPD              │                    │
   │                     │──────────────────────────>│                    │
   │                     │                           │                    │
   │                     │                    4. CUPS recibe              │
   │                     │                       el trabajo               │
   │                     │                           │                    │
   │                     │                    5. Script bash:             │
   │                     │                       • Identifica usuario     │
   │                     │                       • Busca IP impresora     │
   │                     │                       • Agrega cabeceras PJL   │
   │                     │                       • Registra en log        │
   │                     │                           │                    │
   │                     │                    6. Envía a la               │
   │                     │                       impresora                │
   │                     │                           │───────────────────>│
   │                     │                           │                    │
   │                     │                           │            7. IMPRIME
```

**En paralelo, AlwaysPrint observa sin intervenir:**
- `AlwaysPrintService` → comprueba que CPM está activo. Ve que sí → no hace nada.
- `AlwaysPrintTray` → reporta a la nube: *"Todo OK, sin contingencia"* + ejecuta checks periódicos de red.

---

## Flujo de contingencia — Lexmark CPM falla

> AlwaysPrint toma el control automáticamente. El usuario no nota nada.

```
USUARIO                 PC                                         IMPRESORA
   │                     │                                              │
   │  1. Ctrl+P,         │                                              │
   │  elige "LexmarkBBVA"│                                              │
   │────────────────────>│                                              │
   │                     │                                              │
   │              2. El trabajo entra                                   │
   │                 a la cola Windows                                  │
   │                     │                                              │
   │              3. Lexmark CPM ❌                                     │
   │                 No funciona.                                        │
   │                 Los trabajos                                        │
   │                 se acumulan                                         │
   │                 en la cola.                                         │
   │                     │                                              │
   │              4. AlwaysPrintService                                 │
   │                 detecta los trabajos                               │
   │                 acumulados → activa                                │
   │                 contingencia                                        │
   │                     │                                              │
   │              5. AlwaysPrintService                                 │
   │                 toma el control:                                    │
   │                 • Lee trabajos de la cola                          │
   │                 • Obtiene IP directa                               │
   │                   de la impresora                                  │
   │                 • Envía directo                                    │
   │                   (sin pasar por Linux)                            │
   │                     │─────────────────────────────────────────────>│
   │                     │                                              │
   │                     │                                      6. IMPRIME
   │                     │                                              │
   │              7. Notifica al Tray:                                  │
   │                 "contingencia activa"                               │
   │                     │                                              │
   │              8. Tray notifica a la nube:                           │
   │                 "⚠️ contingencia en W10BBVA02"                    │
   │                     │                                              │
   │              9. Admin ve en APCM:                                  │
   │                 "1 workstation en contingencia"                     │
```

> **Nota importante:** en contingencia, el trabajo va directo del PC a la impresora. No hay enrutamiento inteligente, no hay cabeceras PJL, no hay registro de auditoría en Linux.

---

## Comunicación dentro del PC

Los dos procesos de AlwaysPrint necesitan hablarse, pero corren con permisos distintos. Se comunican por un **Named Pipe** (canal interno de Windows).

```
AlwaysPrintService              Named Pipe              AlwaysPrintTray
(corre como SYSTEM)          ◄────────────►          (corre como USUARIO)
    │                                                        │
    │  Envía al Tray:                    Envía al Service:  │
    │  • Config actual                   • Nueva config      │
    │  • Trabajo impreso (telemetría)      de la nube        │
    │  • "Pong" (sigo vivo)             • ¿Existe la cola?  │
    │                                   • ¿Corre LPD?       │
    │                                   • "Ping" (salud)     │
```

**¿Por qué dos procesos separados?**

| | AlwaysPrintService | AlwaysPrintTray |
|---|---|---|
| **Permisos** | SYSTEM (máximo) | Usuario normal |
| **Necesita** | Leer colas de impresión, modificar registro Windows | Conectarse a internet, mostrar UI al usuario |
| **Inicia** | Con el PC | Cuando el usuario inicia sesión |

---

## Panel de administración — APCM

APCM es el panel web en la nube. **Solo monitorea, no imprime.**

```
Lo que ve el administrador:
┌────────────────────────────────────────────────────────┐
│  📊 Dashboard                                          │
│  Total: 150 workstations                               │
│  🟢 Online: 142  |  ⚫ Offline: 6  |  ⚠️ Contingencia: 2 │
├────────────────────────────────────────────────────────┤
│  🖥️ Estaciones                                        │
│  192.168.1.100 | W10BBVA01 | 🟢 Online | Cola: OK     │
│  192.168.1.101 | W10BBVA02 | ⚠️ Contingencia          │
│  192.168.1.102 | W10BBVA03 | ⚫ Offline                │
└────────────────────────────────────────────────────────┘
```

**El admin SÍ puede:**
- Cambiar configuración de todas las workstations a la vez (ej: intervalo de telemetría)
- Ver qué workstations están en contingencia
- Ver estadísticas de impresión (cantidad, tiempos)
- Ver resultados de checks de conectividad
- Autorizar nuevas IPs públicas

**El admin NO puede:**
- Imprimir (APCM no participa en el flujo de impresión)
- Forzar la contingencia (es completamente automática)
- Intervenir en un trabajo de impresión en curso

**¿Cómo se conectan los PCs con APCM?** Cada `AlwaysPrintTray` mantiene una conexión **WebSocket permanente** hacia la nube. Por ahí fluye configuración, telemetría y estado.

---

## Línea de tiempo — Encendido de un PC

```
TIEMPO    EVENTO
──────    ─────────────────────────────────────────────────────────────

00:00     PC se enciende
          ├─ AlwaysPrintService arranca (servicio Windows automático)
          └─ Lexmark CPM Client arranca

00:01     AlwaysPrintService inicializa:
          ├─ Verifica que no haya otra instancia corriendo
          ├─ Elimina Trays huérfanos de sesiones anteriores
          ├─ Crea el Named Pipe
          └─ Espera a que un usuario inicie sesión...

02:00     Usuario inicia sesión en Windows
          └─ AlwaysPrintService detecta la sesión
             └─ Lanza AlwaysPrintTray.exe en el contexto del usuario

02:03     AlwaysPrintTray arranca:
          ├─ Aparece el iconito en la bandeja del sistema
          ├─ Verifica que el Service esté corriendo → OK
          ├─ Se conecta al Named Pipe → OK
          ├─ Hace health check de dominios APCM → OK
          └─ Notifica al Service: "Tray inicializado OK"

02:04     AlwaysPrintTray se conecta a la nube (si CloudEnabled=1):
          ├─ Abre WebSocket con APCM
          ├─ Envía "register" con datos del PC (hostname, IP, versión)
          ├─ APCM responde con config_update
          ├─ Tray aplica config → se la pasa al Service por Named Pipe
          ├─ Inicia TelemetryReporter (reporta cada 5 min)
          └─ Inicia ConnectivityMonitor (checks periódicos de red)

02:05     Sistema listo. El usuario puede imprimir.
          ├─ AlwaysPrintService vigila CPM continuamente
          └─ AlwaysPrintTray reporta estado a la nube continuamente

∞         Si CPM falla en algún momento:
          ├─ AlwaysPrintService detecta trabajos acumulados en la cola
          ├─ Activa contingencia → envía directo a IP de impresora
          ├─ Notifica al Tray por Named Pipe
          └─ Tray notifica a APCM → Admin ve "⚠️ contingencia"
```

---

## Decisión clave: ¿Quién imprime qué?

```
¿CPM funciona?
      │
      ├─── SÍ ──► Flujo normal
      │            Cola → CPM → Servidor Linux → Impresora
      │            (con enrutamiento, PJL, auditoría)
      │
      └─── NO ──► Contingencia
                   Cola → AlwaysPrintService → IP directa impresora
                   (sin enrutamiento inteligente, sin auditoría)
```

La detección es automática. La contingencia se activa sola y se desactiva sola cuando CPM vuelve a funcionar.

---

*© 2026 Inversiones On Line SAC — Robles.AI*
