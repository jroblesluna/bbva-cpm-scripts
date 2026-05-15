#!/bin/bash
# ============================================================================
# AlwaysPrint Cloud — Script de testing de comunicación Cliente ↔ APCM
#
# Simula las operaciones que el Client Tray realiza contra el backend.
# Requiere: curl, websocat (brew install websocat coreutils)
#
# Uso:
#   ./test-client.sh              # Producción (https://alwaysprint.apps.iol.pe)
#   ./test-client.sh local        # Desarrollo local (http://localhost:8000)
#   APCM_URL=http://x ./test-client.sh  # URL custom
# ============================================================================

set -euo pipefail

# === CONFIGURACIÓN ===

# Detectar flags
VERBOSE=false
ARGS=()
for arg in "$@"; do
    case "$arg" in
        --verbose|-v) VERBOSE=true ;;
        *) ARGS+=("$arg") ;;
    esac
done

# Detectar modo: "local" como primer argumento activa localhost
if [ "${ARGS[0]:-}" = "local" ] || [ "${ARGS[0]:-}" = "dev" ]; then
    BASE_URL="http://localhost:8000"
    API_URL="$BASE_URL/api/v1"
    WS_URL="ws://localhost:8000/ws/workstation"
    MODE="LOCAL"
else
    BASE_URL="${APCM_URL:-https://alwaysprint.apps.iol.pe}"
    API_URL="$BASE_URL/api/v1"
    # Derivar URL WebSocket según protocolo
    if [[ "$BASE_URL" == https://* ]]; then
        WS_URL="${BASE_URL/https:\/\//wss://}/ws/workstation"
    else
        WS_URL="${BASE_URL/http:\/\//ws://}/ws/workstation"
    fi
    MODE="PROD"
fi

# Datos simulados de workstation
IP_PRIVATE="${TEST_IP:-192.168.1.100}"
HOSTNAME="${TEST_HOSTNAME:-W10TEST01}"
OS_SERIAL="${TEST_SERIAL:-00331-10000-00001-AA123}"
CURRENT_USER="${TEST_USER:-operador01}"
LOCALE="es"
CLIENT_VERSION="1.26.514.1400"

# Colores
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; }
info() { echo -e "${CYAN}→${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
verbose() { if [ "$VERBOSE" = true ]; then echo -e "${YELLOW}  ▸${NC} $1"; fi; }

# ============================================================================
# FUNCIONES DE TEST
# ============================================================================

test_health() {
    echo ""
    info "Testing: GET $API_URL/health"
    verbose "Protocolo: HTTP GET"
    verbose "URL: $API_URL/health"
    RESPONSE=$(curl -s -w "\n%{http_code}" "$API_URL/health" 2>&1)
    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    BODY=$(echo "$RESPONSE" | sed '$d')
    verbose "Response HTTP $HTTP_CODE: $BODY"

    if [ "$HTTP_CODE" = "200" ]; then
        ok "Health check OK ($HTTP_CODE)"
        echo "   $BODY"
    else
        fail "Health check FAILED ($HTTP_CODE)"
        echo "   $BODY"
    fi
}

test_version() {
    echo ""
    info "Testing: GET $API_URL/version"
    verbose "Protocolo: HTTP GET"
    verbose "URL: $API_URL/version"
    RESPONSE=$(curl -s -w "\n%{http_code}" "$API_URL/version" 2>&1)
    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    BODY=$(echo "$RESPONSE" | sed '$d')
    verbose "Response HTTP $HTTP_CODE: $BODY"

    if [ "$HTTP_CODE" = "200" ]; then
        ok "Version OK ($HTTP_CODE)"
        echo "   $BODY"
    else
        fail "Version FAILED ($HTTP_CODE)"
        echo "   $BODY"
    fi
}

test_websocket_register() {
    echo ""
    info "Testing: WebSocket registro de workstation"
    info "URL: $WS_URL"
    info "Datos: ip=$IP_PRIVATE, hostname=$HOSTNAME, user=$CURRENT_USER"

    if ! command -v websocat &> /dev/null; then
        warn "websocat no instalado. Instalar con: brew install websocat"
        warn "Intentando con curl (limitado)..."
        echo ""
        return
    fi

    REGISTER_MSG=$(cat <<EOF
{"type":"register","ip_private":"$IP_PRIVATE","hostname":"$HOSTNAME","os_serial":"$OS_SERIAL","current_user":"$CURRENT_USER","locale":"$LOCALE","client_version":"$CLIENT_VERSION","workstation_id":null}
EOF
)

    info "Enviando mensaje de registro..."
    echo "$REGISTER_MSG"

    # Conectar, enviar registro, leer respuesta (timeout 5s)
    verbose "Protocolo: WebSocket"
    verbose "URL: $WS_URL"
    verbose "Request: $REGISTER_MSG"
    RESPONSE=$(echo "$REGISTER_MSG" | gtimeout 5 websocat -n1 "$WS_URL" 2>&1) || true

    if [ -z "$RESPONSE" ]; then
        verbose "Sin respuesta con -n1, reintentando..."
        RESPONSE=$(echo "$REGISTER_MSG" | gtimeout 5 websocat "$WS_URL" 2>&1) || true
    fi

    verbose "Response: ${RESPONSE:-<vacío/conexión cerrada>}"

    if [ -n "$RESPONSE" ]; then
        ok "Respuesta recibida:"
        echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "   $RESPONSE"
    else
        # Verificar si la conexión fue rechazada (1008 = IP no autorizada)
        warn "Conexión cerrada por el servidor (probable código 1008 — IP no autorizada)"
        info "Esto es NORMAL si tu IP pública no está autorizada en APCM."
        info "Verifica en Dashboard → Pending IPs si tu IP aparece como pendiente."
    fi
}

test_websocket_ping_pong() {
    echo ""
    info "Testing: WebSocket ping/pong (mantener conexión)"

    if ! command -v websocat &> /dev/null; then
        warn "websocat no instalado."
        return
    fi

    REGISTER_MSG='{"type":"register","ip_private":"'"$IP_PRIVATE"'","hostname":"'"$HOSTNAME"'","os_serial":"'"$OS_SERIAL"'","current_user":"'"$CURRENT_USER"'","locale":"'"$LOCALE"'","client_version":"'"$CLIENT_VERSION"'","workstation_id":null}'

    info "Conectando y esperando ping del servidor (max 35s)..."
    verbose "Protocolo: WebSocket"
    verbose "URL: $WS_URL"
    verbose "Request: $REGISTER_MSG"
    info "WebSocket abierto. El servidor debe enviar un ping dentro de 30s..."

    # Mantener conexión abierta 33s para recibir al menos un ping (cada 30s)
    RESPONSE=$({ echo "$REGISTER_MSG"; sleep 33; } | gtimeout 35 websocat "$WS_URL" 2>&1) || true
    
    verbose "Response: ${RESPONSE:-<vacío/conexión cerrada>}"

    if echo "$RESPONSE" | grep -q "ping"; then
        ok "Ping recibido del servidor"
        echo "$RESPONSE" | while read -r line; do
            echo "$line" | python3 -m json.tool 2>/dev/null || echo "   $line"
        done
    elif [ -z "$RESPONSE" ]; then
        warn "Conexión cerrada por el servidor (probable código 1008 — IP no autorizada)"
        info "Requiere IP autorizada para recibir pings."
    else
        ok "Mensajes recibidos:"
        echo "$RESPONSE" | while read -r line; do
            echo "$line" | python3 -m json.tool 2>/dev/null || echo "   $line"
        done
    fi
}

test_websocket_telemetry() {
    echo ""
    info "Testing: WebSocket envío de telemetría"

    if ! command -v websocat &> /dev/null; then
        warn "websocat no instalado."
        return
    fi

    # Primero registrar, luego enviar telemetría
    MESSAGES=$(cat <<EOF
{"type":"register","ip_private":"$IP_PRIVATE","hostname":"$HOSTNAME","os_serial":"$OS_SERIAL","current_user":"$CURRENT_USER","locale":"$LOCALE","client_version":"$CLIENT_VERSION","workstation_id":null}
{"type":"telemetry","queue_status":"ok","contingency_active":false,"jobs_identified":3,"avg_release_time_ms":1200,"disconnection_log":[]}
EOF
)

    info "Enviando registro + telemetría..."
    verbose "Protocolo: WebSocket"
    verbose "URL: $WS_URL"
    verbose "Request[1]: {\"type\":\"register\",...}"
    verbose "Request[2]: {\"type\":\"telemetry\",\"queue_status\":\"ok\",...}"
    # sleep mantiene la conexión abierta para recibir respuestas
    RESPONSE=$({ echo "$MESSAGES"; sleep 3; } | gtimeout 5 websocat "$WS_URL" 2>&1 | head -3) || true
    verbose "Response: ${RESPONSE:-<vacío/conexión cerrada>}"

    if [ -n "$RESPONSE" ]; then
        ok "Respuesta:"
        echo "$RESPONSE" | while read -r line; do
            echo "$line" | python3 -m json.tool 2>/dev/null || echo "   $line"
        done
    else
        warn "Conexión cerrada por el servidor (probable código 1008 — IP no autorizada)"
        info "Requiere IP autorizada para enviar telemetría."
    fi
}

test_websocket_connectivity() {
    echo ""
    info "Testing: WebSocket envío de resultado de conectividad"

    if ! command -v websocat &> /dev/null; then
        warn "websocat no instalado."
        return
    fi

    MESSAGES=$(cat <<EOF
{"type":"register","ip_private":"$IP_PRIVATE","hostname":"$HOSTNAME","os_serial":"$OS_SERIAL","current_user":"$CURRENT_USER","locale":"$LOCALE","client_version":"$CLIENT_VERSION","workstation_id":null}
{"type":"connectivity_result","check_id":"chk-001","check_type":"http","target":"https://google.com","success":true,"latency_ms":120,"error":null}
EOF
)

    info "Enviando registro + resultado de conectividad..."
    verbose "Protocolo: WebSocket"
    verbose "URL: $WS_URL"
    verbose "Request[1]: {\"type\":\"register\",...}"
    verbose "Request[2]: {\"type\":\"connectivity_result\",\"check_id\":\"chk-001\",...}"
    RESPONSE=$({ echo "$MESSAGES"; sleep 3; } | gtimeout 5 websocat "$WS_URL" 2>&1 | head -3) || true
    verbose "Response: ${RESPONSE:-<vacío/conexión cerrada>}"

    if [ -n "$RESPONSE" ]; then
        ok "Respuesta:"
        echo "$RESPONSE" | while read -r line; do
            echo "$line" | python3 -m json.tool 2>/dev/null || echo "   $line"
        done
    else
        warn "Conexión cerrada por el servidor (probable código 1008 — IP no autorizada)"
        info "Requiere IP autorizada para enviar conectividad."
    fi
}

test_websocket_status_update() {
    echo ""
    info "Testing: WebSocket actualización de estado (contingencia)"

    if ! command -v websocat &> /dev/null; then
        warn "websocat no instalado."
        return
    fi

    MESSAGES=$(cat <<EOF
{"type":"register","ip_private":"$IP_PRIVATE","hostname":"$HOSTNAME","os_serial":"$OS_SERIAL","current_user":"$CURRENT_USER","locale":"$LOCALE","client_version":"$CLIENT_VERSION","workstation_id":null}
{"type":"status_update","contingency_active":true,"current_user":"$CURRENT_USER"}
EOF
)

    info "Enviando registro + status_update (contingencia=true)..."
    verbose "Protocolo: WebSocket"
    verbose "URL: $WS_URL"
    verbose "Request[1]: {\"type\":\"register\",...}"
    verbose "Request[2]: {\"type\":\"status_update\",\"contingency_active\":true,...}"
    RESPONSE=$({ echo "$MESSAGES"; sleep 3; } | gtimeout 5 websocat "$WS_URL" 2>&1 | head -3) || true
    verbose "Response: ${RESPONSE:-<vacío/conexión cerrada>}"

    if [ -n "$RESPONSE" ]; then
        ok "Respuesta:"
        echo "$RESPONSE" | while read -r line; do
            echo "$line" | python3 -m json.tool 2>/dev/null || echo "   $line"
        done
    else
        warn "Conexión cerrada por el servidor (probable código 1008 — IP no autorizada)"
        info "Requiere IP autorizada para enviar status_update."
    fi
}

test_api_setup_status() {
    echo ""
    info "Testing: GET $API_URL/setup/status (verificar si necesita setup)"
    verbose "Protocolo: HTTP GET"
    verbose "URL: $API_URL/setup/status"
    RESPONSE=$(curl -s -w "\n%{http_code}" "$API_URL/setup/status" 2>&1)
    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    BODY=$(echo "$RESPONSE" | sed '$d')
    verbose "Response HTTP $HTTP_CODE: $BODY"

    if [ "$HTTP_CODE" = "200" ]; then
        ok "Setup status OK ($HTTP_CODE)"
        echo "   $BODY"
    else
        fail "Setup status FAILED ($HTTP_CODE)"
        echo "   $BODY"
    fi
}

# ============================================================================
# MENÚ PRINCIPAL
# ============================================================================

show_menu() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}   AlwaysPrint Cloud — Test de Comunicación Cliente          ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}   Target: $BASE_URL ($MODE)   ${CYAN}║${NC}"
    if [ "$VERBOSE" = true ]; then
    echo -e "${CYAN}║${NC}   Verbose: ON                                               ${CYAN}║${NC}"
    fi
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "  === API REST ==="
    echo "  1) Health check          (/api/v1/health)"
    echo "  2) Version               (/api/v1/version)"
    echo "  3) Setup status          (/api/v1/setup/status)"
    echo ""
    echo "  === WebSocket ==="
    echo "  4) Registro de workstation   (register)"
    echo "  5) Ping/Pong                 (esperar ping del servidor)"
    echo "  6) Enviar telemetría         (telemetry)"
    echo "  7) Enviar conectividad       (connectivity_result)"
    echo "  8) Actualizar estado         (status_update / contingencia)"
    echo ""
    echo "  === Batch ==="
    echo "  9) Ejecutar TODOS los tests"
    echo ""
    echo "  0) Salir"
    echo ""
}

run_all() {
    test_health
    test_version
    test_api_setup_status
    test_websocket_register
    test_websocket_telemetry
    test_websocket_connectivity
    test_websocket_status_update
}

# ============================================================================
# MAIN LOOP
# ============================================================================

while true; do
    clear
    show_menu
    read -rp "  Selecciona opción: " choice

    clear
    case $choice in
        1) test_health ;;
        2) test_version ;;
        3) test_api_setup_status ;;
        4) test_websocket_register ;;
        5) test_websocket_ping_pong ;;
        6) test_websocket_telemetry ;;
        7) test_websocket_connectivity ;;
        8) test_websocket_status_update ;;
        9) run_all ;;
        0) echo ""; info "Saliendo."; exit 0 ;;
        *) warn "Opción inválida" ;;
    esac

    echo ""
    read -rp "  Presiona Enter para continuar..."
done
