output "app_url" {
  value = "https://${var.subdomain}.${var.zone_name}"
}

output "ec2_public_ip" {
  description = "IP publica del servidor - apunta tu dominio a esta IP"
  value       = module.ec2.public_ip
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

output "github_codestar_connection_arn" {
  description = "Aprobar en AWS Console -> Developer Tools -> Connections"
  value       = module.cicd.codestar_connection_arn
}

output "manual_dns_records" {
  description = "Registros a agregar en Hostinger para que la app funcione"
  value = {
    "CNAME_app" = {
      tipo    = "CNAME"
      nombre  = "${var.subdomain}.${var.zone_name}"
      apunta_a = "-- no aplica, usa el registro A --"
    }
    "A_app" = {
      tipo    = "A"
      nombre  = "${var.subdomain}"
      valor   = module.ec2.public_ip
      nota    = "En Hostinger: tipo A, nombre 'alwaysprint.apps', valor = IP de arriba"
    }
  }
}

output "setup_instructions" {
  value = <<-EOT

    ====================================================================
    PASOS DESPUÉS DE TERRAFORM APPLY
    ====================================================================

    1. AGREGAR REGISTRO DNS EN HOSTINGER (apps.iol.pe):
       Tipo  : A
       Nombre: alwaysprint.apps
       Valor : ${module.ec2.public_ip}

       Esto apunta alwaysprint.apps.iol.pe a tu servidor EC2.
       Let's Encrypt se configura automáticamente una vez que el DNS propague.

    2. APROBAR CONEXIÓN GITHUB:
       AWS Console -> Developer Tools -> Settings -> Connections
       Aprueba: ${module.cicd.codestar_connection_arn}

    3. PRIMER DEPLOY (push imágenes a ECR):
       # Generar clave SSH si no tienes:
       # ssh-keygen -t rsa -b 4096 -f ~/.ssh/alwaysprint

       # Backend
       aws ecr get-login-password --region ${var.aws_region} | \
         docker login --username AWS --password-stdin ${module.ecr.backend_repository_url}
       cd AlwaysPrintProject/Cloud/backend
       docker build -t ${module.ecr.backend_repository_url}:latest .
       docker push ${module.ecr.backend_repository_url}:latest

       # Frontend
       cd AlwaysPrintProject/Cloud/frontend
       docker build -t ${module.ecr.frontend_repository_url}:latest .
       docker push ${module.ecr.frontend_repository_url}:latest

       # Trigger deploy en EC2
       ssh -i ~/.ssh/alwaysprint ec2-user@${module.ec2.public_ip} \
         "/opt/alwaysprint/deploy.sh all"

    4. A partir de ahí, cada git push dispara el pipeline automaticamente.
    ====================================================================
  EOT
}
