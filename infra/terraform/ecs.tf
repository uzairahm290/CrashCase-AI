resource "aws_ecs_cluster" "main" {
  name = var.name
  setting {
    name  = "containerInsights"
    value = "disabled" # enable for per-task metrics; it costs extra
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
}

# Private DNS so the worker and API find Redis at redis.crashcase.local
resource "aws_service_discovery_private_dns_namespace" "main" {
  name = "${var.name}.local"
  vpc  = aws_vpc.main.id
}

resource "aws_service_discovery_service" "redis" {
  name = "redis"
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id
    dns_records {
      ttl  = 10
      type = "A"
    }
  }
}

resource "aws_cloudwatch_log_group" "svc" {
  for_each          = toset(["api", "worker", "web", "redis"])
  name              = "/ecs/${var.name}/${each.key}"
  retention_in_days = var.log_retention_days
}

locals {
  api_image = "${aws_ecr_repository.repo["api"].repository_url}:${var.image_tag}"
  web_image = "${aws_ecr_repository.repo["web"].repository_url}:${var.image_tag}"

  app_env = [
    { name = "CC_REDIS_URL", value = "redis://redis.${var.name}.local:6379/0" },
    { name = "CC_INDEX_BACKEND", value = "pgvector" },
    { name = "CC_STORAGE_BACKEND", value = "s3" },
    { name = "CC_S3_BUCKET", value = aws_s3_bucket.data.bucket },
    { name = "CC_DETECTOR_BACKEND", value = var.detector_backend },
    { name = "CC_AUTO_SEED", value = "false" },
    { name = "CC_CORS_ORIGINS", value = "http://${aws_lb.main.dns_name}" },
  ]
  app_secrets = [
    { name = "CC_DATABASE_URL", valueFrom = aws_ssm_parameter.database_url.arn },
    { name = "CC_LLM_API_KEY", valueFrom = aws_ssm_parameter.llm_api_key.arn },
  ]

  logs = { for k, g in aws_cloudwatch_log_group.svc : k => {
    logDriver = "awslogs"
    options = {
      "awslogs-group"         = g.name
      "awslogs-region"        = var.region
      "awslogs-stream-prefix" = k
    }
  } }
}

# --- Task definitions -----------------------------------------------------------------

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name             = "api"
    image            = local.api_image
    essential        = true
    portMappings     = [{ containerPort = 8000 }]
    environment      = local.app_env
    secrets          = local.app_secrets
    logConfiguration = local.logs["api"]
    command          = ["uvicorn", "crashcase.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
  }])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  container_definitions = jsonencode([{
    name             = "worker"
    image            = local.api_image
    essential        = true
    portMappings     = [{ containerPort = 9100 }]
    environment      = local.app_env
    secrets          = local.app_secrets
    logConfiguration = local.logs["worker"]
    command          = ["celery", "-A", "crashcase.worker.tasks", "worker", "--pool=threads", "--concurrency=2", "--loglevel=info"]
  }])
}

resource "aws_ecs_task_definition" "web" {
  family                   = "${var.name}-web"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  container_definitions = jsonencode([{
    name         = "web"
    image        = local.web_image
    essential    = true
    portMappings = [{ containerPort = 3000 }]
    environment = [
      # Through the ALB's API listener, so canary weights apply to real user traffic.
      { name = "API_URL", value = "http://${aws_lb.main.dns_name}:8080" },
      { name = "API_DOCS_URL", value = var.admin_cidr == "" ? "" : "http://${aws_lb.main.dns_name}:8080/docs" },
    ]
    logConfiguration = local.logs["web"]
  }])
}

resource "aws_ecs_task_definition" "redis" {
  family                   = "${var.name}-redis"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  container_definitions = jsonencode([{
    name             = "redis"
    image            = "public.ecr.aws/docker/library/redis:7-alpine"
    essential        = true
    portMappings     = [{ containerPort = 6379 }]
    logConfiguration = local.logs["redis"]
  }])
}

# --- Services ---------------------------------------------------------------------------

locals {
  network = {
    subnets          = aws_subnet.public[*].id
    assign_public_ip = true
  }
}

resource "aws_ecs_service" "redis" {
  name            = "redis"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.redis.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = local.network.subnets
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = true
  }
  service_registries {
    registry_arn = aws_service_discovery_service.redis.arn
  }
}

resource "aws_ecs_service" "api" {
  for_each        = toset(["stable", "canary"])
  name            = "api-${each.key}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = each.key == "stable" ? 1 : 0
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = local.network.subnets
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = true
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api[each.key].arn
    container_name   = "api"
    container_port   = 8000
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  health_check_grace_period_seconds = 30

  # Image versions and counts are managed by the deploy pipeline and autoscaling.
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }
  depends_on = [aws_lb_listener.api]
}

resource "aws_ecs_service" "worker" {
  name            = "worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1

  # Workers are retry-safe (acks_late), so Spot capacity is fine and ~70% cheaper.
  capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 1
  }
  network_configuration {
    subnets          = local.network.subnets
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = true
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }
}

resource "aws_ecs_service" "web" {
  name            = "web"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.web.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = local.network.subnets
    security_groups  = [aws_security_group.web.id]
    assign_public_ip = true
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 3000
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }
  depends_on = [aws_lb_listener.web]
}
