# Fix: Detección de IP Pública del Cliente

## Problema

El sistema estaba registrando IPs privadas (172.18.0.1, 192.168.x.x, etc.) en lugar de las IPs públicas de los clientes. Esto impedía identificar correctamente la organización desde la cual se conectaba el cliente.

### Causa Raíz

La función `get_client_ip()` en `app/core/utils.py` estaba priorizando incorrectamente el header `X-Client-Private-IP` sobre los headers de proxy que contienen la IP pública real (`X-Forwarded-For`, `X-Real-IP`).

## Solución Implementada

### 1. Corrección de la Función `get_client_ip()`

**Archivo**: `app/core/utils.py`

**Cambio**: Se modificó la prioridad de detección de IP para usar correctamente los headers de proxy:

```python
def get_client_ip(request: Request) -> str:
    """
    Obtiene la IP PÚBLICA del cliente desde la solicitud HTTP.
    
    Prioridad (para identificar la organización por IP pública):
    1. Header X-Forwarded-For (IP pública real cuando hay proxy/load balancer)
    2. Header X-Real-IP (usado por Nginx, contiene IP pública)
    3. IP directa del cliente (request.client.host)
    """
    # Verificar header X-Forwarded-For para proxies reversos
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    
    # Verificar X-Real-IP (usado por Nginx)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    # IP directa del cliente (cuando no hay proxy)
    return request.client.host if request.client else "unknown"
```

**Nota**: Se eliminó intencionalmente la prioridad del header `X-Client-Private-IP` porque contiene la IP privada de la red local del cliente, no la IP pública que identifica a la organización.

### 2. Configuración de Nginx

La configuración de Nginx ya estaba correcta en `terraform/modules/ec2/user_data.sh.tpl`:

```nginx
location /api/ {
    proxy_pass http://localhost:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 300s;
}
```

Estos headers aseguran que la IP pública del cliente se pase correctamente al backend.

## Limpieza de Datos Existentes

### Script de Limpieza

Se creó el script `scripts/fix_private_ips.py` para eliminar IPs privadas registradas incorrectamente.

**Uso**:

```bash
cd /opt/alwaysprint/backend
source venv/bin/activate  # o conda activate alwaysprint
python scripts/fix_private_ips.py
```

El script:
1. Identifica todas las IPs privadas en la tabla `public_ips`
2. Muestra un resumen de las IPs que serán eliminadas
3. Solicita confirmación antes de eliminar
4. Elimina los registros de IPs privadas

### Rangos de IPs Privadas Detectados

El script identifica y elimina IPs en los siguientes rangos:
- `10.0.0.0/8` (10.x.x.x)
- `172.16.0.0/12` (172.16.x.x - 172.31.x.x)
- `192.168.0.0/16` (192.168.x.x)
- `127.0.0.0/8` (127.x.x.x - loopback)

## Verificación

### 1. Verificar Headers en Nginx

Conectarse al servidor EC2 y verificar los logs de Nginx:

```bash
sudo tail -f /var/log/nginx/access.log
```

Buscar las IPs en los logs. Deberían ser IPs públicas, no privadas.

### 2. Verificar en la Base de Datos

Conectarse a la base de datos y verificar las IPs registradas:

```sql
SELECT ip_address, is_authorized, account_id, first_seen 
FROM public_ips 
ORDER BY first_seen DESC 
LIMIT 10;
```

Las IPs deberían ser públicas (no 10.x.x.x, 172.16-31.x.x, 192.168.x.x).

### 3. Verificar en el Dashboard

1. Ir a **Accounts** → **Pending Public IPs**
2. Las IPs mostradas deberían ser públicas
3. Ejemplo de IP pública válida: `203.0.113.45`, `198.51.100.23`
4. Ejemplo de IP privada inválida: `172.18.0.1`, `192.168.1.100`

### 4. Probar con un Cliente Real

1. Instalar el cliente AlwaysPrint en una workstation
2. Iniciar el cliente y dejar que se conecte al backend
3. Verificar en el dashboard que la IP registrada sea la IP pública de la organización
4. Usar https://whatismyipaddress.com/ desde la workstation para confirmar la IP pública

## Impacto

### Antes del Fix
- ❌ IPs privadas registradas (172.18.0.1, 192.168.x.x)
- ❌ Imposible identificar la organización por IP
- ❌ Múltiples organizaciones aparecían con la misma IP privada

### Después del Fix
- ✅ IPs públicas registradas correctamente
- ✅ Cada organización identificada por su IP pública única
- ✅ Sistema de autorización de IPs funcional

## Deployment

### Pasos para Aplicar el Fix

1. **Actualizar el código del backend**:
   ```bash
   git pull origin main
   cd /opt/alwaysprint
   ./deploy.sh backend
   ```

2. **Ejecutar el script de limpieza**:
   ```bash
   cd /opt/alwaysprint/backend
   python scripts/fix_private_ips.py
   ```

3. **Verificar que funciona**:
   - Conectar un cliente nuevo
   - Verificar que la IP registrada sea pública
   - Autorizar la IP y asignarla a una cuenta

## Notas Adicionales

### ¿Por qué se registraban IPs privadas?

Cuando el backend corre en Docker, `request.client.host` devuelve la IP del contenedor Docker (172.18.0.1) o la IP de la red interna, no la IP pública del cliente. Por eso es crítico usar los headers `X-Forwarded-For` o `X-Real-IP` que Nginx configura correctamente.

### ¿Qué pasa si no hay proxy?

Si el backend se ejecuta directamente sin proxy (ej: desarrollo local), `request.client.host` devolverá la IP correcta. En producción con Nginx, los headers de proxy tienen prioridad.

### Seguridad

Los headers `X-Forwarded-For` y `X-Real-IP` pueden ser falsificados por clientes maliciosos. En producción, Nginx debe estar configurado para sobrescribir estos headers (usando `proxy_set_header` en lugar de `proxy_add_header`), lo cual ya está implementado correctamente.

## Referencias

- [FastAPI Request Object](https://fastapi.tiangolo.com/advanced/using-request-directly/)
- [Nginx proxy_set_header](http://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_set_header)
- [X-Forwarded-For Header](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Forwarded-For)

---

**Fecha**: 2026-05-14  
**Autor**: Antonio Robles  
**Versión**: 1.0
