variable "project_name" { type = string }
variable "environment" { type = string }
variable "ssh_public_key" {
  description = "Clave pública SSH ed25519 — generada una sola vez externamente"
  type        = string
}
