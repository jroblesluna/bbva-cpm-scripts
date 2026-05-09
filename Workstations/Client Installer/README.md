# Client Installer

El ejecutable del cliente de Lexmark Cloud Print Manager **no se incluye** en este repositorio debido a su tamaño (~160 MB).  
Existen **dos formas** de obtener el instalador actualizado:

---

## 📥 Método 1: Descarga desde Google Drive (versión validada)
- **Fuente (Google Drive):** <https://drive.google.com/file/d/1LsV04QTjbRpztplooVyfXX2Y2QRyqmPP/view>
- **Archivo esperado:** `LPMC_3.6.0_UPD_PCLXL_3.0.8.0_Win_2.2.91.exe`

Coloca el archivo descargado en este mismo directorio (`Workstations/Client Installer`).

> **Sugerencia:** Conserva una copia interna (Share/Drive corporativo) con control de versiones y checksums.

### 🔐 Verificación de integridad (opcional)
Una vez descargado el `.exe`, calcula su **SHA256** y archívalo junto a este README.

- **Windows (PowerShell):**
```powershell
Get-FileHash '.\LPMC_3.6.0_UPD_PCLXL_3.0.8.0_Win_2.2.91.exe' -Algorithm SHA256
```

- **Linux / macOS:**
```bash
shasum -a 256 "LPMC_3.6.0_UPD_PCLXL_3.0.8.0_Win_2.2.91.exe"
# o
openssl dgst -sha256 "LPMC_3.6.0_UPD_PCLXL_3.0.8.0_Win_2.2.91.exe"
```

> **SHA256 esperado:**
```bash
24f20ad5f2865cea5566e4e43baecd56454fa415534d418b95e0473ff7f69485
```
---

## ☁️ Método 2: Generar paquete desde la Cloud CPM de Lexmark (última versión)

1. Acceder al portal **Cloud CPM de Lexmark**.
2. Ir a **Gestión de la Impresión** → **Clientes de Impresión**.
3. Seleccionar:
   - **Cliente:** Windows®
   - **Tipo de paquete:** Personalizado
4. En las opciones de configuración:
   - **Desactivar**: Cloud Print Management
   - **Activar**: Hybrid Print Management
   - **Nombre de cola personalizado:** `LexmarkBBVA`
   - **Permitir cambios de configuración en liberación**: habilitado
5. Presionar **Create Package**.
6. Descargar el **ZIP** generado, que contiene:
   - `LPMC_xxx.exe`
   - `configuration.json`  
   Ambos deben permanecer **juntos en la misma carpeta**.

### 🔧 Modificación requerida en `configuration.json`
Añadir (o actualizar) la sección del proxy:
```json
"webProxySettings" : {
  "enabled" : true,
  "address" : "http://pac.zscalertwo.net/qcNztsBj8RN7/PER_NOAGENTE_ZS_v2.pac"
}
```

### ⚠️ Importante
- Ejecutar el `.exe` **con permisos administrativos**.
- Se adjunta un `configuration.json` de referencia en este repositorio.

---

## ⚙️ Configuración acompañante
Deja **`configuration.json`** en este mismo directorio, ya que el instalador lo detecta para aplicar la configuración (cola `LexmarkBBVA`, driver `Lexmark Universal v2 XL`, puertos, PAC, etc.).

---

## 🧭 Ruta esperada en el instalador (ejemplo)
```
Proyecto_Cloud/
└── Client_Installer/
    ├── configuration.json        # referencia o modificado
    ├── LPMC_3.6.x_xxx.exe        # descargado según el método elegido
```

---

## 🖥️ Instalación interactiva
Haz doble clic sobre el `.exe` con permisos administrativos y sigue el asistente. Verifica que queden creadas las colas y servicios esperados por CPM.

## 🤖 Instalación silenciosa (para software distribution)
Ejemplos de parámetros típicos de instaladores NSIS/InstallShield/MSI. **Ajusta según el tipo real del instalador** si difiere:

- **Si es MSI** (o expone MSI interno):
```bat
msiexec /i "LPMC_3.6.x_xxx.exe" /qn
```

- **Si es InstallShield**:
```bat
"LPMC_3.6.x_xxx.exe" /s /v"/qn"
```

- **Si es NSIS**:
```bat
"LPMC_3.6.x_xxx.exe" /S
```

> **Nota:** Consulta la documentación oficial del build LPMC para confirmar la sintaxis exacta del modo silencioso.

---

## 🧪 Post-instalación
- Verifica servicio **Lexmark** y puertos internos (`9167`, `9443`, `3334`).  
- Comprueba la creación de la cola **LexmarkBBVA** con el driver **Lexmark Universal v2 XL**.  
- Prueba un job de impresión de ejemplo.

---

## 🔐 Seguridad y cumplimiento
- Descarga solo desde fuentes confiables (sitio de Lexmark, Drive corporativo o portal oficial).
- Mantén actualizado el **PAC/Proxy** en `configuration.json`.
- No compartas enlaces públicos si contienen licencias propietarias.


---

**Robles.AI**  
Email: antonio@robles.ai  
Teléfono: +1 408 590 0153  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados  
Producto de la familia de automatización Robles.AI  
Prohibida la utilización sin autorización de Inversiones On Line SAC
