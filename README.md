# Lexmark Cloud Print Manager – Filtros y Utilidades BBVA

Este paquete contiene scripts desarrollados para la integración de **Lexmark Cloud Print Manager (CPM)** en entornos **Linux SUSE 12** (servidores CUPS) y **Windows Cliente** (usuarios finales en BBVA).  

---

## 📂 Contenido

- **filtro_nacarpr**: Filtro CUPS que intercepta trabajos de impresión en Linux SUSE 12 y los redirige dinámicamente a las estaciones Windows correspondientes.  
- **filtro_winhostuser**: Script auxiliar que mantiene el archivo de mapeo entre hostname de la VM Linux, usuario Windows e IP.  
- **update_winhostuser.bat**: Script en Windows que genera un archivo temporal con `hostname|usuario|ip` y lo envía por LPR al servidor Linux (cola `CPMWinHostUser`).  

---

## ⚙️ Requerimientos

1. **Servidor Linux SUSE 12** con:
   - CUPS instalado y corriendo (`cupsd`).
   - Puerto LPD (515) habilitado (`cups-lpd` activo).
   - Permisos `sudo` para `lpadmin`.
   - Archivo de driver PPD: `/root/bin/Lexmark.Cups.ppd.gz`.
   - Archivo de mapping: `/tmp/win_hostname_user.txt`.

2. **Cliente Windows** con:
   - Lexmark Cloud Print Manager instalado y configurado.
   - Soporte para enviar jobs por LPR (`lpr.exe`).
   - Acceso de red al servidor Linux (`s0xxxx...nacarpe.igrupobbva`).

---

## 🖥️ Scripts

### 1. filtro_nacarpr

**Rol:** Filtro de impresión principal para CUPS en Linux.  

Funciones:
- Identifica spool recibido (SPOOLID, SPOOLNAME, SPOOLTYPE).
- Determina usuario y puesto de la VM Linux.
- Consulta el mapping (`/tmp/win_hostname_user.txt`) para obtener usuario genérico e IP de Windows.
- Verifica puerto 515 abierto en host destino.
- Crea la cola CUPS dinámica si no existe o actualiza la URI si cambió la IP.
- Inserta cabeceras PJL (usuario, jobname, holdkey).
- Procesa diferentes tipos de spool: HP Printer Job, PCL, PostScript.
- Envía el job modificado a la cola CUPS correspondiente.
- Log completo en `/tmp/lexmark.log`.

Logs generados:
- `/tmp/lexmark.log` → Registro detallado de cada spool y pasos.

---

### 2. filtro_winhostuser

**Rol:** Script en Linux para mantener actualizado el archivo de mapping (`/tmp/win_hostname_user.txt`).  

**Entrada esperada:**  
Archivo spool con la primera línea en formato:

    hostname|usuario|ip

Validaciones:
- Línea con exactamente 3 campos separados por `|`.
- Hostname con longitud 11 o 12 caracteres.
- Usuario debe comenzar con `o` o `p`.
- IP debe comenzar con `118.`

Acciones:
- Normaliza hostname a 11 caracteres.
- Elimina línea previa si existe y agrega la nueva.
- Registra cambios en `/tmp/lexmark_winhostuser.log`.

Ejemplo de línea en DB:

    w1038401p12|ope01|118.45.23.12

---

### 3. update_winhostuser.bat

**Rol:** Script ejecutado en cada estación Windows para enviar `hostname|usuario|ip` al servidor Linux.  

Pasos:
1. Lee `Nacar_Suse12.vmx` para obtener la MAC y calcular el servidor LPR destino (`s0xxxx00x.nacarpe.igrupobbva`).
2. Extrae el IP real del cliente Windows (evita 169.* y 127.*).
3. Genera cadena de datos: `%COMPUTERNAME%|%USERNAME%|%IP%`.
4. Escribe un archivo temporal `hostuser_XXXX.txt` en `%TEMP%`.
5. Envía al servidor con: `lpr -S %SERVER% -P CPMWinHostUser "%TEMPFILE%"`.
6. Elimina el archivo temporal.

Logs visibles en consola: MAC, server, queue, IP detectada, datos generados, ejecución de LPR.

---

## 📊 Flujo de Operación

    [Windows Cliente]
       |
       |  (update_winhostuser.bat con lpr)
       v
    [Linux SUSE: cola CPMWinHostUser]
       |
       |  (filtro_winhostuser actualiza /tmp/win_hostname_user.txt)
       v
    [Base de datos de mapping: /tmp/win_hostname_user.txt]
       |
       |  (filtro_nacarpr consulta mapping)
       v
    [Reenvío de spool vía LPD]
       |
       v
    [Windows Host destino con Lexmark CPM]

---

## 🔒 Consideraciones de Seguridad

- LPD (puerto 515) no cifra datos → usar solo en red interna segura.  
- Archivos temporales en `/tmp` deben limpiarse periódicamente.  
- Validaciones de formato en `filtro_winhostuser` reducen riesgo de corrupción en el mapping.  

---

## 📑 Archivos Importantes

- `/tmp/lexmark.log` → log principal de filtro_nacarpr.  
- `/tmp/lexmark_winhostuser.log` → log de actualizaciones.  
- `/tmp/win_hostname_user.txt` → base de datos mapping.  
- `/root/bin/Lexmark.Cups.ppd.gz` → driver para colas CUPS.  

---

## 👤 Autor / Soporte

- Javier Robles – Lexmark International  
- 📧 antonio@robles.ai  
- 🗓 Última actualización: 29/08/2025