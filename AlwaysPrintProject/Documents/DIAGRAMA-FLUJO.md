# AlwaysPrint — Diagrama Completo del Sistema

---

## Vista General: Todos los Componentes

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                      │
│                              ☁️  INTERNET (NUBE)                                     │
│                                                                                      │
│         ┌────────────────────────────────────────────────────────┐                  │
│         │  APCM — AlwaysPrint Cloud Manager                       │                  │
│         │                                                         │                  │
│         │  ┌─────────────────┐    ┌──────────────────────────┐  │                  │
│         │  │ Frontend Next.js│    │ Backend FastAPI           │  │                  │
│         │  │ (panel web para │    │ • API REST               │  │                  │
│         │  │  administradores│    │ • WebSocket              │  │                  │
│         │  │  de TI)         │    │ • PostgreSQL             │  │                  │
│         │  └─────────────────┘    └──────────────────────────┘  │                  │
│         │                                                         │                  │
│         │  Funciones:                                             │                  │
│         │  • Ver estado de TODOS los PCs en tiempo real           │                  │
│         │  • Cambiar configuración remotamente                    │                  │
│         │  • Ver telemetría (estadísticas de impresión)           │                  │
│         │  • Ver resultados de checks de conectividad             │                  │
│         │  • Gestionar organizaciones y usuarios                  │                  │
│         │                                                         │                  │
│         │  ⚠️  NO PARTICIPA EN EL FLUJO DE IMPRESIÓN             │                  │
│         │     Solo es un panel de control/monitoreo               │                  │
│         └───────────────────────────┬────────────────────────────┘                  │
│                                     │                                                │
│                                     │ WebSocket (WSS)                                │
│                                     │ • Reportes de estado                           │
│                                     │ • Configuración remota                         │
│                                     │ • Telemetría                                   │
│                                     │ • Checks de conectividad                       │
│                                     │                                                │
└─────────────────────────────────────┼────────────────────────────────────────────────┘
                                      │
                                      │
┌─────────────────────────────────────┼────────────────────────────────────────────────┐
│                                     │                                                │
│                    🏢 RED INTERNA BBVA (LAN)                                         │
│                                     │                                                │
│  ┌──────────────────────────────────┼─────────────────────────────────────────────┐ │
│  │  PC DEL EMPLEADO (Windows 10/11) │                                              │ │
│  │                                  │                                              │ │
│  │  ┌──────────────────────────────────────────────────────────────────────────┐  │ │
│  │  │  AlwaysPrintService (servicio Windows, corre como SYSTEM)                 │  │ │
│  │  │                                                                           │  │ │
│  │  │  • Arranca automáticamente con el PC                                      │  │ │
│  │  │  • Vigila si Lexmark CPM está funcionando                                 │  │ │
│  │  │  • Si CPM falla → redirige trabajos a IP de impresora                     │  │ │
│  │  │  • Guarda configuración en registro Windows (HKLM)                        │  │ │
│  │  │  • Lanza el Tray cuando un usuario inicia sesión                          │  │ │
│  │  └──────────────────────────────────┬────────────────────────────────────────┘  │ │
│  │                                     │ Named Pipe                                │ │
│  │                                     │ (canal de comunicación                    │ │
│  │                                     │  interno entre los dos                    │ │
│  │                                     │  programas)                               │ │
│  │  ┌──────────────────────────────────┴────────────────────────────────────────┐  │ │
│  │  │  AlwaysPrintTray (app de bandeja, corre como USUARIO)                      │  │ │
│  │  │                                                                            │  │ │
│  │  │  • Iconito en la bandeja del sistema (junto al reloj)                      │  │ │
│  │  │  • Se conecta a APCM (nube) por WebSocket ─────────────────────────────────┼──┘ │
│  │  │  • Descarga configuración de la nube → se la pasa al Service               │    │
│  │  │  • Reporta telemetría a la nube                                            │    │
│  │  │  • Ejecuta checks de conectividad (HTTP, TCP, DNS, ping)                   │    │
│  │  │  • Muestra notificaciones al usuario                                       │    │
│  │  └───────────────────────────────────────────────────────────────────────────┘    │
│  │                                                                                    │
│  │  ┌───────────────────────────────────────────────────────────────────────────┐    │
│  │  │  Lexmark CPM Client (software de Lexmark, producción)                      │    │
│  │  │                                                                            │    │
│  │  │  • Captura trabajos de la cola "LexmarkBBVA"                               │    │
│  │  │  • Los envía al servidor Linux por protocolo LPD (puerto 515)              │    │
│  │  │  • Es el sistema PRINCIPAL de impresión                                    │    │
│  │  └──────────────────────────────────┬────────────────────────────────────────┘    │
│  │                                     │                                              │
│  │  ┌───────────────────────────────────────────────────────────────────────────┐    │
│  │  │  Cola "LexmarkBBVA" (impresora virtual de Windows)                         │    │
│  │  │                                                                            │    │
│  │  │  • El usuario selecciona esta "impresora" al imprimir                      │    │
│  │  │  • No es una impresora real, es un punto de entrada                        │    │
│  │  └───────────────────────────────────────────────────────────────────────────┘    │
│  └────────────────────────────────────────────────────────────────────────────────────┘
│                                        │
│                                        │ LPD (puerto 515)
│                                        │ por red LAN
│                                        ▼
│  ┌────────────────────────────────────────────────────────────────────────────────────┐
│  │  SERVIDOR LINUX (SUSE 12, gestionado por BBVA)                                     │
│  │                                                                                    │
│  │  • Siempre encendido                                                               │
│  │  • Ejecuta CUPS (sistema de colas de impresión de Linux)                           │
│  │  • Tiene scripts bash ("filtros") que:                                             │
│  │    - Identifican quién imprimió                                                    │
│  │    - Buscan la IP de la impresora correcta                                         │
│  │    - Agregan cabeceras PJL (instrucciones para la impresora)                       │
│  │    - Registran todo (auditoría)                                                    │
│  │  • Recibe de TODOS los PCs y envía a TODAS las impresoras                         │
│  └───────────────────────────────────────┬────────────────────────────────────────────┘
│                                          │
│                                          │ Red LAN
│                                          ▼
│  ┌────────────────────────────────────────────────────────────────────────────────────┐
│  │  IMPRESORAS FÍSICAS (HP, Lexmark, etc.)                                            │
│  │                                                                                    │
│  │  • Conectadas a la red LAN de BBVA                                                 │
│  │  • Cada una tiene su IP fija (ej: 192.168.1.50)                                   │
│  │  • Reciben trabajos y los imprimen en papel                                        │
│  └────────────────────────────────────────────────────────────────────────────────────┘
│                                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## CASO 1: Flujo Normal (Producción) — Todo funciona bien

