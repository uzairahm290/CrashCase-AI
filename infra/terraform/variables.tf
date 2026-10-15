variable "region" {
  description = "AWS region. ap-south-1 (Mumbai) is the closest to Pakistan."
  type        = string
  default     = "ap-south-1"
}

variable "name" {
  description = "Prefix for every resource."
  type        = string
  default     = "crashcase"
}

variable "image_tag" {
  description = "Image tag to start with. Later deploys come from GitHub Actions, not Terraform."
  type        = string
  default     = "latest"
}

variable "github_repo" {
  description = "owner/repo allowed to deploy through GitHub OIDC."
  type        = string
  default     = "uzairahm290/crashcase-ai"
}

variable "admin_cidr" {
  description = "CIDR allowed to reach the API docs and metrics on port 8080 directly. Empty = web tier only."
  type        = string
  default     = ""
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "api_cpu" {
  type    = number
  default = 512
}

variable "api_memory" {
  type    = number
  default = 1024
}

variable "worker_cpu" {
  description = "Raise to 2048 when running real YOLO/CLIP models on CPU."
  type        = number
  default     = 1024
}

variable "worker_memory" {
  type    = number
  default = 2048
}

variable "api_max_tasks" {
  type    = number
  default = 4
}

variable "worker_max_tasks" {
  type    = number
  default = 3
}

variable "llm_api_key" {
  description = "Groq API key for written reports. Empty = template reports."
  type        = string
  default     = ""
  sensitive   = true
}

variable "detector_backend" {
  description = "stub until trained weights are in S3, then yolo."
  type        = string
  default     = "stub"
}

variable "log_retention_days" {
  type    = number
  default = 14
}
