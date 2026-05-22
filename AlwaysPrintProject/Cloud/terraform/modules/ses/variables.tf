variable "project_name" { type = string }
variable "environment" { type = string }
variable "aws_region" { type = string }
variable "aws_account_id" { type = string }
variable "zone_name" {
  description = "Dominio DNS (ej: apps.iol.pe o dev.iol.pe) — debe existir como zona en Route53"
  type        = string
}
variable "from_email" {
  description = "Dirección de origen para emails (ej: noreply@alwaysprint.apps.iol.pe o noreply@alwaysprint.dev.iol.pe)"
  type        = string
}
