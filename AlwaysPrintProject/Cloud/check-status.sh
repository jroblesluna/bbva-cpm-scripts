#!/bin/bash
# =============================================================================
# AlwaysPrint Cloud Manager - Script de verificación de estado
# Ejecutar desde tu máquina local para verificar que todo está operativo
#
# Uso: ./check-status.sh <dev|prod>
#
# Flujo:
#   0. Selecciona entorno y lee outputs de Terraform
#   1. Verifica DNS (registros A, DKIM, MX)
#   2. Verifica infraestructura AWS (EC2, RDS, ECR)
#   3. Verifica containers y aplicación vía SSM
#   4. Verifica endpoints públicos (HTTPS, SSL)
#   5. Muestra errores recientes
#   6. Muestra acciones recomendadas si hay problemas
# =============================================================================

set -o pipefail

# =============================================================================
# VALIDACIÓN DE PARÁMETRO
# =============================================================================
ENV="${1:-}"

if [ -z "$ENV" ] || { [ "$ENV" != "dev" ] && [ "$ENV" != "prod" ]; }; then
    echo "Uso: ./check-status.sh <dev|prod>"
    echo ""
    echo "  dev   — Verificar entorno de desarrollo (cuenta 040982755196)"
    echo "  prod  — Verificar entorno de producción (cuenta 425642439683)"
    exit 1
fi

# Configuración por entorno
if [ "$ENV" = "dev" ]; then
    AWS_PROFILE="AlwaysPrint-dev-040982755196"
    TF_WORKSPACE="dev"
    TF_VARS="dev.tfvars"
    ECR_PREFIX="alwaysprint-dev"
    EC2_TAG="alwaysprint-dev-ec2"
    ENV_LABEL="DESARROLLO"
else
    AWS_PROFILE="AlwaysPrint-prod-425642439683"
    TF_WORKSPACE="prod"
    TF_VARS="prod.tfvars"
    ECR_PREFIX="alwaysprint-prod"
    EC2_TAG="alwaysprint-prod-ec2"
    ENV_LABEL="PRODUCCIÓN"
fi

export AWS_PROFILE
AWS_REGION="us-west-2"

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

TIMEOUT=10
PASS=0
FAIL=0
WARN=0
SSL_AUTOFIX=false

# Acumular recomendaciones
RECOMMENDATIONS=()

print_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
}

check_ok() {
    echo -e "  ${GREEN}✓${NC} $1"
    PASS=$((PASS + 1))
}

check_fail() {
    echo -e "  ${RED}✗${NC} $1"
    FAIL=$((FAIL + 1))
}

check_warn() {
    echo -e "  ${YELLOW}⚠${NC} $1"
    WARN=$((WARN + 1))
}

recommend() {
    RECOMMENDATIONS+=("$1")
}

# Ejecutar comando SSM y esperar resultado
ssm_exec() {
    local instance_id="$1"
    local commands="$2"
    local wait_seconds="${3:-8}"
    
    local cmd_id=$(aws ssm send-command \
        --instance-ids "$instance_id" \
        --document-name "AWS-RunShellScript" \
        --parameters "{\"commands\":$commands}" \
        --query "Command.CommandId" \
        --output text \
        --region "$AWS_REGION" 2>/dev/null)
    
    if [ -z "$cmd_id" ] || [ "$cmd_id" = "None" ]; then
        echo ""
        return 1
    fi
    
    sleep "$wait_seconds"
    
    aws ssm get-command-invocation \
        --command-id "$cmd_id" \
        --instance-id "$instance_id" \
        --query 'StandardOutputContent' \
        --output text \
        --region "$AWS_REGION" 2>/dev/null
}

# =============================================================================
# 0. TERRAFORM OUTPUTS (fuente de verdad de la infraestructura)
# =============================================================================
print_header "0. ENTORNO: $ENV_LABEL [$ENV] — Perfil: $AWS_PROFILE"

TF_DIR="$(cd "$(dirname "$0")/terraform" 2>/dev/null && pwd)"

