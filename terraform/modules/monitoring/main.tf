###############################################################################
# Monitoring — CloudWatch Dashboards + Alarms + AWS Budgets
###############################################################################

variable "project_name" { type = string }
variable "environment" { type = string }
variable "agentcore_runtime_arn" { type = string }
variable "monthly_budget" { type = number }
variable "alert_threshold_pct" { type = number }

locals {
  name_prefix = "${var.project_name}-${var.environment}"
}
