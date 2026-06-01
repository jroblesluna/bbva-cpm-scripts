# Outputs del módulo S3

output "bucket_name" {
  description = "Nombre del bucket S3 de artefactos"
  value       = aws_s3_bucket.artifacts.id
}

output "bucket_arn" {
  description = "ARN del bucket S3 de artefactos"
  value       = aws_s3_bucket.artifacts.arn
}

output "docs_bucket_name" {
  description = "Nombre del bucket S3 de documentación pública"
  value       = aws_s3_bucket.docs.id
}

output "docs_bucket_arn" {
  description = "ARN del bucket S3 de documentación pública"
  value       = aws_s3_bucket.docs.arn
}

output "docs_bucket_url" {
  description = "URL base para descarga pública de documentos"
  value       = "https://${aws_s3_bucket.docs.bucket_regional_domain_name}"
}
