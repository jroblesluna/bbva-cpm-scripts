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
            PROFILE="AlwaysPrint-dev-747301449278"
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
aws s3 rm "s3://$BUCKET/tmp/cleanup_empty_vlans.py" \
    --profile "$PROFILE" --region "$REGION" --quiet 2>/dev/null || true
aws s3 rm "s3://$BUCKET/tmp/relocate_unknown_workstations.py" \
    --profile "$PROFILE" --region "$REGION" --quiet 2>/dev/null || true
aws s3 rm "s3://$BUCKET/tmp/cleanup_non118_cidrs.py" \
    --profile "$PROFILE" --region "$REGION" --quiet 2>/dev/null || true
aws s3 rm "s3://$BUCKET/tmp/reassign_from_special_vlans.py" \
    --profile "$PROFILE" --region "$REGION" --quiet 2>/dev/null || true
aws s3 rm "s3://$BUCKET/tmp/rescue_zzz_by_cidr.py" \
    --profile "$PROFILE" --region "$REGION" --quiet 2>/dev/null || true
echo "   ✓ Limpieza completada"

# === Step 6: Reubicar workstations con hostname no-estándar a VLAN desconocida ===
if [[ "$STATUS" == "Success" ]]; then
    echo ""
    echo "📍 Reubicando workstations con hostname no-estándar..."

    # Subir script de reubicación
    RELOCATE_SCRIPT="$REPO_ROOT/AlwaysPrintProject/Cloud/backend/app/scripts/relocate_unknown_workstations.py"
    aws s3 cp "$RELOCATE_SCRIPT" "s3://$BUCKET/tmp/relocate_unknown_workstations.py" \
        --profile "$PROFILE" --region "$REGION" --quiet || true

    STEP6_CMD="aws s3 cp s3://$BUCKET/tmp/relocate_unknown_workstations.py /tmp/relocate_unknown_workstations.py --region $REGION && docker cp /tmp/relocate_unknown_workstations.py $CONTAINER:/tmp/relocate_unknown_workstations.py && docker exec $CONTAINER python /tmp/relocate_unknown_workstations.py --org $ORG $DRY_RUN"

    STEP6_COMMAND_ID=$(aws ssm send-command \
        --instance-ids "$INSTANCE" \
        --document-name "AWS-RunShellScript" \
        --parameters "{\"commands\":[\"$STEP6_CMD\"]}" \
        --timeout-seconds 120 \
        --profile "$PROFILE" \
        --region "$REGION" \
        --output text \
        --query "Command.CommandId")

    echo "   Command ID: $STEP6_COMMAND_ID"
    sleep 5

    STEP6_WAITED=0
    STEP6_STATUS=""
    while [[ $STEP6_WAITED -lt $MAX_WAIT ]]; do
        STEP6_STATUS=$(aws ssm get-command-invocation \
            --command-id "$STEP6_COMMAND_ID" \
            --instance-id "$INSTANCE" \
            --profile "$PROFILE" \
            --region "$REGION" \
            --output text \
            --query "Status" 2>/dev/null || echo "Pending")

        if [[ "$STEP6_STATUS" == "Success" || "$STEP6_STATUS" == "Failed" || "$STEP6_STATUS" == "TimedOut" ]]; then
            break
        fi

        sleep 3
        STEP6_WAITED=$((STEP6_WAITED + 3))
    done

    if [[ "$STEP6_STATUS" == "Success" ]]; then
        aws ssm get-command-invocation \
            --command-id "$STEP6_COMMAND_ID" \
            --instance-id "$INSTANCE" \
            --profile "$PROFILE" \
            --region "$REGION" \
            --output text \
            --query "StandardOutputContent"
    elif [[ "$STEP6_STATUS" == "Failed" ]]; then
        echo "   ⚠️  Error reubicando workstations:"
        aws ssm get-command-invocation \
            --command-id "$STEP6_COMMAND_ID" \
            --instance-id "$INSTANCE" \
            --profile "$PROFILE" \
            --region "$REGION" \
            --output text \
            --query "StandardErrorContent"
    else
        echo "   ⚠️  Timeout esperando resultado de reubicación"
    fi

    # Limpiar script temporal de S3
    aws s3 rm "s3://$BUCKET/tmp/relocate_unknown_workstations.py" \
        --profile "$PROFILE" --region "$REGION" --quiet 2>/dev/null || true
fi

