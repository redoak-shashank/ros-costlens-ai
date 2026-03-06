###############################################################################
# AgentCore — Runtime, Gateway, Memory, Secrets
#
# Central module: the AgentCore Runtime runs all agent code.
# EventBridge and API Gateway invoke it via the invoker Lambda (thin bridge).
# The Gateway provides MCP tools (Cost Explorer, Athena, etc.) to agents.
###############################################################################

# ---------- Input Variables ----------

variable "project_name" { type = string }
variable "environment" { type = string }
variable "aws_region" { type = string }
variable "bedrock_model_id" { type = string }

# Data pipeline references
variable "cur_bucket_arn" { type = string }
variable "cur_bucket_name" { type = string }
variable "athena_workgroup" { type = string }
variable "athena_database" { type = string }

# DynamoDB cache
variable "cache_table_name" { type = string }
variable "cache_table_arn" { type = string }

# Dashboard
variable "dashboard_bucket_arn" { type = string }
variable "dashboard_bucket_name" { type = string }

# Slack
variable "slack_channel_id" {
  type    = string
  default = ""
}

# Budget
variable "monthly_budget" {
  type    = number
  default = 1000
}

# ---------- Locals & Data ----------

locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
