# Variables de entrada del módulo S3

variable "project_name" {
  type        = string
  description = "Nombre del proyecto (usado en tags)"
}

variable "environment" {
  type        = string
  description = "Ambiente de despliegue (usado en tags)"
}

variable "ec2_role_arn" {
  type        = string
  description = "ARN del rol IAM del EC2 para la política de lectura del bucket"
}
