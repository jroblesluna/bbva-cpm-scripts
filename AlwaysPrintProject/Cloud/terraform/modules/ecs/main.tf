locals {
  prefix = "${var.project_name}-${var.environment}"

  backend_env_merged = merge(var.backend_env_vars, {
    CORS_ORIGINS = var.public_url
    API_V1_STR   = "/api/v1"
  })

  frontend_env_merged = merge(var.frontend_env_vars, {
    NEXT_PUBLIC_API_URL = var.public_url
    NEXT_PUBLIC_WS_URL  = replace(var.public_url, "https://", "wss://")
  })

  backend_secrets_base = [
    {
      name      = "DATABASE_URL"
      valueFrom = var.database_url_secret_arn
    },
    {
      name      = "SECRET_KEY"
      valueFrom = var.secret_key_arn
    }
  ]

  backend_secrets = var.enable_redis ? concat(local.backend_secrets_base, [{
    name      = "REDIS_URL"
    valueFrom = var.redis_url_secret_arn
  }]) : local.backend_secrets_base
}

# -------------------------------------------------------------------
# ECS Cluster
# -------------------------------------------------------------------
resource "aws_ecs_cluster" "main" {
  name = "${local.prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = { Name = "${local.prefix}-cluster" }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

# -------------------------------------------------------------------
# CloudWatch Log Groups
# -------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${local.prefix}/backend"
  retention_in_days = 30

  tags = { Name = "${local.prefix}-logs-backend" }
}

resource "aws_cloudwatch_log_group" "frontend" {
  name              = "/ecs/${local.prefix}/frontend"
  retention_in_days = 30

  tags = { Name = "${local.prefix}-logs-frontend" }
}

# -------------------------------------------------------------------
# IAM - Task Execution Role (para ECR pull + Secrets Manager)
# -------------------------------------------------------------------
resource "aws_iam_role" "task_execution" {
  name = "${local.prefix}-ecs-task-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${local.prefix}-ecs-task-execution" }
}

resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "task_execution_secrets" {
  name = "${local.prefix}-ecs-secrets-access"
  role = aws_iam_role.task_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = "arn:aws:secretsmanager:${var.aws_region}:${var.aws_account_id}:secret:/${var.project_name}/${var.environment}/*"
    }]
  })
}

# -------------------------------------------------------------------
# IAM - Task Role (permisos del proceso en runtime)
# -------------------------------------------------------------------
resource "aws_iam_role" "task" {
  name = "${local.prefix}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${local.prefix}-ecs-task" }
}

resource "aws_iam_role_policy" "task_cloudwatch" {
  name = "${local.prefix}-ecs-task-cloudwatch"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ]
      Resource = "*"
    }]
  })
}

# -------------------------------------------------------------------
# Task Definition: Backend (FastAPI)
# -------------------------------------------------------------------
resource "aws_ecs_task_definition" "backend" {
  family                   = "${local.prefix}-backend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.backend_cpu
  memory                   = var.backend_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name      = "backend"
    image     = "${var.backend_ecr_url}:latest"
    essential = true

    portMappings = [{
      containerPort = var.backend_port
      protocol      = "tcp"
    }]

    # Ejecuta migraciones antes de iniciar el servidor
    command = [
      "sh", "-c",
      "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${var.backend_port} --workers 2"
    ]

    environment = [
      for k, v in local.backend_env_merged : { name = k, value = v }
    ]

    secrets = local.backend_secrets

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.backend.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "backend"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:${var.backend_port}/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
  }])

  tags = { Name = "${local.prefix}-task-backend" }
}

# -------------------------------------------------------------------
# Task Definition: Frontend (Next.js)
# -------------------------------------------------------------------
resource "aws_ecs_task_definition" "frontend" {
  family                   = "${local.prefix}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.frontend_cpu
  memory                   = var.frontend_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name      = "frontend"
    image     = "${var.frontend_ecr_url}:latest"
    essential = true

    portMappings = [{
      containerPort = var.frontend_port
      protocol      = "tcp"
    }]

    environment = [
      for k, v in local.frontend_env_merged : { name = k, value = v }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.frontend.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "frontend"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:${var.frontend_port}/ || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 30
    }
  }])

  tags = { Name = "${local.prefix}-task-frontend" }
}

# -------------------------------------------------------------------
# ECS Services
# -------------------------------------------------------------------
resource "aws_ecs_service" "backend" {
  name            = "${local.prefix}-backend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = var.backend_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.backend_sg_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.backend_target_group_arn
    container_name   = "backend"
    container_port   = var.backend_port
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # Ignora cambios en la imagen para que CodePipeline pueda actualizarla
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  tags = { Name = "${local.prefix}-svc-backend" }
}

resource "aws_ecs_service" "frontend" {
  name            = "${local.prefix}-frontend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = var.frontend_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.frontend_sg_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.frontend_target_group_arn
    container_name   = "frontend"
    container_port   = var.frontend_port
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  tags = { Name = "${local.prefix}-svc-frontend" }
}
