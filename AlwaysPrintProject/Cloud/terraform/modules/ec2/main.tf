locals {
  prefix       = "${var.project_name}-${var.environment}"
  ecr_registry = "${var.aws_account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
  public_url   = "https://${var.domain_name}"
  ws_url       = "wss://${var.domain_name}"

  backend_env = merge(var.backend_env_vars, {
    CORS_ORIGINS = local.public_url
    API_V1_STR   = "/api/v1"
    REDIS_URL    = "redis://redis:6379/0"
    AWS_REGION   = var.aws_region
    FRONTEND_URL = local.public_url
  })
}

data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "state"
    values = ["available"]
  }
}

# IAM role para el EC2
resource "aws_iam_role" "ec2" {
  name = "${local.prefix}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "ses" {
  role       = aws_iam_role.ec2.name
  policy_arn = var.ses_send_policy_arn
}

resource "aws_iam_role_policy" "ec2_permissions" {
  name = "${local.prefix}-ec2-policy"
  role = aws_iam_role.ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability", "ecr:DescribeRegistry"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:/${var.project_name}/${var.environment}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion"]
        Resource = "arn:aws:s3:::${var.project_name}-${var.environment}-artifacts/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:ListBucketVersions"]
        Resource = "arn:aws:s3:::${var.project_name}-${var.environment}-artifacts"
      }
    ]
  })
}

# ============================================================================
# Política IAM para AWS Bedrock - Análisis de logs con Claude
# ============================================================================
# IMPORTANTE: El acceso al modelo debe habilitarse manualmente en:
#   AWS Console → Amazon Bedrock → Model access → Request model access
#   Seleccionar: Anthropic → Claude 3.5 Sonnet
#   Región: us-west-2
#
# Sin este paso manual, las invocaciones al modelo fallarán con AccessDeniedException
# incluso teniendo la política IAM correcta.
# ============================================================================
resource "aws_iam_role_policy" "bedrock_invoke_model" {
  name = "${local.prefix}-bedrock-invoke-model"
  role = aws_iam_role.ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowBedrockInvokeModel"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = [
          "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-sonnet*",
          "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-opus*",
          "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-haiku*",
          "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-3*"
        ]
      },
      {
        Sid    = "AllowBedrockListModels"
        Effect = "Allow"
        Action = [
          "bedrock:ListFoundationModels",
          "bedrock:GetFoundationModel"
        ]
        Resource = ["*"]
      }
    ]
  })
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${local.prefix}-ec2-profile"
  role = aws_iam_role.ec2.name
}

# Elastic IP (estática, no cambia aunque el EC2 se reinicie)
resource "aws_eip" "main" {
  domain = "vpc"
  tags   = { Name = "${local.prefix}-eip" }
}

resource "aws_eip_association" "main" {
  instance_id   = aws_instance.main.id
  allocation_id = aws_eip.main.id
}

# EC2 Instance (acceso exclusivo via SSM, sin SSH key pair)
resource "aws_instance" "main" {
  ami                    = data.aws_ami.amazon_linux_2023.id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [var.security_group_id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true
  }

  user_data_replace_on_change = false

  user_data = base64encode(templatefile("${path.module}/user_data.sh.tpl", {
    aws_region          = var.aws_region
    ecr_registry        = local.ecr_registry
    backend_ecr_url     = var.backend_ecr_url
    frontend_ecr_url    = var.frontend_ecr_url
    backend_port        = var.backend_port
    frontend_port       = var.frontend_port
    domain_name         = var.domain_name
    db_host             = var.db_host
    db_port             = var.db_port
    db_name             = var.db_name
    db_username         = var.db_username
    database_url_secret = var.database_url_secret_arn
    secret_key_secret   = var.secret_key_arn
    backend_env_vars    = join("\n", [for k, v in local.backend_env : "${k}=${v}"])
    public_url          = local.public_url
    ws_url              = local.ws_url
  }))

  tags = { Name = "${local.prefix}-ec2" }

  lifecycle {
    ignore_changes = [ami, user_data]
  }
}
