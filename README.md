# Repositorio de Sistemas de Impresión Corporativa BBVA

Este repositorio contiene dos sistemas complementarios para gestión de impresión corporativa.

**Última actualización**: 28 de agosto de 2026

---

## 🎯 Sistemas en el Repositorio

### 1. Sistema de Producción (Principal) - Lexmark Cloud Print Manager (CPM)

**El sistema de producción es Lexmark Cloud Print Manager en modo Híbrido**, gestionado por BBVA.

**Tecnología**: Lexmark CPM (Hybrid Mode) + Servidor Linux SUSE 12 (CUPS)  
**Ubicación**: `Linux Server/` y `Workstations/`  
**Estado**: ✅ Producción activa  
**Responsable**: BBVA

**Componentes**:
- **Lexmark CPM Client** en workstations Windows (componente principal de producción)
- **Servidor Linux SUSE 12** con CUPS y filtros personalizados (siempre operativo, responsabilidad BBVA)
- **Cola LexmarkBBVA** en Windows (enruta trabajos a través de CPM)
- **LPD Service** y monitoring en Windows
- **Tea4Cups** para generación de PDFs

**Flujo Normal de Producción**:
```
Usuario imprime → Cola LexmarkBBVA (Windows) → Lexmark CPM Client → 
Servidor Linux CUPS → Filtros CPM → Impresora física
```

**Documentación**: Ver sección "Manual del Sistema de Producción" más abajo

---

### 2. Sistema de Contingencia (Complementario) - AlwaysPrint

**Mecanismo de contingencia que se activa cuando Lexmark CPM falla.**

**Tecnología**: C# .NET 4.8 (Client) + Python/TypeScript (Cloud Manager)  
**Ubicación**: `AlwaysPrintProject/`  
**Estado**: ⏳ En desarrollo (80% completo)

**Componentes**:
- **Client**: Software Windows instalado en workstations
  - AlwaysPrintService.exe (servicio)
  - AlwaysPrintTray.exe (interfaz de usuario)
- **Cloud Manager**: Plataforma SaaS para gestión centralizada
  - Backend FastAPI (Python 3.12)
  - Frontend Next.js 15 (TypeScript)

**Propósito**:
- ✅ **Contingencia activa**: Cuando Lexmark CPM falla, AlwaysPrint redirige el tráfico de las colas Windows directamente a las impresoras (IP:puerto estándar)
- ✅ **Monitoreo centralizado**: Visibilidad del estado de workstations y sistema de impresión
- ✅ **Gestión remota**: Configuración centralizada desde Cloud Manager
- ✅ **Coexistencia**: Instalado junto a Lexmark CPM sin interferir en operación normal

**Flujo de Contingencia** (cuando CPM falla):
```
Usuario imprime → Cola Windows → AlwaysPrint detecta falla CPM → 
Redirige tráfico → IP impresora:puerto estándar (bypass CPM/Linux)
```

**Documentación**: `AlwaysPrintProject/README.md`

---

## 📁 Estructura del Repositorio

```
.
├── AlwaysPrintProject/            # Sistema de contingencia
│   ├── Cloud/                     # Plataforma SaaS
│   │   ├── backend/              # FastAPI (Python 3.12)
│   │   ├── frontend/             # Next.js 15 (TypeScript)
│   │   ├── ARCHITECTURE.md       # Arquitectura detallada
│   │   └── README.md
│   ├── Client/                    # Software Windows
│   │   ├── AlwaysPrint.Shared/   # Biblioteca compartida
│   │   ├── AlwaysPrintService/   # Servicio Windows
│   │   ├── AlwaysPrintTray/      # Aplicación de bandeja
│   │   ├── AlwaysPrint.sln       # Solución Visual Studio
│   │   ├── build.ps1             # Script de compilación
│   │   └── README.md
│   └── README.md
│
├── Linux Server/                  # Servidor CUPS (BBVA, siempre operativo)
│   └── root/bin/
│       ├── filtro_nacarpr_pro.cpm      # Filtro producción CPM
│       ├── filtro_contingencia_pro     # Filtro contingencia LPD
│       ├── filtro_winhostuser          # Receptor de mapping
│       ├── create_CPMWinHostUser.sh    # Crear cola de mapping
│       └── Lexmark.Cups.ppd.gz         # PPD base
│
├── Workstations/                  # Componentes Windows (CPM + contingencia)
│   ├── Client Installer/          # Instalador Lexmark CPM (producción)
│   ├── SetupLPD/                  # Scripts LPD/LPR
│   ├── Startup/                   # Scripts de inicio
│   └── LpdServiceMonitor/         # Monitor de servicio LPD
│
├── .kiro/                         # Configuración Kiro
├── AGENTS.md                      # Reglas para agentes IA
└── README.md                      # Este archivo
```



