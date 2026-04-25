# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Sistema híbrido Linux-Windows de gestión de impresión que integra **Lexmark Cloud Print Manager (CPM)** en el entorno bancario BBVA. La arquitectura utiliza:
- **Servidor Linux SUSE 12** ejecutando CUPS con filtros personalizados
- **Estaciones Windows** ejecutando cliente CPM con servicios LPD
- Mapeado dinámico hostname→usuario→IP mantenido por los clientes Windows

## Estructura del Repositorio

```
Linux Server/root/bin/
  filtro_nacarpr_pro.cpm      # Filtro producción CPM (versión actual v202603070100)
  filtro_nacarpr.cpm          # Filtro producción CPM (versión legacy v202510231800)
  filtro_contingencia_pro     # Filtro contingencia LPD directo (versión actual v202601180200)
  filtro_contingencia         # Filtro contingencia LPD directo (versión legacy v202509150000)
  filtro_winhostuser          # Receptor/actualizador de mapeado hostname→IP
  create_CPMWinHostUser.sh    # Crea la cola receptora de mapeados
  Lexmark.Cups.ppd.gz         # PPD base para colas dinámicas

Workstations/
  Startup/update_winhostuser.bat        # Envía mapeado al servidor Linux al inicio
  Client Installer/configuration.json   # Configuración cliente CPM
  Client Installer/README.md            # Instrucciones de instalación del cliente
  SetupLPD/lprlpd.ps1                   # Habilita servicios LPR/LPD en Windows
  SetupLPD/LpdServiceMonitor.msi        # Monitor de servicio LPD
```

Los archivos `_pro` son las versiones de producción actuales. Los archivos sin sufijo son versiones legacy mantenidas como referencia. Los `.cpm` son solo referencia — **no se despliegan directamente**; se copian y renombran (ver "Despliegue").

## Conceptos Clave de Arquitectura

### Dos Modos de Impresión

1. **Modo Producción** (`filtro_nacarpr_pro.cpm`): Enruta por CPM con cabeceras PJL
2. **Modo Contingencia** (`filtro_contingencia_pro`): LPD directo a impresora física, sin CPM

### Nomenclatura de Colas

Colas CUPS siguen el patrón `w10###0SpYY` donde:
- `###` = código de agencia (3 dígitos)
- `S` = identificador del servidor Linux (1 char)
- `YY` = número de puesto normalizado (2 dígitos)

La cola dinámica (`CUPS_QUEUE`) en la versión `_pro` coincide con `WINHOST` (`w10${AGENCIA}0${SERVLIN}p${YY2}`).

### Base de Datos de Mapeado

El archivo `/var/lib/lexmark/win_hostname_user.txt` contiene mapeados dinámicos en formato:
```
w1038401p12|ope01|118.45.23.12
```
Actualizado por los clientes Windows: `update_winhostuser.bat` → cola `CPMWinHostUser` → filtro `filtro_winhostuser`.

`filtro_winhostuser` elimina antes de insertar **todas** las entradas con el mismo hostname **y** todas las entradas con la misma IP, evitando duplicados por cambio de IP o reuso de equipo.

### Archivo de Configuración del Filtro

`/var/lib/lexmark/lexmark_filtro.config` controla el comportamiento del filtro `_pro`:

| Parámetro | Valores | Comportamiento |
|---|---|---|
| `PLANTILLA_GRANDE` | `ON`/`OFF` | Si ON, los puestos XX≥21 se mapean a YY=XX-10; puestos 11-20 son inválidos |
| `USUARIO_GENERICO` | `ON`/`OFF` | Si ON, usa el usuario del mapfile; si OFF, usa el usuario de `finger` |
| `FILTER_DNS_IP` | `0.0.0.0` o IP | Si es IP, resuelve el host Windows por DNS (con fallback w10→w11); si es `0.0.0.0`, usa el mapfile |

### Descubrimiento del Servidor Linux (Windows)

`update_winhostuser.bat` determina la IP del servidor Linux con dos métodos:
1. **virtconf.txt**: Lee `srvhost` de `D:\VirtAplic\VirtRM\virtconf.txt` y sustituye el último octeto por `.210`
2. **VMX MAC**: Extrae la MAC del archivo VMX de la VM (`C:\imagenes_12\Nacar_Suse12.vmx` o `C:\VMware\...`) y construye el hostname: `s0{char11}{char13}{char14}00{char10}.nacarpe.igrupobbva`

> **Dominios distintos**: el BAT usa `.nacarpe.igrupobbva` para resolver el servidor Linux; el filtro `_pro` usa `readonly DOMAIN="pe.igrupobbva"` para resolver los hosts Windows en modo DNS. Son dominios diferentes y no deben confundirse.

### Configuración Cliente CPM (Windows)

