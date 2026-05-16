#!/bin/bash
APP_DIR=/opt/alwaysprint

# ── Esperar red disponible ────────────────────────────────────────────
until ping -c1 -W2 8.8.8.8 &>/dev/null; do sleep 2; done

# ── Sistema ───────────────────────────────────────────────────────────
dnf update -y
dnf install -y docker nginx python3-pip certbot python3-certbot-nginx amazon-ssm-agent

systemctl enable docker
systemctl start docker

# Reiniciar SSM agent tras dnf update para asegurar registro con AWS
systemctl enable amazon-ssm-agent
systemctl restart amazon-ssm-agent

# Docker Compose plugin
mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# ── AWS CLI (viene preinstalado en AL2023) ────────────────────────────
aws ecr get-login-password --region ${aws_region} \
  | docker login --username AWS --password-stdin ${ecr_registry}

# ── Directorio de la app ──────────────────────────────────────────────
mkdir -p $APP_DIR

# ── Variables de entorno del backend ─────────────────────────────────
cat > $APP_DIR/.env <<'ENVFILE'
${backend_env_vars}
ENVFILE

# Variables sensibles desde Secrets Manager
DATABASE_URL=$(aws secretsmanager get-secret-value \
  --secret-id "${database_url_secret}" --region ${aws_region} \
  --query SecretString --output text)
SECRET_KEY=$(aws secretsmanager get-secret-value \
  --secret-id "${secret_key_secret}" --region ${aws_region} \
  --query SecretString --output text)

echo "DATABASE_URL=$DATABASE_URL" >> $APP_DIR/.env
echo "SECRET_KEY=$SECRET_KEY"     >> $APP_DIR/.env

# ── docker-compose.yml ───────────────────────────────────────────────
cat > $APP_DIR/docker-compose.yml <<COMPOSE
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    networks: [app]

  backend:
    image: ${backend_ecr_url}:latest
    restart: unless-stopped
    env_file: /opt/alwaysprint/.env
    ports:
      - "127.0.0.1:${backend_port}:${backend_port}"
    command: >
      sh -c "alembic upgrade head &&
             uvicorn app.main:app --host 0.0.0.0 --port ${backend_port} --workers 1"
    networks: [app]
    depends_on: [redis]

  frontend:
    image: ${frontend_ecr_url}:latest
    restart: unless-stopped
    ports:
      - "127.0.0.1:${frontend_port}:${frontend_port}"
    networks: [app]

networks:
  app:
    driver: bridge
COMPOSE

# ── Nginx config (HTTP primero, Certbot añade HTTPS) ─────────────────
cat > /etc/nginx/conf.d/alwaysprint.conf <<NGINX
server {
    listen 80;
    server_name ${domain_name};

    access_log /var/log/nginx/alwaysprint_access.log;
    error_log /var/log/nginx/alwaysprint_error.log;

    location = /health {
        proxy_pass http://localhost:${backend_port};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /api/ {
        proxy_pass http://localhost:${backend_port};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300s;
    }

    location /ws/ {
        proxy_pass http://localhost:${backend_port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600s;
    }

    location / {
        proxy_pass http://localhost:${frontend_port};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINX

systemctl enable nginx
systemctl start nginx

# ── Script de deploy (usado por CI/CD) ────────────────────────────────
cat > $APP_DIR/deploy.sh <<DEPLOY
#!/bin/bash
SERVICE=\$1  # backend | frontend | all

# Región y registry fijados durante provisión por Terraform
AWS_REGION="${aws_region}"
ECR_REGISTRY="${ecr_registry}"

aws ecr get-login-password --region \$AWS_REGION \\
  | docker login --username AWS --password-stdin \$ECR_REGISTRY

cd /opt/alwaysprint

if [ "\$SERVICE" = "backend" ] || [ "\$SERVICE" = "all" ]; then
  docker compose pull backend
  docker compose up -d backend
fi

if [ "\$SERVICE" = "frontend" ] || [ "\$SERVICE" = "all" ]; then
  docker compose pull frontend
  docker compose up -d frontend
fi
DEPLOY
chmod +x $APP_DIR/deploy.sh

# ── Arrancar containers (imagenes placeholder hasta primer CI/CD) ──────
cd $APP_DIR
# Intenta arrancar; si no hay imagen aun, falla silenciosamente
docker compose pull 2>/dev/null || true
docker compose up -d redis 2>/dev/null || true

# ── Certbot (HTTPS automático) ────────────────────────────────────────
# Cron que verifica cada 2 minutos si SSL está configurado.
# Si no lo está y el DNS apunta al EC2, ejecuta certbot automáticamente.
# Una vez configurado, solo renueva cuando sea necesario.
cat > /opt/alwaysprint/ensure_ssl.sh <<'SSL'
#!/bin/bash
DOMAIN=${domain_name}
EMAIL=antonio@robles.ai

# Si ya tiene certificado válido, solo renovar si es necesario
if [ -d "/etc/letsencrypt/live/$DOMAIN" ]; then
    certbot renew --quiet && systemctl reload nginx 2>/dev/null
    exit 0
fi

# No tiene SSL — verificar si DNS apunta a este EC2
PUBLIC_IP=$(curl -s --max-time 5 http://checkip.amazonaws.com)
DNS_IP=$(dig +short $DOMAIN 2>/dev/null | tail -1)
[ -z "$DNS_IP" ] && DNS_IP=$(getent hosts $DOMAIN 2>/dev/null | awk '{print $1}')

if [ "$PUBLIC_IP" = "$DNS_IP" ]; then
    echo "$(date): DNS OK ($DOMAIN → $PUBLIC_IP). Ejecutando certbot..."
    certbot --nginx -d $DOMAIN --non-interactive --agree-tos -m $EMAIL
    systemctl reload nginx
    echo "$(date): SSL configurado correctamente"
else
    echo "$(date): DNS no apunta al EC2 (DNS=$DNS_IP, EC2=$PUBLIC_IP). Esperando..."
fi
SSL
chmod +x /opt/alwaysprint/ensure_ssl.sh

# Ejecutar inmediatamente en background
nohup /opt/alwaysprint/ensure_ssl.sh >> /var/log/ensure_ssl.log 2>&1 &

# Cron: cada 2 minutos verificar SSL, y renovar cada 12 horas
echo "*/2 * * * * root /opt/alwaysprint/ensure_ssl.sh >> /var/log/ensure_ssl.log 2>&1" >> /etc/crontab