```
    USUARIO                PC DEL EMPLEADO                    SERVIDOR LINUX         IMPRESORA
      │                         │                                  │                     │
      │  1. Ctrl+P en Word      │                                  │                     │
      │  selecciona             │                                  │                     │
      │  "LexmarkBBVA"         │                                  │                     │
      │────────────────────────>│                                  │                     │
      │                         │                                  │                     │
      │               2. Windows pone el                           │                     │
      │                  trabajo en la cola                        │                     │
      │                  "LexmarkBBVA"                             │                     │
      │                         │                                  │                     │
      │               3. Lexmark CPM Client                        │                     │
      │                  toma el trabajo                           │                     │
      │                  de la cola                                │                     │
      │                         │                                  │                     │
      │               4. CPM envía el trabajo                      │                     │
      │                  al servidor Linux                         │                     │
      │                  por red LAN (LPD)                         │                     │
      │                         │─────────────────────────────────>│                     │
      │                         │                                  │                     │
      │                         │                        5. Linux recibe el              │
      │                         │                           trabajo en CUPS              │
      │                         │                                  │                     │
      │                         │                        6. El filtro (script            │
      │                         │                           bash) procesa:              │
      │                         │                           • Identifica usuario         │
      │                         │                           • Busca IP impresora         │
      │                         │                           • Agrega cabeceras PJL       │
      │                         │                           • Registra en log            │
      │                         │                                  │                     │
      │                         │                        7. Linux envía a la             │
      │                         │                           impresora física             │
      │                         │                                  │────────────────────>│
      │                         │                                  │                     │
      │                         │                                  │           8. IMPRIME│
      │                         │                                  │              EL     │
      │                         │                                  │              PAPEL  │
      │                         │                                  │                     │

    ¿Qué hace AlwaysPrint mientras tanto?

      │               AlwaysPrintService:                          │                     │
      │               • Vigila que CPM funcione                    │                     │
      │               • Ve que todo está OK                        │                     │
      │               • NO interviene                              │                     │
      │                         │                                  │                     │
      │               AlwaysPrintTray:                             │                     │
      │               • Reporta a la nube:                         │                     │
      │                 "cola OK, sin contingencia"                 │                     │
      │               • Ejecuta checks de                          │                     │
      │                 conectividad periódicos                     │                     │
```

---

## CASO 2: Contingencia — Lexmark CPM falló