# === Step 7: Mover CIDRs no-118.x de agencias a VLAN ZZZ ===
if [[ "$STATUS" == "Success" ]]; then
    echo ""
    echo "🔀 Moviendo CIDRs no-118.x de agencias a ZZZ..."

    # Subir script
    CIDR_SCRIPT="$REPO_ROOT/AlwaysPrintProject/Cloud/backend/app/scripts/cleanup_non118_cidrs.py"
    aws s3 cp "$CIDR_SCRIPT" "s3://$BUCKET/tmp/cleanup_non118_cidrs.py" \
        --profile "$PROFILE" --region "$REGION" --quiet || true

    STEP7_CMD="aws s3 cp s3://$BUCKET/tmp/cleanup_non118_cidrs.py /tmp/cleanup_non118_cidrs.py --region $REGION && docker cp /tmp/cleanup_non118_cidrs.py $CONTAINER:/tmp/cleanup_non118_cidrs.py && docker exec $CONTAINER python /tmp/cleanup_non118_cidrs.py --org $ORG $DRY_RUN"

    STEP7_COMMAND_ID=$(aws ssm send-command \
        --instance-ids "$INSTANCE" \
        --document-name "AWS-RunShellScript" \
        --parameters "{\"commands\":[\"$STEP7_CMD\"]}" \
        --timeout-seconds 120 \
        --profile "$PROFILE" \
        --region "$REGION" \
        --output text \
        --query "Command.CommandId")

    echo "   Command ID: $STEP7_COMMAND_ID"
    sleep 5

    STEP7_WAITED=0
    STEP7_STATUS=""
    while [[ $STEP7_WAITED -lt $MAX_WAIT ]]; do
        STEP7_STATUS=$(aws ssm get-command-invocation \
            --command-id "$STEP7_COMMAND_ID" \
            --instance-id "$INSTANCE" \
            --profile "$PROFILE" \
            --region "$REGION" \
            --output text \
            --query "Status" 2>/dev/null || echo "Pending")

        if [[ "$STEP7_STATUS" == "Success" || "$STEP7_STATUS" == "Failed" || "$STEP7_STATUS" == "TimedOut" ]]; then
            break
        fi

        sleep 3
        STEP7_WAITED=$((STEP7_WAITED + 3))
    done

    if [[ "$STEP7_STATUS" == "Success" ]]; then
        aws ssm get-command-invocation \
            --command-id "$STEP7_COMMAND_ID" \
            --instance-id "$INSTANCE" \
            --profile "$PROFILE" \
            --region "$REGION" \
            --output text \
            --query "StandardOutputContent"
    elif [[ "$STEP7_STATUS" == "Failed" ]]; then
        echo "   ⚠️  Error moviendo CIDRs:"
        aws ssm get-command-invocation \
            --command-id "$STEP7_COMMAND_ID" \
            --instance-id "$INSTANCE" \
            --profile "$PROFILE" \
            --region "$REGION" \
            --output text \
            --query "StandardErrorContent"
    else
        echo "   ⚠️  Timeout esperando resultado de limpieza de CIDRs"
    fi

    # Limpiar script temporal de S3
    aws s3 rm "s3://$BUCKET/tmp/cleanup_non118_cidrs.py" \
        --profile "$PROFILE" --region "$REGION" --quiet 2>/dev/null || true
fi

