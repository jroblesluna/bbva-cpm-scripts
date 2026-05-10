variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "security_group_id" {
  type = string
}

variable "acm_certificate_arn" {
  type = string
}

variable "frontend_port" {
  type = number
}

variable "backend_port" {
  type = number
}