---

## 🏗️ Arquitectura - Sistema de Producción y Contingencia

### Flujo Normal (Producción - Lexmark CPM)

```
┌─────────────────────────────────────────────────────────────┐
│                    WORKSTATION WINDOWS                       │
│                                                              │
│  Usuario imprime                                            │
│       ↓                                                      │
│  ┌────────────────────────────────────────────────────┐    │
│  │  SISTEMA DE PRODUCCIÓN (Lexmark CPM)               │    │
│  │  • Cola LexmarkBBVA                                │    │
│  │  • Lexmark CPM Client ← COMPONENTE PRINCIPAL       │    │
│  │  • LPD Service (puerto 515)                        │    │
│  │  • LpdServiceMonitor                               │    │
│  └────────────────┬───────────────────────────────────┘    │
└───────────────────┼─────────────────────────────────────────┘
                    │
                    │ Tráfico CPM (puerto 9167/9443)
                    ↓
┌─────────────────────────────────────────────────────────────┐
│              SERVIDOR LINUX SUSE 12 (BBVA)                   │
│              Siempre operativo                               │
│                                                              │
│  • CUPS + Filtros personalizados                            │
│  • Enrutamiento inteligente                                 │
│  • Tea4Cups (PDFs)                                          │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ↓
         Impresora física
```

### Flujo de Contingencia (Cuando CPM falla)

```
┌─────────────────────────────────────────────────────────────┐
│                    WORKSTATION WINDOWS                       │
│                                                              │
│  Usuario imprime                                            │
│       ↓                                                      │
│  ┌────────────────────────────────────────────────────┐    │
│  │  Cola Windows                                      │    │
│  └────────────────┬───────────────────────────────────┘    │
│                   │                                          │
│                   │ CPM no responde ✗                       │
│                   ↓                                          │
│  ┌────────────────────────────────────────────────────┐    │
│  │  SISTEMA DE CONTINGENCIA (AlwaysPrint)             │    │
│  │  • AlwaysPrintService detecta falla                │    │
│  │  • Redirige tráfico a IP:puerto estándar           │    │
│  │  • AlwaysPrintTray notifica al usuario             │    │
│  └────────────────┬───────────────────────────────────┘    │
└───────────────────┼─────────────────────────────────────────┘
                    │
                    │ Bypass CPM/Linux
                    │ Directo a IP:puerto estándar (LPD/RAW)
                    ↓
         Impresora física (directo)
         
                    │
                    │ Telemetría y estado
                    ↓
┌─────────────────────────────────────────────────────────────┐
│              ALWAYSPRINT CLOUD MANAGER                       │
│              • Monitoreo de fallas                           │
│              • Alertas a administradores                     │
│              • Analytics de contingencia                     │
└─────────────────────────────────────────────────────────────┘
```

**Diferencias Clave**:
- **Producción**: Tráfico pasa por Lexmark CPM → Servidor Linux → Impresora
- **Contingencia**: Tráfico va directo desde Windows → Impresora (bypass completo)
- **Servidor Linux**: Siempre operativo (responsabilidad BBVA), pero no se usa en contingencia

---

## 🧭 Arquitectura de Resolución de Impresión

El servidor Linux no conoce de antemano la IP de la workstation Windows a la que debe enviar cada trabajo. Esa relación se resuelve en **dos fases**: primero un registro de mapping (workstation → servidor), y luego una resolución en tiempo de impresión (job → workstation destino).

### Nomenclatura: dos nombres relacionados por una transformación

Todas las nomenclaturas comparten los mismos campos: **XXX** = código de agencia
(3 dígitos), **Y** = servidor de agencia (SERVLIN, 1 dígito), **ZZ** = número de
puesto (2 dígitos). Cambian solo el prefijo y la longitud según el contexto.

