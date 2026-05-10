output "codestar_connection_arn" {
  description = "ARN de la conexión GitHub - debe aprobarse manualmente en AWS Console"
  value       = aws_codestarconnections_connection.github.arn
}

output "artifact_bucket_name" {
  value = aws_s3_bucket.artifacts.bucket
}

output "backend_pipeline_name" {
  value = aws_codepipeline.backend.name
}

output "frontend_pipeline_name" {
  value = aws_codepipeline.frontend.name
}

output "backend_codebuild_name" {
  value = aws_codebuild_project.backend.name
}

output "frontend_codebuild_name" {
  value = aws_codebuild_project.frontend.name
}
