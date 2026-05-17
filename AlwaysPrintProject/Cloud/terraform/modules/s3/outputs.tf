# Outputs del módulo S3

output "bucket_name" {
  description = "Nombre del bucket S3 de artefactos"
  value       = aws_s3_bucket.artifacts.id
}

output "bucket_arn" {
  description = "ARN del bucket S3 de artefactos"
  value       = aws_s3_bucket.artifacts.arn
}