| Contexto | Formato | Chars | Ejemplo |
|---|---|---|---|
| **Hostname Windows físico** (agencias) | `W10XXX0YPZZ` / `W11XXX0YPZZ` (+ sufijo `A` opcional) | 11-12 | `W1035401P19`, `W1134901P02A` |
| **Hostname enviado al mapfile** (trunc. a 11) | `w10XXX0YpZZ` / `w11XXX0YpZZ` | 11 | `w1035401p19` |
| **PUESTO** = cola CUPS / `Where` del finger | `w0XXX0YpZZ` | 10 | `w035401p19` |
| **Servidor Nacar Linux** | `s0XXX00Y` | 8 | `s0354001` |
| **MAC del VMX** (`ethernet0.address`) | `??:??:??:YX:XX:ZZ` | — | `00:50:56:19:10:22` |

**La relación clave (coincidencia parcial Windows ↔ Linux):**

El hostname Windows empieza con `w10` o `w11`. Si se reemplazan los **2 caracteres
tras la `w`** por un **solo `0`** (`w10`→`w0`, `w11`→`w0`), se obtiene el PUESTO,
que es el nombre de la cola CUPS y el `Where` del finger:

```
Windows   w1 0 35401 p 19   (11, w10)  ┐
Windows   w1 1 34901 p 02   (11, w11)  ├─ "w10"/"w11" → "w0" ─►  PUESTO w035401p19 (10)
                                       ┘                                 = cola CUPS = finger Where
```

El filtro `filtro_nacarpr` hace la transformación **inversa**: parte del PUESTO
(que obtiene de `lpstat`) y reconstruye el hostname Windows para buscar en el mapfile:

```
PUESTO  w035401p19  ──►  WINHOST="w10${AGENCIA}0${SERVLIN}p${YY2}"  ──►  w1035401p19
        (10, w0)         AGENCIA=354  SERVLIN=1  ZZ=19                    (11, w10)
                         con fallback a w11 si no hay match en el mapfile
```

**Derivación desde la MAC del VMX** (segmentos `YX:XX:ZZ`, ej. `19:10:22`):

```
MAC "??:??:??:YX:XX:ZZ"  ──►  XXX (agencia) = X + XX   Y (SERVLIN) = Y   ZZ (puesto) = ZZ
Ej. "00:50:56:19:10:22"  ──►  XXX = 9,1,0 = "910"      Y = 1             ZZ = "22"

  → VMHOST  = w10 + XXX + 0 + Y + p + ZZ  = w1091001p22
  → SERVER  = s0  + XXX + 00 + Y          = s0910001.nacarpe.igrupobbva
```

> **Nota del mapfile real:** el tercer campo (IP) puede faltar en algunas entradas
> (`w1035401p01a|o0354p13`). El usuario puede ser personal (`P008967`) o genérico
> de oficina (`o0354p04` = `o` + agencia + `p` + puesto).

> **Nota Windows 11 en Sede Central:** el `.bat` deriva el `VMHOST` siempre con
> prefijo `w10`. Si una workstation de Sede corre Windows 11 (VM `w11...`), el
> registro queda como `w10...`; el filtro lo resuelve igual gracias al fallback
> `w10→w11`. Comportamiento intencional.

### Fase 1 — Registro de mapping (`update_winhostuser.bat` → `filtro_winhostuser`)

Al inicio de sesión, cada workstation envía su mapping al servidor Linux vía LPR a la cola `CPMWinHostUser`:

```
Workstation Windows                         Servidor Linux (cola CPMWinHostUser)
───────────────────                         ────────────────────────────────────
update_winhostuser.bat                      filtro_winhostuser
  1. Determina el hostname a enviar   ──►      1. Valida formato (3 campos, 2 pipes)
     (ver decisión Agencia/Sede)              2. Valida hostname (11-12 chars → 11)
  2. Detecta IP local del equipo              3. Valida usuario (o/p/xp) e IP (118.*)
  3. Envía: HOSTNAME|USUARIO|IP        LPR    4. Elimina duplicados por host o IP
                                              5. Escribe en win_hostname_user.txt
```

