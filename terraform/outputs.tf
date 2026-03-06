###############################################################################
# Root Outputs
###############################################################################

# ── Data Pipeline ─────────────────────────────────────────────────────────

output "cur_bucket_name" {
  description = "S3 bucket for CUR data"
  value       = module.data_pipeline.cur_bucket_name
}

output "athena_workgroup" {
  description = "Athena workgroup for CUR queries"
  value       = module.data_pipeline.athena_workgroup_name
}

output "dashboard_data_bucket" {
  description = "S3 bucket for pre-computed dashboard data"
  value       = module.dashboard.data_bucket_name
}

# ── AgentCore ─────────────────────────────────────────────────────────────

output "agentcore_runtime_arn" {
  description = "AgentCore Runtime ARN"
  value       = module.agentcore.runtime_arn
}

output "agentcore_runtime_id" {
  description = "AgentCore Runtime ID"
  value       = module.agentcore.runtime_id
}

output "agentcore_runtime_endpoint_arn" {
  description = "AgentCore Runtime Endpoint ARN (for invocation)"
  value       = module.agentcore.runtime_endpoint_arn
}

output "agentcore_gateway_id" {
  description = "AgentCore Gateway ID (MCP tool registry)"
  value       = module.agentcore.gateway_id
}

output "agentcore_gateway_url" {
  description = "AgentCore Gateway URL (MCP endpoint)"
  value       = module.agentcore.gateway_url
}

output "agent_code_bucket" {
  description = "S3 bucket for agent code packages (deploy here)"
  value       = module.agentcore.agent_code_bucket
}

# ── Slack ──────────────────────────────────────────────────────────────────

output "slack_api_endpoint" {
  description = "API Gateway endpoint for Slack webhook events"
  value       = module.slack_integration.api_endpoint
}

output "slack_secret_arn" {
  description = "Secrets Manager ARN — store bot token here"
  value       = module.agentcore.slack_secret_arn
}

# ── Cache ──────────────────────────────────────────────────────────────────

output "cache_table_name" {
  description = "DynamoDB table for API response caching"
  value       = module.caching.table_name
}
