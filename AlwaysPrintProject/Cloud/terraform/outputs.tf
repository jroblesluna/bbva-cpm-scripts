output "app_url" {
  value = "https://${var.subdomain}.${var.zone_name}"
}

output "ec2_public_ip" {
  description = "IP publica del servidor — actualizar registro A en DNS"
  value       = module.ec2.public_ip
}

output "ec2_instance_id" {
  description = "ID del EC2 (informativo — los workflows lo derivan automaticamente por tag)"
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

output "ses_dns_records" {
  description = "Registros DNS a agregar en el editor de zona del proveedor DNS (zona iol.pe)"
  value       = module.ses.ses_dns_records
}

output "ssm_access" {
  description = "Acceso al servidor via SSM (recomendado)"
  value = {
    comando = "aws ssm start-session --target ${module.ec2.instance_id} --region ${var.aws_region}"
  }
}

output "github_actions_secrets" {
  description = "Unicos secretos requeridos en GitHub Actions (Settings → Secrets → Actions)"
  value = {
    AWS_ACCESS_KEY_ID     = "(IAM Access Key ID con permisos ECR + SSM)"
    AWS_SECRET_ACCESS_KEY = "(IAM Secret Access Key correspondiente)"
  }
}

output "s3_bucket_name" {
  description = "Nombre del bucket S3 de artefactos MSI"
  value       = module.s3.bucket_name
}

output "s3_bucket_arn" {
  description = "ARN del bucket S3 de artefactos MSI"
  value       = module.s3.bucket_arn
}
