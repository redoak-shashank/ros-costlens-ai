###############################################################################
# Slack Integration — API Gateway → AgentCore Runtime
#
# No Lambda in this module. API Gateway routes Slack webhook events to the
# invoker Lambda (from the agentcore module) which forwards to the Runtime.
# Secrets Manager is now in the agentcore module.
###############################################################################

variable "project_name" { type = string }
variable "environment" { type = string }

# ARN + name of the invoker Lambda in the agentcore module
variable "invoker_lambda_arn" { type = string }
variable "invoker_lambda_invoke_arn" { type = string }
variable "invoker_lambda_name" { type = string }

locals {
  name_prefix = "${var.project_name}-${var.environment}"
}
