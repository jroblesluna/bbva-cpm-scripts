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

# ── Variables de entorno del backend (no sensibles) ───────────────────
cat > $APP_DIR/.env.backend <<'ENVFILE'
${backend_env_vars}
ENVFILE

# Variables sensibles desde Secrets Manager
DATABASE_URL=$(aws secretsmanager get-secret-value \
  --secret-id "${database_url_secret}" --region ${aws_region} \
  --query SecretString --output text)
SECRET_KEY=$(aws secretsmanager get-secret-value \
  --secret-id "${secret_key_secret}" --region ${aws_region} \
  --query SecretString --output text)

echo "DATABASE_URL=$DATABASE_URL" >> $APP_DIR/.env.backend
echo "SECRET_KEY=$SECRET_KEY"     >> $APP_DIR/.env.backend

# ── Variables de entorno del frontend ────────────────────────────────
cat > $APP_DIR/.env.frontend <<ENVFILE
NEXT_PUBLIC_API_URL=${public_url}
NEXT_PUBLIC_WS_URL=${ws_url}
NEXT_PUBLIC_APP_NAME=AlwaysPrint Cloud Management
ENVFILE

# ── docker-compose.yml ───────────────────────────────────────────────
cat > $APP_DIR/docker-compose.yml <<COMPOSE
version: '3.8'
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    networks: [app]

  backend:
    image: ${backend_ecr_url}:latest
    restart: unless-stopped
    env_file: /opt/alwaysprint/.env.backend
    command: >
      sh -c "alembic upgrade head &&
             uvicorn app.main:app --host 0.0.0.0 --port ${backend_port} --workers 1"
    networks: [app]
    depends_on: [redis]

  frontend:
    image: ${frontend_ecr_url}:latest
    restart: unless-stopped
    env_file: /opt/alwaysprint/.env.frontend
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

    location /api/ {
        proxy_pass http://localhost:${backend_port};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;
    }

    location /ws/ {
        proxy_pass http://localhost:${backend_port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_read_timeout 3600s;
    }

    location / {
        proxy_pass http://localhost:${frontend_port};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
NGINX

systemctl enable nginx
systemctl start nginx

# ── Script de deploy (usado por CI/CD) ────────────────────────────────
cat > $APP_DIR/deploy.sh <<'DEPLOY'
#!/bin/bash
SERVICE=$1  # backend | frontend | all
AWS_REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region)
ECR_REGISTRY=$(aws ecr describe-registry --region $AWS_REGION --query registryId --output text).dkr.ecr.$AWS_REGION.amazonaws.com

aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin $ECR_REGISTRY

cd /opt/alwaysprint

if [ "$SERVICE" = "backend" ] || [ "$SERVICE" = "all" ]; then
  docker compose pull backend
  docker compose up -d backend
fi

if [ "$SERVICE" = "frontend" ] || [ "$SERVICE" = "all" ]; then
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

# ── Certbot (HTTPS automatico) ────────────────────────────────────────
# Se ejecuta en background con reintentos hasta que el DNS apunte al EC2
cat > /opt/alwaysprint/setup_ssl.sh <<'SSL'
#!/bin/bash
DOMAIN=${domain_name}
EMAIL=antonio@robles.ai

for i in $(seq 1 20); do
  PUBLIC_IP=$(curl -s http://checkip.amazonaws.com)
  DNS_IP=$(nslookup $DOMAIN 2>/dev/null | awk '/^Address: /{print $2}' | tail -1)
  if [ "$PUBLIC_IP" = "$DNS_IP" ]; then
    certbot --nginx -d $DOMAIN --non-interactive --agree-tos -m $EMAIL
    systemctl reload nginx
    echo "SSL configurado correctamente"
    break
  fi
  echo "Esperando que $DOMAIN resuelva a $PUBLIC_IP (intento $i/20)..."
  sleep 60
done
SSL
chmod +x /opt/alwaysprint/setup_ssl.sh
nohup /opt/alwaysprint/setup_ssl.sh >> /var/log/setup_ssl.log 2>&1 &

# Auto-renovacion de Let's Encrypt
echo "0 0,12 * * * root certbot renew --quiet && systemctl reload nginx" \
  >> /etc/crontab