Formato almacenado en `/var/lib/lexmark/win_hostname_user.txt` (ejemplos reales):
```
w1035401p19|o0354p10|118.68.8.59      ← usuario genérico de oficina
w1035401p16|p008967|118.68.8.56       ← usuario personal
w1035401p01a|o0354p13                 ← sin IP (tercer campo ausente)
 (hostname 11-12)  (usuario)  (IP Windows, opcional)
```

**Decisión Agencia vs Sede Central en el `.bat`** (basada en el hostname Windows, `%COMPUTERNAME%`):

| Caso | Condición | Hostname enviado |
|---|---|---|
| **Agencia** | `%COMPUTERNAME%` es `W10XXX0YPZZ`, `W11XXX0YPZZ`, `W10XXX0YPZZA` o `W11XXX0YPZZA` | El propio hostname, truncado a 11 chars |
| **Sede Central** | Cualquier otro (`P017241`, `P017241A`, `XP12345`, `DESKTOP-*`, `W11PRUEBAOF3`, etc.) | `VMHOST` derivado de la MAC del VMX |

En agencias el hostname físico ya es válido (`W1...`); solo se trunca a 11 chars y
se envía tal cual. En Sede Central el nombre físico equivale al usuario
(ej. `P017241`) y no coincide con ninguna cola CUPS, por lo que se deriva el
`VMHOST` desde la MAC del VMX (ver "Derivación desde la MAC" arriba):

```
MAC "00:50:56:19:10:22"  ─►  VMHOST = w1091001p22   (w10 + 910 + 0 + 1 + p + 22)
```

**Fuentes del SERVER (destino del `lpr`):**

1. `D:\VirtAplic\VirtRM\virtconf.txt` (clave `srvhost=`): toma los **3 primeros
   octetos** de esa IP y **fuerza el 4.º octeto a `.210`** (ej. `srvhost=118.68.8.53`
   → `SERVER=118.68.8.210`).
2. Si no hay virtconf: deriva `s0XXX00Y.nacarpe.igrupobbva` desde la MAC del VMX.

En ambos casos, si existe el VMX se deriva además el `VMHOST` (necesario para Sede).

> **Limitación conocida:** una workstation VirtAplic **sin** archivo VMX no puede
> derivar el `VMHOST`. Un hostname de agencia funciona igual (no necesita VMHOST),
> pero un hostname de Sede Central caería en advertencia y se enviaría
> `%COMPUTERNAME%` (que no hará match). Pendiente de identificar la fuente del
> nombre de VM dentro de `virtconf.txt`.

### Fase 2 — Resolución en tiempo de impresión (`filtro_nacarpr`)

Cuando llega un trabajo a una cola CUPS, el filtro de producción resuelve la workstation destino:

```
1. lpstat  ──►  PUESTO (nombre de cola, 10 chars, ej. w035401p19)
2. finger  ──►  USUARIO LDAP de la sesión activa en ese puesto
3. ¿USUARIO = root?  ──► SÍ: job de Nacar Web → cola remota p1<puesto> → FIN
                          NO: continuar
4. Extrae AGENCIA, SERVLIN, POSXX del PUESTO
5. Busca en win_hostname_user.txt por regex:
      ^w10<AGENCIA>0[0-9]p<YY2>[A-Za-z]?\|      (fallback a w11)
6. Obtiene USUARIO final e IP:
      - USUARIO_GENERICO=ON  → usuario del mapfile (columna 2)
      - USUARIO_GENERICO=OFF → usuario del finger
      - FILTER_DNS_IP=0.0.0.0 → IP del mapfile (columna 3)
      - FILTER_DNS_IP=<IP>    → resuelve por DNS (fallback w10→w11)
7. Verifica puerto 515 abierto en la IP destino
8. Crea/actualiza cola dinámica: lpd://<IP>:515/LexmarkBBVA
9. Inyecta encabezado PJL + firma PCL y envía con lp
10. Fallback opcional a Tea4Cups (cola p<puesto>) para PDF
```

### Rol del `finger`

`finger` **solo** se usa para identificar el usuario LDAP con sesión activa en el puesto, cruzando la salida contra el `PUESTO`. No resuelve IP ni hostname de la VM. Ejemplo real de salida (columnas `Login` / `Name` / `Where`):

```
PE.P034887   PE.P034887   w035401p03.nacarpe.igrupobbva
 (login LDAP) (nombre)      (Where = PUESTO/cola CUPS de 10 chars, w0)
```

