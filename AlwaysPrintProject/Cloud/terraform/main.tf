terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }

  # Descomenta y configura cuando tengas un bucket S3 para remote state
  # backend "s3" {
  #   bucket         = "alwaysprint-terraform-state"
  #   key            = "alwaysprint/prod/terraform.tfstate"
  #   region         = "us-west-2"
  #   encrypt        = true
  #   dynamodb_table = "alwaysprint-terraform-locks"
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

# -----------------------------------------------
# Networking (VPC, subnets, SGs)
# -----------------------------------------------
module "networking" {
  source = "./modules/networking"

  project_name          = var.project_name
  environment           = var.environment
  vpc_cidr              = var.vpc_cidr
  public_subnet_cidrs   = var.public_subnet_cidrs
  private_subnet_cidrs  = var.private_subnet_cidrs
  database_subnet_cidrs = var.database_subnet_cidrs
  availability_zones    = var.availability_zones
}

# -----------------------------------------------
# ECR Repositories
# -----------------------------------------------
module "ecr" {
  source = "./modules/ecr"

  project_name    = var.project_name
  environment     = var.environment
  image_tag_limit = var.ecr_image_tag_limit
}

# -----------------------------------------------
# Secrets Manager (genera passwords aleatorias)
# -----------------------------------------------
module "secrets" {
  source = "./modules/secrets"

  project_name = var.project_name
  environment  = var.environment
}

# -----------------------------------------------
# RDS PostgreSQL
# -----------------------------------------------
module "rds" {
  source = "./modules/rds"

  project_name             = var.project_name
  environment              = var.environment
  db_name                  = var.db_name
  db_username              = var.db_username
  db_password              = module.secrets.db_password_value
  db_instance_class        = var.db_instance_class
  db_allocated_storage     = var.db_allocated_storage
  db_max_allocated_storage = var.db_max_allocated_storage
  subnet_ids               = module.networking.database_subnet_ids
  vpc_id                   = module.networking.vpc_id
  security_group_id        = module.networking.rds_sg_id
  deletion_protection      = var.rds_deletion_protection
  backup_retention_days    = var.rds_backup_retention_days
}

# -----------------------------------------------
# ElastiCache Redis (opcional)
# -----------------------------------------------
module "elasticache" {
  source = "./modules/elasticache"
  count  = var.enable_redis ? 1 : 0

  project_name      = var.project_name
  environment       = var.environment
  node_type         = var.redis_node_type
  subnet_ids        = module.networking.database_subnet_ids
  vpc_id            = module.networking.vpc_id
  security_group_id = module.networking.redis_sg_id
}

# -----------------------------------------------
# Secretos de conexión (DATABASE_URL, REDIS_URL)
# Se crean aquí porque dependen de RDS y ElastiCache
# -----------------------------------------------
resource "aws_secretsmanager_secret" "database_url" {
  name                    = "/${var.project_name}/${var.environment}/database_url"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = "postgresql://${var.db_username}:${module.secrets.db_password_value}@${module.rds.db_endpoint}/${var.db_name}"
}

resource "aws_secretsmanager_secret" "redis_url" {
  count                   = var.enable_redis ? 1 : 0
  name                    = "/${var.project_name}/${var.environment}/redis_url"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "redis_url" {
  count         = var.enable_redis ? 1 : 0
  secret_id     = aws_secretsmanager_secret.redis_url[0].id
  secret_string = "redis://${module.elasticache[0].redis_endpoint}:6379/0"
}

# -----------------------------------------------
# ACM Certificate (sin Route53 - validación manual)
# -----------------------------------------------
module "acm" {
  source = "./modules/acm"

  domain_name = "${var.subdomain}.${var.zone_name}"
}

# -----------------------------------------------
# ALB
# -----------------------------------------------
module "alb" {
  source = "./modules/alb"

  project_name        = var.project_name
  environment         = var.environment
  vpc_id              = module.networking.vpc_id
  public_subnet_ids   = module.networking.public_subnet_ids
  security_group_id   = module.networking.alb_sg_id
  acm_certificate_arn = module.acm.certificate_arn
  frontend_port       = var.frontend_port
  backend_port        = var.backend_port
}

# -----------------------------------------------
# ECS Fargate
# -----------------------------------------------
module "ecs" {
  source = "./modules/ecs"

  project_name              = var.project_name
  environment               = var.environment
  aws_region                = var.aws_region
  aws_account_id            = data.aws_caller_identity.current.account_id
  vpc_id                    = module.networking.vpc_id
  private_subnet_ids        = module.networking.private_subnet_ids
  backend_sg_id             = module.networking.backend_sg_id
  frontend_sg_id            = module.networking.frontend_sg_id
  backend_target_group_arn  = module.alb.backend_target_group_arn
  frontend_target_group_arn = module.alb.frontend_target_group_arn
  backend_ecr_url           = module.ecr.backend_repository_url
  frontend_ecr_url          = module.ecr.frontend_repository_url
  backend_cpu               = var.backend_cpu
  backend_memory            = var.backend_memory
  frontend_cpu              = var.frontend_cpu
  frontend_memory           = var.frontend_memory
  backend_desired_count     = var.backend_desired_count
  frontend_desired_count    = var.frontend_desired_count
  backend_port              = var.backend_port
  frontend_port             = var.frontend_port
  public_url                = "https://${var.subdomain}.${var.zone_name}"
  backend_env_vars          = var.backend_env_vars
  frontend_env_vars         = var.frontend_env_vars
  database_url_secret_arn   = aws_secretsmanager_secret.database_url.arn
  secret_key_arn            = module.secrets.secret_key_arn
  redis_url_secret_arn      = var.enable_redis ? aws_secretsmanager_secret.redis_url[0].arn : ""
  enable_redis              = var.enable_redis

  depends_on = [
    aws_secretsmanager_secret_version.database_url,
    aws_secretsmanager_secret_version.redis_url,
  ]
}

# -----------------------------------------------
# CI/CD (CodePipeline + CodeBuild)
# -----------------------------------------------
module "cicd" {
  source = "./modules/cicd"

  project_name                 = var.project_name
  environment                  = var.environment
  aws_region                   = var.aws_region
  aws_account_id               = data.aws_caller_identity.current.account_id
  github_owner                 = var.github_owner
  github_repo                  = var.github_repo
  github_branch                = var.github_branch
  backend_ecr_repository_name  = module.ecr.backend_repository_name
  frontend_ecr_repository_name = module.ecr.frontend_repository_name
  backend_ecr_url              = module.ecr.backend_repository_url
  frontend_ecr_url             = module.ecr.frontend_repository_url
  ecs_cluster_name             = module.ecs.cluster_name
  backend_service_name         = module.ecs.backend_service_name
  frontend_service_name        = module.ecs.frontend_service_name
  artifact_bucket_name         = var.pipeline_artifact_bucket_name
  backend_source_path          = var.backend_source_path
  frontend_source_path         = var.frontend_source_path
  public_url                   = "https://${var.subdomain}.${var.zone_name}"
  frontend_env_vars            = var.frontend_env_vars
}
