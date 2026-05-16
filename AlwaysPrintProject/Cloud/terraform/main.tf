terraform {
  required_version = ">= 1.5"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.0" }
    random = { source = "hashicorp/random", version = "~> 3.5" }
    tls    = { source = "hashicorp/tls", version = "~> 4.0" }
  }
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

module "networking" {
  source                = "./modules/networking"
  project_name          = var.project_name
  environment           = var.environment
  vpc_cidr              = var.vpc_cidr
  public_subnet_cidrs   = var.public_subnet_cidrs
  database_subnet_cidrs = var.database_subnet_cidrs
  availability_zones    = var.availability_zones
}

module "ecr" {
  source          = "./modules/ecr"
  project_name    = var.project_name
  environment     = var.environment
  image_tag_limit = var.ecr_image_tag_limit
}

module "secrets" {
  source       = "./modules/secrets"
  project_name = var.project_name
  environment  = var.environment
}

module "rds" {
  source                   = "./modules/rds"
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

resource "aws_secretsmanager_secret" "database_url" {
  name                    = "/${var.project_name}/${var.environment}/database_url"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = "postgresql://${var.db_username}:${module.secrets.db_password_value}@${module.rds.db_endpoint}/${var.db_name}"

  lifecycle {
    ignore_changes = [secret_string]
  }
}

module "ses" {
  source         = "./modules/ses"
  project_name   = var.project_name
  environment    = var.environment
  aws_region     = var.aws_region
  aws_account_id = data.aws_caller_identity.current.account_id
  zone_name      = var.zone_name
  from_email     = var.ses_from_email
}

module "ec2" {
  source                  = "./modules/ec2"
  project_name            = var.project_name
  environment             = var.environment
  aws_region              = var.aws_region
  aws_account_id          = data.aws_caller_identity.current.account_id
  instance_type           = var.ec2_instance_type
  subnet_id               = module.networking.public_subnet_ids[0]
  security_group_id       = module.networking.ec2_sg_id
  backend_ecr_url         = module.ecr.backend_repository_url
  frontend_ecr_url        = module.ecr.frontend_repository_url
  backend_port            = var.backend_port
  frontend_port           = var.frontend_port
  domain_name             = "${var.subdomain}.${var.zone_name}"
  db_host                 = module.rds.db_endpoint
  db_port                 = module.rds.db_port
  db_name                 = var.db_name
  db_username             = var.db_username
  backend_env_vars        = var.backend_env_vars
  ses_send_policy_arn     = module.ses.ses_send_policy_arn
  database_url_secret_arn = aws_secretsmanager_secret.database_url.arn
  secret_key_arn          = module.secrets.secret_key_arn

  depends_on = [aws_secretsmanager_secret_version.database_url, module.ses]
}

# CI/CD manejado por GitHub Actions (ver .github/workflows/)
