variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "node_type" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "vpc_id" {
  type = string
}

variable "security_group_id" {
  description = "Security group al que pertenece el cluster Redis (ya tiene la regla de ingress desde backend)"
  type        = string
}
