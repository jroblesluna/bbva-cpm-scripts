variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "aws_account_id" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "backend_sg_id" {
  type = string
}

variable "frontend_sg_id" {
  type = string
}

variable "backend_target_group_arn" {
  type = string
}

variable "frontend_target_group_arn" {
  type = string
}

variable "backend_ecr_url" {
  type = string
}

variable "frontend_ecr_url" {
  type = string
}

variable "backend_cpu" {
  type = number
}

variable "backend_memory" {
  type = number
}

variable "frontend_cpu" {
  type = number
}

variable "frontend_memory" {
  type = number
}

variable "backend_desired_count" {
  type = number
}

variable "frontend_desired_count" {
  type = number
}

variable "backend_port" {
  type = number
}

variable "frontend_port" {
  type = number
}

variable "public_url" {
  type = string
}

variable "backend_env_vars" {
  type = map(string)
}

variable "frontend_env_vars" {
  type = map(string)
}

variable "database_url_secret_arn" {
  type = string
}

variable "secret_key_arn" {
  type = string
}

variable "redis_url_secret_arn" {
  type = string
}

variable "enable_redis" {
  type = bool
}
