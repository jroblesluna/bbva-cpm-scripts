locals {
  prefix    = "${var.project_name}-${var.environment}"
  ecr_registry = "${var.aws_account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
}

# -------------------------------------------------------------------
# S3 Bucket para artefactos de CodePipeline
# -------------------------------------------------------------------
resource "aws_s3_bucket" "artifacts" {
  bucket        = var.artifact_bucket_name
  force_destroy = true

  tags = { Name = var.artifact_bucket_name }
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# -------------------------------------------------------------------
# Conexión GitHub vía CodeStar (se aprueba manualmente 1 vez)
# -------------------------------------------------------------------
resource "aws_codestarconnections_connection" "github" {
  name          = "${local.prefix}-github"
  provider_type = "GitHub"

  tags = { Name = "${local.prefix}-github-connection" }
}

# -------------------------------------------------------------------
# IAM - Role para CodeBuild
# -------------------------------------------------------------------
resource "aws_iam_role" "codebuild" {
  name = "${local.prefix}-codebuild"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codebuild.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${local.prefix}-codebuild-role" }
}

resource "aws_iam_role_policy" "codebuild" {
  name = "${local.prefix}-codebuild-policy"
  role = aws_iam_role.codebuild.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:BatchCheckLayerAvailability",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:GetAuthorizationToken"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:GetObjectVersion"]
        Resource = "${aws_s3_bucket.artifacts.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetBucketAcl", "s3:GetBucketLocation"]
        Resource = aws_s3_bucket.artifacts.arn
      }
    ]
  })
}

# -------------------------------------------------------------------
# IAM - Role para CodePipeline
# -------------------------------------------------------------------
resource "aws_iam_role" "codepipeline" {
  name = "${local.prefix}-codepipeline"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codepipeline.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${local.prefix}-codepipeline-role" }
}

resource "aws_iam_role_policy" "codepipeline" {
  name = "${local.prefix}-codepipeline-policy"
  role = aws_iam_role.codepipeline.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:GetObjectVersion", "s3:GetBucketVersioning"]
        Resource = ["${aws_s3_bucket.artifacts.arn}", "${aws_s3_bucket.artifacts.arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["codebuild:BatchGetBuilds", "codebuild:StartBuild"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["codestar-connections:UseConnection"]
        Resource = aws_codestarconnections_connection.github.arn
      },
      {
        Effect = "Allow"
        Action = [
          "ecs:DescribeServices",
          "ecs:DescribeTaskDefinition",
          "ecs:DescribeTasks",
          "ecs:ListTasks",
          "ecs:RegisterTaskDefinition",
          "ecs:UpdateService"
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = "*"
        Condition = {
          StringEqualsIfExists = {
            "iam:PassedToService" = ["ecs-tasks.amazonaws.com"]
          }
        }
      }
    ]
  })
}

# -------------------------------------------------------------------
# CodeBuild: Backend
# -------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "codebuild_backend" {
  name              = "/codebuild/${local.prefix}-backend"
  retention_in_days = 14
}

