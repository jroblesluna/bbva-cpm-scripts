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

variable "github_owner" {
  type = string
}

variable "github_repo" {
  type = string
}

variable "github_branch" {
  type = string
}

variable "backend_ecr_repository_name" {
  type = string
}

variable "frontend_ecr_repository_name" {
  type = string
}

variable "backend_ecr_url" {
  type = string
}

variable "frontend_ecr_url" {
  type = string
}

variable "ecs_cluster_name" {
  type = string
}

variable "backend_service_name" {
  type = string
}

variable "frontend_service_name" {
  type = string
}

variable "artifact_bucket_name" {
  type = string
}

variable "backend_source_path" {
  description = "Ruta en el repo que dispara el pipeline de backend (ej: AlwaysPrintProject/Cloud/backend)"
  type        = string
}

variable "frontend_source_path" {
  description = "Ruta en el repo que dispara el pipeline de frontend (ej: AlwaysPrintProject/Cloud/frontend)"
  type        = string
}

variable "public_url" {
  description = "URL pública de la app para inyectar en variables NEXT_PUBLIC_*"
  type        = string
}

variable "frontend_env_vars" {
  description = "Variables de entorno del frontend (se inyectan como build args en Docker)"
  type        = map(string)
}
