# Lexmark Cloud Print Manager – Filtros y Utilidades BBVA

Paquete con **scripts, configuraciones y utilidades** para integrar **Lexmark Cloud Print Manager (CPM)** en un entorno híbrido **Linux SUSE 12 (CUPS)** ⇄ **Windows (clientes CPM)**. 

Permite:
- Identificar al usuario/puesto Windows desde Linux (mapping dinámico).
- Enviar trabajos a **CPM** (normal) o a **impresora física por contingencia** (LPD directo), con copia opcional a **Tea4Cups** para PDF.
- Crear/actualizar colas CUPS dinámicamente.

> **Autor / Soporte:** Javier Robles – Lexmark International · 📧 antonio@robles.ai  
> **Versión:** v2025-09-15

---

## 📂 Árbol del repositorio
```
.
├── Linux Server
│   └── root
│       └── bin
│           ├── create_CPMWinHostUser.sh
│           ├── filtro_contingencia
│           ├── filtro_nacarpr
│           ├── filtro_winhostuser
│           └── Lexmark.Cups.ppd.gz
├── README.md
└── Workstations
    ├── Client Installer
    │   ├── configuration.json
    │   └── LPMC_3.5.3_UPD_PCLXL_3.0.7.0_Win_2.2.73.exe
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
- **cups‑lpd** habilitado (xinetd) y **TCP/515** permitido desde las estaciones.
- `sudo` para que el usuario **lp** ejecute `lpadmin`, `cupsenable`, `cupsaccept` sin contraseña.
- **PPD** base: `/root/bin/Lexmark.Cups.ppd.gz`.
- **Base de mapeo** dinámica: `/tmp/win_hostname_user.txt`.
- **Logs**:
  - `/tmp/lexmark.log` → filtros `filtro_nacarpr` / `filtro_contingencia`.
  - `/tmp/lexmark_winhostuser.log` → `filtro_winhostuser`.

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
# lpadmin -p CPMWinHostUser -D 'Impresora CPM Win Host User' -L 'CMPWinHostUser' -E -v file:/dev/null -i /root/bin/filtro_winhostuser
```
Esta cola recibe archivos enviados por Windows con el formato: `hostname|usuario|ip` y actualiza `/tmp/win_hostname_user.txt`.

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

## 💾 Scripts incluidos (resumen)

### `create_CPMWinHostUser.sh`
Crea la cola receptora de mapping `CPMWinHostUser` usando `filtro_winhostuser`.

### `filtro_winhostuser`
- Entrada: `hostname|usuario|ip` (1ª línea del spool).  
- Validaciones: hostname 11–12 chars; usuario inicia con `o`/`p`; IP inicia con `118.`.  
- Normaliza a 11 chars y **actualiza** `/tmp/win_hostname_user.txt` (formato: `w1XXXXXXpXX|usuario|IP`).
- Log: `/tmp/lexmark_winhostuser.log`.

### `filtro_nacarpr`
- Obtiene `PUESTO`, `USUARIO`, `SPOOLTYPE` y **maping** desde `/tmp/win_hostname_user.txt`.
- Verifica **TCP/515** en el Windows destino; crea/actualiza **cola CUPS dinámica** `w1<puesto>` apuntando a `lpd://<WINIP>:515/LexmarkBBVA` (driver `Lexmark.Cups.ppd.gz`).
- Inserta **PJL** (USERNAME, JOBNAME, HOLDKEY, etc.). Soporta PCL/PostScript/HP PJL.
- Envía a la cola destino; opcionalmente duplica **spool original** a Tea4Cups `p<puesto>`.
- Log: `/tmp/lexmark.log`.

### `filtro_contingencia`
- Identifica **cola ejecutora** y **DEVICE_URI**; extrae **IP física** de la impresora.
- Reenvía **sin modificar** por backend LPD nativo de CUPS.
- Si existe `p<puesto>`, también envía el original a Tea4Cups.
- Log: `/tmp/lexmark.log`.

---

## 🪟 Preparación de Workstations Windows

1. **Habilitar LPR/LPD**  
   Ejecutar `SetupLPD/lprlpd.ps1` con privilegios (habilita características de impresión LPD/LPR según política).

2. **Instalar servicio monitor**  
   ```bat
   msiexec /i SetupLPD\LpdServiceMonitor.msi /qn
   ```

3. **Configurar script de inicio**  
   Agregar `Workstations/Startup/update_winhostuser.bat` al arranque (Inicio del usuario o GPO). Este script:
   - Lee `Nacar_Suse12.vmx` para deducir el **servidor** LPR.
   - Detecta IP válida del equipo.
   - Envía `hostname|usuario|ip` a la cola Linux `CPMWinHostUser`.

4. **Instalar CPM**  
   Ejecutar el instalador (recomendado **3.6.0**) junto a `Client Installer/configuration.json`:
   - Cola **LexmarkBBVA**.
   - Driver **Lexmark Universal v2 XL**.
   - Puertos internos 9167, 9443, 3334.
   - PAC/Proxy según `configuration.json`.

---

## ✅ Verificaciones rápidas
- **cups‑lpd**: `ss -lntp | grep :515` · `systemctl status xinetd`  
- **Firewall**: `iptables -L -n | grep 515`  
- **Colas CUPS**: `lpstat -v` · `lpstat -p -d`  
- **Mapping**: ver `/tmp/win_hostname_user.txt`
- **Prueba manual LPR** (Linux → Windows):
  ```bash
  echo test > /tmp/test.txt
  /usr/lib/cups/backend/lpd 999 user Job 1 "" /tmp/test.txt lpd://<WINIP>:515/LexmarkBBVA
  ```

---

## 🔒 Consideraciones de seguridad
- LPD es **texto claro** → limitar a redes internas y subredes permitidas.
- Limpiar periódicamente `/tmp` y rotar logs.
- `sudoers` restringido **solo** a binarios requeridos (`lpadmin`, `cupsenable`, `cupsaccept`).
- Proteger `configuration.json` y credenciales relacionadas.

---

## 🧰 Operación diaria
- Revisar `/tmp/lexmark.log` ante incidencias de envío o creación de colas.
- Si cambia la IP del host Windows, `filtro_nacarpr` actualizará la cola en el siguiente job.
- Para forzar recreación de cola: eliminar con `lpadmin -x w1<puesto>` y re‑imprimir.

---

## 🆘 Troubleshooting
- **No llega mapping**: validar `update_winhostuser.bat` (consola), `CPMWinHostUser` activa y logs `lexmark_winhostuser.log`.
- **Puerto 515 cerrado**: revisar firewall local/segmento; en Linux verificar regla INPUT.
- **Cola apunta a IP incorrecta**: confirmar `/tmp/win_hostname_user.txt` y **lpstat -v** de la cola dinámica.
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
- **2025‑09‑15**: Añadido **filtro_contingencia** (LPD directo sin modificar + Tea4Cups opcional). Manual de uso paso a paso, reglas de firewall y ejemplo de visudo. Mejora de validaciones en `filtro_winhostuser`. Actualización de comandos `lpadmin` para colas CPM/Contingencia.
