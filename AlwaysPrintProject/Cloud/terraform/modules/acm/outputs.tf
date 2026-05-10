output "certificate_arn" {
  description = "ARN del certificado (puede estar pendiente de validación DNS)"
  value       = aws_acm_certificate.main.arn
}

output "validation_options" {
  description = "Registros CNAME que debes agregar en tu proveedor DNS para validar el certificado"
  value       = aws_acm_certificate.main.domain_validation_options
}