El `Where` es el **PUESTO de 10 chars** (`w0...`), que el filtro transforma al
hostname Windows de 11 chars (`w1...`) para buscar en el mapfile.

### Resumen del recorrido completo

```
[Arranque] Workstation ──LPR──► CPMWinHostUser ──► win_hostname_user.txt
                                                          │
[Impresión] Job ──► cola CUPS ──► filtro_nacarpr ─────────┘
                                        │  (busca IP por PUESTO en el mapfile)
                                        ▼
                          lpd://<IP_Windows>:515/LexmarkBBVA ──► Impresora
```

---

## 🚀 Quick Start

### Sistema de Producción (Lexmark CPM)

Ver sección "Manual del Sistema de Producción" más abajo para:
- Configuración de Lexmark CPM Client (componente principal)
- Configuración del servidor Linux SUSE (BBVA)
- Instalación de filtros CUPS
- Configuración de workstations Windows
- Troubleshooting completo

### Sistema de Contingencia (AlwaysPrint)

```bash
# Ver documentación completa
cd AlwaysPrintProject
cat README.md

# Cloud Manager - Backend
cd Cloud/backend
conda env create -f environment.yml
conda activate alwaysprint
alembic upgrade head
uvicorn app.main:app --reload

# Cloud Manager - Frontend
cd Cloud/frontend
npm install
npm run dev

# Client Windows
cd Client
.\build.ps1
msiexec /i AlwaysPrint.msi /qn
```

---

## 📚 Documentación

### Archivos en la Raíz
- **README.md** (este archivo) - Visión general del repositorio completo
- **AGENTS.md** - Reglas para agentes IA trabajando con filtros CUPS

### Sistema de Contingencia (AlwaysPrint)
- `AlwaysPrintProject/README.md` - Visión general del proyecto
- `AlwaysPrintProject/Cloud/README.md` - Cloud Manager (instalación, configuración)
- `AlwaysPrintProject/Cloud/ARCHITECTURE.md` - Arquitectura detallada multi-tenant
- `AlwaysPrintProject/Client/README.md` - Cliente Windows (compilación, instalación)
- `AlwaysPrintProject/Client/AlwaysPrint.Shared/README.md` - Biblioteca compartida
- `AlwaysPrintProject/Client/AlwaysPrintService/README.md` - Servicio Windows
- `AlwaysPrintProject/Client/AlwaysPrintTray/README.md` - Aplicación de bandeja

### Sistema de Producción (Lexmark CPM)
- Ver sección "Manual del Sistema de Producción" en este archivo (más abajo)
- **Componente principal**: Lexmark CPM Client en Windows
- **Infraestructura**: Servidor Linux SUSE 12 (BBVA)

---

## 📞 Contacto

Para consultas sobre este repositorio, contactar a través de los canales oficiales de Robles.AI.

---
---
---

# Manual del Sistema de Producción

Sistema principal de impresión corporativa BBVA basado en **Lexmark Cloud Print Manager (CPM) en modo Híbrido**.

**Estado**: ✅ Producción activa  
**Componente Principal**: Lexmark CPM Client (Windows)  
**Infraestructura**: Servidor Linux SUSE 12 + CUPS (BBVA)

---

## Descripción

**El sistema de producción es Lexmark Cloud Print Manager (CPM) en modo Híbrido**, que integra:

- **Lexmark CPM Client** en workstations Windows (componente principal que gestiona la impresión)
- **Servidor Linux SUSE 12** con CUPS y filtros personalizados (infraestructura BBVA, siempre operativa)
- **Cola LexmarkBBVA** en Windows que enruta trabajos a través de CPM
- Mapeado dinámico hostname→usuario→IP mantenido por los clientes Windows

**Flujo de Impresión en Producción**:
```
Usuario → Cola LexmarkBBVA (Windows) → Lexmark CPM Client → 
Servidor Linux CUPS → Filtros personalizados → Impresora física
```

**Nota importante**: El servidor Linux es responsabilidad de BBVA y está siempre operativo. Cuando Lexmark CPM falla, el sistema de contingencia AlwaysPrint redirige el tráfico directamente a las impresoras (bypass del servidor Linux).

---

## Requerimientos