`Workstations/Client Installer/configuration.json`:
- Cola híbrida: `LexmarkBBVA` (puerto loopback 9167, universal 9443)
- Driver: `Lexmark Universal v2 XL`
- Proxy: PAC de Zscaler (`zscalertwo.net`)
- Late binding habilitado

## Archivos Críticos en Servidor Linux

### Binarios (`/root/bin`)
- `filtro_nacarpr_pro.cpm` → copiar como `filtro_nacarpr` al desplegar
- `filtro_contingencia_pro` → copiar como `filtro_contingencia` al desplegar
- `filtro_winhostuser` - no requiere renombrado

### Mapeados y Logs
- `/var/lib/lexmark/win_hostname_user.txt` - BD hostname→usuario→IP
- `/var/lib/lexmark/lexmark_filtro.config` - parámetros de comportamiento del filtro
- `/var/lib/lexmark/lexmark.log` - log principal de filtros
- `/var/lib/lexmark/lexmark_winhostuser.log` - log de actualizaciones de mapeado

## Comportamiento de Filtros

### `filtro_nacarpr_pro.cpm`
1. Lee configuración de `lexmark_filtro.config`
2. Extrae `PUESTO` desde nombre de cola CUPS via `lpstat` y `USUARIO` via `finger`; si `USUARIO=root`, el job proviene de **Nacar Web** (no sesión LDAP): lo reenvía a la cola Tea4Cups remota `p1${PUESTO:1}` y termina sin procesar CPM
3. Descompone nomenclatura: agencia, servidor Linux, número de puesto, calcula YY
4. Busca host Windows por regex `^w10${AGENCIA}0[0-9]p${YY2}[A-Za-z]?\|` en mapfile (modo MAP) o resuelve por DNS con fallback w10→w11 (modo DNS)
5. Determina usuario final (mapfile o finger según `USUARIO_GENERICO`)
6. Verifica conectividad TCP/515
7. Crea o actualiza cola CUPS dinámica con URI `lpd://$WINIP:515/LexmarkBBVA`
8. Inyecta cabeceras PJL (USERNAME, JOBNAME, HOLDKEY, etc.)
9. Maneja PCL5 (con caso especial UA011 Carta Fianza), PostScript y genérico
10. Envía a Tea4Cups local `p${PUESTO:1}` si la cola existe

### `filtro_contingencia_pro`
1. Extrae `USUARIO` via `finger`; si es `root` (Nacar Web), reenvía a `p1${PUESTO:1}` y termina
2. Extrae IP de impresora física desde `$DEVICE_URI` o `lpstat`
3. Envía spool original sin modificar via `/usr/lib/cups/backend/lpd`
4. Sin inyección PJL ni modificación del job
5. Envía a Tea4Cups local `p${PUESTO:1}` si la cola existe; propaga el código de retorno del backend LPD

### `filtro_winhostuser`
1. Lee primera línea del spool: `hostname|usuario|ip`
2. Valida: hostname 11-12 chars, usuario empieza con 'o'/'p'/'xp', IP empieza con '118.'
3. Normaliza hostname a 11 chars
4. Actualiza BD reemplazando entrada previa del mismo host

### Nomenclatura de Colas Tea4Cups

| Patrón | Construcción | Uso |
|---|---|---|
| `p${PUESTO:1}` | Elimina el primer char ('w') de PUESTO | Cola Tea4Cups local (captura PDF en agencia) |
| `p1${PUESTO:1}` | Prefixa con 'p1' | Cola remota sede central, para jobs de Nacar Web (usuario=root) |

## Despliegue

### Actualizar filtro de producción en servidor Linux
```bash
# Copiar versión _pro al nombre de despliegue
cp /root/bin/filtro_nacarpr_pro.cpm /root/bin/filtro_nacarpr
cp /root/bin/filtro_contingencia_pro /root/bin/filtro_contingencia

# Reinstalar filtro en todas las colas desactualizadas
for q in $(ls /etc/cups/interfaces/); do
  if ! diff -q "/etc/cups/interfaces/$q" /root/bin/filtro_nacarpr > /dev/null 2>&1; then
    lpadmin -p "$q" -i /root/bin/filtro_nacarpr
    echo "Actualizada: $q"
  fi
done
```

> **Importante**: `lpadmin -i` copia el filtro a `/etc/cups/interfaces/<cola>`. Los cambios al archivo fuente en `/root/bin/` **no afectan** las colas existentes hasta reinstalar.

## Creación de Colas

### Cola Producción (CPM)
```bash
lpadmin -p w012301p01 -D 'Impresora Lexmark CPM' -L 'filtro_nacarpr' -E \
  -v lpd://118.64.40.11:515/lp -i /root/bin/filtro_nacarpr
```

### Cola Contingencia (Directa)
```bash
lpadmin -p w012301p01 -D 'Impresora Lexmark Contingencia' -L 'filtro_contingencia' -E \
  -v lpd://118.64.40.11:515/lp -i /root/bin/filtro_contingencia
```