resource "aws_codebuild_project" "backend" {
  name          = "${local.prefix}-build-backend"
  description   = "Build y push de imagen Docker del backend"
  build_timeout = 20
  service_role  = aws_iam_role.codebuild.arn

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/standard:7.0"
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = true

    environment_variable {
      name  = "ECR_REGISTRY"
      value = local.ecr_registry
    }
    environment_variable {
      name  = "ECR_REPOSITORY"
      value = var.backend_ecr_repository_name
    }
    environment_variable {
      name  = "AWS_DEFAULT_REGION"
      value = var.aws_region
    }
    environment_variable {
      name  = "BACKEND_SOURCE_PATH"
      value = var.backend_source_path
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.codebuild_backend.name
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = <<-BUILDSPEC
      version: 0.2
      phases:
        pre_build:
          commands:
            - echo Logging in to Amazon ECR...
            - aws ecr get-login-password --region $AWS_DEFAULT_REGION | docker login --username AWS --password-stdin $ECR_REGISTRY
            - IMAGE_TAG=$(echo $CODEBUILD_RESOLVED_SOURCE_VERSION | cut -c1-8)
        build:
          commands:
            - echo Building backend image...
            - cd $BACKEND_SOURCE_PATH
            - docker build -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG .
            - docker tag $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG $ECR_REGISTRY/$ECR_REPOSITORY:latest
        post_build:
          commands:
            - echo Pushing backend image...
            - docker push $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG
            - docker push $ECR_REGISTRY/$ECR_REPOSITORY:latest
            - printf '[{"name":"backend","imageUri":"%s:%s"}]' $ECR_REGISTRY/$ECR_REPOSITORY $IMAGE_TAG > $CODEBUILD_SRC_DIR/imagedefinitions.json
      artifacts:
        files:
          - imagedefinitions.json
    BUILDSPEC
  }

  tags = { Name = "${local.prefix}-codebuild-backend" }
}

# -------------------------------------------------------------------
# CodeBuild: Frontend
# -------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "codebuild_frontend" {
  name              = "/codebuild/${local.prefix}-frontend"
  retention_in_days = 14
}

resource "aws_codebuild_project" "frontend" {
  name          = "${local.prefix}-build-frontend"
  description   = "Build y push de imagen Docker del frontend"
  build_timeout = 20
  service_role  = aws_iam_role.codebuild.arn

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/standard:7.0"
    type                        = "LINUX_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = true

    environment_variable {
      name  = "ECR_REGISTRY"
      value = local.ecr_registry
    }
    environment_variable {
      name  = "ECR_REPOSITORY"
      value = var.frontend_ecr_repository_name
    }
    environment_variable {
      name  = "AWS_DEFAULT_REGION"
      value = var.aws_region
    }
    environment_variable {
      name  = "FRONTEND_SOURCE_PATH"
      value = var.frontend_source_path
    }
    environment_variable {
      name  = "NEXT_PUBLIC_API_URL"
      value = var.public_url
    }
    environment_variable {
      name  = "NEXT_PUBLIC_WS_URL"
      value = replace(var.public_url, "https://", "wss://")
    }
    dynamic "environment_variable" {
      for_each = var.frontend_env_vars
      content {
        name  = environment_variable.key
        value = environment_variable.value
      }
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.codebuild_frontend.name
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = <<-BUILDSPEC
      version: 0.2
      phases:
        pre_build:
          commands:
            - echo Logging in to Amazon ECR...
            - aws ecr get-login-password --region $AWS_DEFAULT_REGION | docker login --username AWS --password-stdin $ECR_REGISTRY
            - IMAGE_TAG=$(echo $CODEBUILD_RESOLVED_SOURCE_VERSION | cut -c1-8)
        build:
          commands:
            - echo Building frontend image...
            - cd $FRONTEND_SOURCE_PATH
            - |
              docker build \
                --build-arg NEXT_PUBLIC_API_URL="$NEXT_PUBLIC_API_URL" \
                --build-arg NEXT_PUBLIC_WS_URL="$NEXT_PUBLIC_WS_URL" \
                --build-arg NEXT_PUBLIC_APP_NAME="$NEXT_PUBLIC_APP_NAME" \
                -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG .
            - docker tag $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG $ECR_REGISTRY/$ECR_REPOSITORY:latest
        post_build:
          commands:
            - echo Pushing frontend image...
            - docker push $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG
            - docker push $ECR_REGISTRY/$ECR_REPOSITORY:latest
            - printf '[{"name":"frontend","imageUri":"%s:%s"}]' $ECR_REGISTRY/$ECR_REPOSITORY $IMAGE_TAG > $CODEBUILD_SRC_DIR/imagedefinitions.json
      artifacts:
        files:
          - imagedefinitions.json
    BUILDSPEC
  }

  tags = { Name = "${local.prefix}-codebuild-frontend" }
}

