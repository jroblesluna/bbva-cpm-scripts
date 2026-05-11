resource "random_password" "db_password" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}:?"
}

resource "random_password" "secret_key" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "db_password" {
  name                    = "/${var.project_name}/${var.environment}/db_password"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id     = aws_secretsmanager_secret.db_password.id
  secret_string = random_password.db_password.result
}

resource "aws_secretsmanager_secret" "secret_key" {
  name                    = "/${var.project_name}/${var.environment}/secret_key"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "secret_key" {
  secret_id     = aws_secretsmanager_secret.secret_key.id
  secret_string = random_password.secret_key.result
}

# Clave privada SSH guardada en Secrets Manager
# Para bajarla: aws secretsmanager get-secret-value --secret-id /alwaysprint/prod/ssh_private_key --query SecretString --output text > alwaysprint.pem
# La clave SSH se gestiona externamente (generada una sola vez y subida manualmente).
# Para recuperarla: aws secretsmanager get-secret-value --secret-id /alwaysprint/prod/ssh_private_key
resource "aws_secretsmanager_secret" "ssh_private_key" {
  name                    = "/${var.project_name}/${var.environment}/ssh_private_key"
  recovery_window_in_days = 0
}
