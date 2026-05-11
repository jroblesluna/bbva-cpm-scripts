output "db_password_value" {
  value     = random_password.db_password.result
  sensitive = true
}

output "db_password_arn" {
  value = aws_secretsmanager_secret.db_password.arn
}

output "secret_key_arn" {
  value = aws_secretsmanager_secret.secret_key.arn
}

output "ssh_public_key" {
  value = var.ssh_public_key
}

output "ssh_private_key_secret_arn" {
  value = aws_secretsmanager_secret.ssh_private_key.arn
}
