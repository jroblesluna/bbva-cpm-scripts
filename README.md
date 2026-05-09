# Repositorio de Sistemas de Impresión Corporativa BBVA

Este repositorio contiene dos sistemas complementarios para gestión de impresión corporativa.

**Última actualización**: 8 de mayo de 2026

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
- Detecta la IP válida del equipo.
- Envía `hostname|usuario|ip` a la cola Linux `CPMWinHostUser`.

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

---

## Troubleshooting

**No llega mapping:** validar `update_winhostuser.bat` en consola, verificar cola `CPMWinHostUser` activa y revisar `/var/lib/lexmark/lexmark_winhostuser.log`.

**Puerto 515 cerrado:** revisar firewall local/segmento; en Linux verificar regla INPUT con `iptables -L -n | grep 515`.

**Cola apunta a IP incorrecta:** confirmar `/var/lib/lexmark/win_hostname_user.txt` y `lpstat -v <cola>`. El filtro auto-corrige la URI en el siguiente job.

**Host Windows no encontrado en mapfile:** el mapfile puede tener entradas `w11XXXXX` mientras la regex busca `w10XXXXX`. Verificar el prefijo real con `cat /var/lib/lexmark/win_hostname_user.txt`.

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
