#!/bin/bash
# setup.sh — punto de entrada único para terraform plan/apply
#
# Uso:
#   ./setup.sh plan               # terraform plan
#   ./setup.sh apply              # terraform apply
#   ./setup.sh plan  --rotate-key # forzar rotación de clave SSH
#   ./setup.sh apply --rotate-key
#
# Gestión de clave SSH:
#   - Si el secret no existe en Secrets Manager → genera par de claves y lo crea
#   - Si ya existe → deriva la clave pública y sincroniza terraform.tfvars
#   - Con --rotate-key → genera y sobreescribe el secret existente

set -euo pipefail

COMMAND="${1:-plan}"
ROTATE_KEY=false
[ "${2:-}" = "--rotate-key" ] && ROTATE_KEY=true

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TFVARS="$SCRIPT_DIR/terraform.tfvars"
SECRET_ID="/alwaysprint/prod/ssh_private_key"
REGION="${AWS_DEFAULT_REGION:-us-west-2}"

# ── Validar comando ───────────────────────────────────────────────────────────
if [[ "$COMMAND" != "plan" && "$COMMAND" != "apply" ]]; then
  echo "Uso: $0 [plan|apply] [--rotate-key]"
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

# ── Gestión de clave SSH ──────────────────────────────────────────────────────
SECRET_EXISTS=false
if aws secretsmanager get-secret-value \
     --secret-id "$SECRET_ID" --region "$REGION" &>/dev/null; then
  SECRET_EXISTS=true
fi

if [ "$SECRET_EXISTS" = "false" ] || [ "$ROTATE_KEY" = "true" ]; then

  if [ "$ROTATE_KEY" = "true" ] && [ "$SECRET_EXISTS" = "true" ]; then
    echo "⚠️  Rotando clave SSH (--rotate-key)..."
  else
    echo "🔑 Secret SSH no existe. Generando nuevo par de claves..."
  fi

  TMP_KEY=$(mktemp)
  rm -f "$TMP_KEY"  # ssh-keygen necesita que el archivo NO exista
  ssh-keygen -t ed25519 -f "$TMP_KEY" -N "" -q
  PRIVATE_KEY=$(cat "$TMP_KEY")
  PUBLIC_KEY=$(cat "${TMP_KEY}.pub")
  rm -f "$TMP_KEY" "${TMP_KEY}.pub"

  if [ "$SECRET_EXISTS" = "true" ]; then
    aws secretsmanager put-secret-value \
      --secret-id "$SECRET_ID" \
      --secret-string "$PRIVATE_KEY" \
      --region "$REGION" > /dev/null
    echo "✅ Secret SSH actualizado en Secrets Manager."
  else
    aws secretsmanager create-secret \
      --name "$SECRET_ID" \
      --description "Clave SSH privada para EC2 alwaysprint-prod" \
      --secret-string "$PRIVATE_KEY" \
      --region "$REGION" > /dev/null
    echo "✅ Secret SSH creado en Secrets Manager."
  fi

else
  echo "✅ Secret SSH encontrado. Derivando clave pública..."

  PRIVATE_KEY=$(aws secretsmanager get-secret-value \
    --secret-id "$SECRET_ID" --region "$REGION" \
    --query SecretString --output text)

  TMP_KEY=$(mktemp)
  printf '%s\n' "$PRIVATE_KEY" > "$TMP_KEY"
  chmod 600 "$TMP_KEY"
  PUBLIC_KEY=$(ssh-keygen -y -f "$TMP_KEY")
  rm -f "$TMP_KEY"
fi

# ── Sincronizar terraform.tfvars con la clave pública correcta ────────────────
CURRENT_KEY=$(grep '^ssh_public_key' "$TFVARS" 2>/dev/null \
  | sed 's/ssh_public_key *= *"\(.*\)"/\1/' || echo "")

if [ "$CURRENT_KEY" != "$PUBLIC_KEY" ]; then
  echo "🔄 Actualizando ssh_public_key en terraform.tfvars..."
  # Compatible con macOS (BSD sed) y Linux (GNU sed)
  if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s|^ssh_public_key = .*|ssh_public_key = \"$PUBLIC_KEY\"|" "$TFVARS"
  else
    sed -i "s|^ssh_public_key = .*|ssh_public_key = \"$PUBLIC_KEY\"|" "$TFVARS"
  fi
  echo "✅ terraform.tfvars sincronizado."
else
  echo "✅ ssh_public_key en terraform.tfvars ya está sincronizado."
fi

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
esac
