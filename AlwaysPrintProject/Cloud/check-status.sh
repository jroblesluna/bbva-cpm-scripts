#!/bin/bash
# =============================================================================
# AlwaysPrint Cloud Manager - Script de verificación de estado
# Ejecutar desde tu máquina local para verificar que todo está operativo
# =============================================================================

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # Sin color

# Configuración
DOMAIN="alwaysprint.apps.iol.pe"
AWS_PROFILE="Antonio-Robles-425642439683"
TIMEOUT=10

# Detectar Instance ID dinámicamente (busca instancia con tag o nombre que contenga "alwaysprint")
detect_instance_id() {
    # Intentar encontrar la instancia por tag Name
    local id=$(aws ec2 describe-instances \
        --filters "Name=tag:Name,Values=*alwaysprint*" "Name=instance-state-name,Values=running" \
        --query 'Reservations[0].Instances[0].InstanceId' \
        --output text \
        --profile "$AWS_PROFILE" 2>/dev/null)
    
    # Si no encuentra por tag, buscar por Elastic IP
    if [ -z "$id" ] || [ "$id" = "None" ]; then
        id=$(aws ec2 describe-addresses \
            --filters "Name=public-ip,Values=34.213.90.95" \
            --query 'Addresses[0].InstanceId' \
            --output text \
            --profile "$AWS_PROFILE" 2>/dev/null)
    fi
    
    # Si aún no encuentra, buscar cualquier instancia running en el perfil
    if [ -z "$id" ] || [ "$id" = "None" ]; then
        id=$(aws ec2 describe-instances \
            --filters "Name=instance-state-name,Values=running" \
            --query 'Reservations[].Instances[?Tags[?contains(Value, `alwaysprint`) || contains(Value, `AlwaysPrint`)]].InstanceId' \
            --output text \
            --profile "$AWS_PROFILE" 2>/dev/null | head -1)
    fi
    
    echo "$id"
}

INSTANCE_ID=$(detect_instance_id)
if [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" = "None" ]; then
    echo -e "${YELLOW}⚠ No se pudo detectar Instance ID automáticamente.${NC}"
    echo -e "${YELLOW}  Puedes pasarlo como argumento: ./check-status.sh i-0xxxxxxxxxx${NC}"
    # Permitir pasar como argumento
    if [ -n "$1" ]; then
        INSTANCE_ID="$1"
    fi
fi

# Contadores
PASS=0
FAIL=0
WARN=0

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

# =============================================================================
# 1. VERIFICACIÓN DE ENDPOINTS PÚBLICOS
# =============================================================================
print_header "1. ENDPOINTS PÚBLICOS"

# Health check del backend
echo -e "\n  ${BLUE}Backend Health Check:${NC}"
HEALTH=$(curl -s --max-time $TIMEOUT "https://${DOMAIN}/api/v1/health" 2>/dev/null)
if [ $? -eq 0 ] && echo "$HEALTH" | grep -q "healthy"; then
    BUILD_TAG=$(echo "$HEALTH" | grep -o '"build_tag":"[^"]*"' | cut -d'"' -f4)
    check_ok "Backend OK — build: ${BUILD_TAG:-dev}"
else
    check_fail "Backend NO responde o no está healthy"
fi

# Version endpoint
VERSION=$(curl -s --max-time $TIMEOUT "https://${DOMAIN}/api/v1/version" 2>/dev/null)
if [ $? -eq 0 ] && echo "$VERSION" | grep -q "build_tag"; then
    TAG=$(echo "$VERSION" | grep -o '"build_tag":"[^"]*"' | cut -d'"' -f4)
    check_ok "Version endpoint OK — tag: ${TAG:-dev}"
else
    check_warn "Version endpoint no disponible"
fi

# Swagger UI
echo -e "\n  ${BLUE}Swagger UI:${NC}"
SWAGGER_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time $TIMEOUT "https://${DOMAIN}/docs" 2>/dev/null)
if [ "$SWAGGER_STATUS" = "200" ]; then
    check_ok "Swagger UI accesible (/docs)"
