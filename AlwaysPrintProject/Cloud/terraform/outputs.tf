output "app_url" {
  value = "https://${var.subdomain}.${var.zone_name}"
}

output "ec2_public_ip" {
  description = "IP publica del servidor"
  value       = module.ec2.public_ip
}

output "ec2_instance_id" {
  description = "ID del EC2 - agregar como secreto EC2_INSTANCE_ID en GitHub"
  value       = module.ec2.instance_id
}

output "rds_endpoint" {
  value = module.rds.db_endpoint
}

output "backend_ecr_url" {
  value = module.ecr.backend_repository_url
}

output "frontend_ecr_url" {
  value = module.ecr.frontend_repository_url
}

output "ssh_private_key_command" {
  description = "Comando para bajar la clave SSH y conectarte al EC2"
  value       = "aws secretsmanager get-secret-value --secret-id /${var.project_name}/${var.environment}/ssh_private_key --region ${var.aws_region} --query SecretString --output text > alwaysprint.pem && chmod 600 alwaysprint.pem && ssh -i alwaysprint.pem ec2-user@${module.ec2.public_ip}"
}

output "ses_dns_records" {
  description = "Registros DNS a agregar manualmente en Hostinger (zona iol.pe)"
  value       = module.ses.ses_dns_records
}

output "github_actions_secrets" {
  description = "Secretos a configurar en GitHub → Settings → Secrets and variables → Actions"
  value = {
    AWS_ACCESS_KEY_ID     = "(tu Access Key ID de IAM)"
    AWS_SECRET_ACCESS_KEY = "(tu Secret Access Key de IAM)"
    AWS_REGION            = var.aws_region
    EC2_INSTANCE_ID       = module.ec2.instance_id
    BACKEND_ECR_URL       = module.ecr.backend_repository_url
    FRONTEND_ECR_URL      = module.ecr.frontend_repository_url
  }
}
