#!/bin/bash
# Script para actualizar la configuración de Nginx y asegurar que pase correctamente
# los headers X-Forwarded-For y X-Real-IP al backend.
#
# Uso: bash fix-nginx-config.sh

set -e

echo "=== Actualizando configuración de Nginx ==="

# Backup de la configuración actual
sudo cp /etc/nginx/conf.d/alwaysprint.conf /etc/nginx/conf.d/alwaysprint.conf.backup.$(date +%Y%m%d%H%M%S)

# Crear nueva configuración
sudo tee /etc/nginx/conf.d/alwaysprint.conf > /dev/null <<'NGINX'
server {
    listen 80;
    server_name alwaysprint.apps.iol.pe;

    # Configuración de logs con IP real del cliente
    log_format main_ext '$remote_addr - $remote_user [$time_local] "$request" '
                        '$status $body_bytes_sent "$http_referer" '
                        '"$http_user_agent" "$http_x_forwarded_for"';
    
    access_log /var/log/nginx/alwaysprint_access.log main_ext;
    error_log /var/log/nginx/alwaysprint_error.log;

    location = /health {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }

    location /ws/ {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
    }

    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX

echo "✓ Configuración de Nginx actualizada"

# Verificar sintaxis
echo "Verificando sintaxis de Nginx..."
sudo nginx -t

# Recargar Nginx
echo "Recargando Nginx..."
sudo systemctl reload nginx

echo "✓ Nginx recargado correctamente"

# Mostrar la configuración actual
echo ""
echo "=== Configuración actual de Nginx ==="
cat /etc/nginx/conf.d/alwaysprint.conf

echo ""
echo "=== Verificación completa ==="
echo "Nginx está configurado para pasar correctamente los headers:"
echo "  - X-Real-IP: \$remote_addr (IP pública del cliente)"
echo "  - X-Forwarded-For: \$proxy_add_x_forwarded_for (cadena de IPs)"
echo ""
echo "Prueba la detección de IP con:"
echo "  curl -v https://alwaysprint.apps.iol.pe/api/v1/health"
