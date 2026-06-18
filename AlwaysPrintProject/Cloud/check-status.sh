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
#   5. Consulta métricas de escalabilidad (WebSocket, memoria, FD, pool BD, red)
#   6. Valida variables de entorno
#   7. Muestra estadísticas de la instancia
#   8. Muestra errores recientes y acciones recomendadas
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

# Acumular registros DNS pendientes (tipo|nombre|valor)
DNS_PENDING=()

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

# Ejecutar comando SSM y esperar resultado (con reintentos y detalle)
ssm_exec() {
    local instance_id="$1"
    local commands="$2"
    local wait_seconds="${3:-8}"
    local max_retries=3
    local retry=0

    # Enviar comando
    local cmd_id=$(aws ssm send-command \
        --instance-ids "$instance_id" \
        --document-name "AWS-RunShellScript" \
        --parameters "{\"commands\":$commands}" \
        --query "Command.CommandId" \
        --output text \
        --region "$AWS_REGION" 2>/dev/null)

    if [ -z "$cmd_id" ] || [ "$cmd_id" = "None" ]; then
        echo "" >&2
        echo "  ⚠ SSM: no se pudo enviar comando (send-command falló)" >&2
        return 1
    fi

    # Esperar resultado con reintentos
    while [ $retry -lt $max_retries ]; do
        sleep "$wait_seconds"
        
        local status=$(aws ssm get-command-invocation \
            --command-id "$cmd_id" \
            --instance-id "$instance_id" \
            --query 'Status' \
            --output text \
            --region "$AWS_REGION" 2>/dev/null)

        case "$status" in
            Success)
                aws ssm get-command-invocation \
                    --command-id "$cmd_id" \
                    --instance-id "$instance_id" \
                    --query 'StandardOutputContent' \
                    --output text \
                    --region "$AWS_REGION" 2>/dev/null
                return 0
                ;;
            Failed)
                echo "" >&2
                echo "  ⚠ SSM: comando falló (cmd_id=$cmd_id)" >&2
                return 1
                ;;
            InProgress)
                retry=$((retry + 1))
                if [ $retry -lt $max_retries ]; then
                    echo "  ⏳ SSM: aún en progreso (intento $retry/$max_retries, cmd_id=${cmd_id:0:8}...)" >&2
                fi
                ;;
            *)
                retry=$((retry + 1))
                if [ $retry -lt $max_retries ]; then
                    echo "  ⏳ SSM: estado=$status (intento $retry/$max_retries)" >&2
                fi
                ;;
        esac
    done

    # Último intento: obtener lo que haya
    local output=$(aws ssm get-command-invocation \
        --command-id "$cmd_id" \
        --instance-id "$instance_id" \
        --query 'StandardOutputContent' \
        --output text \
        --region "$AWS_REGION" 2>/dev/null)

    if [ -n "$output" ] && [ "$output" != "None" ]; then
        echo "$output"
        return 0
    fi

    echo "" >&2
    echo "  ⚠ SSM: timeout después de $max_retries intentos (cmd_id=${cmd_id:0:8}...)" >&2
    return 1
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