# === Step 8: Reasignar workstations de VLAN_xxxx a sus agencias ===
if [[ "$STATUS" == "Success" ]]; then
    echo ""
    echo "🏢 Reasignando workstations de VLAN_xxxx a agencias..."

    # Subir script
    REASSIGN_SCRIPT="$REPO_ROOT/AlwaysPrintProject/Cloud/backend/app/scripts/reassign_from_special_vlans.py"
    aws s3 cp "$REASSIGN_SCRIPT" "s3://$BUCKET/tmp/reassign_from_special_vlans.py" \
        --profile "$PROFILE" --region "$REGION" --quiet || true

    STEP8_CMD="aws s3 cp s3://$BUCKET/tmp/reassign_from_special_vlans.py /tmp/reassign_from_special_vlans.py --region $REGION && docker cp /tmp/reassign_from_special_vlans.py $CONTAINER:/tmp/reassign_from_special_vlans.py && docker exec $CONTAINER python /tmp/reassign_from_special_vlans.py --org $ORG $DRY_RUN"

    STEP8_COMMAND_ID=$(aws ssm send-command \
        --instance-ids "$INSTANCE" \
        --document-name "AWS-RunShellScript" \
        --parameters "{\"commands\":[\"$STEP8_CMD\"]}" \
        --timeout-seconds 120 \
        --profile "$PROFILE" \
        --region "$REGION" \
        --output text \
        --query "Command.CommandId")

    echo "   Command ID: $STEP8_COMMAND_ID"
    sleep 5

    STEP8_WAITED=0
    STEP8_STATUS=""
    while [[ $STEP8_WAITED -lt $MAX_WAIT ]]; do
        STEP8_STATUS=$(aws ssm get-command-invocation \
            --command-id "$STEP8_COMMAND_ID" \
            --instance-id "$INSTANCE" \
            --profile "$PROFILE" \
            --region "$REGION" \
            --output text \
            --query "Status" 2>/dev/null || echo "Pending")

        if [[ "$STEP8_STATUS" == "Success" || "$STEP8_STATUS" == "Failed" || "$STEP8_STATUS" == "TimedOut" ]]; then
            break
        fi

        sleep 3
        STEP8_WAITED=$((STEP8_WAITED + 3))
    done

    if [[ "$STEP8_STATUS" == "Success" ]]; then
        aws ssm get-command-invocation \
            --command-id "$STEP8_COMMAND_ID" \
            --instance-id "$INSTANCE" \
            --profile "$PROFILE" \
            --region "$REGION" \
            --output text \
            --query "StandardOutputContent"
    elif [[ "$STEP8_STATUS" == "Failed" ]]; then
        echo "   ⚠️  Error reasignando workstations:"
        aws ssm get-command-invocation \
            --command-id "$STEP8_COMMAND_ID" \
            --instance-id "$INSTANCE" \
            --profile "$PROFILE" \
            --region "$REGION" \
            --output text \
            --query "StandardErrorContent"
    else
        echo "   ⚠️  Timeout esperando resultado de reasignación"
    fi

    # Limpiar script temporal de S3
    aws s3 rm "s3://$BUCKET/tmp/reassign_from_special_vlans.py" \
        --profile "$PROFILE" --region "$REGION" --quiet 2>/dev/null || true
fi

# === Step 9: Rescatar workstations de ZZZ por coincidencia CIDR ===
if [[ "$STATUS" == "Success" ]]; then
    echo ""
    echo "🔍 Rescatando workstations de ZZZ por coincidencia CIDR..."

    # Subir script
    RESCUE_SCRIPT="$REPO_ROOT/AlwaysPrintProject/Cloud/backend/app/scripts/rescue_zzz_by_cidr.py"
    aws s3 cp "$RESCUE_SCRIPT" "s3://$BUCKET/tmp/rescue_zzz_by_cidr.py" \
        --profile "$PROFILE" --region "$REGION" --quiet || true

    STEP9_CMD="aws s3 cp s3://$BUCKET/tmp/rescue_zzz_by_cidr.py /tmp/rescue_zzz_by_cidr.py --region $REGION && docker cp /tmp/rescue_zzz_by_cidr.py $CONTAINER:/tmp/rescue_zzz_by_cidr.py && docker exec $CONTAINER python /tmp/rescue_zzz_by_cidr.py --org $ORG $DRY_RUN"

    STEP9_COMMAND_ID=$(aws ssm send-command \
        --instance-ids "$INSTANCE" \
        --document-name "AWS-RunShellScript" \
        --parameters "{\"commands\":[\"$STEP9_CMD\"]}" \
        --timeout-seconds 120 \
        --profile "$PROFILE" \
        --region "$REGION" \
        --output text \
        --query "Command.CommandId")

    echo "   Command ID: $STEP9_COMMAND_ID"
    sleep 5

    STEP9_WAITED=0
    STEP9_STATUS=""
    while [[ $STEP9_WAITED -lt $MAX_WAIT ]]; do
        STEP9_STATUS=$(aws ssm get-command-invocation \
            --command-id "$STEP9_COMMAND_ID" \
            --instance-id "$INSTANCE" \
            --profile "$PROFILE" \
            --region "$REGION" \
            --output text \
            --query "Status" 2>/dev/null || echo "Pending")

        if [[ "$STEP9_STATUS" == "Success" || "$STEP9_STATUS" == "Failed" || "$STEP9_STATUS" == "TimedOut" ]]; then
            break
        fi

        sleep 3
        STEP9_WAITED=$((STEP9_WAITED + 3))
    done

    if [[ "$STEP9_STATUS" == "Success" ]]; then
        aws ssm get-command-invocation \
            --command-id "$STEP9_COMMAND_ID" \
            --instance-id "$INSTANCE" \
            --profile "$PROFILE" \
            --region "$REGION" \
            --output text \
            --query "StandardOutputContent"
    elif [[ "$STEP9_STATUS" == "Failed" ]]; then
        echo "   ⚠️  Error rescatando workstations:"
        aws ssm get-command-invocation \
            --command-id "$STEP9_COMMAND_ID" \
            --instance-id "$INSTANCE" \
            --profile "$PROFILE" \
            --region "$REGION" \
            --output text \
            --query "StandardErrorContent"
    else
        echo "   ⚠️  Timeout esperando resultado de rescate"
    fi

    # Limpiar script temporal de S3
    aws s3 rm "s3://$BUCKET/tmp/rescue_zzz_by_cidr.py" \
        --profile "$PROFILE" --region "$REGION" --quiet 2>/dev/null || true