```
    USUARIO                PC DEL EMPLEADO                                        IMPRESORA
      │                         │                                                      │
      │  1. Ctrl+P en Word      │                                                      │
      │  selecciona             │                                                      │
      │  "LexmarkBBVA"         │                                                      │
      │────────────────────────>│                                                      │
      │                         │                                                      │
      │               2. Windows pone el                                               │
      │                  trabajo en la cola                                             │
      │                  "LexmarkBBVA"                                                  │
      │                         │                                                      │
      │               3. Lexmark CPM Client                                            │
      │                  ❌ NO FUNCIONA                                                │
      │                  (caído, error, Linux                                           │
      │                   inalcanzable, etc.)                                           │
      │                         │                                                      │
      │               4. AlwaysPrintService                                             │
      │                  DETECTA que CPM falló                                          │
      │                  (trabajos se acumulan                                          │
      │                   en la cola sin salir)                                         │
      │                         │                                                      │
      │               5. AlwaysPrintService                                             │
      │                  TOMA EL CONTROL:                                               │
      │                  • Lee los trabajos                                             │
      │                    de la cola                                                   │
      │                  • Busca la IP directa                                          │
      │                    de la impresora                                              │
      │                  • Envía DIRECTO a la                                           │
      │                    impresora por red                                            │
      │                    (sin pasar por Linux)                                        │
      │                         │─────────────────────────────────────────────────────>│
      │                         │                                                      │
      │                         │                                                      │
      │               6. AlwaysPrintService                                    7. IMPRIME
      │                  notifica al Tray:                                        EL
      │                  "contingencia activa"                                    PAPEL
      │                         │                                                      │
      │               7. AlwaysPrintTray                                                │
      │                  notifica a la nube:                                            │
      │                  "contingencia activa                                           │
      │                   en esta workstation"                                          │
      │                         │                                                      │
      │               8. El admin ve en el                                              │
      │                  panel web (APCM):                                              │
      │                  "⚠️ 1 workstation                                             │
      │                   en contingencia"                                              │
      │                         │                                                      │

    ⚠️  EL SERVIDOR LINUX NO PARTICIPÓ EN NADA
        El trabajo fue directo del PC a la impresora
        Sin enrutamiento inteligente, sin cabeceras PJL, sin auditoría
```

---

## Relación con APCM (la nube) — Siempre activa, en ambos casos

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│  APCM (NUBE) — Panel de administración                                      │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                                                                        │  │
│  │   Lo que el ADMIN ve en el navegador:                                  │  │
│  │                                                                        │  │
│  │   📊 Dashboard                                                         │  │
│  │   ┌─────────────────────────────────────────────────────────────┐     │  │
│  │   │  Total: 150 workstations                                     │     │  │
│  │   │  Online: 142  |  Offline: 6  |  Contingencia: 2             │     │  │
│  │   └─────────────────────────────────────────────────────────────┘     │  │
│  │                                                                        │  │
│  │   🖥️ Estaciones                                                       │  │
│  │   ┌─────────────────────────────────────────────────────────────┐     │  │
│  │   │  192.168.1.100  |  W10BBVA01  |  🟢 Online  |  Cola: OK    │     │  │
│  │   │  192.168.1.101  |  W10BBVA02  |  🟠 Contingencia           │     │  │
│  │   │  192.168.1.102  |  W10BBVA03  |  ⚫ Offline                 │     │  │
│  │   └─────────────────────────────────────────────────────────────┘     │  │
│  │                                                                        │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ¿Qué puede HACER el admin desde aquí?                                      │
│                                                                              │
│  • Cambiar la configuración de todas las workstations a la vez              │
│    (ej: cambiar el intervalo de telemetría de 5 min a 10 min)               │
│  • Ver qué workstations están en contingencia                                │
│  • Ver estadísticas de impresión (cuántos trabajos, tiempos)                │
│  • Ver si la red funciona bien (checks de conectividad)                      │
│  • Enviar mensajes a las workstations                                        │
│  • Autorizar nuevas IPs públicas                                             │
│                                                                              │
│  ¿Qué NO puede hacer?                                                       │
│                                                                              │
│  • NO puede imprimir                                                         │
│  • NO puede intervenir en el flujo de impresión                              │
│  • NO puede forzar la contingencia (es automática)                           │
│                                                                              │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   │ WebSocket (conexión permanente)
                                   │
┌──────────────────────────────────┼───────────────────────────────────────────┐
│  RED INTERNA BBVA                │                                            │
│                                  │                                            │
│  PC 1 (AlwaysPrintTray) ─────────┤  Cada Tray mantiene una conexión          │
│  PC 2 (AlwaysPrintTray) ─────────┤  WebSocket abierta con APCM.              │
│  PC 3 (AlwaysPrintTray) ─────────┤                                           │
│  ...                              │  Por esta conexión fluye:                 │
│  PC 150 (AlwaysPrintTray) ────────┘  • Config (nube → PC)                    │
│                                      • Telemetría (PC → nube)                 │
│                                      • Estado (PC → nube)                     │
│                                      • Checks conectividad (PC → nube)        │
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## Comunicación entre componentes dentro del PC

