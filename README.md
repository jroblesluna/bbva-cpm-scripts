# Lexmark Cloud Print Manager – Filtros y Utilidades BBVA

Paquete con **scripts, configuraciones y utilidades** para integrar **Lexmark Cloud Print Manager (CPM)** en un entorno híbrido **Linux SUSE 12 (CUPS)** ⇄ **Windows (clientes CPM)**.

## Características principales

- Identificar al usuario/puesto Windows desde Linux (mapping dinámico).
- Enviar trabajos a **CPM** (normal) o a **impresora física por contingencia** (LPD directo), con copia opcional a **Tea4Cups** para PDF.
- Crear/actualizar colas CUPS dinámicamente.
- Enrutamiento diferenciado Tea4Cups: cola remota sede central (Nacar Web) vs cola local (usuario LDAP).

> **Autor / Soporte:** Javier Robles – Lexmark International · antonio@robles.ai

---

## Árbol del repositorio

```
.
├── Linux Server
│   └── root
│       └── bin
│           ├── create_CPMWinHostUser.sh
│           ├── filtro_contingencia            ← legacy (referencia)
│           ├── filtro_contingencia_pro        ← versión actual de producción
│           ├── filtro_nacarpr.cpm             ← legacy (referencia)
│           ├── filtro_nacarpr_pro.cpm         ← versión actual de producción
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

> Los archivos `_pro` son las versiones activas. Los archivos sin sufijo son versiones legacy mantenidas como referencia. **No modificar los legacy.**

---

## Requerimientos

### Servidor Linux (SUSE 12)
- **CUPS** instalado/activo.
- **Carpeta de instalación:** `/root/bin`
- **Filtro producción:** `filtro_nacarpr_pro.cpm` → renombrar/copiar como `/root/bin/filtro_nacarpr` al desplegar.
- **Filtro contingencia:** `filtro_contingencia_pro` → renombrar/copiar como `/root/bin/filtro_contingencia` al desplegar.
- **cups-lpd** habilitado (xinetd) y **TCP/515** permitido desde las estaciones.
- `sudo` para que el usuario **lp** ejecute `lpadmin`, `cupsenable`, `cupsaccept` sin contraseña.
- **Backend LPD** con permisos de ejecución: `chmod 755 /usr/lib/cups/backend/lpd`
- **PPD** base: `/root/bin/Lexmark.Cups.ppd.gz`.
- **Base de mapeo** dinámica: `/var/lib/lexmark/win_hostname_user.txt`.
- **Configuración del filtro:** `/var/lib/lexmark/lexmark_filtro.config` (se crea automáticamente si no existe).
- **Logs**:
  - `/var/lib/lexmark/lexmark.log` → filtros `filtro_nacarpr` / `filtro_contingencia`.
  - `/var/lib/lexmark/lexmark_winhostuser.log` → `filtro_winhostuser`.

### Workstations Windows
- **Servicios LPR/LPD** habilitados (ver `SetupLPD/lprlpd.ps1`).
- **Cliente CPM** (recomendado ≥ 3.6.0) instalado con `configuration.json` adyacente.
- **LpdServiceMonitor.msi** instalado como servicio.
- **Script de arranque** `Startup/update_winhostuser.bat` configurado (Inicio del usuario o GPO).

---

## Configuración Linux — Manual de uso

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

## Scripts incluidos (detalle)

### `filtro_nacarpr` (producción: `filtro_nacarpr_pro.cpm`)
**Objetivo:** Enviar trabajos a CPM en Windows creando/ajustando colas CUPS dinámicas con cabeceras PJL.

**Pasos clave:**
1. Extrae `PUESTO` desde `lpstat` y `USUARIO` desde `finger` (fallback a `$2`).
2. Si `USUARIO=root` (Nacar Web): envía spool a `p1<puesto>` (sede central) y termina.
3. Consulta `win_hostname_user.txt` (modo MAPA) o resuelve por DNS con fallback w10→w11 (modo DNS) para obtener `WINIP`.
4. Verifica **TCP/515** en `WINIP`.
5. Crea/actualiza cola CUPS dinámica `w10<agencia>0<srv>p<YY>` con URI `lpd://$WINIP:515/LexmarkBBVA`.
6. Inserta PJL (USERNAME, JOBNAME, HOLDKEY, etc.). Adapta para PCL5 / PostScript / HP PJL.
7. Envía trabajo modificado a CPM y spool original a Tea4Cups `p<puesto>` si existe.

### `filtro_contingencia` (producción: `filtro_contingencia_pro`)
**Objetivo:** Bypass total de CPM. Reenvía el spool original sin modificar a la impresora física.

**Pasos clave:**
1. Identifica `PUESTO` y extrae IP física desde `$DEVICE_URI` o `lpstat -v`.
2. Llama al backend nativo `/usr/lib/cups/backend/lpd` con el archivo original.
3. Si existe `p<puesto>`, duplica envío a Tea4Cups para PDF.
4. Retorna el exit code del backend LPD.

### `filtro_winhostuser`
**Objetivo:** Mantener la base de mapping dinámico `hostname → usuario → IP`.

**Entrada:** primera línea del spool con `hostname|usuario|ip`.

**Validaciones:**
- Hostname: 11–12 caracteres (normaliza a 11).
- Usuario: debe iniciar con `o` o `p`.
- IP: debe iniciar con `118.`.

Actualiza `/var/lib/lexmark/win_hostname_user.txt` reemplazando entradas previas del mismo host.

### `create_CPMWinHostUser.sh`
Crea la cola receptora de mapping `CPMWinHostUser`:
```bash
lpadmin -p CPMWinHostUser -D 'Impresora CPM Win Host User' -L 'CMPWinHostUser' -E \
  -v file:/dev/null -i /root/bin/filtro_winhostuser
```

### `Lexmark.Cups.ppd.gz`
PPD genérico base utilizado por `filtro_nacarpr` para crear colas dinámicas CUPS.

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

## Anexos
Ejemplo de línea en BD de mapping:
```
w1038401p12|ope01|118.45.23.12
```

---

## Historial de cambios

- **v202601180100**: `filtro_nacarpr_pro.cpm` — soporte DNS con fallback w10→w11, parámetros `USUARIO_GENERICO` y `FILTER_DNS_IP`, enrutamiento Tea4Cups diferenciado root (Nacar Web) vs LDAP, funciones auxiliares con timestamps en log.
- **v202601180200**: `filtro_contingencia_pro` — refactorización con funciones auxiliares y manejo de errores mejorado.
- **v202510231800**: `filtro_nacarpr.cpm` — versión legacy, mantenida como referencia.
- **v202509190000**: Fix reconocimiento PCL `HP Printer Job` y `PJL encapsulated PostScript` (bug `file` en SUSE 12).
- **v202509180000**: Restauración `filtro_winhostuser`.
- **v202509170000**: Actualización comandos `lpadmin`. `update_winhostuser.bat`: lectura VirtAplic antes de VMX.
- **v202509150000**: `filtro_contingencia` — LPD directo sin modificar + Tea4Cups opcional.
- **v202509120000**: Manual de uso paso a paso, reglas de firewall y ejemplo de visudo.