# -------------------------------------------------------------------
# CodePipeline V2: Backend
# (se dispara solo cuando hay cambios en backend_source_path/**)
# -------------------------------------------------------------------
resource "aws_codepipeline" "backend" {
  name          = "${local.prefix}-pipeline-backend"
  role_arn      = aws_iam_role.codepipeline.arn
  pipeline_type = "V2"

  trigger {
    provider_type = "CodeStarSourceConnection"
    git_configuration {
      source_action_name = "Source"
      push {
        branches {
          includes = [var.github_branch]
        }
        file_paths {
          includes = ["${var.backend_source_path}/**"]
        }
      }
    }
  }

  artifact_store {
    location = aws_s3_bucket.artifacts.bucket
    type     = "S3"
  }

  stage {
    name = "Source"
    action {
      name             = "Source"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      output_artifacts = ["source_output"]

      configuration = {
        ConnectionArn    = aws_codestarconnections_connection.github.arn
        FullRepositoryId = "${var.github_owner}/${var.github_repo}"
        BranchName       = var.github_branch
        DetectChanges    = "true"
      }
    }
  }

  stage {
    name = "Build"
    action {
      name             = "Build"
      category         = "Build"
      owner            = "AWS"
      provider         = "CodeBuild"
      version          = "1"
      input_artifacts  = ["source_output"]
      output_artifacts = ["build_output"]

      configuration = {
        ProjectName = aws_codebuild_project.backend.name
      }
    }
  }

  stage {
    name = "Deploy"
    action {
      name            = "Deploy"
      category        = "Deploy"
      owner           = "AWS"
      provider        = "ECS"
      version         = "1"
      input_artifacts = ["build_output"]

      configuration = {
        ClusterName = var.ecs_cluster_name
        ServiceName = var.backend_service_name
        FileName    = "imagedefinitions.json"
      }
    }
  }

  tags = { Name = "${local.prefix}-pipeline-backend" }
}

# -------------------------------------------------------------------
# CodePipeline V2: Frontend
# -------------------------------------------------------------------
resource "aws_codepipeline" "frontend" {
  name          = "${local.prefix}-pipeline-frontend"
  role_arn      = aws_iam_role.codepipeline.arn
  pipeline_type = "V2"

  trigger {
    provider_type = "CodeStarSourceConnection"
    git_configuration {
      source_action_name = "Source"
      push {
        branches {
          includes = [var.github_branch]
        }
        file_paths {
          includes = ["${var.frontend_source_path}/**"]
        }
      }
    }
  }

  artifact_store {
    location = aws_s3_bucket.artifacts.bucket
    type     = "S3"
  }

  stage {
    name = "Source"
    action {
      name             = "Source"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      output_artifacts = ["source_output"]

      configuration = {
        ConnectionArn    = aws_codestarconnections_connection.github.arn
        FullRepositoryId = "${var.github_owner}/${var.github_repo}"
        BranchName       = var.github_branch
        DetectChanges    = "true"
      }
    }
  }

  stage {
    name = "Build"
    action {
      name             = "Build"
      category         = "Build"
      owner            = "AWS"
      provider         = "CodeBuild"
      version          = "1"
      input_artifacts  = ["source_output"]
      output_artifacts = ["build_output"]

      configuration = {
        ProjectName = aws_codebuild_project.frontend.name
      }
    }
  }

  stage {
    name = "Deploy"
    action {
      name            = "Deploy"
      category        = "Deploy"
      owner           = "AWS"
      provider        = "ECS"
      version         = "1"
      input_artifacts = ["build_output"]

      configuration = {
        ClusterName = var.ecs_cluster_name
        ServiceName = var.frontend_service_name
        FileName    = "imagedefinitions.json"
      }
    }
  }

  tags = { Name = "${local.prefix}-pipeline-frontend" }
}
