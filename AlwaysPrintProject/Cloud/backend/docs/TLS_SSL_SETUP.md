# Configuración de TLS/SSL para Producción

**Fecha**: 8 de mayo de 2026  
**Versión**: 1.0.0

---

## 📋 Resumen

Este documento describe cómo configurar TLS/SSL para AlwaysPrint Cloud Management en producción, garantizando comunicaciones seguras entre clientes y servidor.

---

## 🎯 Objetivos

- Habilitar HTTPS para todas las comunicaciones
- Configurar certificados SSL válidos
- Implementar mejores prácticas de seguridad TLS
- Configurar redirección HTTP → HTTPS
- Habilitar HSTS (HTTP Strict Transport Security)

---

## 🔧 Opciones de Implementación

### Opción 1: Reverse Proxy (Recomendado)

Usar un reverse proxy (Nginx, Apache, Caddy) delante de FastAPI para manejar TLS.

**Ventajas**:
- Mejor rendimiento
- Configuración más flexible
- Manejo de certificados centralizado
- Load balancing integrado

**Desventajas**:
- Componente adicional a mantener

### Opción 2: TLS Directo en FastAPI

Configurar TLS directamente en Uvicorn/FastAPI.

**Ventajas**:
- Arquitectura más simple
- Menos componentes

**Desventajas**:
- Menor rendimiento
- Menos flexible

---

## 🚀 Implementación con Nginx (Recomendado)

### 1. Obtener Certificados SSL

#### Opción A: Let's Encrypt (Gratuito)

```bash
# Instalar Certbot
sudo apt-get update
sudo apt-get install certbot python3-certbot-nginx

# Obtener certificado
sudo certbot --nginx -d api.alwaysprint.com
```

#### Opción B: Certificado Comercial

1. Generar CSR (Certificate Signing Request)
2. Comprar certificado de CA (DigiCert, GlobalSign, etc.)
3. Instalar certificado en servidor

### 2. Configurar Nginx

Crear archivo de configuración: `/etc/nginx/sites-available/alwaysprint`

```nginx
# Redirección HTTP → HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name api.alwaysprint.com;
    
    # Redireccionar todo el tráfico a HTTPS
    return 301 https://$server_name$request_uri;
}

# Servidor HTTPS
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name api.alwaysprint.com;
    
    # === CERTIFICADOS SSL ===
    ssl_certificate /etc/letsencrypt/live/api.alwaysprint.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.alwaysprint.com/privkey.pem;
    
    # === CONFIGURACIÓN TLS ===
    # Protocolos TLS (solo TLS 1.2 y 1.3)
    ssl_protocols TLSv1.2 TLSv1.3;
    
    # Ciphers seguros
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
    ssl_prefer_server_ciphers off;
    
    # Sesión SSL
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_session_tickets off;
    
    # OCSP Stapling
    ssl_stapling on;
    ssl_stapling_verify on;
    ssl_trusted_certificate /etc/letsencrypt/live/api.alwaysprint.com/chain.pem;
    resolver 8.8.8.8 8.8.4.4 valid=300s;
    resolver_timeout 5s;
    
    # === HEADERS DE SEGURIDAD ===
    # HSTS (HTTP Strict Transport Security)
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
    
    # Otros headers (ya manejados por middleware, pero por si acaso)
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    
    # === CONFIGURACIÓN DE PROXY ===
    # Tamaño máximo de body (para uploads)
    client_max_body_size 10M;
    
    # Timeouts
    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;
    
    # Proxy a FastAPI
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        
        # Headers de proxy
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        
        # WebSocket support
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    
    # === LOGS ===
    access_log /var/log/nginx/alwaysprint_access.log;
    error_log /var/log/nginx/alwaysprint_error.log;
}
```

### 3. Habilitar Configuración

```bash
# Crear symlink
sudo ln -s /etc/nginx/sites-available/alwaysprint /etc/nginx/sites-enabled/

# Verificar configuración
sudo nginx -t

# Recargar Nginx
sudo systemctl reload nginx
```

### 4. Renovación Automática de Certificados

Let's Encrypt configura renovación automática, pero verificar:

```bash
# Verificar timer de renovación
sudo systemctl status certbot.timer

# Probar renovación (dry-run)
sudo certbot renew --dry-run
```

---

## 🔒 Implementación con TLS Directo en FastAPI

### 1. Generar Certificados

```bash
# Certificado autofirmado (solo para desarrollo/testing)
openssl req -x509 -newkey rsa:4096 -nodes \
  -out cert.pem -keyout key.pem -days 365 \
  -subj "/CN=localhost"
```

