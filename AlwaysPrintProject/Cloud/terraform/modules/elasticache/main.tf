locals {
  prefix = "${var.project_name}-${var.environment}"
}

resource "aws_elasticache_subnet_group" "main" {
  name       = "${local.prefix}-redis-subnet-group"
  subnet_ids = var.subnet_ids

  tags = { Name = "${local.prefix}-redis-subnet-group" }
}

resource "aws_elasticache_parameter_group" "redis7" {
  name   = "${local.prefix}-redis7"
  family = "redis7"

  tags = { Name = "${local.prefix}-redis-params" }
}

resource "aws_elasticache_cluster" "main" {
  cluster_id           = "${local.prefix}-redis"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.node_type
  num_cache_nodes      = 1
  parameter_group_name = aws_elasticache_parameter_group.redis7.name
  subnet_group_name    = aws_elasticache_subnet_group.main.name
  security_group_ids   = [var.security_group_id]
  port                 = 6379

  tags = { Name = "${local.prefix}-redis" }
}
