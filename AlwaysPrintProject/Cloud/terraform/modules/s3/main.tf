# Módulo S3 — Bucket de artefactos MSI para AlwaysPrint
# Este módulo crea un bucket S3 seguro con versionado, cifrado y acceso restringido

locals {
  # Nombre del bucket incluye environment para evitar colisión entre cuentas
  bucket_name = "${var.project_name}-${var.environment}-artifacts"
}

resource "aws_s3_bucket" "artifacts" {
  bucket        = local.bucket_name
  force_destroy = true

  tags = {
    Name        = local.bucket_name
    Project     = var.project_name
    Environment = var.environment
  }
}

# Habilitar versionado para preservar versiones históricas del MSI
resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Cifrado del lado del servidor con AES-256 (SSE-S3)
resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Bloquear todo acceso público al bucket
resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Control de propiedad — deshabilita ACLs, el propietario del bucket tiene control total
resource "aws_s3_bucket_ownership_controls" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Política del bucket — acceso para el rol EC2 (lectura, listado de versiones y eliminación)
resource "aws_s3_bucket_policy" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "PermitirLecturaEC2"
        Effect    = "Allow"
        Principal = { AWS = var.ec2_role_arn }
        Action    = ["s3:GetObject"]
        Resource  = "${aws_s3_bucket.artifacts.arn}/*"
      },
      {
        Sid       = "PermitirListadoEC2"
        Effect    = "Allow"
        Principal = { AWS = var.ec2_role_arn }
        Action    = ["s3:ListBucket", "s3:ListBucketVersions"]
        Resource  = aws_s3_bucket.artifacts.arn
      },
      {
        Sid       = "PermitirEliminacionVersionesEC2"
        Effect    = "Allow"
        Principal = { AWS = var.ec2_role_arn }
        Action    = ["s3:DeleteObject", "s3:DeleteObjectVersion"]
        Resource  = "${aws_s3_bucket.artifacts.arn}/*"
      }
    ]
  })
}
