variable "project_name" { type = string }
variable "environment" { type = string }
variable "aws_region" { type = string }
variable "aws_account_id" { type = string }
variable "instance_type" { type = string }
variable "subnet_id" { type = string }
variable "security_group_id" { type = string }
variable "backend_ecr_url" { type = string }
variable "frontend_ecr_url" { type = string }
variable "backend_port" { type = number }
variable "frontend_port" { type = number }
variable "domain_name" { type = string }
variable "db_host" { type = string }
variable "db_port" { type = number }
variable "db_name" { type = string }
variable "db_username" { type = string }
variable "backend_env_vars" { type = map(string) }
variable "database_url_secret_arn" { type = string }
variable "secret_key_arn" { type = string }
variable "ses_send_policy_arn" {
  description = "ARN de la política IAM de envío SES"
  type        = string
}
