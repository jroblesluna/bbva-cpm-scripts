#!/bin/bash
# setup.sh — punto de entrada único para terraform plan/apply/destroy
#
# Uso:
#   ./setup.sh dev plan      # terraform plan con dev.tfvars
#   ./setup.sh prod plan     # terraform plan con prod.tfvars
#   ./setup.sh dev apply     # terraform apply con dev.tfvars
#   ./setup.sh prod apply    # terraform apply con prod.tfvars
#   ./setup.sh dev destroy   # terraform destroy con dev.tfvars

set -euo pipefail

ENV="${1:-}"
COMMAND="${2:-plan}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Validar entorno ───────────────────────────────────────────────────────────
if [[ "$ENV" != "dev" && "$ENV" != "prod" ]]; then
  echo "Uso: $0 [dev|prod] [plan|apply|destroy]"
  exit 1
fi

# ── Validar comando ───────────────────────────────────────────────────────────
if [[ "$COMMAND" != "plan" && "$COMMAND" != "apply" && "$COMMAND" != "destroy" ]]; then
  echo "Uso: $0 [dev|prod] [plan|apply|destroy]"
  exit 1
fi

# ── Seleccionar profile AWS según entorno ─────────────────────────────────────
case "$ENV" in
  dev)
    export AWS_PROFILE="AlwaysPrint-dev-747301449278"
    ;;
  prod)
    export AWS_PROFILE="AlwaysPrint-prod-425642439683"
    ;;
esac

TFVARS_FILE="$SCRIPT_DIR/${ENV}.tfvars"

if [ ! -f "$TFVARS_FILE" ]; then
  echo "ERROR: archivo $TFVARS_FILE no encontrado."
  exit 1
fi

# ── Verificar credenciales AWS ────────────────────────────────────────────────
if ! aws sts get-caller-identity --profile "$AWS_PROFILE" &>/dev/null; then
  echo "ERROR: No hay credenciales AWS configuradas para profile $AWS_PROFILE."
  echo "Ejecuta: aws configure --profile $AWS_PROFILE"
  exit 1
fi

echo "────────────────────────────────────────────────"
echo "  AlwaysPrint Cloud — Terraform $COMMAND"
echo "  Entorno:  $ENV"
echo "  Profile:  $AWS_PROFILE"
echo "  Var-file: ${ENV}.tfvars"
echo "────────────────────────────────────────────────"
echo ""

# ── Terraform init si no está inicializado ────────────────────────────────────
if [ ! -d "$SCRIPT_DIR/.terraform" ]; then
  echo "Ejecutando terraform init..."
  terraform -chdir="$SCRIPT_DIR" init
  echo ""
fi

# ── Seleccionar workspace (un state independiente por entorno) ─────────────────
CURRENT_WS=$(terraform -chdir="$SCRIPT_DIR" workspace show)
if [ "$CURRENT_WS" != "$ENV" ]; then
  echo "Cambiando workspace: $CURRENT_WS → $ENV"
  terraform -chdir="$SCRIPT_DIR" workspace select "$ENV" 2>/dev/null || \
    terraform -chdir="$SCRIPT_DIR" workspace new "$ENV"
  echo ""
fi

# ── Ejecutar terraform ────────────────────────────────────────────────────────
PLAN_FILE="$SCRIPT_DIR/.tfplan-${ENV}"

case "$COMMAND" in
  plan)
    terraform -chdir="$SCRIPT_DIR" plan -var-file="$TFVARS_FILE" -out="$PLAN_FILE"
    echo ""
    echo "Plan guardado en: $PLAN_FILE"
    echo "Para aplicar: ./setup.sh $ENV apply"
    ;;
  apply)
    if [ -f "$PLAN_FILE" ]; then
      echo "Aplicando plan guardado..."
      terraform -chdir="$SCRIPT_DIR" apply "$PLAN_FILE"
      rm -f "$PLAN_FILE"
    else
      terraform -chdir="$SCRIPT_DIR" apply -var-file="$TFVARS_FILE"
    fi
    ;;
  destroy)
    terraform -chdir="$SCRIPT_DIR" destroy -var-file="$TFVARS_FILE"
    ;;
esac