fi

# === Step 10: Eliminar VLANs vacías (sin workstations referenciando) — PASO FINAL ===
if [[ "$STATUS" == "Success" ]]; then
    echo ""
    echo "🗑️  Eliminando VLANs sin workstations asignadas..."

    # Subir script de limpieza
    CLEANUP_SCRIPT="$REPO_ROOT/AlwaysPrintProject/Cloud/backend/app/scripts/cleanup_empty_vlans.py"
    aws s3 cp "$CLEANUP_SCRIPT" "s3://$BUCKET/tmp/cleanup_empty_vlans.py" \
        --profile "$PROFILE" --region "$REGION" --quiet || true

    STEP10_CMD="aws s3 cp s3://$BUCKET/tmp/cleanup_empty_vlans.py /tmp/cleanup_empty_vlans.py --region $REGION && docker cp /tmp/cleanup_empty_vlans.py $CONTAINER:/tmp/cleanup_empty_vlans.py && docker exec $CONTAINER python /tmp/cleanup_empty_vlans.py --org $ORG $DRY_RUN"

    STEP10_COMMAND_ID=$(aws ssm send-command \
        --instance-ids "$INSTANCE" \
        --document-name "AWS-RunShellScript" \
        --parameters "{\"commands\":[\"$STEP10_CMD\"]}" \
        --timeout-seconds 120 \
        --profile "$PROFILE" \
        --region "$REGION" \
        --output text \
        --query "Command.CommandId")

    echo "   Command ID: $STEP10_COMMAND_ID"
    sleep 5

    STEP10_WAITED=0
    STEP10_STATUS=""
    while [[ $STEP10_WAITED -lt $MAX_WAIT ]]; do
        STEP10_STATUS=$(aws ssm get-command-invocation \
            --command-id "$STEP10_COMMAND_ID" \
            --instance-id "$INSTANCE" \
            --profile "$PROFILE" \
            --region "$REGION" \
            --output text \
            --query "Status" 2>/dev/null || echo "Pending")

        if [[ "$STEP10_STATUS" == "Success" || "$STEP10_STATUS" == "Failed" || "$STEP10_STATUS" == "TimedOut" ]]; then
            break
        fi

        sleep 3
        STEP10_WAITED=$((STEP10_WAITED + 3))
    done

    if [[ "$STEP10_STATUS" == "Success" ]]; then
        aws ssm get-command-invocation \
            --command-id "$STEP10_COMMAND_ID" \
            --instance-id "$INSTANCE" \
            --profile "$PROFILE" \
            --region "$REGION" \
            --output text \
            --query "StandardOutputContent"
    elif [[ "$STEP10_STATUS" == "Failed" ]]; then
        echo "   ⚠️  Error eliminando VLANs vacías:"
        aws ssm get-command-invocation \
            --command-id "$STEP10_COMMAND_ID" \
            --instance-id "$INSTANCE" \
            --profile "$PROFILE" \
            --region "$REGION" \
            --output text \
            --query "StandardErrorContent"
    else
        echo "   ⚠️  Timeout esperando resultado de limpieza de VLANs"
    fi

    # Limpiar script temporal de S3
    aws s3 rm "s3://$BUCKET/tmp/cleanup_empty_vlans.py" \
        --profile "$PROFILE" --region "$REGION" --quiet 2>/dev/null || true
fi

echo ""
echo "============================================================"
echo "  Finalizado"
echo "============================================================"
