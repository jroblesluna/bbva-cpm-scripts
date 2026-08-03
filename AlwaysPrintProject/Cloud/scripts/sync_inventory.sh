#!/bin/bash
# ============================================================
# Script de sincronización de inventario AlwaysPrint
# Ejecuta el sync desde laptop vía AWS SSM
#
# Uso:
#   ./sync_inventory.sh [--dry-run] [--env prod|dev]
#
# Ejemplos:
#   ./sync_inventory.sh --dry-run --env prod    # Validar sin cambios en PROD
#   ./sync_inventory.sh --env prod              # Ejecutar sync en PROD
#   ./sync_inventory.sh --env dev               # Ejecutar sync en DEV
# ============================================================

set -e

# === Configuración ===
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
CSV_FILE="$REPO_ROOT/AlwaysPrintProject/Inventario_Canonico.csv"

# === Configuración por entorno (compatible bash 3.x macOS) ===
get_config() {
    case "$ENV" in
        prod)
            PROFILE="AlwaysPrint-prod-425642439683"
            INSTANCE="i-0b42738edf1860c00"
            BUCKET="alwaysprint-prod-docs"
            ;;
        dev)
            PROFILE="AlwaysPrint-dev-040982755196"
            INSTANCE="i-071e328b4dc75a63d"
            BUCKET="alwaysprint-dev-docs"
            ;;
        *)
            echo "❌ Entorno '$ENV' no válido. Usar: prod | dev"
            exit 1
            ;;
    esac
}

REGION="us-west-2"
ORG="BBVA"
CONTAINER="alwaysprint-backend-1"

# === Parsear argumentos ===
DRY_RUN=""
ENV="prod"

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run) DRY_RUN="--dry-run"; shift ;;
        --env) ENV="$2"; shift 2 ;;
        *) echo "Argumento desconocido: $1"; exit 1 ;;
    esac
done

# Cargar configuración del entorno seleccionado
get_config

echo "============================================================"
echo "  Sync Inventario AlwaysPrint"
echo "============================================================"
echo "  Entorno:   $ENV"
echo "  Profile:   $PROFILE"
echo "  Instance:  $INSTANCE"
echo "  CSV:       $CSV_FILE"
echo "  Dry-run:   ${DRY_RUN:-NO}"
echo "============================================================"
echo ""

# === Verificar que el CSV existe ===
if [[ ! -f "$CSV_FILE" ]]; then
    echo "❌ CSV no encontrado: $CSV_FILE"
    exit 1
fi

# === Step 1: Subir CSV a S3 ===
echo "📤 Subiendo CSV a S3..."
aws s3 cp "$CSV_FILE" "s3://$BUCKET/tmp/Inventario_Canonico.csv" \
    --profile "$PROFILE" --region "$REGION" --quiet || true
echo "   ✓ CSV subido a s3://$BUCKET/tmp/Inventario_Canonico.csv"

# Subir también el script Python (para que funcione sin deploy)
PY_SCRIPT="$REPO_ROOT/AlwaysPrintProject/Cloud/backend/app/scripts/sync_inventory.py"
aws s3 cp "$PY_SCRIPT" "s3://$BUCKET/tmp/sync_inventory.py" \
    --profile "$PROFILE" --region "$REGION" --quiet || true
echo "   ✓ Script Python subido a S3"

# === Step 2: Ejecutar via SSM ===
echo ""
echo "🚀 Ejecutando sync en $ENV..."

CMD="aws s3 cp s3://$BUCKET/tmp/Inventario_Canonico.csv /tmp/Inventario_Canonico.csv --region $REGION && aws s3 cp s3://$BUCKET/tmp/sync_inventory.py /tmp/sync_inventory.py --region $REGION && docker cp /tmp/sync_inventory.py $CONTAINER:/tmp/sync_inventory.py && docker cp /tmp/Inventario_Canonico.csv $CONTAINER:/tmp/Inventario_Canonico.csv && docker exec $CONTAINER python /tmp/sync_inventory.py /tmp/Inventario_Canonico.csv --org $ORG $DRY_RUN"

COMMAND_ID=$(aws ssm send-command \
    --instance-ids "$INSTANCE" \
    --document-name "AWS-RunShellScript" \
    --parameters "{\"commands\":[\"$CMD\"]}" \
    --timeout-seconds 300 \
    --profile "$PROFILE" \
    --region "$REGION" \
    --output text \
    --query "Command.CommandId")

echo "   Command ID: $COMMAND_ID"
echo ""

# === Step 3: Esperar resultado ===
echo "⏳ Esperando resultado..."
sleep 5

MAX_WAIT=60
WAITED=0
STATUS=""

while [[ $WAITED -lt $MAX_WAIT ]]; do
    STATUS=$(aws ssm get-command-invocation \
        --command-id "$COMMAND_ID" \
        --instance-id "$INSTANCE" \
        --profile "$PROFILE" \
        --region "$REGION" \
        --output text \
        --query "Status" 2>/dev/null || echo "Pending")
    
    if [[ "$STATUS" == "Success" || "$STATUS" == "Failed" || "$STATUS" == "TimedOut" ]]; then
        break
    fi
    
    sleep 5
    WAITED=$((WAITED + 5))
    echo "   ... esperando ($WAITED s)"
done

echo ""

# === Step 4: Mostrar output ===
if [[ "$STATUS" == "Success" ]]; then
    echo "✅ Ejecución exitosa:"
    echo "------------------------------------------------------------"
    aws ssm get-command-invocation \
        --command-id "$COMMAND_ID" \
        --instance-id "$INSTANCE" \
        --profile "$PROFILE" \
        --region "$REGION" \
        --output text \
        --query "StandardOutputContent"
    echo "------------------------------------------------------------"
elif [[ "$STATUS" == "Failed" ]]; then
    echo "❌ Ejecución fallida:"
    echo "------------------------------------------------------------"
    aws ssm get-command-invocation \
        --command-id "$COMMAND_ID" \
        --instance-id "$INSTANCE" \
        --profile "$PROFILE" \
        --region "$REGION" \
        --output text \
        --query "StandardErrorContent"
    echo "------------------------------------------------------------"
    # También mostrar stdout por si hay info parcial
    aws ssm get-command-invocation \
        --command-id "$COMMAND_ID" \
        --instance-id "$INSTANCE" \
        --profile "$PROFILE" \
        --region "$REGION" \
        --output text \
        --query "StandardOutputContent"
else
    echo "⚠️  Timeout esperando resultado (status=$STATUS)"
    echo "   Verificar manualmente:"
    echo "   aws ssm get-command-invocation --command-id $COMMAND_ID --instance-id $INSTANCE --profile $PROFILE --region $REGION"
fi

# === Step 5: Limpiar CSV de S3 ===
echo ""
echo "🧹 Limpiando archivos temporales de S3..."
aws s3 rm "s3://$BUCKET/tmp/Inventario_Canonico.csv" \
    --profile "$PROFILE" --region "$REGION" --quiet 2>/dev/null || true
aws s3 rm "s3://$BUCKET/tmp/sync_inventory.py" \
    --profile "$PROFILE" --region "$REGION" --quiet 2>/dev/null || true
echo "   ✓ Limpieza completada"
echo ""
echo "============================================================"
echo "  Finalizado"
echo "============================================================"
