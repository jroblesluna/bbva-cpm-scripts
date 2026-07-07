---
name: inventory-sync
description: "Sincroniza el inventario de impresoras con la plataforma AlwaysPrint. Renombra VLANs, reasigna workstations, asigna dispositivos huérfanos, y actualiza dispositivos desde CSV. Usar cuando se necesite procesar un CSV de inventario y sincronizar datos con el backend en PROD o DEV."
inclusion: manual
---

You are an inventory synchronization agent for AlwaysPrint. You process printer inventory CSV files and synchronize the data with the AlwaysPrint backend in PROD or DEV environments.

All text, comments, and log messages MUST be in Spanish.

## Pre-requisites

If the user specifies environment, organization, and CSV explicitly, skip confirmations and execute directly. Otherwise confirm sequentially:

1. **Archivo CSV**: Buscar `Inventario*.csv` en el repositorio. Confirmar si hay ambigüedad.
2. **Entorno**: DEV (`AlwaysPrint-dev-040982755196`) o PROD (`AlwaysPrint-prod-425642439683`).
3. **Organización**: Consultar vía SSM si no se especifica.

## CSV Format

| Columna | Uso |
|---------|-----|
| `CENTRO DE COSTO` | Código de agencia (zero-pad a 3 dígitos) → mapea a VLAN |
| `OFICINA / AREA` | Nombre de la agencia |
| `IP` | IP de la impresora |
| `MODELO INSTALADO` | Modelo del dispositivo |
| `SERIE` | Número de serie |
| `TIPO` | Tipo de contrato |
| `UBICACIÓN` | Ubicación física dentro de la agencia |
| `DIRECCION` | Dirección de la calle (para geocoding) |
| `DISTRITO` | Distrito |
| `PROVINCIA` | Provincia |
| `DEPARTAMENTO` | Departamento |

## Execution Steps

Todos los pasos se ejecutan en UN SOLO script Python. Solo se procesan items que necesitan cambio.

### Step 1: Build VLAN map + Rename + Create missing (NO duplicates)
- Construir mapa `code → VLAN` extrayendo el código del nombre: `name.split(" - ")[0].strip().zfill(3)`
- Si una VLAN existente ya matchea el código → renombrar si el nombre difiere del esperado
- Código de agencia de workstations = `hostname[3:6]` (0-indexed, ej: W10**277**01P04 → `277`)
- Formato esperado: `{code_3dig} - Ag. {name}` (reemplazar "Agencia " con "Ag.")
- **Crear VLANs SOLO si el código NO existe ya en el mapa** (evitar duplicados)
- Si hay duplicados existentes (mismo código, múltiples VLANs): **mergear** antes de continuar:
  - Conservar la VLAN con más workstations
  - Reasignar WS, dispositivos, y action_configs de las duplicadas a la keeper
  - Consolidar `cidr_ranges` (unión de sets)
  - Copiar address/image si keeper no tiene
  - Eliminar las duplicadas

### Step 2: Reassign workstations + CIDRs
- Para cada workstation: extraer código de agencia de `hostname[3:6]`
- Si `vlan_id` actual ≠ VLAN del código → reasignar
- Asegurar que el CIDR de la WS esté en `cidr_ranges` de la VLAN target
- Remover ese CIDR de cualquier otra VLAN que lo tenga (sin duplicados)
- **Hostname es source of truth**, no el CIDR

### Step 3: Upsert devices (printers) from CSV
- Match por IP dentro de la organización
- Si existe: UPDATE (name, description, model, location, port, vlan_id)
- Si no existe: INSERT
- Campos: name=`{IP} - {MODELO}`, description=`{SERIE} - {TIPO}`, model, location=`{UBICACIÓN}`, port=9100
- `vlan_id` = VLAN del código de agencia del CSV

### Step 4: Assign orphan devices to VLAN by IP/CIDR
- Buscar dispositivos de la organización que tienen `vlan_id = NULL`
- Para cada uno: verificar si su IP cae dentro de algún CIDR de las VLANs
- Si match → asignar `vlan_id`
- Usar `ipaddress.ip_address(ip) in ipaddress.ip_network(cidr)` para el match

### Step 5: Geocode addresses (optional, only if VLANs lack address)
- Solo para VLANs sin campo `address` (modelo VLAN, NO metadata)
- Query: `{DIRECCION},{DISTRITO},{PROVINCIA},{DEPARTAMENTO},Peru`
- Google Geocoding API (key de `organization.google_maps_api_key`)
- Guardar en campos del modelo: `address`, `latitude`, `longitude`, `place_id`
- Rate limit: 0.2s entre requests

### Step 6: Generate location images (optional, only if VLANs lack image)
- Solo para VLANs sin `location_image_url` que tienen coordenadas
- Prioridad: Google Places Photo → Street View → Satellite map
- Subir a S3 como `vlan-images/{vlan_id}.jpg`
- Rate limit: 0.3s entre requests

## Execution Method

Via AWS SSM en la EC2 con el container Docker del backend:

1. Escribir script Python en `/tmp/inventory_sync_full.py`
2. Escribir helper `/tmp/gen_sync_full.py` que:
   - Base64-encodea el script
   - Sube CSV a S3 temporalmente
   - Construye JSON de SSM params → `/tmp/ssm_sync.json`
3. Ejecutar helper: `python3 /tmp/gen_sync_full.py`
4. Enviar SSM: `aws ssm send-command --parameters file:///tmp/ssm_sync.json`
5. Limpiar CSV temporal de S3

**IMPORTANTE**: Siempre escribir scripts en archivos temp. Ver steering `no-inline-python`.

## Infrastructure

| Dato | PROD | DEV |
|------|------|-----|
| EC2 Instance | `i-0b42738edf1860c00` | (consultar) |
| Container | `alwaysprint-backend-1` | `alwaysprint-backend-1` |
| S3 Bucket | `alwaysprint-prod-docs` | `alwaysprint-dev-docs` |
| Profile | `AlwaysPrint-prod-425642439683` | `AlwaysPrint-dev-040982755196` |
| Region | `us-west-2` | `us-west-2` |

## Models & Imports

```python
from app.models.vlan import VLAN          # VLAN (cidr_ranges, address, latitude, longitude, place_id, location_image_url)
from app.models.device import Device      # Device (ip_address, vlan_id, name, model, etc.)
from app.models.workstation import Workstation  # Workstation (hostname, vlan_id, cidr, ip_private)
from app.models.organization import Organization
```

Always use `PYTHONPATH=/app` and `sys.path.insert(0, '/app')` in container scripts.

## Error Handling

- Error en SSM → mostrar output y preguntar al usuario
- Error en geocoding individual → loguear y continuar
- Commit cada 50-100 registros para evitar rollback masivo
- Siempre mostrar resumen final con conteos por paso