else
    check_warn "Swagger UI retorna HTTP $SWAGGER_STATUS"
fi

# Frontend
echo -e "\n  ${BLUE}Frontend:${NC}"
FRONTEND_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time $TIMEOUT "https://${DOMAIN}/" 2>/dev/null)
if [ "$FRONTEND_STATUS" = "200" ] || [ "$FRONTEND_STATUS" = "302" ] || [ "$FRONTEND_STATUS" = "307" ]; then
    check_ok "Frontend accesible (HTTP $FRONTEND_STATUS)"
else
    check_fail "Frontend retorna HTTP $FRONTEND_STATUS"
fi

# SSL Certificate
echo -e "\n  ${BLUE}Certificado SSL:${NC}"
SSL_EXPIRY=$(echo | openssl s_client -servername "$DOMAIN" -connect "${DOMAIN}:443" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
if [ -n "$SSL_EXPIRY" ]; then
    EXPIRY_EPOCH=$(date -j -f "%b %d %H:%M:%S %Y %Z" "$SSL_EXPIRY" +%s 2>/dev/null || date -d "$SSL_EXPIRY" +%s 2>/dev/null)
    NOW_EPOCH=$(date +%s)
    DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))
    if [ "$DAYS_LEFT" -gt 14 ]; then
        check_ok "SSL válido — expira en ${DAYS_LEFT} días ($SSL_EXPIRY)"
    elif [ "$DAYS_LEFT" -gt 0 ]; then
        check_warn "SSL expira pronto — ${DAYS_LEFT} días restantes"
    else
        check_fail "SSL EXPIRADO"
    fi
else
    check_warn "No se pudo verificar certificado SSL"
fi

# =============================================================================
# 2. VERIFICACIÓN DE CONECTIVIDAD
# =============================================================================
print_header "2. CONECTIVIDAD"

# DNS
echo -e "\n  ${BLUE}Resolución DNS:${NC}"
IP_RESOLVED=$(dig +short "$DOMAIN" 2>/dev/null | head -1)
if [ -n "$IP_RESOLVED" ]; then
    check_ok "$DOMAIN → $IP_RESOLVED"
    if [ "$IP_RESOLVED" = "34.213.90.95" ]; then
        check_ok "IP coincide con Elastic IP esperada (34.213.90.95)"
    else
        check_warn "IP no coincide con Elastic IP esperada (34.213.90.95), resolvió: $IP_RESOLVED"
    fi
else
    check_fail "No se pudo resolver DNS para $DOMAIN"
fi

# Puerto 443
echo -e "\n  ${BLUE}Puertos:${NC}"
if nc -z -w 5 "$DOMAIN" 443 2>/dev/null; then
    check_ok "Puerto 443 (HTTPS) abierto"
else
    check_fail "Puerto 443 (HTTPS) cerrado o no accesible"
fi

# =============================================================================
# 3. VERIFICACIÓN AWS (requiere AWS CLI configurado)
# =============================================================================
print_header "3. INFRAESTRUCTURA AWS"

# Verificar si AWS CLI está disponible
if ! command -v aws &> /dev/null; then
    check_warn "AWS CLI no instalado — saltando verificaciones de infraestructura"