### Servidor Linux (SUSE 12)
- **CUPS** instalado/activo
- **Carpeta de instalación:** `/root/bin`
- **Filtro producción:** `filtro_nacarpr_pro.cpm` → renombrar/copiar como `/root/bin/filtro_nacarpr` al desplegar
- **Filtro contingencia:** `filtro_contingencia_pro` → renombrar/copiar como `/root/bin/filtro_contingencia` al desplegar
- **cups-lpd** habilitado (xinetd) y **TCP/515** permitido desde las estaciones
- `sudo` para que el usuario **lp** ejecute `lpadmin`, `cupsenable`, `cupsaccept` sin contraseña
- **Backend LPD** con permisos de ejecución: `chmod 755 /usr/lib/cups/backend/lpd`
- **PPD** base: `/root/bin/Lexmark.Cups.ppd.gz`
- **Base de mapeo** dinámica: `/var/lib/lexmark/win_hostname_user.txt`
- **Configuración del filtro:** `/var/lib/lexmark/lexmark_filtro.config` (se crea automáticamente si no existe)
- **Logs**:
  - `/var/lib/lexmark/lexmark.log` → filtros `filtro_nacarpr` / `filtro_contingencia`
  - `/var/lib/lexmark/lexmark_winhostuser.log` → `filtro_winhostuser`

### Workstations Windows
- **Servicios LPR/LPD** habilitados (ver `SetupLPD/lprlpd.ps1`)
- **Cliente CPM** (recomendado ≥ 3.6.0) instalado con `configuration.json` adyacente
- **LpdServiceMonitor.msi** instalado como servicio
- **Script de arranque** `Startup/update_winhostuser.bat` configurado (Inicio del usuario o GPO)

---

## Configuración Linux

### 1) Conceder sudo a `lp` (visudo)
```sudoers
lp ALL=(ALL) NOPASSWD: /usr/sbin/lpadmin, /usr/sbin/cupsenable, /usr/sbin/cupsaccept
```

### 2) Habilitar `cups-lpd` (xinetd)
Editar `/etc/xinetd.d/cups-lpd`:
```conf
service printer {
    socket_type = stream
    protocol    = tcp
    wait        = no
    user        = lp
    group       = sys
    server      = /usr/lib/cups/daemon/cups-lpd
    server_args = -o document-format=application/octet-stream
    disable     = no
}
```
```bash
systemctl restart xinetd
ss -lntp | grep :515    # verificar escucha
```

### 3) Firewall con política INPUT=DROP
```bash
iptables -A INPUT -p tcp -s 118.63.108.0/24 --dport 515 -m state --state NEW -j ACCEPT
# Ajustar redes según TI. Persistir reglas según estándar de la distro.
```

### 4) Permisos al backend LPD de CUPS
```bash
sudo chmod 755 /usr/lib/cups/backend/lpd
```

### 5) Crear cola CPMWinHostUser (recepción de mapping)
```bash
/root/bin/create_CPMWinHostUser.sh
```
Esta cola recibe archivos enviados por Windows con el formato `hostname|usuario|ip` y actualiza `/var/lib/lexmark/win_hostname_user.txt`.

### 6) Configuración del filtro (`lexmark_filtro.config`)

El filtro de producción lee `/var/lib/lexmark/lexmark_filtro.config`. Se crea con valores por defecto si no existe. Parámetros:

| Parámetro | Valores | Comportamiento |
|---|---|---|
| `PLANTILLA_GRANDE` | `ON`/`OFF` | Si ON, puestos XX≥21 se mapean a YY=XX-10; puestos 11-20 son inválidos |
| `USUARIO_GENERICO` | `ON`/`OFF` | Si ON, usa el usuario del mapfile; si OFF, usa el usuario de `finger` |
| `FILTER_DNS_IP` | `0.0.0.0` o IP | Si es IP, resuelve el host Windows por DNS (fallback w10→w11); si `0.0.0.0`, usa el mapfile |

---

## Alta de colas de impresión (CUPS)

### A) Producción (CPM) — usa `filtro_nacarpr`
```bash
lpadmin -p w012301p01 -D 'Impresora con filtro_nacarpr Lexmark' -L 'filtro_nacarpr' -E \
  -v lpd://118.64.40.11:515/lp -i /root/bin/filtro_nacarpr
```

