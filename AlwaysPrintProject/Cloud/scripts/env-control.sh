#!/bin/bash
# =============================================================================
# AlwaysPrint Cloud Manager - Control de Entorno (Stop/Start)
# Ejecutar desde tu máquina local para detener o iniciar un entorno completo.
#
# Uso:
#   ./env-control.sh stop <dev|prod>   — Detener entorno (EC2 + RDS)
#   ./env-control.sh start <dev|prod>  — Iniciar entorno (EC2 + RDS)
#   ./env-control.sh status <dev|prod> — Ver estado actual
#
# Al detener:
#   - EC2: se detiene (containers se apagan automáticamente)
#   - RDS: se detiene (se auto-inicia después de 7 días — limitación AWS)
#   - Costo residual: ~$5/mes (EBS + RDS storage + IP elástica)
#
# Al iniciar:
#   - RDS: se inicia (tarda ~3-5 min en estar available)
#   - EC2: se inicia (containers se levantan via docker compose on boot)
#   - Tiempo total: ~5-7 min hasta que todo esté operativo
#
# SEGURIDAD: Para PROD se pide confirmación explícita.
# =============================================================================

set -o pipefail

# =============================================================================
# COLORES Y UTILIDADES
# =============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

print_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
}

print_ok() {
    echo -e "  ${GREEN}✓${NC} $1"
}

print_warn() {
    echo -e "  ${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "  ${RED}✗${NC} $1"
}

print_info() {
    echo -e "  ${CYAN}→${NC} $1"
}

# =============================================================================
# VALIDACIÓN DE PARÁMETROS
# =============================================================================
ACTION="${1:-}"
ENV="${2:-}"

if [ -z "$ACTION" ] || [ -z "$ENV" ]; then
    echo "Uso: ./env-control.sh <stop|start|status> <dev|prod>"
    echo ""
    echo "  stop   — Detener EC2 + RDS (máximo ahorro)"
    echo "  start  — Iniciar RDS + EC2 (restaurar operación)"
    echo "  status — Ver estado actual de EC2 y RDS"
    echo ""
    echo "Ejemplos:"
    echo "  ./env-control.sh stop dev     # Apagar entorno DEV"
    echo "  ./env-control.sh start dev    # Encender entorno DEV"
    echo "  ./env-control.sh status prod  # Ver estado de PROD"
    exit 1
fi

if [ "$ACTION" != "stop" ] && [ "$ACTION" != "start" ] && [ "$ACTION" != "status" ]; then
    echo -e "${RED}Error: acción '$ACTION' no válida. Use: stop, start, status${NC}"
    exit 1
fi

if [ "$ENV" != "dev" ] && [ "$ENV" != "prod" ]; then
    echo -e "${RED}Error: entorno '$ENV' no válido. Use: dev, prod${NC}"
    exit 1
fi

# =============================================================================
# CONFIGURACIÓN POR ENTORNO
# =============================================================================
if [ "$ENV" = "dev" ]; then
    AWS_PROFILE="AlwaysPrint-dev-747301449278"
    EC2_TAG="alwaysprint-dev-ec2"
    RDS_IDENTIFIER="alwaysprint-dev-postgres"
    ENV_LABEL="DESARROLLO"
else
    AWS_PROFILE="AlwaysPrint-prod-425642439683"
    EC2_TAG="alwaysprint-prod-ec2"
    RDS_IDENTIFIER="alwaysprint-prod-postgres"
    ENV_LABEL="PRODUCCIÓN"
fi

export AWS_PROFILE
AWS_REGION="us-west-2"

# =============================================================================
# FUNCIONES DE DESCUBRIMIENTO
# =============================================================================

get_ec2_instance_id() {
    aws ec2 describe-instances \
        --filters "Name=tag:Name,Values=$EC2_TAG" \
        --query "Reservations[0].Instances[0].InstanceId" \
        --output text \
        --region "$AWS_REGION" 2>/dev/null
}

get_ec2_state() {
    local instance_id="$1"
    aws ec2 describe-instances \
        --instance-ids "$instance_id" \
        --query "Reservations[0].Instances[0].State.Name" \
        --output text \
        --region "$AWS_REGION" 2>/dev/null
}

get_rds_status() {
    aws rds describe-db-instances \
        --db-instance-identifier "$RDS_IDENTIFIER" \
        --query "DBInstances[0].DBInstanceStatus" \
        --output text \
        --region "$AWS_REGION" 2>/dev/null
}

