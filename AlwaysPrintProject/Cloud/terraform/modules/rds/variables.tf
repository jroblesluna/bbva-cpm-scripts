variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "db_name" {
  type = string
}

variable "db_username" {
  type = string
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "db_instance_class" {
  type = string
}

variable "db_allocated_storage" {
  type = number
}

variable "db_max_allocated_storage" {
  type = number
}

variable "subnet_ids" {
  type = list(string)
}

variable "vpc_id" {
  type = string
}

variable "security_group_id" {
  description = "Security group al que pertenece la instancia RDS (ya tiene la regla de ingress desde backend)"
  type        = string
}

variable "deletion_protection" {
  type = bool
}

variable "backup_retention_days" {
  type = number
}
