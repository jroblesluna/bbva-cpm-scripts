output "backend_repository_url" {
  value = aws_ecr_repository.backend.repository_url
}

output "frontend_repository_url" {
  value = aws_ecr_repository.frontend.repository_url
}

output "backend_repository_name" {
  value = aws_ecr_repository.backend.name
}

output "frontend_repository_name" {
  value = aws_ecr_repository.frontend.name
}
