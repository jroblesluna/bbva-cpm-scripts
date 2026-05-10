# ====================================================================
# AlwaysPrint Cloud - Terraform Variables
# Personaliza todos los valores antes de ejecutar terraform apply
# ====================================================================

# -------------------------------------------------------------------
# General
# -------------------------------------------------------------------
aws_region   = "us-west-2"
project_name = "alwaysprint"
environment  = "prod"

# -------------------------------------------------------------------
# Networking
# -------------------------------------------------------------------
vpc_cidr              = "10.0.0.0/16"
public_subnet_cidrs   = ["10.0.1.0/24", "10.0.2.0/24"]
private_subnet_cidrs  = ["10.0.11.0/24", "10.0.12.0/24"]
database_subnet_cidrs = ["10.0.21.0/24", "10.0.22.0/24"]
availability_zones    = ["us-west-2a", "us-west-2b"]

# -------------------------------------------------------------------
# ECR
# -------------------------------------------------------------------
ecr_image_tag_limit = 10

# -------------------------------------------------------------------
# Base de datos RDS PostgreSQL
# -------------------------------------------------------------------
db_name                   = "alwaysprint"
db_username               = "alwaysprint_admin"
db_instance_class         = "db.t3.small"
db_allocated_storage      = 20
db_max_allocated_storage  = 100
rds_deletion_protection   = true
rds_backup_retention_days = 7

# -------------------------------------------------------------------
# Redis (ElastiCache)
# Cambiar a false si no se necesita caché
# -------------------------------------------------------------------
enable_redis    = true
redis_node_type = "cache.t3.micro"

# -------------------------------------------------------------------
# Dominio
# La app estará en: https://alwaysprint.apps.iol.pe
# -------------------------------------------------------------------
zone_name = "apps.iol.pe"
subdomain = "alwaysprint"

# -------------------------------------------------------------------
# ECS Fargate - Puertos
# -------------------------------------------------------------------
backend_port  = 8000
frontend_port = 3000

# -------------------------------------------------------------------
# ECS Fargate - Recursos
# CPU: 256=0.25vCPU, 512=0.5vCPU, 1024=1vCPU, 2048=2vCPU
# Memoria en MB
# -------------------------------------------------------------------
backend_cpu    = 512
backend_memory = 1024
frontend_cpu   = 256
frontend_memory = 512

backend_desired_count  = 1
frontend_desired_count = 1

# -------------------------------------------------------------------
# Variables de entorno del backend (no sensibles)
# Las sensibles (DATABASE_URL, SECRET_KEY, REDIS_URL) van en AWS Secrets Manager
# y son generadas automáticamente por Terraform
# -------------------------------------------------------------------
backend_env_vars = {
  LOG_LEVEL                   = "INFO"
  ACCESS_TOKEN_EXPIRE_MINUTES = "1440"
  ALGORITHM                   = "HS256"
  DB_POOL_SIZE                = "20"
  DB_MAX_OVERFLOW             = "10"
  DB_POOL_TIMEOUT             = "30"
  DB_POOL_RECYCLE             = "3600"
  WS_PING_INTERVAL            = "30"
  WS_PING_TIMEOUT             = "60"
  RATE_LIMIT_LOGIN            = "5"
  RATE_LIMIT_API              = "100"
  CACHE_TTL_SECONDS           = "300"
  API_V1_STR                  = "/api/v1"
}

# -------------------------------------------------------------------
# Variables de entorno del frontend (no sensibles)
# NEXT_PUBLIC_API_URL y NEXT_PUBLIC_WS_URL se inyectan automáticamente
# desde la variable zone_name y subdomain
# -------------------------------------------------------------------
frontend_env_vars = {
  NEXT_PUBLIC_APP_NAME = "AlwaysPrint Cloud Management"
}

# -------------------------------------------------------------------
# CI/CD - GitHub + CodePipeline
# -------------------------------------------------------------------
github_owner  = "jroblesluna"
github_repo   = "bbva-cpm-scripts"
github_branch = "main"

# Debe ser globalmente único en AWS (incluye tu account ID si quieres)
pipeline_artifact_bucket_name = "alwaysprint-pipeline-artifacts-prod"

# Rutas dentro del repo que disparan cada pipeline
backend_source_path  = "AlwaysPrintProject/Cloud/backend"
frontend_source_path = "AlwaysPrintProject/Cloud/frontend"