if [ -d "$TF_DIR/.terraform" ]; then
    echo -e "  ${CYAN}Seleccionando workspace '$TF_WORKSPACE' y leyendo outputs...${NC}"
    
    # Cambiar al workspace correcto
    terraform -chdir="$TF_DIR" workspace select "$TF_WORKSPACE" >/dev/null 2>&1
    
    TF_OUTPUT=$(terraform -chdir="$TF_DIR" output -json 2>/dev/null)
    
    if [ $? -eq 0 ] && [ -n "$TF_OUTPUT" ]; then
        DOMAIN=$(echo "$TF_OUTPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('app_url',{}).get('value','').replace('https://',''))" 2>/dev/null)
        INSTANCE_ID=$(echo "$TF_OUTPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ec2_instance_id',{}).get('value',''))" 2>/dev/null)
        EC2_IP=$(echo "$TF_OUTPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ec2_public_ip',{}).get('value',''))" 2>/dev/null)
        RDS_ENDPOINT=$(echo "$TF_OUTPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('rds_endpoint',{}).get('value',''))" 2>/dev/null)
        BACKEND_ECR=$(echo "$TF_OUTPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('backend_ecr_url',{}).get('value',''))" 2>/dev/null)
        FRONTEND_ECR=$(echo "$TF_OUTPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('frontend_ecr_url',{}).get('value',''))" 2>/dev/null)
        
        check_ok "Terraform state leído correctamente"
        echo -e "  ${NC}  Domain:       ${DOMAIN:-no definido}"
        echo -e "  ${NC}  Instance ID:  ${INSTANCE_ID:-no definido}"
        echo -e "  ${NC}  EC2 IP:       ${EC2_IP:-no definido}"
        echo -e "  ${NC}  RDS:          ${RDS_ENDPOINT:-no definido}"
        echo -e "  ${NC}  Backend ECR:  ${BACKEND_ECR:-no definido}"
        echo -e "  ${NC}  Frontend ECR: ${FRONTEND_ECR:-no definido}"
    else
        check_warn "No se pudieron leer outputs de Terraform (¿infraestructura no aplicada?)"
        recommend "Ejecutar: terraform workspace select $TF_WORKSPACE && terraform apply -var-file=$TF_VARS"
    fi
else
    check_warn "Terraform no inicializado en $TF_DIR"
    recommend "Ejecutar: cd terraform && terraform init"
fi

