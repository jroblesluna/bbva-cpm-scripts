variable "aws_region" {
  description = "Región AWS donde se despliega la infraestructura"
  type        = string
}

variable "project_name" {
  description = "Nombre del proyecto (usado como prefijo en recursos)"
  type        = string
}

variable "environment" {
  description = "Entorno de despliegue (prod, staging, dev)"
  type        = string
}

# -------------------------------------------------------------------
# Networking
# -------------------------------------------------------------------
variable "vpc_cidr" {
  description = "CIDR block del VPC principal"
  type        = string
}

variable "public_subnet_cidrs" {
  description = "Lista de CIDRs para subnets públicas (ALB). Debe coincidir con availability_zones"
  type        = list(string)
}

variable "private_subnet_cidrs" {
  description = "Lista de CIDRs para subnets privadas (ECS tasks). Debe coincidir con availability_zones"
  type        = list(string)
}

variable "database_subnet_cidrs" {
  description = "Lista de CIDRs para subnets de base de datos (RDS, ElastiCache). Debe coincidir con availability_zones"
  type        = list(string)
}

variable "availability_zones" {
  description = "Lista de Availability Zones a usar. Mínimo 2 para alta disponibilidad"
  type        = list(string)
}

# -------------------------------------------------------------------
# ECR
# -------------------------------------------------------------------
variable "ecr_image_tag_limit" {
  description = "Número máximo de imágenes a mantener en ECR por repositorio (lifecycle policy)"
  type        = number
}

# -------------------------------------------------------------------
# Base de datos
# -------------------------------------------------------------------
variable "db_name" {
  description = "Nombre de la base de datos PostgreSQL"
  type        = string
}

variable "db_username" {
  description = "Usuario administrador de PostgreSQL"
  type        = string
}

variable "db_instance_class" {
  description = "Clase de instancia RDS (ej: db.t3.micro, db.t3.small)"
  type        = string
}

variable "db_allocated_storage" {
  description = "Almacenamiento inicial de RDS en GB"
  type        = number
}

variable "db_max_allocated_storage" {
  description = "Almacenamiento máximo de RDS en GB (autoscaling)"
  type        = number
}

variable "rds_deletion_protection" {
  description = "Protección contra eliminación accidental de RDS"
  type        = bool
}

variable "rds_backup_retention_days" {
  description = "Días de retención de backups automáticos de RDS"
  type        = number
}

# -------------------------------------------------------------------
# ElastiCache Redis
# -------------------------------------------------------------------
variable "enable_redis" {
  description = "Habilitar Redis ElastiCache para caché de la aplicación"
  type        = bool
}

variable "redis_node_type" {
  description = "Tipo de nodo de ElastiCache Redis (ej: cache.t3.micro)"
  type        = string
}

# -------------------------------------------------------------------
# Dominio y DNS
# -------------------------------------------------------------------
variable "zone_name" {
  description = "Nombre de la zona hospedada en Route53 (ej: apps.iol.pe)"
  type        = string
}

variable "subdomain" {
  description = "Subdominio de la aplicación dentro de zone_name (ej: alwaysprint)"
  type        = string
}

# -------------------------------------------------------------------
# ECS Fargate
# -------------------------------------------------------------------
variable "backend_port" {
  description = "Puerto en el que escucha el contenedor backend (FastAPI)"
  type        = number
}

variable "frontend_port" {
  description = "Puerto en el que escucha el contenedor frontend (Next.js)"
  type        = number
}

variable "backend_cpu" {
  description = "CPU asignada al task de backend en unidades Fargate (256=0.25vCPU)"
  type        = number
}

variable "backend_memory" {
  description = "Memoria asignada al task de backend en MB"
  type        = number
}

variable "frontend_cpu" {
  description = "CPU asignada al task de frontend en unidades Fargate"
  type        = number
}

variable "frontend_memory" {
  description = "Memoria asignada al task de frontend en MB"
  type        = number
}

variable "backend_desired_count" {
  description = "Número deseado de tasks de backend en ejecución"
  type        = number
}

variable "frontend_desired_count" {
  description = "Número deseado de tasks de frontend en ejecución"
  type        = number
}

# -------------------------------------------------------------------
# Variables de entorno de la aplicación (no sensibles)
# -------------------------------------------------------------------
variable "backend_env_vars" {
  description = "Map de variables de entorno no sensibles para el backend"
  type        = map(string)
}

variable "frontend_env_vars" {
  description = "Map de variables de entorno no sensibles para el frontend"
  type        = map(string)
}

# -------------------------------------------------------------------
# CI/CD - GitHub + CodePipeline
# -------------------------------------------------------------------
variable "github_owner" {
  description = "Owner o organización del repositorio en GitHub"
  type        = string
}

variable "github_repo" {
  description = "Nombre del repositorio en GitHub (sin owner)"
  type        = string
}

variable "github_branch" {
  description = "Rama de GitHub que dispara el pipeline (ej: main)"
  type        = string
}

variable "pipeline_artifact_bucket_name" {
  description = "Nombre del bucket S3 para artefactos de CodePipeline (debe ser globalmente único)"
  type        = string
}

variable "backend_source_path" {
  description = "Ruta relativa al backend dentro del repo (ej: AlwaysPrintProject/Cloud/backend)"
  type        = string
}

variable "frontend_source_path" {
  description = "Ruta relativa al frontend dentro del repo (ej: AlwaysPrintProject/Cloud/frontend)"
  type        = string
}
