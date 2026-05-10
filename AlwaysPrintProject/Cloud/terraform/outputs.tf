output "app_url" {
  description = "URL pública de la aplicación"
  value       = "https://${var.subdomain}.${var.zone_name}"
}

output "alb_dns_name" {
  description = "DNS del Application Load Balancer"
  value       = module.alb.alb_dns_name
}

output "acm_certificate_arn" {
  description = "ARN del certificado SSL/TLS"
  value       = module.acm.certificate_arn
}

output "ecs_cluster_name" {
  value = module.ecs.cluster_name
}

output "backend_ecr_url" {
  value = module.ecr.backend_repository_url
}

output "frontend_ecr_url" {
  value = module.ecr.frontend_repository_url
}

output "rds_endpoint" {
  description = "Endpoint de conexión a RDS PostgreSQL"
  value       = module.rds.db_endpoint
}

output "github_codestar_connection_arn" {
  description = "ARN de la conexión CodeStar a GitHub - DEBE APROBARSE MANUALMENTE en la consola AWS"
  value       = module.cicd.codestar_connection_arn
}

output "backend_pipeline_name" {
  value = module.cicd.backend_pipeline_name
}

output "frontend_pipeline_name" {
  value = module.cicd.frontend_pipeline_name
}

# -------------------------------------------------------------------
# Registros DNS a agregar manualmente en tu proveedor DNS
# -------------------------------------------------------------------
output "manual_dns_records" {
  description = "Registros DNS a crear en tu proveedor (Hostinger, Cloudflare, GoDaddy, etc.)"
  value = {
    "1_ssl_validation_CNAME" = {
      description = "Valida el certificado SSL - agregar como CNAME en tu proveedor DNS"
      records     = module.acm.validation_options
    }
    "2_app_CNAME" = {
      description = "Apunta tu dominio al load balancer - agregar como CNAME"
      name        = "${var.subdomain}.${var.zone_name}"
      value       = module.alb.alb_dns_name
    }
  }
}

output "setup_instructions" {
  description = "Instrucciones post-despliegue"
  value       = <<-EOT

    ====================================================================
    PASOS OBLIGATORIOS DESPUÉS DE TERRAFORM APPLY
    ====================================================================

    1. AGREGAR 2 REGISTROS DNS EN TU PROVEEDOR DNS:

       a) CNAME de validación SSL:
          Revisa el output "manual_dns_records.1_ssl_validation_CNAME"
          Agrega ese CNAME en tu proveedor DNS.
          ACM valida automáticamente en ~5 minutos.

       b) CNAME de la aplicación:
          Nombre : ${var.subdomain}   (o ${var.subdomain}.${var.zone_name})
          Tipo   : CNAME
          Valor  : (ver output alb_dns_name)

    2. APROBAR CONEXIÓN GITHUB:
       AWS Console → Developer Tools → Settings → Connections
       Aprueba la conexión pendiente con GitHub.

    3. PRIMER DESPLIEGUE (push de imágenes iniciales a ECR):
       Ver output "backend_ecr_url" y "frontend_ecr_url" para los comandos exactos.

    4. A partir de ahí, cada git push a main dispara el pipeline automáticamente.
    ====================================================================
  EOT
}
