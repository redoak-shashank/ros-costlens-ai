###############################################################################
# Global Variables
###############################################################################

variable "deploy_phase" {
  description = <<-EOT
    Controls monitoring deployment:
      1 = Full system (data pipeline, agentcore runtime, scheduling, slack)
      2 = + Monitoring (CloudWatch alarms, dashboards, Budgets)
  EOT
  type    = number
  default = 1

  validation {
    condition     = var.deploy_phase >= 1 && var.deploy_phase <= 2
    error_message = "deploy_phase must be 1 or 2."
  }
}

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name used for resource naming and tagging"
  type        = string
  default     = "agentcore-billing"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

# ---------- Budget ----------

variable "monthly_budget" {
  description = "Monthly AWS spend budget in USD"
  type        = number
  default     = 1000
}

variable "alert_threshold_pct" {
  description = "Budget alert threshold percentage"
  type        = number
  default     = 80
}

# ---------- Slack ----------

variable "slack_channel_id" {
  description = "Slack channel ID for cost reports"
  type        = string
  default     = ""
}

# ---------- CUR ----------

variable "cur_s3_prefix" {
  description = "S3 prefix for CUR report files"
  type        = string
  default     = "cur-reports"
}

variable "cur_retention_months" {
  description = "Number of months to retain CUR data"
  type        = number
  default     = 13
}

# ---------- Bedrock ----------

variable "bedrock_model_id" {
  description = "Bedrock model ID for agent LLM calls"
  type        = string
  default     = "anthropic.claude-sonnet-4-5-20250929-v1:0"
}
