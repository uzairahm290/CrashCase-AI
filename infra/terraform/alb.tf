resource "aws_lb" "main" {
  name               = var.name
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
  idle_timeout       = 120 # multi-photo uploads
}

resource "aws_lb_target_group" "web" {
  name        = "${var.name}-web"
  port        = 3000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check {
    path    = "/"
    matcher = "200"
  }
  deregistration_delay = 15
}

# Two target groups for the API: "stable" serves the current version, "canary" the new one.
# The deploy workflow shifts listener weights between them (see scripts/deploy/canary.sh).
resource "aws_lb_target_group" "api" {
  for_each    = toset(["stable", "canary"])
  name        = "${var.name}-api-${each.key}"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
  deregistration_delay = 15
}

resource "aws_lb_listener" "web" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_lb_listener" "api" {
  load_balancer_arn = aws_lb.main.arn
  port              = 8080
  protocol          = "HTTP"
  default_action {
    type = "forward"
    forward {
      target_group {
        arn    = aws_lb_target_group.api["stable"].arn
        weight = 100
      }
      target_group {
        arn    = aws_lb_target_group.api["canary"].arn
        weight = 0
      }
    }
  }
  # Weights are owned by the deploy pipeline after the first apply.
  lifecycle {
    ignore_changes = [default_action]
  }
}