# =============================================================================
# COMANDO: STATUS
# =============================================================================
do_status() {
    print_header "Estado del Entorno: $ENV_LABEL [$ENV]"

    # EC2
    local instance_id=$(get_ec2_instance_id)
    if [ -z "$instance_id" ] || [ "$instance_id" = "None" ]; then
        print_error "EC2: no se encontró instancia con tag '$EC2_TAG'"
    else
        local ec2_state=$(get_ec2_state "$instance_id")
        case "$ec2_state" in
            running)  print_ok "EC2 ($instance_id): ${GREEN}running${NC}" ;;
            stopped)  print_warn "EC2 ($instance_id): ${YELLOW}stopped${NC}" ;;
            stopping) print_warn "EC2 ($instance_id): ${YELLOW}stopping...${NC}" ;;
            pending)  print_info "EC2 ($instance_id): ${CYAN}starting...${NC}" ;;
            *)        print_error "EC2 ($instance_id): $ec2_state" ;;
        esac
    fi

    # RDS
    local rds_status=$(get_rds_status)
    case "$rds_status" in
        available) print_ok "RDS ($RDS_IDENTIFIER): ${GREEN}available${NC}" ;;
        stopped)   print_warn "RDS ($RDS_IDENTIFIER): ${YELLOW}stopped${NC}" ;;
        stopping)  print_warn "RDS ($RDS_IDENTIFIER): ${YELLOW}stopping...${NC}" ;;
        starting)  print_info "RDS ($RDS_IDENTIFIER): ${CYAN}starting...${NC}" ;;
        *)         print_error "RDS ($RDS_IDENTIFIER): $rds_status" ;;
    esac

    # Resumen de costos
    echo ""
    if [ "$ec2_state" = "stopped" ] && [ "$rds_status" = "stopped" ]; then
        print_info "Costo estimado: ~\$5/mes (solo almacenamiento EBS + RDS storage)"
    elif [ "$ec2_state" = "running" ] && [ "$rds_status" = "available" ]; then
        print_info "Costo estimado: ~\$50-80/mes (EC2 + RDS + transferencia)"
    else
        print_info "Estado mixto — algunos recursos siguen consumiendo"
    fi
    echo ""
}

# =============================================================================
# COMANDO: STOP
# =============================================================================
do_stop() {
    print_header "Deteniendo Entorno: $ENV_LABEL [$ENV]"

    # Confirmación para PROD
    if [ "$ENV" = "prod" ]; then
        echo ""
        echo -e "  ${RED}⚠ ADVERTENCIA: Vas a detener PRODUCCIÓN${NC}"
        echo -e "  ${RED}  Esto desconectará TODAS las workstations activas.${NC}"
        echo ""
        read -p "  Escribe 'DETENER PROD' para confirmar: " confirm
        if [ "$confirm" != "DETENER PROD" ]; then
            echo -e "  ${YELLOW}Cancelado.${NC}"
            exit 0
        fi
        echo ""
    fi

    # Obtener Instance ID
    local instance_id=$(get_ec2_instance_id)
    if [ -z "$instance_id" ] || [ "$instance_id" = "None" ]; then
        print_error "No se encontró instancia EC2 con tag '$EC2_TAG'"
        exit 1
    fi

    # 1. Detener EC2
    local ec2_state=$(get_ec2_state "$instance_id")
    if [ "$ec2_state" = "stopped" ]; then
        print_ok "EC2 ya está detenido ($instance_id)"
    elif [ "$ec2_state" = "running" ]; then
        print_info "Deteniendo EC2 ($instance_id)..."
        aws ec2 stop-instances \
            --instance-ids "$instance_id" \
            --region "$AWS_REGION" > /dev/null 2>&1
        
        # Esperar a que se detenga (max 120s)
        local tries=0
        while [ $tries -lt 24 ]; do
            sleep 5
            ec2_state=$(get_ec2_state "$instance_id")
            if [ "$ec2_state" = "stopped" ]; then
                break
            fi
            tries=$((tries + 1))
            printf "."
        done
        echo ""
        
        if [ "$ec2_state" = "stopped" ]; then
            print_ok "EC2 detenido exitosamente"
        else
            print_warn "EC2 aún en estado '$ec2_state' (puede tardar más)"
        fi
    else
        print_warn "EC2 en estado inesperado: $ec2_state"
    fi

    # 2. Detener RDS
    local rds_status=$(get_rds_status)
    if [ "$rds_status" = "stopped" ]; then
        print_ok "RDS ya está detenido ($RDS_IDENTIFIER)"
    elif [ "$rds_status" = "available" ]; then
        print_info "Deteniendo RDS ($RDS_IDENTIFIER)..."
        aws rds stop-db-instance \
            --db-instance-identifier "$RDS_IDENTIFIER" \
            --region "$AWS_REGION" > /dev/null 2>&1
        
        # Esperar a que se detenga (max 180s)
        local tries=0
        while [ $tries -lt 36 ]; do
            sleep 5
            rds_status=$(get_rds_status)
            if [ "$rds_status" = "stopped" ]; then
                break
            fi
            tries=$((tries + 1))
            printf "."
        done
        echo ""
        
        if [ "$rds_status" = "stopped" ]; then
            print_ok "RDS detenido exitosamente"
        else
            print_warn "RDS aún en estado '$rds_status' (puede tardar hasta 5 min)"
        fi
    else
        print_warn "RDS en estado inesperado: $rds_status"
    fi

    # Resumen
    echo ""
    print_header "Resumen"
    print_ok "Entorno $ENV_LABEL detenido"
    print_info "Costo residual: ~\$5/mes (EBS + RDS storage)"
    print_info "Para reiniciar: ./env-control.sh start $ENV"
    echo ""
    
    if [ "$rds_status" != "stopped" ]; then
        print_warn "NOTA: RDS puede tardar 2-5 min adicionales en detenerse completamente."
        print_warn "      AWS auto-reinicia RDS después de 7 días si sigue detenido."
    fi
    echo ""
}