### B) Contingencia (directo a impresora física) — usa `filtro_contingencia`
El filtro detecta la IP real desde el `DEVICE_URI` de la cola y reenvía el spool original sin modificar.
```bash
lpadmin -p w012301p01 -D 'Impresora con filtro_contingencia Lexmark' -L 'filtro_contingencia' -E \
  -v lpd://118.64.40.11:515/lp -i /root/bin/filtro_contingencia
```

### C) Integración con Tea4Cups (opcional)
Si se requiere derivación a PDF, debe existir la cola CUPS `p<puesto>` (ej. `p012301p01`) configurada con el backend Tea4Cups. Los filtros la detectan y envían el spool original a dicha cola.

**Enrutamiento Tea4Cups según origen del job:**
- **Usuario `root` (Nacar Web):** el job se envía a `p1<puesto>` (cola remota en servidor sede central → archivo accesible via compartido de red desde fuera de la oficina) y el filtro termina sin procesar CPM.
- **Usuario LDAP:** flujo normal CPM + spool a `p<puesto>` (cola local Tea4Cups → PDF accesible via web del servidor Nacar dentro de la oficina).

---

## Preparación de Workstations Windows

### 1. Habilitar LPR/LPD
Ejecutar `SetupLPD/lprlpd.ps1` con privilegios de administrador.

### 2. Instalar servicio monitor LPD
```powershell
msiexec /i .\LpdServiceMonitor.msi /qn /L*v install.log
Get-Service LpdServiceMonitor
Get-Service LPDSVC
```
> El MSI instala en `C:\Program Files\RoblesAI\LPD Service Monitor\` con inicio automático en cuenta `LocalSystem`.

### 3. Configurar script de inicio
Agregar `Workstations/Startup/update_winhostuser.bat` al arranque (Inicio del usuario o GPO). Este script:
- Lee `virtconf.txt` (clave `srvhost=`) o `Nacar_Suse12.vmx` para deducir la IP del servidor Linux.
- Deriva el hostname de la VM Linux desde la MAC del VMX (necesario para Sede Central).
- Decide qué hostname enviar según `%COMPUTERNAME%` (ver "Arquitectura de Resolución de Impresión"):
  - **Agencia** (`W1######P##`): envía el hostname truncado a 11 chars.
  - **Sede Central** (`P######`, `XP#####`, etc.): envía el `VMHOST` derivado de la MAC.
- Detecta la IP válida del equipo.
- Envía `hostname|usuario|ip` a la cola Linux `CPMWinHostUser`.

> El script incluye un flag `DEBUG` (por defecto `1`) que imprime trazas `[DBG]` paso a paso. Para modo silencioso, ejecutar con `set DEBUG=0` o cambiar el valor por defecto. Los mensajes `[ERROR]` y `[ADVERTENCIA]` se muestran siempre.

### 4. Instalar cliente CPM
Ejecutar el instalador junto a `Client Installer/configuration.json` (deben estar en la misma carpeta):
- Cola `LexmarkBBVA`, driver `Lexmark Universal v2 XL`.
- Puertos internos 9167, 9443.
- PAC/Proxy Zscaler según `configuration.json`.

Ver `Workstations/Client Installer/README.md` para instrucciones completas.

---

## Verificaciones rápidas

### Servicios y conectividad
```bash
ss -lntp | grep :515          # cups-lpd escuchando
systemctl status xinetd       # xinetd activo
iptables -L -n | grep 515     # reglas de firewall
lpstat -v                     # colas CUPS y URIs
lpstat -p -d                  # estado de colas
cat /var/lib/lexmark/win_hostname_user.txt   # base de mapping
tail -f /var/lib/lexmark/lexmark.log         # log principal
bash -c "</dev/tcp/IP/515"    # test conectividad TCP/515
```

### Prueba manual LPR (Linux → Windows)
```bash
echo test > /var/lib/lexmark/test.txt
/usr/lib/cups/backend/lpd 999 user Job 1 "" /var/lib/lexmark/test.txt lpd://<WINIP>:515/LexmarkBBVA
```

### Firma de una cola asociada a `filtro_nacarpr` (producción)

Una cola CUPS correctamente configurada con el filtro de producción se ve así en
la interfaz web de CUPS (o en `lpstat`):