### Cola Receptora de Mapeados
```bash
/root/bin/create_CPMWinHostUser.sh
```

## Verificación y Diagnóstico

### Prueba Manual de Impresión (Linux → Windows)
```bash
echo test > /var/lib/lexmark/test.txt
/usr/lib/cups/backend/lpd 999 user Job 1 "" /var/lib/lexmark/test.txt lpd://118.63.108.x:515/LexmarkBBVA
```

### Estado de Servicios
```bash
ss -lntp | grep :515          # LPD escuchando
systemctl status xinetd       # xinetd activo
lpstat -v                     # colas CUPS y URIs
lpstat -p -d                  # estado de colas
cat /var/lib/lexmark/win_hostname_user.txt   # BD de mapeados
tail -f /var/lib/lexmark/lexmark.log         # log principal
tail -f /var/lib/lexmark/lexmark_winhostuser.log  # log mapeados
iptables -L -n | grep 515     # reglas de firewall
bash -c "</dev/tcp/IP/515"    # test conectividad TCP/515
```

### Verificar Filtro Aplicado en Colas CUPS

Los filtros se copian a `/etc/cups/interfaces/<nombre-cola>` al ejecutar `lpadmin -i`.
El archivo fuente de producción es `/root/bin/filtro_nacarpr` (que debe ser `filtro_nacarpr_pro.cpm` renombrado).

```bash
# Listar interfaces instaladas
ls -la /etc/cups/interfaces/

# Comparar el filtro aplicado en una cola con el fuente de producción
diff /etc/cups/interfaces/w034101p12 /root/bin/filtro_nacarpr

# Sin diferencias = filtro correcto aplicado.
# Con diferencias = la cola tiene una versión desactualizada; reinstalar:
lpadmin -p w034101p12 -i /root/bin/filtro_nacarpr

# Verificar todas las colas de producción de una vez
for q in $(ls /etc/cups/interfaces/); do
  if ! diff -q "/etc/cups/interfaces/$q" /root/bin/filtro_nacarpr > /dev/null 2>&1; then
    echo "DESACTUALIZADA: $q"
  fi
done
```

### Habilitar Debug en Filtros
Descomentar `set -x` en la primera sección del filtro correspondiente.

## Configuración del Cliente Windows

### Habilitar LPD/LPR
```powershell
# Ejecutar lprlpd.ps1 con permisos de administrador
dism /online /Enable-Feature /FeatureName:Printing-Foundation-LPDPrintService /All /NoRestart
dism /online /Enable-Feature /FeatureName:Printing-Foundation-LPRPortMonitor /All /NoRestart
```

### Instalar Monitor LPD
```powershell
msiexec /i .\LpdServiceMonitor.msi /qn /L*v install.log
Get-Service LpdServiceMonitor
Get-Service LPDSVC
```

### Instalar Cliente CPM
Ver `Workstations/Client Installer/README.md` para instrucciones completas.
El `.exe` y `configuration.json` deben estar en la misma carpeta al instalar.

## Problemas Comunes

### Sin mapeado para la estación
- Verificar que `update_winhostuser.bat` se ejecuta al inicio
- Comprobar que la cola `CPMWinHostUser` existe y está habilitada
- Revisar `/var/lib/lexmark/lexmark_winhostuser.log`

### Puerto 515 cerrado
- Verificar reglas de firewall en servidor Linux y cliente Windows
- Confirmar xinetd activo y cups-lpd habilitado
- Test: `bash -c "</dev/tcp/IP/515"`

### Cola apunta a IP incorrecta
- Revisar mapfile: `/var/lib/lexmark/win_hostname_user.txt`
- Verificar: `lpstat -v <nombre_cola>`
- El filtro auto-corrige la URI en el siguiente job de impresión

### Tea4Cups no genera PDF
- Confirmar que existe la cola `p<puesto>`
- Verificar que la cola usa backend Tea4Cups

## Seguridad

- LPD es texto plano — restringir a redes internas
- Firewall permite TCP/515 solo desde subredes autorizadas (ej. `118.63.108.0/24`)
- `sudoers` limitado a: `lpadmin`, `cupsenable`, `cupsaccept` para usuario `lp`
- Permisos backend: `chmod 755 /usr/lib/cups/backend/lpd`

## Convención de Versiones

El formato es `vYYYYMMDDhhmm`:
- v202603070100: `filtro_nacarpr_pro.cpm` — versión actual con soporte DNS, USUARIO_GENERICO, fallback w10→w11 en modo MAPA
- v202601180200: `filtro_contingencia_pro` — versión actual
- v202510231800: `filtro_nacarpr.cpm` — versión legacy
- v202509150000: `filtro_contingencia` — versión legacy
