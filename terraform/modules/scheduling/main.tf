###############################################################################
# Scheduling — EventBridge Rules → AgentCore Runtime
#
# No Lambdas in this module. EventBridge rules invoke the thin invoker
# Lambda (from the agentcore module) which forwards to the Runtime.
###############################################################################

variable "project_name" { type = string }
variable "environment" { type = string }

# ARN + name of the invoker Lambda in the agentcore module
variable "invoker_lambda_arn" { type = string }
variable "invoker_lambda_name" { type = string }

locals {
  name_prefix = "${var.project_name}-${var.environment}"
}