# Fallbacks si Terraform no proporcionó datos
if [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" = "None" ]; then
    EC2_INFO=$(aws ec2 describe-instances \
        --region "$AWS_REGION" \
        --filters "Name=tag:Name,Values=$EC2_TAG" "Name=instance-state-name,Values=running" \
        --query "Reservations[0].Instances[0].[InstanceId,PublicIpAddress]" \
        --output text 2>/dev/null)
    
    if [ -n "$EC2_INFO" ] && [ "$EC2_INFO" != "None" ]; then
        INSTANCE_ID=$(echo "$EC2_INFO" | awk '{print $1}')
        EC2_IP=$(echo "$EC2_INFO" | awk '{print $2}')
    fi
fi

# =============================================================================
# 1. VALIDACIÓN DNS
# =============================================================================
print_header "1. VALIDACIÓN DNS"

echo -e "\n  ${BLUE}Registros DNS:${NC}"
DNS_OK=false
IP_RESOLVED=$(dig +short "$DOMAIN" 2>/dev/null | head -1)
if [ -n "$IP_RESOLVED" ]; then
    if [ -n "$EC2_IP" ] && [ "$IP_RESOLVED" = "$EC2_IP" ]; then
        check_ok "$DOMAIN → $IP_RESOLVED (coincide con EC2)"
        DNS_OK=true
    elif [ -n "$EC2_IP" ]; then
        check_fail "$DOMAIN → $IP_RESOLVED (NO coincide con EC2: $EC2_IP)"
        recommend "Actualizar DNS: $DOMAIN → $EC2_IP (registro A)"
    else
        check_warn "$DOMAIN → $IP_RESOLVED (EC2 IP aún no disponible para comparar)"
    fi
else
    check_fail "No se pudo resolver DNS para $DOMAIN"
    recommend "Configurar registro A: $DOMAIN → ${EC2_IP:-<EC2_IP>}"
fi

# =============================================================================
# 2. INFRAESTRUCTURA AWS
# =============================================================================
print_header "2. INFRAESTRUCTURA AWS"

if ! command -v aws &> /dev/null; then
    check_fail "AWS CLI no instalado"
    recommend "Instalar AWS CLI: brew install awscli"
else
    # EC2
    echo -e "\n  ${BLUE}EC2 Instance:${NC}"
    if [ -n "$INSTANCE_ID" ] && [ "$INSTANCE_ID" != "None" ]; then
        EC2_STATE=$(aws ec2 describe-instances \
            --instance-ids "$INSTANCE_ID" \
            --query 'Reservations[0].Instances[0].State.Name' \
            --output text \
            --region "$AWS_REGION" 2>/dev/null)
        
        if [ "$EC2_STATE" = "running" ]; then
            check_ok "EC2 $INSTANCE_ID — running"
        elif [ -n "$EC2_STATE" ] && [ "$EC2_STATE" != "None" ]; then
            check_fail "EC2 $INSTANCE_ID — estado: $EC2_STATE"
        else
            check_fail "EC2 $INSTANCE_ID — no encontrado"
        fi

        EC2_STATUS=$(aws ec2 describe-instance-status \
            --instance-ids "$INSTANCE_ID" \
            --query 'InstanceStatuses[0].[InstanceStatus.Status, SystemStatus.Status]' \
            --output text \
            --region "$AWS_REGION" 2>/dev/null)
        
        if echo "$EC2_STATUS" | grep -q "ok.*ok"; then
            check_ok "EC2 status checks — OK"
        elif [ -n "$EC2_STATUS" ] && [ "$EC2_STATUS" != "None" ]; then
            check_warn "EC2 status checks — $EC2_STATUS (puede estar inicializando)"
        fi
    else
        check_fail "Instance ID no disponible"
        recommend "No se detectó instancia EC2. Ejecutar terraform apply -var-file=$TF_VARS"
    fi

    # RDS
    echo -e "\n  ${BLUE}RDS PostgreSQL:${NC}"
    RDS_ID="${ECR_PREFIX}-postgres"
    RDS_STATUS=$(aws rds describe-db-instances \
        --db-instance-identifier "$RDS_ID" \
        --query "DBInstances[0].DBInstanceStatus" \
        --output text \
        --region "$AWS_REGION" 2>/dev/null)
    
    if [ "$RDS_STATUS" = "available" ]; then
        check_ok "RDS — available"
    elif [ -n "$RDS_STATUS" ] && [ "$RDS_STATUS" != "None" ]; then
        check_warn "RDS — $RDS_STATUS"
    else
        check_fail "RDS no encontrado"
    fi

    # ECR
    echo -e "\n  ${BLUE}ECR Repositories:${NC}"
    BACKEND_IMAGES=$(aws ecr describe-images \
        --repository-name "${ECR_PREFIX}-backend" \
        --query 'imageDetails | length(@)' \
        --output text \
        --region "$AWS_REGION" 2>/dev/null)
    
    if [ -n "$BACKEND_IMAGES" ] && [ "$BACKEND_IMAGES" != "0" ] && [ "$BACKEND_IMAGES" != "None" ]; then
        BACKEND_LATEST=$(aws ecr describe-images \
            --repository-name "${ECR_PREFIX}-backend" \
            --query 'imageDetails | sort_by(@, &imagePushedAt) | [-1].imageTags[0]' \
            --output text \
            --region "$AWS_REGION" 2>/dev/null)
        check_ok "Backend ECR — $BACKEND_IMAGES imágenes (última: ${BACKEND_LATEST:-latest})"
    else
        check_warn "Backend ECR — sin imágenes"
    fi

    FRONTEND_IMAGES=$(aws ecr describe-images \
        --repository-name "${ECR_PREFIX}-frontend" \
        --query 'imageDetails | length(@)' \
        --output text \
        --region "$AWS_REGION" 2>/dev/null)
    
    if [ -n "$FRONTEND_IMAGES" ] && [ "$FRONTEND_IMAGES" != "0" ] && [ "$FRONTEND_IMAGES" != "None" ]; then
        FRONTEND_LATEST=$(aws ecr describe-images \
            --repository-name "${ECR_PREFIX}-frontend" \
            --query 'imageDetails | sort_by(@, &imagePushedAt) | [-1].imageTags[0]' \
            --output text \
            --region "$AWS_REGION" 2>/dev/null)
        check_ok "Frontend ECR — $FRONTEND_IMAGES imágenes (última: ${FRONTEND_LATEST:-latest})"
    else
        check_warn "Frontend ECR — sin imágenes"
    fi

    # S3
    echo -e "\n  ${BLUE}S3 Artifacts:${NC}"
    S3_BUCKET="${ECR_PREFIX}-artifacts"
    S3_EXISTS=$(aws s3api head-bucket --bucket "$S3_BUCKET" 2>&1)
    if [ $? -eq 0 ]; then
        check_ok "S3 bucket $S3_BUCKET — existe"
    else
        check_fail "S3 bucket $S3_BUCKET — no encontrado"
    fi
fi

# =============================================================================
# 3. CONTAINERS Y APLICACIÓN (vía SSM)
# =============================================================================
print_header "3. CONTAINERS Y APLICACIÓN (vía SSM)"

if [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" = "None" ]; then
    check_warn "Instance ID no disponible — saltando"
else
    echo -e "  ${CYAN}Consultando estado de containers...${NC}"
    
    CONTAINER_STATUS=$(ssm_exec "$INSTANCE_ID" '["echo BACKEND_STATUS=$(docker inspect --format={{.State.Status}} alwaysprint-backend-1 2>/dev/null || echo not_found); echo BACKEND_IMAGE=$(docker inspect --format={{.Config.Image}} alwaysprint-backend-1 2>/dev/null || echo N/A); echo FRONTEND_STATUS=$(docker inspect --format={{.State.Status}} alwaysprint-frontend-1 2>/dev/null || echo not_found); echo FRONTEND_IMAGE=$(docker inspect --format={{.Config.Image}} alwaysprint-frontend-1 2>/dev/null || echo N/A); echo REDIS_STATUS=$(docker inspect --format={{.State.Status}} alwaysprint-redis-1 2>/dev/null || echo not_found); echo HEALTH=$(curl -s http://localhost:8000/api/v1/health 2>/dev/null || echo FAIL); echo FRONTEND_HTTP=$(curl -s -o /dev/null -w %{http_code} http://localhost:3000/ 2>/dev/null || echo 000); echo NGINX_STATUS=$(systemctl is-active nginx 2>/dev/null || echo inactive); echo SSL_EXISTS=$(test -d /etc/letsencrypt/live && ls /etc/letsencrypt/live/ | head -1 || echo no)"]' 10)
    
    if [ -n "$CONTAINER_STATUS" ]; then
        eval $(echo "$CONTAINER_STATUS" | grep -E "^(BACKEND_|FRONTEND_|REDIS_|HEALTH|NGINX_|SSL_)" | head -20)
        
        # Backend
        echo -e "\n  ${BLUE}Backend:${NC}"
        if [ "$BACKEND_STATUS" = "running" ]; then
            check_ok "Container — running"
        elif [ "$BACKEND_STATUS" = "not_found" ]; then
            check_fail "Container — no existe"
            recommend "Backend no desplegado. Ejecutar workflow Deploy Backend en GitHub Actions"
        else
            check_fail "Container — $BACKEND_STATUS"
        fi
        
        if echo "$HEALTH" | grep -q "healthy"; then
            BTAG=$(echo "$HEALTH" | grep -o '"build_tag":"[^"]*"' | cut -d'"' -f4)
            check_ok "Health check — OK (build: ${BTAG:-dev})"
        elif [ "$BACKEND_STATUS" = "running" ]; then
            check_fail "Health check — FALLO"
        fi
        echo -e "  ${NC}  Imagen: ${BACKEND_IMAGE:-N/A}"
        
        # Frontend
        echo -e "\n  ${BLUE}Frontend:${NC}"
        if [ "$FRONTEND_STATUS" = "running" ]; then
            check_ok "Container — running"
        elif [ "$FRONTEND_STATUS" = "not_found" ]; then
            check_fail "Container — no existe"
            recommend "Frontend no desplegado. Ejecutar workflow Deploy Frontend en GitHub Actions"
        else
            check_fail "Container — $FRONTEND_STATUS"
        fi
        
        if [ "$FRONTEND_HTTP" = "200" ] || [ "$FRONTEND_HTTP" = "302" ] || [ "$FRONTEND_HTTP" = "307" ]; then
            check_ok "HTTP local — $FRONTEND_HTTP"
        elif [ "$FRONTEND_STATUS" = "running" ]; then
            check_fail "HTTP local — $FRONTEND_HTTP"
        fi
        echo -e "  ${NC}  Imagen: ${FRONTEND_IMAGE:-N/A}"
        
        # Redis
        echo -e "\n  ${BLUE}Redis:${NC}"
        if [ "$REDIS_STATUS" = "running" ]; then
            check_ok "Container — running"
        else
            check_warn "Container — ${REDIS_STATUS:-not_found}"
        fi
        
        # Nginx & SSL
        echo -e "\n  ${BLUE}Nginx & SSL:${NC}"
        if [ "$NGINX_STATUS" = "active" ]; then
            check_ok "Nginx — active"
        else
            check_fail "Nginx — ${NGINX_STATUS:-inactive}"
        fi
        
        if [ "$SSL_EXISTS" != "no" ] && [ -n "$SSL_EXISTS" ]; then
            check_ok "Certificado SSL — presente ($SSL_EXISTS)"
        else
            check_warn "Certificado SSL — no configurado"
            SSL_AUTOFIX=true
        fi
    else
        check_fail "No se pudo conectar vía SSM"
        recommend "SSM no responde. Verificar IAM role con AmazonSSMManagedInstanceCore"
    fi
fi

# =============================================================================
# 4. ENDPOINTS PÚBLICOS
# =============================================================================
print_header "4. ENDPOINTS PÚBLICOS"

echo -e "\n  ${BLUE}HTTPS:${NC}"
if [ "$DNS_OK" = "true" ]; then
    HEALTH_RESP=$(curl -s --max-time $TIMEOUT "https://${DOMAIN}/api/v1/health" 2>/dev/null)
    if [ $? -eq 0 ] && echo "$HEALTH_RESP" | grep -q "healthy"; then
        BUILD=$(echo "$HEALTH_RESP" | grep -o '"build_tag":"[^"]*"' | cut -d'"' -f4)
        check_ok "Backend HTTPS — OK (build: ${BUILD:-dev})"
    else
        HEALTH_HTTP=$(curl -s --max-time $TIMEOUT "http://${EC2_IP}/api/v1/health" 2>/dev/null)
        if echo "$HEALTH_HTTP" | grep -q "healthy"; then
            check_warn "Backend responde en HTTP directo pero no HTTPS"
        else
            check_fail "Backend no responde en HTTPS ni HTTP directo"
        fi
    fi

    FRONTEND_RESP=$(curl -s -o /dev/null -w "%{http_code}" --max-time $TIMEOUT "https://${DOMAIN}/" 2>/dev/null)
    if [ "$FRONTEND_RESP" = "200" ] || [ "$FRONTEND_RESP" = "302" ] || [ "$FRONTEND_RESP" = "307" ]; then
        check_ok "Frontend HTTPS — HTTP $FRONTEND_RESP"
    else
        check_warn "Frontend HTTPS — HTTP ${FRONTEND_RESP:-timeout}"
    fi
else
    echo -e "  ${YELLOW}  DNS no apunta al EC2 — probando HTTP directo a $EC2_IP${NC}"
    if [ -n "$EC2_IP" ]; then
        HEALTH_DIRECT=$(curl -s --max-time $TIMEOUT "http://${EC2_IP}/api/v1/health" 2>/dev/null)
        if echo "$HEALTH_DIRECT" | grep -q "healthy"; then
            check_ok "Backend HTTP directo ($EC2_IP) — OK"
        else
            check_fail "Backend no responde por HTTP directo a $EC2_IP"
        fi
        
        FRONT_DIRECT=$(curl -s -o /dev/null -w "%{http_code}" --max-time $TIMEOUT "http://${EC2_IP}/" 2>/dev/null)
        if [ "$FRONT_DIRECT" = "200" ] || [ "$FRONT_DIRECT" = "302" ] || [ "$FRONT_DIRECT" = "307" ]; then
            check_ok "Frontend HTTP directo ($EC2_IP) — HTTP $FRONT_DIRECT"
        else
            check_warn "Frontend HTTP directo — HTTP ${FRONT_DIRECT:-timeout}"
        fi
    fi
fi

# SSL
echo -e "\n  ${BLUE}Certificado SSL:${NC}"
if [ "$DNS_OK" = "true" ]; then
    SSL_EXPIRY=$(echo | openssl s_client -servername "$DOMAIN" -connect "${DOMAIN}:443" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
    if [ -n "$SSL_EXPIRY" ]; then
        EXPIRY_EPOCH=$(date -j -f "%b %d %H:%M:%S %Y %Z" "$SSL_EXPIRY" +%s 2>/dev/null || date -d "$SSL_EXPIRY" +%s 2>/dev/null)
        NOW_EPOCH=$(date +%s)
        DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))
        if [ "$DAYS_LEFT" -gt 14 ]; then
            check_ok "SSL válido — expira en ${DAYS_LEFT} días"
        elif [ "$DAYS_LEFT" -gt 0 ]; then
            check_warn "SSL expira pronto — ${DAYS_LEFT} días"
        else
            check_fail "SSL EXPIRADO"
        fi
    else
        check_warn "SSL no disponible (certbot pendiente)"
        SSL_AUTOFIX=true
    fi
else
    check_warn "SSL no verificable (DNS no apunta al EC2)"
fi

# =============================================================================
# 5. ERRORES RECIENTES
# =============================================================================
print_header "5. ERRORES RECIENTES"

if [ -n "$INSTANCE_ID" ] && [ "$INSTANCE_ID" != "None" ]; then
    LOGS=$(ssm_exec "$INSTANCE_ID" '["echo \"=== BACKEND ===\"; docker logs alwaysprint-backend-1 --tail 30 2>&1 | grep -i \"error\\|traceback\\|critical\" | tail -5 || echo \"Sin errores\"; echo; echo \"=== FRONTEND ===\"; docker logs alwaysprint-frontend-1 --tail 30 2>&1 | grep -i \"error\" | grep -v \"favicon\\|_next\\|NEXT\" | tail -3 || echo \"Sin errores\""]' 8)
    
    if [ -n "$LOGS" ] && [ "$LOGS" != "None" ]; then
        echo ""
        echo "$LOGS" | while IFS= read -r line; do
            if echo "$line" | grep -qi "error\|traceback\|critical"; then
                echo -e "  ${RED}│${NC} $line"
            elif echo "$line" | grep -qi "==="; then
                echo -e "  ${BLUE}│${NC} $line"
            elif echo "$line" | grep -qi "Sin errores"; then
                echo -e "  ${GREEN}│${NC} $line"
            else
                echo -e "  ${NC}│ $line"
            fi
        done
        
        if echo "$LOGS" | grep -qi "error\|traceback\|critical"; then
            check_warn "Se encontraron errores en logs recientes"
        else
            check_ok "Sin errores en logs recientes"
        fi
    fi
else
    check_warn "No se pueden consultar logs (sin Instance ID)"
fi

# =============================================================================
# RESUMEN Y RECOMENDACIONES
# =============================================================================
print_header "RESUMEN [$ENV_LABEL]"

echo ""
echo -e "  ${GREEN}✓ Pasaron:${NC}  $PASS"
echo -e "  ${RED}✗ Fallaron:${NC} $FAIL"
echo -e "  ${YELLOW}⚠ Warnings:${NC} $WARN"
echo ""

if [ $FAIL -eq 0 ] && [ $WARN -eq 0 ]; then
    echo -e "  ${GREEN}══════════════════════════════════════════${NC}"
    echo -e "  ${GREEN}  ✓ $ENV_LABEL 100% OPERATIVO${NC}"
    echo -e "  ${GREEN}══════════════════════════════════════════${NC}"
elif [ $FAIL -eq 0 ]; then
    echo -e "  ${GREEN}══════════════════════════════════════════${NC}"
    echo -e "  ${GREEN}  ✓ $ENV_LABEL OPERATIVO (con warnings)${NC}"
    echo -e "  ${GREEN}══════════════════════════════════════════${NC}"
elif [ $FAIL -le 2 ]; then
    echo -e "  ${YELLOW}══════════════════════════════════════════${NC}"
    echo -e "  ${YELLOW}  ⚠ $ENV_LABEL CON PROBLEMAS MENORES${NC}"
    echo -e "  ${YELLOW}══════════════════════════════════════════${NC}"
else
    echo -e "  ${RED}══════════════════════════════════════════${NC}"
    echo -e "  ${RED}  ✗ $ENV_LABEL CON PROBLEMAS${NC}"
    echo -e "  ${RED}══════════════════════════════════════════${NC}"
fi

# Mostrar recomendaciones si hay problemas
if [ ${#RECOMMENDATIONS[@]} -gt 0 ]; then
    echo ""
    echo -e "  ${BOLD}Acciones recomendadas:${NC}"
    echo ""
    for i in "${!RECOMMENDATIONS[@]}"; do
        echo -e "  ${CYAN}$((i+1)).${NC} ${RECOMMENDATIONS[$i]}"
    done
    
    # Ofrecer certbot automático solo si DNS apunta correctamente
    if [ "$SSL_AUTOFIX" = "true" ] && [ "$DNS_OK" = "true" ]; then
        echo ""
        echo -e -n "  ${BOLD}¿Ejecutar certbot automáticamente? [y/N]:${NC} "
        read -r REPLY
        if [[ "$REPLY" =~ ^[Yy]$ ]]; then
            echo -e "  ${CYAN}Ejecutando certbot vía SSM...${NC}"
            FIX_CMD_ID=$(aws ssm send-command \
                --instance-ids "$INSTANCE_ID" \
                --document-name "AWS-RunShellScript" \
                --parameters "{\"commands\":[\"certbot --nginx -d $DOMAIN --non-interactive --agree-tos -m antonio@robles.ai && systemctl reload nginx\"]}" \
                --query "Command.CommandId" \
                --output text \
                --region "$AWS_REGION" 2>/dev/null)
            
            if [ -n "$FIX_CMD_ID" ] && [ "$FIX_CMD_ID" != "None" ]; then
                echo -e "  ${CYAN}Esperando resultado (15s)...${NC}"
                sleep 15
                FIX_RESULT=$(aws ssm get-command-invocation \
                    --command-id "$FIX_CMD_ID" \
                    --instance-id "$INSTANCE_ID" \
                    --query '[Status, StandardOutputContent]' \
                    --output text \
                    --region "$AWS_REGION" 2>/dev/null)
                
                if echo "$FIX_RESULT" | grep -qi "Success\|Successfully"; then
                    echo -e "  ${GREEN}✓ SSL configurado correctamente${NC}"
                else
                    echo -e "  ${RED}✗ Falló. Verificar manualmente vía SSM${NC}"
                fi
            fi
        fi
    fi
fi

echo ""
echo -e "  ${BLUE}Dashboard:${NC}  https://${DOMAIN}"
echo -e "  ${BLUE}API Docs:${NC}   https://${DOMAIN}/docs"
echo -e "  ${BLUE}Health:${NC}     https://${DOMAIN}/api/v1/health"
[ -n "$EC2_IP" ] && echo -e "  ${BLUE}HTTP directo:${NC} http://${EC2_IP}/api/v1/health"
echo ""
