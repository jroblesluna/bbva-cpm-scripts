aws_region   = "us-west-2"

project_name = "alwaysprint-dev"
environment  = "dev"

vpc_cidr              = "10.0.0.0/16"
public_subnet_cidrs   = ["10.0.1.0/24", "10.0.2.0/24"]
database_subnet_cidrs = ["10.0.21.0/24", "10.0.22.0/24"]
availability_zones    = ["us-west-2a", "us-west-2b"]

ecr_image_tag_limit = 5

db_name                   = "alwaysprint"
db_username               = "alwaysprint_admin"
db_instance_class         = "db.t3.micro"
db_allocated_storage      = 20
db_max_allocated_storage  = 50
rds_deletion_protection   = false
rds_backup_retention_days = 0

zone_name      = "dev.iol.pe"
subdomain      = "alwaysprint"
ses_from_email = "noreply@dev.iol.pe"

backend_port  = 8000
frontend_port = 3000

# Free tier: t3.micro
ec2_instance_type = "t3.micro"

backend_env_vars = {
  LOG_LEVEL                   = "DEBUG"
  SES_ENABLED                 = "true"
  SES_FROM_EMAIL              = "noreply@dev.iol.pe"
  ACCESS_TOKEN_EXPIRE_MINUTES = "1440"
  ALGORITHM                   = "HS256"
  DB_POOL_SIZE                = "5"
  DB_MAX_OVERFLOW             = "3"
  DB_POOL_TIMEOUT             = "30"
  DB_POOL_RECYCLE             = "3600"
  WS_PING_INTERVAL            = "30"
  WS_PING_TIMEOUT             = "60"
  RATE_LIMIT_LOGIN            = "50"
  RATE_LIMIT_API              = "500"
  CACHE_TTL_SECONDS           = "60"
  API_V1_STR                  = "/api/v1"
  S3_ARTIFACTS_BUCKET         = "alwaysprint-dev-dev-artifacts"
}