else
    if [ -n "$INSTANCE_ID" ] && [ "$INSTANCE_ID" != "None" ]; then
        echo -e "\n  ${BLUE}Instance ID detectado:${NC} $INSTANCE_ID"
    else
        check_warn "No se detectó Instance ID — saltando verificaciones EC2/SSM"
    fi

    # Estado del EC2
    echo -e "\n  ${BLUE}EC2 Instance:${NC}"
    if [ -n "$INSTANCE_ID" ] && [ "$INSTANCE_ID" != "None" ]; then
        EC2_STATE=$(aws ec2 describe-instances \
            --instance-ids "$INSTANCE_ID" \
            --query 'Reservations[0].Instances[0].State.Name' \
            --output text \
            --profile "$AWS_PROFILE" 2>/dev/null)
        
        if [ "$EC2_STATE" = "running" ]; then
            check_ok "EC2 $INSTANCE_ID está running"
        elif [ -n "$EC2_STATE" ]; then
            check_fail "EC2 $INSTANCE_ID está en estado: $EC2_STATE"
        else
            check_warn "No se pudo consultar estado del EC2 (verificar perfil AWS)"
        fi

        # Status checks del EC2
        EC2_STATUS=$(aws ec2 describe-instance-status \
            --instance-ids "$INSTANCE_ID" \
            --query 'InstanceStatuses[0].[InstanceStatus.Status, SystemStatus.Status]' \
            --output text \
            --profile "$AWS_PROFILE" 2>/dev/null)
        
        if echo "$EC2_STATUS" | grep -q "ok.*ok"; then
            check_ok "EC2 status checks: OK"
        elif [ -n "$EC2_STATUS" ]; then
            check_warn "EC2 status checks: $EC2_STATUS"
        fi
    fi

    # Estado del RDS
    echo -e "\n  ${BLUE}RDS PostgreSQL:${NC}"
    RDS_STATUS=$(aws rds describe-db-instances \
        --query 'DBInstances[?contains(DBInstanceIdentifier, `alwaysprint`)].DBInstanceStatus' \
        --output text \
        --profile "$AWS_PROFILE" 2>/dev/null)
    
    if [ "$RDS_STATUS" = "available" ]; then
        check_ok "RDS PostgreSQL está available"
    elif [ -n "$RDS_STATUS" ]; then
        check_warn "RDS PostgreSQL estado: $RDS_STATUS"
    else
        check_warn "No se pudo consultar estado del RDS"
    fi
fi

# =============================================================================
# 4. VERIFICACIÓN DE CONTAINERS (vía SSM)
# =============================================================================
print_header "4. CONTAINERS DOCKER (vía SSM)"

if ! command -v aws &> /dev/null; then
    check_warn "AWS CLI no instalado — saltando verificación de containers"