```
w091001p22 (inactiva, aceptando trabajos, compartida)
  Descripción:  Impresora con filtro_nacarpr Lexmark
  Ubicación:    filtro_nacarpr
  Controlador:  Local System V Printer (escala de grises)
  Conexión:     lpd://118.180.54.14:515/lp
```

Puntos a verificar:
- **Nombre de cola** con formato `w0XXX0YpZZ` (10 chars, prefijo `w0`).
- **Descripción/Ubicación** mencionan `filtro_nacarpr`.
- **Controlador** "Local System V Printer" (usa el interface script, no un PPD raw).
- **Estado normal**: "inactiva, aceptando trabajos, compartida" — la cola procesa
  bajo demanda; "inactiva" no significa deshabilitada.
- Un job cancelado con **"La impresora no responde"** corresponde al fallo del
  puerto 515 en la IP destino (el filtro aborta con `Puerto 515 cerrado`).

---

## Troubleshooting

**No llega mapping:** validar `update_winhostuser.bat` en consola, verificar cola `CPMWinHostUser` activa y revisar `/var/lib/lexmark/lexmark_winhostuser.log`.

**Puerto 515 cerrado:** revisar firewall local/segmento; en Linux verificar regla INPUT con `iptables -L -n | grep 515`.

**Cola apunta a IP incorrecta:** confirmar `/var/lib/lexmark/win_hostname_user.txt` y `lpstat -v <cola>`. El filtro auto-corrige la URI en el siguiente job.

**Host Windows no encontrado en mapfile:** el mapfile puede tener entradas `w11XXXXX` mientras la regex busca `w10XXXXX`. Verificar el prefijo real con `cat /var/lib/lexmark/win_hostname_user.txt`.

**Workstation de Sede Central sin entrada en mapfile:** el hostname físico Windows (`P017241`) no coincide con las colas CUPS. El `.bat` debe enviar el hostname de la VM (`w10...`) derivado de la MAC del VMX. Si la máquina es VirtAplic **sin** VMX, ese hostname no se puede derivar (limitación conocida): revisar la traza `[DBG]` del script y el log `lexmark_winhostuser.log` para confirmar qué se envió.

**Tea4Cups no genera PDF:** confirmar existencia de cola `p<puesto>` y que usa backend Tea4Cups.

**Verificar qué filtro está aplicado en una cola:**
```bash
# Listar interfaces instaladas en CUPS
ls -la /etc/cups/interfaces/

# Comparar cola específica con el fuente de producción
diff /etc/cups/interfaces/w034101p12 /root/bin/filtro_nacarpr
# Sin salida = filtro correcto. Con diferencias = reinstalar:
lpadmin -p w034101p12 -i /root/bin/filtro_nacarpr

# Detectar todas las colas con filtro desactualizado
for q in $(ls /etc/cups/interfaces/); do
  if ! diff -q "/etc/cups/interfaces/$q" /root/bin/filtro_nacarpr > /dev/null 2>&1; then
    echo "DESACTUALIZADA: $q"
  fi
done
```

**Habilitar debug en filtros:** descomentar `set -x` en la primera sección del filtro correspondiente en `/root/bin/`.

---

## Consideraciones de seguridad
- LPD es texto claro → limitar a redes internas y subredes permitidas.
- Limpiar periódicamente `/var/lib/lexmark` y rotar logs.
- `sudoers` restringido solo a binarios requeridos (`lpadmin`, `cupsenable`, `cupsaccept`).
- Proteger `configuration.json` y credenciales relacionadas.

---

## Operación diaria
- Revisar `/var/lib/lexmark/lexmark.log` ante incidencias de envío o creación de colas.
- Si cambia la IP del host Windows, `filtro_nacarpr` actualiza la cola automáticamente en el siguiente job.
- Para forzar recreación de una cola: `lpadmin -x w1<puesto>` y re-imprimir.
- Al desplegar una nueva versión del filtro: copiar `filtro_nacarpr_pro.cpm` como `/root/bin/filtro_nacarpr` y reinstalar en las colas afectadas con `lpadmin -p <cola> -i /root/bin/filtro_nacarpr`.


---

**Robles.AI**  
Email: antonio@robles.ai  
Teléfono: +1 408 590 0153  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados  
Producto de la familia de automatización Robles.AI  
Prohibida la utilización sin autorización de Inversiones On Line SAC
