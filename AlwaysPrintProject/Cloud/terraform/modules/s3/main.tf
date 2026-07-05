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

# =============================================================================
# Bucket S3 — Documentación pública (descarga libre)
# =============================================================================

locals {
  docs_bucket_name = "${var.project_name}-${var.environment}-docs"
}

resource "aws_s3_bucket" "docs" {
  bucket        = local.docs_bucket_name
  force_destroy = true

  tags = {
    Name        = local.docs_bucket_name
    Project     = var.project_name
    Environment = var.environment
  }
}

# Cifrado del lado del servidor con AES-256
resource "aws_s3_bucket_server_side_encryption_configuration" "docs" {
  bucket = aws_s3_bucket.docs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Permitir acceso público al bucket de documentación
resource "aws_s3_bucket_public_access_block" "docs" {
  bucket                  = aws_s3_bucket.docs.id
  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

# Control de propiedad — deshabilita ACLs
resource "aws_s3_bucket_ownership_controls" "docs" {
  bucket = aws_s3_bucket.docs.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Política pública — cualquiera puede descargar objetos del bucket de docs
resource "aws_s3_bucket_policy" "docs" {
  bucket = aws_s3_bucket.docs.id

  # Esperar a que el bloqueo de acceso público se aplique primero
  depends_on = [aws_s3_bucket_public_access_block.docs]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "PermitirDescargaPublica"
        Effect    = "Allow"
        Principal = "*"
        Action    = ["s3:GetObject"]
        Resource  = "${aws_s3_bucket.docs.arn}/*"
      },
      {
        Sid       = "PermitirSubidaEC2"
        Effect    = "Allow"
        Principal = { AWS = var.ec2_role_arn }
        Action    = ["s3:PutObject", "s3:DeleteObject"]
        Resource  = "${aws_s3_bucket.docs.arn}/*"
      },
      {
        Sid       = "PermitirListadoEC2Docs"
        Effect    = "Allow"
        Principal = { AWS = var.ec2_role_arn }
        Action    = ["s3:ListBucket"]
        Resource  = aws_s3_bucket.docs.arn
      }
    ]
  })
}

# Lifecycle: eliminar objetos temporales de imágenes (tagueados temporal=true) después de 1 día
resource "aws_s3_bucket_lifecycle_configuration" "docs" {
  bucket = aws_s3_bucket.docs.id

  rule {
    id     = "limpiar-imagenes-temporales"
    status = "Enabled"

    filter {
      and {
        prefix = "vlan-images/"
        tags = {
          temporal = "true"
        }
      }
    }

    expiration {
      days = 1
    }
  }
}
