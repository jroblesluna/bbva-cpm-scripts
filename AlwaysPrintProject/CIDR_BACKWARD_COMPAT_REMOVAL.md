# Eliminación de Compatibilidad con Clientes sin CIDR

## Contexto

Durante el desarrollo de la feature "Workstation CIDR & VLAN Registration", se hizo el campo `cidr` **opcional** en el backend para mantener compatibilidad con workstations que aún ejecutan versiones antiguas del Tray (sin soporte CIDR).

**Estado actual**: El campo `cidr` es `Optional[str]` — si no se envía, el backend usa el fallback `detect_vlan_for_ip` (detección de VLAN por IP privada).

**Objetivo**: Una vez que **todas** las workstations en producción estén actualizadas a una versión del Tray que envíe `cidr`, eliminar el fallback y hacer `cidr` obligatorio.

---

## Pre-requisitos para Eliminar la Compatibilidad

1. **Todas las workstations deben tener versión del Tray >= 2.x.x** (la que incluye `GetOutboundCIDR()`)
2. Verificar en la BD que no existan workstations con `tray_version = NULL` o versiones anteriores
3. Verificar que no haya workstations con `cidr = NULL` que sigan conectándose activamente

### Query de verificación:

```sql
-- Workstations activas sin CIDR (candidatas a problemas si se hace obligatorio)
SELECT id, ip_private, hostname, tray_version, cidr, last_connection
FROM workstations
WHERE is_online = true AND cidr IS NULL
ORDER BY last_connection DESC;

-- Conteo de workstations por versión del Tray
SELECT tray_version, COUNT(*) as total, 
       SUM(CASE WHEN is_online THEN 1 ELSE 0 END) as online
FROM workstations
GROUP BY tray_version
ORDER BY tray_version DESC;
```

Si ambas queries retornan 0 workstations activas sin CIDR, es seguro proceder.

---

## Cambios a Realizar

### 1. Backend — Schema HTTP (`app/schemas/workstation.py`)

```python
# ANTES (compatible con clientes antiguos):
cidr: Optional[str] = Field(None, description="CIDR de la subred...")

# DESPUÉS (obligatorio):
cidr: str = Field(..., description="CIDR de la subred de la workstation (ej: 192.168.1.0/24)")
```

Actualizar el validator:
```python
# ANTES:
def validar_cidr(cls, v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    ...

# DESPUÉS:
def validar_cidr(cls, v: str) -> str:
    ...
```

### 2. Backend — Schema WebSocket (`app/schemas/websocket.py`)

Mismo cambio que el schema HTTP:
```python
# ANTES:
cidr: Optional[str] = Field(None, description="CIDR de la subred...")

# DESPUÉS:
cidr: str = Field(..., description="CIDR de la subred de la workstation (ej: 192.168.1.0/24)")
```

### 3. Backend — Servicio (`app/services/workstation.py`)

Eliminar el fallback por IP en `register_workstation`:

```python
# ANTES:
if normalized_cidr:
    vlan_id = self.detect_or_create_vlan_for_cidr(db, organization_id, normalized_cidr)
else:
    # Fallback: detectar VLAN por IP privada (legacy)
    vlan_id = self.detect_vlan_for_ip(db, organization_id, ip_private)

# DESPUÉS:
vlan_id = self.detect_or_create_vlan_for_cidr(db, organization_id, normalized_cidr)
```

Esto aplica en dos lugares del método `register_workstation`:
- Línea ~448: workstation existente
- Línea ~524: workstation nueva

### 4. Backend — Tests (`tests/unit/test_cidr_validation_endpoints.py`)

Revertir el test de campo obligatorio:
```python
# ANTES:
def test_cidr_sin_campo_es_aceptado(self):
    """Registro sin campo cidr es aceptado (backward compatibility)."""
    request = WorkstationRegisterRequest(ip_private="192.168.1.50")
    assert request.cidr is None

# DESPUÉS:
def test_cidr_sin_campo_obligatorio(self):
    """Registro sin campo cidr es rechazado."""
    with pytest.raises(ValidationError):
        WorkstationRegisterRequest(ip_private="192.168.1.50")
```

### 5. (Opcional) Eliminar método `detect_vlan_for_ip`

Si ya no se usa en ningún otro lugar, eliminar el método legacy de detección por IP.

---

## Archivos Afectados

| Archivo | Cambio |
|---|---|
| `Cloud/backend/app/schemas/workstation.py` | `cidr` de Optional a obligatorio |
| `Cloud/backend/app/schemas/websocket.py` | `cidr` de Optional a obligatorio |
| `Cloud/backend/app/services/workstation.py` | Eliminar fallback `detect_vlan_for_ip` |
| `Cloud/backend/tests/unit/test_cidr_validation_endpoints.py` | Revertir test a obligatorio |

---

## Riesgos

- **Workstations desactualizadas quedarán bloqueadas**: No podrán registrarse (HTTP 422). Esto es intencional — fuerza la actualización.
- **Workstations offline con versión antigua**: Al reconectarse recibirán 422. Deben actualizarse manualmente o via auto-update antes de eliminar la compatibilidad.

---

## Checklist Pre-Eliminación

- [ ] Verificar que 0 workstations activas tienen `cidr = NULL`
- [ ] Verificar que 0 workstations activas tienen `tray_version` anterior a la versión con CIDR
- [ ] Comunicar a los administradores que workstations sin actualizar dejarán de funcionar
- [ ] Desplegar la versión del Tray con CIDR a todas las organizaciones (auto-update habilitado)
- [ ] Esperar al menos 1 semana después del despliegue completo
- [ ] Aplicar los cambios de este documento
- [ ] Ejecutar tests (`pytest`)
- [ ] Desplegar backend actualizado

---

*Documento creado: 2026-05-19*  
*Feature: workstation-cidr-vlan-registration*
