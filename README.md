# Lexmark Cloud Print Manager – Filtros y Utilidades BBVA

Paquete con **scripts, configuraciones y utilidades** para integrar **Lexmark Cloud Print Manager (CPM)** en un entorno híbrido **Linux SUSE 12 (CUPS)** ⇄ **Windows (clientes CPM)**.

## Características principales

- Identificar al usuario/puesto Windows desde Linux (mapping dinámico).
- Enviar trabajos a **CPM** (normal) o a **impresora física por contingencia** (LPD directo), con copia opcional a **Tea4Cups** para PDF.
- Crear/actualizar colas CUPS dinámicamente.

> **Autor / Soporte:** Javier Robles – Lexmark International · 📧 antonio@robles.ai
> **Versión:** v202510231800

---

## 📂 Árbol del repositorio
```
.
├── Linux Server
│   └── root
│       └── bin
│           ├── create_CPMWinHostUser.sh
│           ├── filtro_contingencia
│           ├── filtro_nacarpr.cpm
│           ├── filtro_winhostuser
│           └── Lexmark.Cups.ppd.gz
├── README.md
└── Workstations
    ├── Client Installer
    │   ├── configuration.json
    │   └── README.md
    ├── SetupLPD
    │   ├── LpdServiceMonitor.msi
    │   └── lprlpd.ps1
    └── Startup
        └── update_winhostuser.bat
```

---

## ⚙️ Requerimientos

### Servidor Linux (SUSE 12)
- **CUPS** instalado/activo.
- **Carpeta de Instalación:** `/root/bin`
- **Filtro Principal:** `filtro_nacarpr` (Renombrar desde `filtro_nacarpr.cpm`)
- **cups-lpd** habilitado (xinetd) y **TCP/515** permitido desde las estaciones.
- `sudo` para que el usuario **lp** ejecute `lpadmin`, `cupsenable`, `cupsaccept` sin contraseña.
- **Backend LPD** con permisos de ejecución mediante `chmod 755 /usr/lib/cups/backend/lpd`
- **PPD** base: `/root/bin/Lexmark.Cups.ppd.gz`.
- **Base de mapeo** dinámica: `/var/lib/lexmark/win_hostname_user.txt`.
- **Logs**:
  - `/var/lib/lexmark/lexmark.log` → filtros `filtro_nacarpr` / `filtro_contingencia`.
  - `/var/lib/lexmark/lexmark_winhostuser.log` → `filtro_winhostuser`.

### Workstations Windows
- **Servicios LPR/LPD** habilitados (ver `SetupLPD/lprlpd.ps1`).
- **Cliente CPM** (recomendado ≥ 3.6.0) instalado con `configuration.json` adyacente.
- **LpdServiceMonitor.msi** instalado como servicio.
- **Script de arranque** `Startup/update_winhostuser.bat` configurado (Inicio del usuario o GPO).

---

## 🛠️ Configuración Linux — **Manual de uso**

### 1) Conceder sudo a `lp` (visudo)
Permite crear/activar colas sin intervención. Agregar en **visudo**:
```sudoers
lp ALL=(ALL) NOPASSWD: /usr/sbin/lpadmin, /usr/sbin/cupsenable, /usr/sbin/cupsaccept
```

### 2) Habilitar `cups-lpd` (xinetd)
Editar **/etc/xinetd.d/cups-lpd**:
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
Reiniciar xinetd: `systemctl restart xinetd`  
Verificar escucha: `ss -lntp | grep :515`

### 3) Firewall con política INPUT=DROP
Permitir **TCP/515** desde el segmento de agencias (ej. `118.63.108.0/24`). Ejemplo **iptables**:
```bash
iptables -A INPUT -p tcp -s 118.63.108.0/24 --dport 515 -m state --state NEW -j ACCEPT
# Ajustar redes según TI. Persistir reglas según estándar de la distro.
```

### 4) Permisos al backend LPD de CUPS
```bash
sudo chmod 755 /usr/lib/cups/backend/lpd
```

### 5) Crear cola **CPMWinHostUser** (recepción de mapping)
Ejecutar:
```bash
/root/bin/create_CPMWinHostUser.sh
# Internamente:
# lpadmin -p CPMWinHostUser -D 'Impresora CPM Win Host User' -L 'CPMWinHostUser' -E -v file:/dev/null -i /root/bin/filtro_winhostuser
```
Esta cola recibe archivos enviados por Windows con el formato: `hostname|usuario|ip` y actualiza `/var/lib/lexmark/win_hostname_user.txt`.

---

## 🖨️ Alta de colas de impresión (CUPS)

### A) **Producción (CPM)** — usa `filtro_nacarpr`
```bash
lpadmin -p w012301p01   -D 'Impresora con filtro_nacarpr Lexmark'   -L 'filtro_nacarpr' -E   -v lpd://118.64.40.11:515/lp   -i /root/bin/filtro_nacarpr
```