### 2. Configurar Uvicorn

Modificar comando de inicio:

```bash
# Con certificados
uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --ssl-keyfile=./key.pem \
  --ssl-certfile=./cert.pem
```

O en código Python:

```python
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        ssl_keyfile="./key.pem",
        ssl_certfile="./cert.pem",
        reload=False
    )
```

---

## 🧪 Verificación de Configuración

### 1. Verificar Certificado

```bash
# Verificar certificado SSL
openssl s_client -connect api.alwaysprint.com:443 -servername api.alwaysprint.com

# Verificar fecha de expiración
echo | openssl s_client -connect api.alwaysprint.com:443 2>/dev/null | openssl x509 -noout -dates
```

### 2. Probar Configuración TLS

Usar herramientas online:
- **SSL Labs**: https://www.ssllabs.com/ssltest/
- **Security Headers**: https://securityheaders.com/

Objetivo: Obtener calificación A o A+

### 3. Verificar Headers de Seguridad

```bash
# Verificar headers
curl -I https://api.alwaysprint.com

# Debe incluir:
# - Strict-Transport-Security
# - X-Frame-Options
# - X-Content-Type-Options
# - Content-Security-Policy
```

### 4. Verificar Redirección HTTP → HTTPS

```bash
# Debe redirigir a HTTPS
curl -I http://api.alwaysprint.com
# HTTP/1.1 301 Moved Permanently
# Location: https://api.alwaysprint.com/
```

---

## 📊 Mejores Prácticas

### 1. Protocolos TLS

✅ **Usar**: TLS 1.2 y TLS 1.3  
❌ **Evitar**: TLS 1.0, TLS 1.1, SSL 2.0, SSL 3.0

### 2. Ciphers

Usar solo ciphers seguros:
- ECDHE (Perfect Forward Secrecy)
- AES-GCM (Authenticated Encryption)
- Evitar RC4, DES, 3DES

### 3. Certificados

- Usar certificados de CA confiable
- Renovar antes de expiración
- Usar certificados wildcard si hay subdominios
- Implementar OCSP Stapling

### 4. HSTS

- Habilitar HSTS con `max-age` largo (1 año)
- Incluir subdominios (`includeSubDomains`)
- Considerar preload list

### 5. Monitoreo

- Monitorear expiración de certificados
- Alertas 30 días antes de expiración
- Logs de errores SSL/TLS
- Métricas de handshake TLS

---

## 🔧 Configuración de Variables de Entorno

Actualizar `.env` para producción:

```env
# === PRODUCCIÓN ===

# Base de datos
DATABASE_URL=postgresql://user:password@localhost:5432/alwaysprint

# Seguridad
SECRET_KEY=<GENERAR_CLAVE_SEGURA_ALEATORIA>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# CORS (solo dominios de producción)
CORS_ORIGINS=https://app.alwaysprint.com,https://admin.alwaysprint.com

# Redis (para rate limiting en producción)
REDIS_URL=redis://localhost:6379/0

# Logging
LOG_LEVEL=INFO
LOG_FILE=/var/log/alwaysprint/app.log
```

---

## 🚨 Troubleshooting

### Problema: Certificado no confiable

**Causa**: Certificado autofirmado o CA no reconocida  
**Solución**: Usar certificado de CA confiable (Let's Encrypt, DigiCert, etc.)

### Problema: Mixed Content Warnings

**Causa**: Recursos cargados por HTTP en página HTTPS  
**Solución**: Asegurar que todos los recursos usen HTTPS

### Problema: WebSocket no funciona con HTTPS

**Causa**: Configuración incorrecta de proxy  
**Solución**: Verificar headers `Upgrade` y `Connection` en Nginx

### Problema: Renovación de certificado falla

**Causa**: Puerto 80 bloqueado o dominio no resuelve  
**Solución**: Verificar DNS y firewall, asegurar que puerto 80 esté abierto

---

## 📚 Referencias

- **Mozilla SSL Configuration Generator**: https://ssl-config.mozilla.org/
- **Let's Encrypt Documentation**: https://letsencrypt.org/docs/
- **OWASP TLS Cheat Sheet**: https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Protection_Cheat_Sheet.html
- **Nginx SSL Module**: http://nginx.org/en/docs/http/ngx_http_ssl_module.html

---

**Robles.AI**  
Email: antonio@robles.ai  
Teléfono: +1 408 590 0153  
Web: https://robles.ai

---

© 2026 Inversiones On Line SAC - Todos los derechos reservados  
Producto de la familia de automatización Robles.AI  
Prohibida la utilización sin autorización de Inversiones On Line SAC