elif [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" = "None" ]; then
    check_warn "Instance ID no disponible — saltando verificación de containers"
else
    echo -e "  ${YELLOW}Ejecutando comando remoto vía SSM...${NC}"
    
    SSM_OUTPUT=$(aws ssm send-command \
        --instance-ids "$INSTANCE_ID" \
        --document-name "AWS-RunShellScript" \
        --parameters 'commands=["docker compose -f /opt/alwaysprint/docker-compose.yml ps --format json 2>/dev/null || docker compose -f /opt/alwaysprint/docker-compose.yml ps"]' \
        --output json \
        --profile "$AWS_PROFILE" 2>/dev/null)
    
    if [ $? -eq 0 ]; then
        COMMAND_ID=$(echo "$SSM_OUTPUT" | grep -o '"CommandId": "[^"]*"' | cut -d'"' -f4)
        
        if [ -n "$COMMAND_ID" ]; then
            # Esperar a que el comando termine
            sleep 5
            
            RESULT=$(aws ssm get-command-invocation \
                --command-id "$COMMAND_ID" \
                --instance-id "$INSTANCE_ID" \
                --query 'StandardOutputContent' \
                --output text \
                --profile "$AWS_PROFILE" 2>/dev/null)
            
            if [ -n "$RESULT" ] && [ "$RESULT" != "None" ]; then
                echo ""
                echo "$RESULT" | while IFS= read -r line; do
                    if echo "$line" | grep -qi "running\|up\|healthy"; then
                        echo -e "  ${GREEN}│${NC} $line"
                    elif echo "$line" | grep -qi "exit\|dead\|unhealthy"; then
                        echo -e "  ${RED}│${NC} $line"
                    else
                        echo -e "  ${NC}│ $line"
                    fi
                done
                echo ""
                check_ok "Comando SSM ejecutado correctamente"
            else
                check_warn "SSM: esperando resultado (puede tardar unos segundos más)"
                echo -e "  ${YELLOW}  Ejecutar manualmente:${NC}"
                echo -e "  aws ssm get-command-invocation --command-id $COMMAND_ID --instance-id $INSTANCE_ID --profile $AWS_PROFILE"
            fi
        fi
    else
        check_warn "No se pudo ejecutar comando SSM (verificar permisos)"
    fi
fi

# =============================================================================
# 5. VERIFICACIÓN DE LOGS RECIENTES (vía SSM)
# =============================================================================
print_header "5. LOGS RECIENTES (últimos errores)"

if command -v aws &> /dev/null && [ -n "$INSTANCE_ID" ] && [ "$INSTANCE_ID" != "None" ]; then
    SSM_LOGS=$(aws ssm send-command \
        --instance-ids "$INSTANCE_ID" \
        --document-name "AWS-RunShellScript" \
        --parameters 'commands=["echo \"=== BACKEND (últimos errores) ===\"; docker logs alwaysprint-backend-1 --tail 20 2>&1 | grep -i \"error\\|traceback\\|critical\" | tail -5; echo \"\"; echo \"=== FRONTEND (últimos errores) ===\"; docker logs alwaysprint-frontend-1 --tail 20 2>&1 | grep -i \"error\\|warn\" | tail -5; echo \"\"; echo \"=== NGINX ===\"; tail -5 /var/log/nginx/error.log 2>/dev/null || echo \"Sin errores recientes\""]' \
        --output json \
        --profile "$AWS_PROFILE" 2>/dev/null)
    
    if [ $? -eq 0 ]; then
        LOG_CMD_ID=$(echo "$SSM_LOGS" | grep -o '"CommandId": "[^"]*"' | cut -d'"' -f4)
        sleep 5
        
        LOG_RESULT=$(aws ssm get-command-invocation \
            --command-id "$LOG_CMD_ID" \
            --instance-id "$INSTANCE_ID" \
            --query 'StandardOutputContent' \
            --output text \
            --profile "$AWS_PROFILE" 2>/dev/null)
        
        if [ -n "$LOG_RESULT" ] && [ "$LOG_RESULT" != "None" ]; then
            echo ""
            echo "$LOG_RESULT" | while IFS= read -r line; do
                if echo "$line" | grep -qi "error\|traceback\|critical"; then
                    echo -e "  ${RED}│${NC} $line"
                elif echo "$line" | grep -qi "==="; then
                    echo -e "  ${BLUE}│${NC} $line"
                else
                    echo -e "  ${NC}│ $line"
                fi
            done
        else
            check_warn "Logs: resultado pendiente. Comando ID: $LOG_CMD_ID"
        fi
    fi
else
    check_warn "AWS CLI no disponible o Instance ID no detectado — no se pueden consultar logs remotos"
fi

# =============================================================================
# RESUMEN
# =============================================================================
print_header "RESUMEN"

echo ""
echo -e "  ${GREEN}✓ Pasaron:${NC}  $PASS"
echo -e "  ${RED}✗ Fallaron:${NC} $FAIL"
echo -e "  ${YELLOW}⚠ Warnings:${NC} $WARN"
echo ""

if [ $FAIL -eq 0 ]; then
    echo -e "  ${GREEN}══════════════════════════════════════════${NC}"
    echo -e "  ${GREEN}  ✓ SISTEMA OPERATIVO${NC}"
    echo -e "  ${GREEN}══════════════════════════════════════════${NC}"
elif [ $FAIL -le 2 ]; then
    echo -e "  ${YELLOW}══════════════════════════════════════════${NC}"
    echo -e "  ${YELLOW}  ⚠ SISTEMA CON PROBLEMAS MENORES${NC}"
    echo -e "  ${YELLOW}══════════════════════════════════════════${NC}"
else
    echo -e "  ${RED}══════════════════════════════════════════${NC}"
    echo -e "  ${RED}  ✗ SISTEMA CON PROBLEMAS${NC}"
    echo -e "  ${RED}══════════════════════════════════════════${NC}"
fi

echo ""
echo -e "  ${BLUE}Dashboard:${NC}  https://${DOMAIN}"
echo -e "  ${BLUE}API Docs:${NC}   https://${DOMAIN}/docs"
echo -e "  ${BLUE}Health:${NC}     https://${DOMAIN}/api/v1/health"
echo ""