### B) **Contingencia (directo a impresora física)** — usa `filtro_contingencia`
> El filtro detecta la IP real de la impresora física desde el **DEVICE_URI** de la cola y reenvía el **spool original, sin modificar**, por LPR a `lpd://<IP>:515/lp`. Opcionalmente, duplica el trabajo a Tea4Cups para PDF.
```bash
lpadmin -p w012301p01   -D 'Impresora con filtro_contingencia Lexmark'   -L 'filtro_contingencia' -E   -v lpd://118.64.40.11:515/lp   -i /root/bin/filtro_contingencia
```

### C) Integración con **Tea4Cups** (opcional)
Si se requiere derivación a PDF, debe existir la cola CUPS `p<puesto>` (ej. `p012301p01`) **configurada al backend Tea4Cups**. Los filtros la detectan y envían el **spool original** a dicha cola.

---

## 💾 Scripts incluidos (detalle)

### `create_CPMWinHostUser.sh`
Crea la cola receptora de mapping `CPMWinHostUser` usando `filtro_winhostuser`.

**Comando principal:**
```bash
lpadmin -p CPMWinHostUser -D 'Impresora CPM Win Host User' -L 'CMPWinHostUser' -E -v file:/dev/null -i /root/bin/filtro_winhostuser
```

---

### `filtro_winhostuser`
**Objetivo:** Mantener una base de **mapping dinámico** `hostname → usuario → IP` para consumo de los demás filtros.

**Entrada esperada:** primera línea del spool con `hostname|usuario|ip`.

**Flujo y validaciones:**
- Lee solo la **primera línea** y normaliza CR/LF.
- Valida que existan exactamente **2 pipes** (3 campos).
- **Hostname** de 11–12 caracteres (se normaliza a 11).  
- **Usuario** debe iniciar con `o` o `p`.  
- **IP** debe iniciar con `118.`.
- Escribe/actualiza `DB=/var/lib/lexmark/win_hostname_user.txt` en formato `w1XXXXXXpXX|usuario|IP` **reemplazando** entradas previas del mismo host.
- Log: `/var/lib/lexmark/lexmark_winhostuser.log`.

**Salida:** `0` en éxito; ignora y sale `0` si el formato no es válido (no rompe el flujo de impresión).

---

### `filtro_nacarpr`
**Objetivo:** Enviar trabajos a **CPM en Windows** creando/ajustando **colas CUPS dinámicas** que apunten a la estación correcta y **añadiendo PJL** con metadatos del usuario/host/job.

**Pasos clave:**
1. Deriva `PUESTO`, `USUARIO`, `SPOOLTYPE` y consulta `MAPFILE=/var/lib/lexmark/win_hostname_user.txt` para obtener:
   - `GENERICO` (usuario mapeado) y `WINIP` de la estación.
2. Verifica **TCP/515** en `WINIP` (prueba de conectividad LPD).
3. **Crea/actualiza** la cola `CUPS_QUEUE="w1${PUESTO:1}"` con URI esperado `lpd://$WINIP:515/LexmarkBBVA` y PPD `Lexmark.Cups.ppd.gz`.
4. **Inserta PJL** (USERNAME, JOBNAME, HOLDKEY, etc.). Adapta encabezado para PCL5 / PostScript / HP PJL detectando tipo de spool.
5. Envía el **trabajo modificado** a CPM (`w1<puesto>`) y en paralelo envía el **spool original** a Tea4Cups `p<puesto>` si existe.

**Logs:** `/var/lib/lexmark/lexmark.log`.

**Errores comunes manejados:**
- Sin mapping para el puesto.
- Puerto 515 cerrado en destino.
- URI de la cola desalineado (se corrige automáticamente).

---

### `filtro_contingencia`
**Objetivo:** Bypass total de CPM cuando sea necesario. **Reenvía el spool original, sin modificar**, directo a la **impresora física** usando el backend LPD de CUPS.

**Pasos clave:**
1. Identifica la **cola ejecutora** (`PUESTO`) y el `DEVICE_URI` real de la cola (o lo obtiene vía `lpstat -v`).
2. Extrae la **IP física** desde el `DEVICE_URI` (`lpd://<IP>:515/...`).  
3. Llama al backend nativo **`/usr/lib/cups/backend/lpd`** con el archivo original.  
4. Si existe `p<puesto>`, **duplica** el envío del spool original a Tea4Cups para generación de PDF.  
5. Limpia temporales si corresponde y retorna el **exit code** del backend LPD.

**Logs:** `/var/lib/lexmark/lexmark.log`.

**Notas:**
- No altera el contenido del job (sin PJL extra).
- Usa `DEVICE_URI` de la cola como **fuente de verdad** para la IP física.

