variable "aws_region" { type = string }
variable "project_name" { type = string }
variable "environment" { type = string }

variable "vpc_cidr" { type = string }
variable "public_subnet_cidrs" { type = list(string) }
variable "database_subnet_cidrs" { type = list(string) }
variable "availability_zones" { type = list(string) }

variable "ecr_image_tag_limit" { type = number }

variable "db_name" { type = string }
variable "db_username" { type = string }
variable "db_instance_class" { type = string }
variable "db_allocated_storage" { type = number }
variable "db_max_allocated_storage" { type = number }
variable "rds_deletion_protection" { type = bool }
variable "rds_backup_retention_days" { type = number }

variable "zone_name" { type = string }
variable "subdomain" { type = string }

variable "backend_port" { type = number }
variable "frontend_port" { type = number }

variable "ec2_instance_type" {
  description = "Tipo de instancia EC2 (t3.micro = free tier)"
  type        = string
}

variable "backend_env_vars" { type = map(string) }
variable "frontend_env_vars" { type = map(string) }