# Verificar registros SES (DKIM, MX, SPF) desde outputs de Terraform
if [ -n "$TF_OUTPUT" ]; then
    echo -e "\n  ${BLUE}Registros SES (email):${NC}"

    # Extraer zona base del dominio
    ZONE_NAME=$(echo "$TF_OUTPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ses = d.get('ses_dns_records', {}).get('value', {})
# Obtener zona del primer registro
for k, v in ses.items():
    name = v.get('nombre', '')
    if 'amazonses' in name:
        # Extraer zona: _amazonses.ZONA
        print(name.replace('_amazonses.', ''))
        break
" 2>/dev/null)

    # Verificar TXT _amazonses (verificación de dominio)
    SES_VERIFY=$(dig +short TXT "_amazonses.${ZONE_NAME}" 2>/dev/null | head -1)
    if [ -n "$SES_VERIFY" ]; then
        check_ok "SES verificación — dominio ${ZONE_NAME} verificado"
    else
        check_warn "SES verificación — TXT _amazonses.${ZONE_NAME} no encontrado"
        SES_TXT_VALUE=$(echo "$TF_OUTPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ses = d.get('ses_dns_records', {}).get('value', {})
for k, v in ses.items():
    if 'verificacion' in k:
        print(v.get('valor', ''))
        break
" 2>/dev/null)
        DNS_PENDING+=("TXT|_amazonses.${ZONE_NAME}|${SES_TXT_VALUE}")
    fi

    # Verificar cada DKIM individualmente
    DKIM_RECORDS=$(echo "$TF_OUTPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ses = d.get('ses_dns_records', {}).get('value', {})
for k, v in ses.items():
    if 'dkim' in k:
        print(v.get('nombre', '') + '|' + v.get('valor', ''))
" 2>/dev/null)

    DKIM_OK=0
    DKIM_TOTAL=0
    while IFS='|' read -r dkim_name dkim_value; do
        [ -z "$dkim_name" ] && continue
        DKIM_TOTAL=$((DKIM_TOTAL + 1))
        RESOLVED=$(dig +short CNAME "$dkim_name" 2>/dev/null | head -1)
        if echo "$RESOLVED" | grep -qi "amazonses"; then
            check_ok "DKIM $DKIM_TOTAL — $dkim_name ✓"
            DKIM_OK=$((DKIM_OK + 1))
        else
            check_fail "DKIM $DKIM_TOTAL — $dkim_name → ${RESOLVED:-no resuelve}"
            DNS_PENDING+=("CNAME|${dkim_name}|${dkim_value}")
        fi
    done <<< "$DKIM_RECORDS"

    if [ "$DKIM_TOTAL" -eq 0 ]; then
        check_warn "DKIM — no se encontraron registros en terraform output"
    fi

    # Verificar MX
    MX_NAME="mail.${ZONE_NAME}"
    MX_RECORD=$(dig +short MX "$MX_NAME" 2>/dev/null | head -1)
    if echo "$MX_RECORD" | grep -q "amazonses.com"; then
        check_ok "MX ($MX_NAME) — configurado"
    else
        check_warn "MX ($MX_NAME) — ${MX_RECORD:-no definido}"
        DNS_PENDING+=("MX|${MX_NAME}|10 feedback-smtp.${AWS_REGION}.amazonses.com")
    fi

    # Verificar SPF
    SPF_RECORD=$(dig +short TXT "$MX_NAME" 2>/dev/null | grep "spf" | head -1)
    if echo "$SPF_RECORD" | grep -q "amazonses.com"; then
        check_ok "SPF ($MX_NAME) — incluye amazonses.com"
    else
        check_warn "SPF ($MX_NAME) — ${SPF_RECORD:-no definido}"
        DNS_PENDING+=("TXT|${MX_NAME}|v=spf1 include:amazonses.com ~all")
    fi
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
        
        # Workers Multi-Worker (via /api/v1/health/detailed)
        echo -e "\n  ${BLUE}Workers Uvicorn:${NC}"
        if [ "$BACKEND_STATUS" = "running" ]; then
            # Consultar health/detailed múltiples veces para descubrir todos los workers
            WORKER_INFO=$(ssm_exec "$INSTANCE_ID" '["WORKERS=\"\"; for i in $(seq 1 20); do W=$(curl -s http://localhost:8000/api/v1/health/detailed 2>/dev/null | python3 -c \"import sys,json; d=json.load(sys.stdin); print(d.get(\\\"worker_id\\\",\\\"\\\") + \\\"|\\\" + str(d.get(\\\"connections\\\",{}).get(\\\"workstations\\\",0)) + \\\"|\\\" + str(d.get(\\\"redis\\\",{}).get(\\\"connected\\\",False)) + \\\"|\\\" + str(d.get(\\\"memory_mb\\\",0)))\" 2>/dev/null); [ -n \"$W\" ] && WORKERS=\"$WORKERS\n$W\"; done; echo \"$WORKERS\" | sort | uniq -c | sort -rn | grep -v \"^$\""]' 8)
            
            if [ -n "$WORKER_INFO" ] && ! echo "$WORKER_INFO" | grep -q "FAIL\|Traceback"; then
                # Contar workers únicos
                WORKER_COUNT=$(echo "$WORKER_INFO" | grep -c "|")
                
                if [ "$WORKER_COUNT" -ge 2 ]; then
                    check_ok "Multi-worker activo — $WORKER_COUNT workers detectados"
                elif [ "$WORKER_COUNT" -eq 1 ]; then
                    check_warn "Solo 1 worker detectado (esperado ≥2 en DEV)"
                else
                    check_warn "No se pudieron detectar workers"
                fi
                
                # Mostrar detalle por worker
                echo "$WORKER_INFO" | grep "|" | while IFS= read -r line; do
                    HITS=$(echo "$line" | awk '{print $1}')
                    WDATA=$(echo "$line" | awk '{print $2}')
                    WID=$(echo "$WDATA" | cut -d'|' -f1)
                    WS_COUNT=$(echo "$WDATA" | cut -d'|' -f2)
                    REDIS_CONN=$(echo "$WDATA" | cut -d'|' -f3)
                    MEM_MB=$(echo "$WDATA" | cut -d'|' -f4)
                    
                    REDIS_ICON="🟢"
                    [ "$REDIS_CONN" = "False" ] && REDIS_ICON="🔴"
                    
                    echo -e "  ${NC}    ${WID}: ${WS_COUNT} workstations | Redis: ${REDIS_ICON} | Mem: ${MEM_MB} MB"
                done
            else
                # Fallback: endpoint no disponible (versión vieja sin health/detailed)
                check_warn "Endpoint /health/detailed no disponible (versión anterior a Redis scaling)"
            fi
        fi
        
        # Alembic Migrations
        echo -e "\n  ${BLUE}Alembic Migrations:${NC}"
        ALEMBIC_CURRENT=$(ssm_exec "$INSTANCE_ID" '["docker exec alwaysprint-backend-1 alembic current 2>/dev/null || echo FAIL"]' 5)
        if [ -n "$ALEMBIC_CURRENT" ] && [ "$ALEMBIC_CURRENT" != "FAIL" ]; then
            ALEMBIC_HEAD=$(echo "$ALEMBIC_CURRENT" | grep "(head)" | sed 's/ (head)//')
            if [ -n "$ALEMBIC_HEAD" ]; then
                check_ok "Migración actual — $ALEMBIC_HEAD (head)"
            else
                check_warn "Migración — $ALEMBIC_CURRENT (posiblemente no en head)"
            fi
        else
            check_warn "No se pudo consultar estado de migraciones"
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
        check_fail "SSM: no se obtuvo respuesta de containers (ver detalle arriba)"
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
        recommend "Configurar SSL con certbot para $DOMAIN"
    fi
else
    check_warn "SSL no verificable (DNS no apunta al EC2)"
fi

# =============================================================================
# 5. MÉTRICAS DE ESCALABILIDAD
# =============================================================================
print_header "5. MÉTRICAS DE ESCALABILIDAD"

echo -e "  ${CYAN}Consultando /api/v1/system/metrics...${NC}"

# Necesitamos un token admin para consultar el endpoint protegido
# Intentar obtener métricas vía SSM (curl interno sin auth desde el backend)
if [ -n "$INSTANCE_ID" ] && [ "$INSTANCE_ID" != "None" ] && [ "$BACKEND_STATUS" = "running" ]; then
    METRICS_RAW=$(ssm_exec "$INSTANCE_ID" '["docker exec alwaysprint-backend-1 python -c \"import asyncio; from app.services.scalability_metrics import scalability_collector; from app.core.database import SessionLocal; import json; db = SessionLocal(); m = asyncio.run(scalability_collector.collect_all_metrics(db=db)); db.close(); print(m.model_dump_json())\" 2>&1 || echo FAIL"]' 15)

    # Extraer solo la línea JSON (puede haber logs de SQLAlchemy antes)
    METRICS_JSON=$(echo "$METRICS_RAW" | grep '^{' | tail -1)

    if [ -n "$METRICS_JSON" ] && [ "$METRICS_JSON" != "FAIL" ] && echo "$METRICS_JSON" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
        echo ""

        # Parsear métricas con python3
        METRICS_PARSED=$(echo "$METRICS_JSON" | python3 -c "
import sys, json
m = json.load(sys.stdin)

# WebSocket
ws = m.get('websocket')
if ws:
    total = ws.get('total', 0)
    avail = ws.get('data_available', True)
    if not avail:
        print('WS_STATUS=unavailable')
    elif total > 4500:
        print(f'WS_STATUS=critical')
    elif total > 3000:
        print(f'WS_STATUS=warning')
    else:
        print(f'WS_STATUS=ok')
    print(f'WS_TOTAL={total}')
    print(f'WS_WORKSTATIONS={ws.get(\"workstation_count\", 0)}')
    print(f'WS_OPERATORS={ws.get(\"operator_count\", 0)}')
else:
    print('WS_STATUS=null')

# Memoria Python
mem = m.get('python_memory')
if mem:
    rss = mem.get('rss_mb')
    avg = mem.get('avg_per_workstation_mb')
    container = mem.get('container_total_mb')
    print(f'MEM_RSS={rss if rss is not None else \"N/A\"}')
    print(f'MEM_AVG_WS={avg if avg is not None else \"N/A\"}')
    print(f'MEM_CONTAINER={container if container is not None else \"N/A\"}')
    if avg is not None and avg > 0:
        if avg > 4.0:
            print('MEM_STATUS=critical')
        elif avg > 2.0:
            print('MEM_STATUS=warning')
        else:
            print('MEM_STATUS=ok')
    else:
        print('MEM_STATUS=ok')
else:
    print('MEM_STATUS=null')

# File descriptors
fd = m.get('file_descriptors')
if fd:
    pct = fd.get('usage_percent')
    print(f'FD_OPEN={fd.get(\"open_count\", \"N/A\")}')
    print(f'FD_LIMIT={fd.get(\"limit\", \"N/A\")}')
    print(f'FD_PCT={pct if pct is not None else \"N/A\"}')
    if pct is not None:
        if pct > 80.0:
            print('FD_STATUS=critical')
        elif pct > 60.0:
            print('FD_STATUS=warning')
        else:
            print('FD_STATUS=ok')
    else:
        print('FD_STATUS=null')
else:
    print('FD_STATUS=null')

# Pool BD
pool = m.get('db_pool')
if pool:
    pct = pool.get('usage_percent')
    print(f'POOL_CHECKED={pool.get(\"checked_out\", \"N/A\")}')
    print(f'POOL_IDLE={pool.get(\"idle\", \"N/A\")}')
    print(f'POOL_SIZE={pool.get(\"pool_size\", \"N/A\")}')
    print(f'POOL_PG={pool.get(\"pg_active_connections\", \"N/A\")}')
    print(f'POOL_PCT={pct if pct is not None else \"N/A\"}')
    if pct is not None:
        if pct > 80.0:
            print('POOL_STATUS=critical')
        elif pct > 60.0:
            print('POOL_STATUS=warning')
        else:
            print('POOL_STATUS=ok')
    else:
        print('POOL_STATUS=null')
else:
    print('POOL_STATUS=null')

# Red
net = m.get('network')
if net:
    tx_rate = net.get('tx_rate_bps')
    rx_rate = net.get('rx_rate_bps')
    print(f'NET_RX_BYTES={net.get(\"rx_bytes\", \"N/A\")}')
    print(f'NET_TX_BYTES={net.get(\"tx_bytes\", \"N/A\")}')
    if tx_rate is not None:
        tx_mbs = round(tx_rate / (1024*1024), 2)
        print(f'NET_TX_MBS={tx_mbs}')
        if tx_mbs > 80.0:
            print('NET_STATUS=critical')
        elif tx_mbs > 50.0:
            print('NET_STATUS=warning')
        else:
            print('NET_STATUS=ok')
    else:
        print('NET_TX_MBS=N/A')
        print('NET_STATUS=first_read')
else:
    print('NET_STATUS=null')
" 2>/dev/null)

        if [ -n "$METRICS_PARSED" ]; then
            eval "$METRICS_PARSED"

            # WebSocket
            echo -e "\n  ${BLUE}WebSocket Connections:${NC}"
            if [ "$WS_STATUS" = "ok" ]; then
                check_ok "Total: $WS_TOTAL (ws: $WS_WORKSTATIONS, ops: $WS_OPERATORS) — verde"
            elif [ "$WS_STATUS" = "warning" ]; then
                check_warn "Total: $WS_TOTAL (ws: $WS_WORKSTATIONS, ops: $WS_OPERATORS) — umbral 3000 superado"
            elif [ "$WS_STATUS" = "critical" ]; then
                check_fail "Total: $WS_TOTAL (ws: $WS_WORKSTATIONS, ops: $WS_OPERATORS) — CRÍTICO (>4500)"
                recommend "Conexiones WebSocket en zona crítica ($WS_TOTAL). Considerar escalado horizontal."
            elif [ "$WS_STATUS" = "unavailable" ]; then
                check_warn "ConnectionManager no disponible"
            else
                check_warn "Métrica no disponible"
            fi

            # Memoria Python
            echo -e "\n  ${BLUE}Memoria Python:${NC}"
            if [ "$MEM_STATUS" = "ok" ]; then
                check_ok "RSS: ${MEM_RSS} MB | Por WS: ${MEM_AVG_WS} MB/ws — verde"
            elif [ "$MEM_STATUS" = "warning" ]; then
                check_warn "RSS: ${MEM_RSS} MB | Por WS: ${MEM_AVG_WS} MB/ws — umbral 2 MB/ws superado"
            elif [ "$MEM_STATUS" = "critical" ]; then
                check_fail "RSS: ${MEM_RSS} MB | Por WS: ${MEM_AVG_WS} MB/ws — CRÍTICO (>4 MB/ws)"
                recommend "Memoria por workstation en zona crítica (${MEM_AVG_WS} MB/ws). Investigar memory leaks."
            else
                check_warn "Métrica no disponible"
            fi

            # File Descriptors
            echo -e "\n  ${BLUE}File Descriptors:${NC}"
            if [ "$FD_STATUS" = "ok" ]; then
                check_ok "Abiertos: $FD_OPEN / $FD_LIMIT (${FD_PCT}%) — verde"
            elif [ "$FD_STATUS" = "warning" ]; then
                check_warn "Abiertos: $FD_OPEN / $FD_LIMIT (${FD_PCT}%) — umbral 60% superado"
            elif [ "$FD_STATUS" = "critical" ]; then
                check_fail "Abiertos: $FD_OPEN / $FD_LIMIT (${FD_PCT}%) — CRÍTICO (>80%)"
                recommend "File descriptors en zona crítica (${FD_PCT}%). Verificar fugas de conexiones."
            else
                check_warn "Métrica no disponible"
            fi

            # Pool BD
            echo -e "\n  ${BLUE}Pool de Base de Datos:${NC}"
            if [ "$POOL_STATUS" = "ok" ]; then
                check_ok "En uso: $POOL_CHECKED / $POOL_SIZE (${POOL_PCT}%) | PG activas: $POOL_PG — verde"
            elif [ "$POOL_STATUS" = "warning" ]; then
                check_warn "En uso: $POOL_CHECKED / $POOL_SIZE (${POOL_PCT}%) | PG activas: $POOL_PG — umbral 60% superado"
            elif [ "$POOL_STATUS" = "critical" ]; then
                check_fail "En uso: $POOL_CHECKED / $POOL_SIZE (${POOL_PCT}%) | PG activas: $POOL_PG — CRÍTICO (>80%)"
                recommend "Pool de BD en zona crítica (${POOL_PCT}%). Considerar aumentar pool_size o investigar conexiones sin liberar."
            else
                check_warn "Métrica no disponible"
            fi

            # Red
            echo -e "\n  ${BLUE}Tráfico de Red:${NC}"
            if [ "$NET_STATUS" = "ok" ]; then
                check_ok "TX rate: ${NET_TX_MBS} MB/s — verde"
            elif [ "$NET_STATUS" = "warning" ]; then
                check_warn "TX rate: ${NET_TX_MBS} MB/s — umbral 50 MB/s superado"
            elif [ "$NET_STATUS" = "critical" ]; then
                check_fail "TX rate: ${NET_TX_MBS} MB/s — CRÍTICO (>80 MB/s)"
                recommend "Tráfico de red en zona crítica (${NET_TX_MBS} MB/s). Verificar saturación de ancho de banda."
            elif [ "$NET_STATUS" = "first_read" ]; then
                check_ok "Bytes TX: $NET_TX_BYTES (primera lectura, tasa disponible en próxima consulta)"
            else
                check_warn "Métrica no disponible"
            fi
        else
            check_warn "No se pudieron parsear las métricas de escalabilidad"
        fi
    else
        check_warn "No se pudieron obtener métricas de escalabilidad (backend puede estar inicializando)"
    fi
else
    check_warn "No se pueden consultar métricas (backend no disponible)"
fi

# =============================================================================
# 6. VALIDACIÓN DE VARIABLES DE ENTORNO
# =============================================================================
print_header "6. VALIDACIÓN DE VARIABLES DE ENTORNO"

if [ -n "$INSTANCE_ID" ] && [ "$INSTANCE_ID" != "None" ]; then
    echo -e "  ${CYAN}Verificando variables del backend...${NC}"
    
    DOCKER_ENV=$(ssm_exec "$INSTANCE_ID" '["docker exec alwaysprint-backend-1 env 2>/dev/null"]' 6)
    
    if [ -n "$DOCKER_ENV" ]; then
        # Extraer variables relevantes
        D_BOOTSTRAP=$(echo "$DOCKER_ENV" | grep "^DEFAULT_BOOTSTRAP_DOMAINS=" | cut -d= -f2-)
        D_FRONTEND_URL=$(echo "$DOCKER_ENV" | grep "^FRONTEND_URL=" | cut -d= -f2-)
        D_BUILD_TAG=$(echo "$DOCKER_ENV" | grep "^BUILD_TAG=" | cut -d= -f2-)
        D_LOG_LEVEL=$(echo "$DOCKER_ENV" | grep "^LOG_LEVEL=" | cut -d= -f2-)
        D_DB_URL=$(echo "$DOCKER_ENV" | grep "^DATABASE_URL=" | cut -d= -f2- | sed 's/:[^:@]*@/:***@/')
        
        echo -e "\n  ${BLUE}Variables clave:${NC}"
        
        # Validar DEFAULT_BOOTSTRAP_DOMAINS
        if [ -n "$D_BOOTSTRAP" ]; then
            if [ "$ENV" = "dev" ] && echo "$D_BOOTSTRAP" | grep -q "dev.iol.pe"; then
                check_ok "DEFAULT_BOOTSTRAP_DOMAINS=$D_BOOTSTRAP"
            elif [ "$ENV" = "prod" ] && echo "$D_BOOTSTRAP" | grep -q "apps.iol.pe"; then
                check_ok "DEFAULT_BOOTSTRAP_DOMAINS=$D_BOOTSTRAP"
            else
                check_fail "DEFAULT_BOOTSTRAP_DOMAINS=$D_BOOTSTRAP (no coincide con entorno $ENV)"
                recommend "Corregir DEFAULT_BOOTSTRAP_DOMAINS en /opt/alwaysprint/.env y ejecutar: cd /opt/alwaysprint && docker compose up -d"
            fi
        else
            check_warn "DEFAULT_BOOTSTRAP_DOMAINS no definida (usará default del código: apps.iol.pe)"
            if [ "$ENV" = "dev" ]; then
                recommend "Agregar DEFAULT_BOOTSTRAP_DOMAINS=dev.iol.pe en /opt/alwaysprint/.env y ejecutar: cd /opt/alwaysprint && docker compose up -d"
            fi
        fi
        
        # Validar FRONTEND_URL
        if [ -n "$D_FRONTEND_URL" ]; then
            if echo "$D_FRONTEND_URL" | grep -q "$DOMAIN"; then
                check_ok "FRONTEND_URL=$D_FRONTEND_URL"
            else
                check_warn "FRONTEND_URL=$D_FRONTEND_URL (no coincide con dominio $DOMAIN)"
            fi
        fi
        
        # Mostrar info
        echo -e "  ${NC}  BUILD_TAG:  ${D_BUILD_TAG:-no definido}"
        echo -e "  ${NC}  LOG_LEVEL:  ${D_LOG_LEVEL:-no definido}"
        echo -e "  ${NC}  DB:         ${D_DB_URL:-no definido}"
    else
        check_warn "No se pudieron leer variables del contenedor"
    fi
else
    check_warn "Instance ID no disponible — saltando validación de env vars"
fi

# =============================================================================
# 7. ESTADÍSTICAS DE LA INSTANCIA
# =============================================================================
print_header "7. ESTADÍSTICAS DE LA INSTANCIA"

if [ -n "$INSTANCE_ID" ] && [ "$INSTANCE_ID" != "None" ]; then
    echo -e "  ${CYAN}Consultando recursos...${NC}"
    
    STATS=$(ssm_exec "$INSTANCE_ID" '["echo \"=== MEMORIA ===\"; free -h | grep -E \"Mem:|Swap:\"; echo; echo \"=== DISCO ===\"; df -h / | tail -1; echo; echo \"=== CPU ===\"; uptime; echo; echo \"=== DOCKER ===\"; docker stats --no-stream --format \"table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\" 2>/dev/null | head -5; echo; echo \"=== UPTIME CONTAINERS ===\"; docker ps --format \"table {{.Names}}\t{{.Status}}\t{{.Ports}}\" 2>/dev/null; echo; echo \"=== SWAP ===\"; swapon --show 2>/dev/null || echo none; cat /proc/sys/vm/swappiness 2>/dev/null"]' 8)
    
    if [ -n "$STATS" ]; then
        echo ""
        echo "$STATS" | while IFS= read -r line; do
            if echo "$line" | grep -q "^==="; then
                echo -e "  ${BLUE}│${NC} $line"
            else
                echo -e "  ${NC}│ $line"
            fi
        done
        
        # Verificar disco
        DISK_USE=$(echo "$STATS" | grep "/" | awk '{print $5}' | tr -d '%' | head -1)
        if [ -n "$DISK_USE" ] && [ "$DISK_USE" -gt 85 ]; then
            check_warn "Disco al ${DISK_USE}% — considerar limpieza"
            recommend "Limpiar imágenes Docker antiguas: docker system prune -a --filter 'until=168h'"
        elif [ -n "$DISK_USE" ]; then
            check_ok "Disco al ${DISK_USE}%"
        fi
        
        # Verificar memoria
        MEM_AVAIL=$(echo "$STATS" | grep "Mem:" | awk '{print $7}')
        if [ -n "$MEM_AVAIL" ]; then
            check_ok "Memoria disponible: $MEM_AVAIL"
        fi
        
        # Verificar swap
        SWAP_LINE=$(echo "$STATS" | grep "Swap:" | head -1)
        SWAP_TOTAL=$(echo "$SWAP_LINE" | awk '{print $2}')
        SWAP_USED=$(echo "$SWAP_LINE" | awk '{print $3}')
        SWAP_FILE=$(echo "$STATS" | grep -A1 "=== SWAP ===" | grep -v "===" | grep -v "^$" | head -1)
        SWAPPINESS=$(echo "$STATS" | tail -1 | grep -E "^[0-9]+$")
        
        if [ "$SWAP_TOTAL" = "0B" ] || [ -z "$SWAP_TOTAL" ]; then
            check_warn "Swap no configurado — riesgo de thrashing con poca RAM"
            recommend "Configurar swap: fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile"
        elif echo "$SWAP_FILE" | grep -q "swapfile\|partition"; then
            check_ok "Swap activo: $SWAP_TOTAL total, $SWAP_USED usado (swappiness=${SWAPPINESS:-?})"
        else
            check_ok "Swap: $SWAP_TOTAL total, $SWAP_USED usado"
        fi
    else
        check_warn "No se pudieron obtener estadísticas"
    fi
else
    check_warn "Instance ID no disponible — saltando estadísticas"
fi

# =============================================================================
# 8. ERRORES RECIENTES
# =============================================================================
print_header "8. ERRORES RECIENTES"

if [ -n "$INSTANCE_ID" ] && [ "$INSTANCE_ID" != "None" ]; then
    LOGS=$(ssm_exec "$INSTANCE_ID" '["echo \"=== BACKEND ===\"; docker logs alwaysprint-backend-1 --tail 50 2>&1 | grep -i \"error\\|traceback\\|critical\" | grep -v \"favicon\\|_next/static\" | tail -5 || echo \"Sin errores\"; echo; echo \"=== FRONTEND ===\"; docker logs alwaysprint-frontend-1 --tail 50 2>&1 | grep -i \"error\" | grep -v \"favicon\\|_next/static\\|chunk\" | cut -c1-200 | tail -3 || echo \"Sin errores\""]' 8)
    
    if [ -n "$LOGS" ] && [ "$LOGS" != "None" ]; then
        echo ""
        echo "$LOGS" | while IFS= read -r line; do
            if echo "$line" | grep -qi "Server Action"; then
                echo -e "  ${YELLOW}[Ignored]${NC} ${RED}│${NC} $line"
            elif echo "$line" | grep -qi "error\|traceback\|critical"; then
                echo -e "  ${RED}│${NC} $line"
            elif echo "$line" | grep -qi "==="; then
                echo -e "  ${BLUE}│${NC} $line"
            elif echo "$line" | grep -qi "Sin errores"; then
                echo -e "  ${GREEN}│${NC} $line"
            else
                echo -e "  ${NC}│ $line"
            fi
        done
        
        if echo "$LOGS" | grep -i "error\|traceback\|critical" | grep -qiv "Server Action"; then
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
if [ ${#DNS_PENDING[@]} -gt 0 ]; then
    echo ""
    echo -e "  ${BOLD}Registros DNS pendientes (Zone Editor):${NC}"
    echo ""
    printf "  ${CYAN}%-7s %-55s %s${NC}\n" "Tipo" "Nombre" "Valor"
    printf "  %-7s %-55s %s\n" "-------" "-------------------------------------------------------" "-----"
    for entry in "${DNS_PENDING[@]}"; do
        IFS='|' read -r dtype dname dvalue <<< "$entry"
        printf "  %-7s %-55s %s\n" "$dtype" "$dname" "$dvalue"
    done
fi

if [ ${#RECOMMENDATIONS[@]} -gt 0 ]; then
    echo ""
    echo -e "  ${BOLD}Otras acciones recomendadas:${NC}"
    echo ""
    for i in "${!RECOMMENDATIONS[@]}"; do
        echo -e "  ${CYAN}$((i+1)).${NC} ${RECOMMENDATIONS[$i]}"
    done
fi

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

echo ""
echo -e "  ${BLUE}Dashboard:${NC}  https://${DOMAIN}"
echo -e "  ${BLUE}API Docs:${NC}   https://${DOMAIN}/docs"
echo -e "  ${BLUE}Health:${NC}     https://${DOMAIN}/api/v1/health"
[ -n "$EC2_IP" ] && echo -e "  ${BLUE}HTTP directo:${NC} http://${EC2_IP}/api/v1/health"
echo ""