---

### `Lexmark.Cups.ppd.gz`
PPD genérico base utilizado por `filtro_nacarpr` para crear/actualizar colas dinámicas en CUPS.

---

## 🪟 Preparación de Workstations Windows

### 1. Habilitar LPR/LPD
Ejecutar `SetupLPD/lprlpd.ps1` con privilegios (habilita características de impresión LPD/LPR según política).

### 2. Instalar servicio monitor LPD

Instalar de forma silenciosa con log:

```powershell
msiexec /i .\LpdServiceMonitor.msi /qn /L*v install.log
```

Desinstalar:

```powershell
msiexec /x .\LpdServiceMonitor.msi /qn /L*v uninstall.log
```

> El MSI instala en `C:\Program Files\RoblesAI\LPD Service Monitor\` y crea el servicio
> **LpdServiceMonitor** (inicia automático, cuenta `LocalSystem`).

Comprobar estado:

```powershell
Get-Service LpdServiceMonitor
Get-Service LPDSVC
```

### 3. Configurar script de inicio
Agregar `Workstations/Startup/update_winhostuser.bat` al arranque (Inicio del usuario o GPO). Este script:
- Lee `virtconf.txt` (clave `srvhost=`) o `Nacar_Suse12.vmx` para deducir el **servidor** LPR.
- Detecta IP válida del equipo.
- Envía `hostname|usuario|ip` a la cola Linux `CPMWinHostUser`.

### 4. Instalar cliente CPM
Ejecutar el instalador (recomendado **3.6.0**) junto a `Client Installer/configuration.json`:
- Cola **LexmarkBBVA**.
- Driver **Lexmark Universal v2 XL**.
- Puertos internos 9167, 9443, 3334.
- PAC/Proxy según `configuration.json`.

---

## ✅ Verificaciones rápidas

### Servicios y conectividad
```bash
# Verificar cups-lpd
ss -lntp | grep :515
systemctl status xinetd

# Verificar firewall
iptables -L -n | grep 515

# Verificar colas CUPS
lpstat -v
lpstat -p -d

# Ver base de mapping
cat /var/lib/lexmark/win_hostname_user.txt
```

### Prueba manual LPR (Linux → Windows)
```bash
echo test > /var/lib/lexmark/test.txt
/usr/lib/cups/backend/lpd 999 user Job 1 "" /var/lib/lexmark/test.txt lpd://<WINIP>:515/LexmarkBBVA
```

---

## 🔒 Consideraciones de seguridad
- LPD es **texto claro** → limitar a redes internas y subredes permitidas.
- Limpiar periódicamente `/var/lib/lexmark` y rotar logs.
- `sudoers` restringido **solo** a binarios requeridos (`lpadmin`, `cupsenable`, `cupsaccept`).
- Proteger `configuration.json` y credenciales relacionadas.

---

## 🧰 Operación diaria
- Revisar `/var/lib/lexmark/lexmark.log` ante incidencias de envío o creación de colas.
- Si cambia la IP del host Windows, `filtro_nacarpr` actualizará la cola en el siguiente job.
- Para forzar recreación de cola: eliminar con `lpadmin -x w1<puesto>` y re‑imprimir.

---

## 🆘 Troubleshooting
- **No llega mapping**: validar `update_winhostuser.bat` (consola), `CPMWinHostUser` activa y logs `lexmark_winhostuser.log`.
- **Puerto 515 cerrado**: revisar firewall local/segmento; en Linux verificar regla INPUT.
- **Cola apunta a IP incorrecta**: confirmar `/var/lib/lexmark/win_hostname_user.txt` y **lpstat -v** de la cola dinámica.
- **Tea4Cups no genera PDF**: confirmar existencia de `p<puesto>` y backend configurado.

---

## 📑 Anexos
- Ejemplo de línea en DB de mapping:
  ```
  w1038401p12|ope01|118.45.23.12
  ```
- Fragmentos PJL aplicados (ver scripts) para `USERNAME`, `JOBNAME`, `HOLDKEY`, etc.

---

## 📝 Historial de cambios

- **v202510231800**: Actualización `filtro_nacarpr` (producción)
- **v202509190000**: Actualización `filtro_nacarpr` para reconocer como a PCL HP Printer Job y PJL encapsulated PostScript document text (Fix para Bug de comando file en Suse 12 que afecta a CPM)
- **v202509180000**: Restauración `filtro_winhostuser`
- **v202509170000**: Actualización de comandos `lpadmin` para colas CPM/Contingencia. Actualización de `update_winhostuser.bat` (Lectura de VirtAplic antes de VMX)
- **v202509150000**: Añadido `filtro_contingencia` (LPD directo sin modificar + Tea4Cups opcional)
- **v202509120000**: Manual de uso paso a paso, reglas de firewall y ejemplo de visudo