```
┌─────────────────────────────────────────────────────────────────────────┐
│  DENTRO DE UN PC                                                         │
│                                                                          │
│                                                                          │
│  AlwaysPrintService                    AlwaysPrintTray                   │
│  (SYSTEM, admin)                       (USUARIO, sin admin)              │
│  ┌────────────────────┐               ┌────────────────────┐           │
│  │                    │               │                    │           │
│  │ • Vigila CPM       │    Named      │ • Iconito bandeja  │           │
│  │ • Redirige cola    │◄───Pipe──────►│ • Conecta a nube   │           │
│  │ • Guarda config    │   (canal      │ • Descarga config  │           │
│  │   en registro      │   interno)    │ • Reporta estado   │           │
│  │ • Lanza el Tray    │               │ • Checks de red    │           │
│  │                    │               │ • Notificaciones   │           │
│  └────────────────────┘               └────────────────────┘           │
│                                                                          │
│  ¿Qué se envían por el Named Pipe?                                      │
│                                                                          │
│  Service → Tray:                                                         │
│  • "Aquí está la configuración actual"                                   │
│  • "Se completó un trabajo de impresión (para telemetría)"               │
│  • "Pong" (respuesta a ping de salud)                                    │
│                                                                          │
│  Tray → Service:                                                         │
│  • "La nube mandó esta nueva configuración, aplícala"                    │
│  • "¿La cola LexmarkBBVA existe?"                                        │
│  • "¿El servicio LPD está corriendo?"                                    │
│  • "Ping" (verificar que el Service está vivo)                           │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Resumen: ¿Qué hace cada cosa?

| Componente | Dónde corre | Función principal |
|-----------|-------------|-------------------|
| **Cola "LexmarkBBVA"** | PC del empleado | Impresora virtual donde el usuario "imprime" |
| **Lexmark CPM Client** | PC del empleado | Toma trabajos de la cola y los envía a Linux (PRODUCCIÓN) |
| **AlwaysPrintService** | PC del empleado | Vigila CPM; si falla, redirige directo a impresora (CONTINGENCIA) |
| **AlwaysPrintTray** | PC del empleado | Conecta con la nube, reporta estado, descarga config |
| **Servidor Linux** | Datacenter BBVA | Procesa trabajos: enruta, agrega cabeceras, registra |
| **APCM (nube)** | Internet | Panel de control para administradores (NO imprime) |
| **Impresora** | Oficina BBVA | Imprime el papel |

---

## Línea de tiempo: ¿Qué pasa cuando se enciende un PC?

```
TIEMPO    EVENTO
──────    ──────────────────────────────────────────────────────────────────

00:00     PC se enciende
          └─ AlwaysPrintService arranca automáticamente (servicio Windows)
          └─ Lexmark CPM Client arranca automáticamente

00:01     AlwaysPrintService verifica:
          └─ ¿Hay otra instancia corriendo? → No → continúa
          └─ ¿Hay Trays huérfanos? → Los mata
          └─ Crea el Named Pipe (canal de comunicación)
          └─ Espera a que un usuario inicie sesión...

02:00     Usuario inicia sesión en Windows
          └─ AlwaysPrintService detecta la sesión
          └─ Lanza AlwaysPrintTray.exe en la sesión del usuario

02:03     AlwaysPrintTray arranca:
          └─ Muestra iconito en la bandeja
          └─ Verifica que el Service esté corriendo → OK
          └─ Se conecta al Named Pipe → OK
          └─ Hace health check de dominios → OK
          └─ Notifica al Service: "Tray inicializado OK"

02:04     AlwaysPrintTray (si CloudEnabled=1):
          └─ Se conecta a APCM por WebSocket
          └─ Envía mensaje "register" con datos del PC
          └─ APCM responde con config_update
          └─ Tray descarga config → se la pasa al Service
          └─ Inicia TelemetryReporter (cada 5 min)
          └─ Inicia ConnectivityMonitor (checks periódicos)

02:05     Sistema listo. Usuario puede imprimir.
          └─ AlwaysPrintService vigila CPM continuamente
          └─ AlwaysPrintTray reporta a la nube continuamente

∞         Si CPM falla en algún momento:
          └─ AlwaysPrintService detecta la falla
          └─ Activa contingencia (redirige a IP directa)
          └─ Notifica al Tray → Tray notifica a la nube
          └─ Admin ve "⚠️ contingencia" en el panel web
```

---

© 2026 Inversiones On Line SAC — Robles.AI