# =============================================================================
# COMANDO: START
# =============================================================================
do_start() {
    print_header "Iniciando Entorno: $ENV_LABEL [$ENV]"

    # Obtener Instance ID
    local instance_id=$(get_ec2_instance_id)
    if [ -z "$instance_id" ] || [ "$instance_id" = "None" ]; then
        print_error "No se encontró instancia EC2 con tag '$EC2_TAG'"
        exit 1
    fi

    # 1. Iniciar RDS primero (tarda más)
    local rds_status=$(get_rds_status)
    if [ "$rds_status" = "available" ]; then
        print_ok "RDS ya está disponible ($RDS_IDENTIFIER)"
    elif [ "$rds_status" = "stopped" ]; then
        print_info "Iniciando RDS ($RDS_IDENTIFIER)... (esto tarda 3-5 min)"
        aws rds start-db-instance \
            --db-instance-identifier "$RDS_IDENTIFIER" \
            --region "$AWS_REGION" > /dev/null 2>&1
        
        # Esperar a que esté available (max 360s = 6 min)
        local tries=0
        while [ $tries -lt 72 ]; do
            sleep 5
            rds_status=$(get_rds_status)
            if [ "$rds_status" = "available" ]; then
                break
            fi
            tries=$((tries + 1))
            if [ $((tries % 6)) -eq 0 ]; then
                printf "."
            fi
        done
        echo ""
        
        if [ "$rds_status" = "available" ]; then
            print_ok "RDS disponible"
        else
            print_warn "RDS aún en estado '$rds_status' — continuando con EC2..."
        fi
    else
        print_info "RDS en estado '$rds_status' — esperando..."
    fi

    # 2. Iniciar EC2
    local ec2_state=$(get_ec2_state "$instance_id")
    if [ "$ec2_state" = "running" ]; then
        print_ok "EC2 ya está corriendo ($instance_id)"
    elif [ "$ec2_state" = "stopped" ]; then
        print_info "Iniciando EC2 ($instance_id)..."
        aws ec2 start-instances \
            --instance-ids "$instance_id" \
            --region "$AWS_REGION" > /dev/null 2>&1
        
        # Esperar a que esté running (max 120s)
        local tries=0
        while [ $tries -lt 24 ]; do
            sleep 5
            ec2_state=$(get_ec2_state "$instance_id")
            if [ "$ec2_state" = "running" ]; then
                break
            fi
            tries=$((tries + 1))
            printf "."
        done
        echo ""
        
        if [ "$ec2_state" = "running" ]; then
            print_ok "EC2 corriendo"
        else
            print_warn "EC2 aún en estado '$ec2_state'"
        fi
    else
        print_warn "EC2 en estado inesperado: $ec2_state"
    fi

    # 3. Verificar que containers se levantaron
    if [ "$ec2_state" = "running" ]; then
        print_info "Esperando 30s a que los containers se inicien..."
        sleep 30
        
        # Verificar health
        local health_url=""
        if [ "$ENV" = "dev" ]; then
            health_url="https://alwaysprint.dev.iol.pe/api/v1/health"
        else
            health_url="https://alwaysprint.apps.iol.pe/api/v1/health"
        fi
        
        local http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$health_url" 2>/dev/null)
        if [ "$http_code" = "200" ]; then
            print_ok "Backend respondiendo (HTTP 200)"
        else
            print_warn "Backend aún no responde (HTTP $http_code) — puede tardar 1-2 min más"
            print_info "Verificar con: curl $health_url"
        fi
    fi

    # Resumen
    echo ""
    print_header "Resumen"
    if [ "$ec2_state" = "running" ] && [ "$rds_status" = "available" ]; then
        print_ok "Entorno $ENV_LABEL operativo"
    else
        print_warn "Entorno $ENV_LABEL parcialmente iniciado"
        print_info "Verificar con: ./check-status.sh $ENV"
    fi
    echo ""
}

# =============================================================================
# EJECUCIÓN
# =============================================================================
case "$ACTION" in
    status) do_status ;;
    stop)   do_stop ;;
    start)  do_start ;;
esac
