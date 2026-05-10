resource "aws_acm_certificate" "main" {
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = { Name = var.domain_name }
}

# Los registros CNAME de validación se agregan manualmente en tu proveedor DNS.
# Ver output "manual_dns_records" en outputs.tf del root.
