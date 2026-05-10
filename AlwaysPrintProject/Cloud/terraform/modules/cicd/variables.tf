variable "project_name" { type = string }
variable "environment" { type = string }
variable "aws_region" { type = string }
variable "aws_account_id" { type = string }
variable "github_owner" { type = string }
variable "github_repo" { type = string }
variable "github_branch" { type = string }
variable "backend_ecr_repository_name" { type = string }
variable "frontend_ecr_repository_name" { type = string }
variable "artifact_bucket_name" { type = string }
variable "backend_source_path" { type = string }
variable "frontend_source_path" { type = string }
variable "public_url" { type = string }
variable "frontend_env_vars" { type = map(string) }
variable "ec2_instance_id" {
  description = "EC2 instance ID para deploy via SSM"
  type        = string
}
