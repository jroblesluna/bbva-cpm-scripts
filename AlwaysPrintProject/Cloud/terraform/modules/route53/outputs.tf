output "zone_id" {
  value = aws_route53_zone.main.zone_id
}

output "name_servers" {
  description = "Nameservers a registrar en el proveedor de iol.pe para delegar apps.iol.pe"
  value       = aws_route53_zone.main.name_servers
}
