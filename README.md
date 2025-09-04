# Lexmark Cloud Print Manager – Filtros y Utilidades BBVA

Este paquete contiene los scripts, configuraciones y utilidades desarrollados para la integración de **Lexmark Cloud Print Manager (CPM)** en entornos híbridos **Linux SUSE 12 (servidores CUPS)** y **Windows Cliente** (usuarios finales en BBVA).  

Está diseñado para gestionar la interceptación, transformación y redirección de trabajos de impresión entre entornos virtualizados y los hosts Windows con CPM.

---

## 📂 Estructura de Archivos
```
.
├── Linux Server
│   └── root
│       └── bin
│           ├── filtro_nacarpr
│           ├── filtro_winhostuser
│           └── Lexmark.Cups.ppd.gz
├── README.md
└── Workstations
    ├── Client Installer
    │   ├── configuration.json
    └── Startup
        └── update_winhostuser.bat
```
---

## ⚙️ Requerimientos

### Servidor Linux SUSE 12
- CUPS (`cupsd`) instalado y activo.
- cups-lpd habilitado (puerto 515 TCP abierto).
- Permisos de administración (`sudo` para `lpadmin`).
- Archivo de driver PPD: `/root/bin/Lexmark.Cups.ppd.gz`.
- Base de datos de mapping dinámico: `/tmp/win_hostname_user.txt`.
- Logs:
  - `/tmp/lexmark.log` → jobs procesados por `filtro_nacarpr`.
  - `/tmp/lexmark_winhostuser.log` → actualizaciones de mapping.

### Cliente Windows
- Lexmark Cloud Print Manager (v. 3.5.3).
- Soporte de impresión por `lpr.exe`.
- Acceso de red hacia el servidor SUSE (`*.nacarpe.igrupobbva`).
- Script `update_winhostuser.bat` en carpeta `Startup`.

---

## 🖥️ Scripts

### 1. filtro_nacarpr (Linux)
Filtro principal de impresión en CUPS:  
- Identifica spool y usuario.  
- Consulta mapping (`/tmp/win_hostname_user.txt`).  
- Verifica puerto 515 en destino.  
- Crea/actualiza cola CUPS dinámica.  
- Inserta cabeceras PJL (USERNAME, JOBNAME, HOLDKEY).  
- Soporta PCL, PostScript y HP Printer Job.  
- Log completo en `/tmp/lexmark.log`.

### 2. filtro_winhostuser (Linux)
Mantiene actualizado el mapping:  
- Entrada: `hostname|usuario|ip`.  
- Valida formato (hostname 11–12 chars, usuario `o/p*`, IP `118.*`).  
- Normaliza y actualiza `/tmp/win_hostname_user.txt`.  
- Log en `/tmp/lexmark_winhostuser.log`.

Ejemplo en DB:
w1038401p12|ope01|118.45.23.12

### 3. update_winhostuser.bat (Windows)
Ejecutado al inicio de sesión:  
1. Lee `Nacar_Suse12.vmx` para MAC → calcula servidor LPR.  
2. Detecta IP válida (evita 169.* y 127.*).  
3. Genera cadena `hostname|usuario|ip`.  
4. Envía archivo temporal con `lpr`.  
5. Borra archivo temporal.  
6. Muestra logs en consola.

### 4. configuration.json (Windows)
Archivo de configuración CPM:  
- Servidores (`idpServerUrl`, `cpmServerUrl`).  
- Cola predeterminada: `LexmarkBBVA`.  
- Driver: `Lexmark Universal v2 XL`.  
- Puertos internos: 9167, 9443, 3334.  
- Validación de certificados y proxy PAC (`pac.zscalertwo.net`).  

---

## 📊 Flujo de Operación
```
[Windows Cliente]  
   ↓ (update_winhostuser.bat → LPR)  
[Linux SUSE: cola CPMWinHostUser]  
   ↓ (filtro_winhostuser actualiza mapping)  
[/tmp/win_hostname_user.txt]  
   ↓ (filtro_nacarpr reenvía spool)  
[CUPS dinámica → LPD 515]  
   ↓  
[Windows Host con CPM]
```
---

## 🔒 Consideraciones de Seguridad
- LPD (515) transmite sin cifrado → usar solo en red interna.  
- Archivos temporales en `/tmp` deben limpiarse periódicamente.  
- Validaciones de `filtro_winhostuser` mitigan corrupción de DB.  
- Proteger `configuration.json` (parámetros sensibles).  

---

## 📑 Archivos Clave
- `/root/bin/filtro_nacarpr`  
- `/root/bin/filtro_winhostuser`  
- `/root/bin/Lexmark.Cups.ppd.gz`  
- `/tmp/lexmark.log`  
- `/tmp/lexmark_winhostuser.log`  
- `/tmp/win_hostname_user.txt`  
- `Workstations/Startup/update_winhostuser.bat`  
- `Workstations/Client Installer/configuration.json`  

---

## 👤 Autor / Soporte
- Javier Robles – Lexmark International  
- 📧 antonio@robles.ai  
- 🗓 Última actualización: 04/09/2025