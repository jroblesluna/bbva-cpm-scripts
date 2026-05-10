resource "aws_route53_zone" "main" {
  name = var.zone_name

  tags = { Name = var.zone_name }
}
