#!/bin/bash
# setup.sh — punto de entrada único para terraform plan/apply/destroy
#
# Uso:
#   ./setup.sh plan     # terraform plan
#   ./setup.sh apply    # terraform apply
#   ./setup.sh destroy  # terraform destroy

set -euo pipefail

COMMAND="${1:-plan}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Validar comando ───────────────────────────────────────────────────────────
if [[ "$COMMAND" != "plan" && "$COMMAND" != "apply" && "$COMMAND" != "destroy" ]]; then
  echo "Uso: $0 [plan|apply|destroy]"
  exit 1
fi

# ── Verificar credenciales AWS ────────────────────────────────────────────────
if ! aws sts get-caller-identity &>/dev/null; then
  echo "ERROR: No hay credenciales AWS configuradas."
  echo "Ejecuta: aws configure  o  export AWS_PROFILE=tu-profile"
  exit 1
fi

echo "────────────────────────────────────────────────"
echo "  AlwaysPrint Cloud — Terraform $COMMAND"
echo "────────────────────────────────────────────────"
echo ""

# ── Terraform init si no está inicializado ────────────────────────────────────
if [ ! -d "$SCRIPT_DIR/.terraform" ]; then
  echo "Ejecutando terraform init..."
  terraform -chdir="$SCRIPT_DIR" init
  echo ""
fi

# ── Ejecutar terraform ────────────────────────────────────────────────────────
case "$COMMAND" in
  plan)
    terraform -chdir="$SCRIPT_DIR" plan
    ;;
  apply)
    terraform -chdir="$SCRIPT_DIR" apply
    ;;
  destroy)
    terraform -chdir="$SCRIPT_DIR" destroy
    ;;
esac
