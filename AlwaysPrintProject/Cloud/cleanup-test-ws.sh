#!/bin/bash
# Elimina workstations de prueba vía SSM
# Uso:
#   ./cleanup-test-ws.sh              # Dry run
#   ./cleanup-test-ws.sh --delete     # Eliminar

PROFILE="AlwaysPrint-dev-040982755196"
INSTANCE="i-071e328b4dc75a63d"
PATTERN="W10-LT"
ACTION="count"

while [[ $# -gt 0 ]]; do
    case $1 in
        --delete) ACTION="delete"; shift;;
        --pattern) PATTERN="$2"; shift 2;;
        *) shift;;
    esac
done

echo "═══════════════════════════════════════"
echo "  Cleanup Workstations de Prueba"
echo "═══════════════════════════════════════"
echo "  Patrón:   ${PATTERN}%"
echo "  Acción:   $ACTION"
echo "═══════════════════════════════════════"
echo ""

# Generar JSON de parámetros con Python (evita problemas de quoting)
PARAMS_FILE=$(mktemp /tmp/ssm_XXXXXX.json)

if [ "$ACTION" = "delete" ]; then
python3 - "$PARAMS_FILE" "$PATTERN" << 'PYEOF'
import json, sys
params_file, pattern = sys.argv[1], sys.argv[2]
cmds = [
    f"docker exec alwaysprint-backend-1 python3 -c \"import os,sqlalchemy as sa;e=sa.create_engine(os.environ['DATABASE_URL']);c=e.connect();n=c.execute(sa.text(\\\"SELECT COUNT(*) FROM workstations WHERE hostname LIKE '{pattern}%'\\\")).scalar();print(f'Total: {{n}}');c.execute(sa.text(\\\"DELETE FROM telemetry_logs WHERE workstation_id IN (SELECT id FROM workstations WHERE hostname LIKE '{pattern}%')\\\")); c.execute(sa.text(\\\"DELETE FROM message_deliveries WHERE workstation_id IN (SELECT id FROM workstations WHERE hostname LIKE '{pattern}%')\\\")); d=c.execute(sa.text(\\\"DELETE FROM workstations WHERE hostname LIKE '{pattern}%'\\\")).rowcount;c.commit();print(f'Eliminadas: {{d}}')\""
]
json.dump({"commands": cmds}, open(params_file, 'w'))
PYEOF
else
python3 - "$PARAMS_FILE" "$PATTERN" << 'PYEOF'
import json, sys
params_file, pattern = sys.argv[1], sys.argv[2]
cmds = [
    f"docker exec alwaysprint-backend-1 python3 -c \"import os,sqlalchemy as sa;e=sa.create_engine(os.environ['DATABASE_URL']);c=e.connect();n=c.execute(sa.text(\\\"SELECT COUNT(*) FROM workstations WHERE hostname LIKE '{pattern}%'\\\")).scalar();print(f'Total {pattern}*: {{n}}');print('Usar --delete para eliminar')\""
]
json.dump({"commands": cmds}, open(params_file, 'w'))
PYEOF
fi

CMD_ID=$(aws ssm send-command \
    --profile "$PROFILE" \
    --instance-ids "$INSTANCE" \
    --document-name "AWS-RunShellScript" \
    --parameters "file://$PARAMS_FILE" \
    --output text \
    --query "Command.CommandId" \
    --no-cli-pager 2>&1)

rm -f "$PARAMS_FILE"

if [[ "$CMD_ID" == *"ERROR"* ]] || [ -z "$CMD_ID" ]; then
    echo "ERROR: $CMD_ID"
    exit 1
fi

echo "Ejecutando ($CMD_ID)..."
sleep 8

aws ssm get-command-invocation \
    --profile "$PROFILE" \
    --instance-id "$INSTANCE" \
    --command-id "$CMD_ID" \
    --output text \
    --query "StandardOutputContent" \
    --no-cli-pager 2>/dev/null

STDERR=$(aws ssm get-command-invocation \
    --profile "$PROFILE" \
    --instance-id "$INSTANCE" \
    --command-id "$CMD_ID" \
    --output text \
    --query "StandardErrorContent" \
    --no-cli-pager 2>/dev/null)

if [ -n "$STDERR" ] && [ "$STDERR" != "None" ]; then
    echo "STDERR: $STDERR"
fi
