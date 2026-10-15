output "app_url" {
  description = "Open this in a browser."
  value       = "http://${aws_lb.main.dns_name}"
}

output "api_url" {
  value = "http://${aws_lb.main.dns_name}:8080"
}

output "ecr_api" {
  value = aws_ecr_repository.repo["api"].repository_url
}

output "ecr_web" {
  value = aws_ecr_repository.repo["web"].repository_url
}

output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "github_deploy_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN secret in GitHub."
  value       = aws_iam_role.github_deploy.arn
}

output "cluster" {
  value = aws_ecs_cluster.main.name
}

output "api_listener_arn" {
  value = aws_lb_listener.api.arn
}

output "api_target_groups" {
  value = { for k, tg in aws_lb_target_group.api : k => tg.arn }
}

output "network" {
  description = "For one-off tasks (seeding): subnets and security group."
  value = {
    subnets        = aws_subnet.public[*].id
    security_group = aws_security_group.app.id
  }
}
