###############################################################################
# AgentCore Billing Intelligence — Root Module
#
# Architecture: AgentCore Runtime at the center.
#   • Runtime runs all agent code (LangGraph multi-agent graph)
#   • Gateway provides MCP tools (Cost Explorer, Athena, etc.)
#   • EventBridge triggers scheduled reports via invoker Lambda
#   • API Gateway routes Slack events via invoker Lambda
#   • All business logic lives in the Runtime — no logic in Lambdas
#
# Deploy phases:
#   1 = Core infrastructure (data pipeline, agentcore, scheduling, slack)
#   2 = + Monitoring (CloudWatch alarms, dashboards, Budgets)
###############################################################################

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.70"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

###############################################################################
# Phase 1 — Everything (all serverless, pay-per-use)
###############################################################################

# ── Data Pipeline (CUR → S3 → Glue → Athena) ────────────────────────────

module "data_pipeline" {
  source               = "./modules/data-pipeline"
  project_name         = var.project_name
  environment          = var.environment
  aws_region           = var.aws_region
  cur_s3_prefix        = var.cur_s3_prefix
  cur_retention_months = var.cur_retention_months
}

# ── Dashboard S3 Bucket (pre-computed JSON for Streamlit) ─────────────────

module "dashboard" {
  source       = "./modules/dashboard"
  project_name = var.project_name
  environment  = var.environment
}

# ── API Cache (DynamoDB) ──────────────────────────────────────────────────

module "caching" {
  source       = "./modules/caching"
  project_name = var.project_name
  environment  = var.environment
}

# ── AgentCore (Runtime + Gateway + Memory + Secrets) ─────────────────────

module "agentcore" {
  source           = "./modules/agentcore"
  project_name     = var.project_name
  environment      = var.environment
  aws_region       = var.aws_region
  bedrock_model_id = var.bedrock_model_id

  # Data pipeline
  cur_bucket_arn  = module.data_pipeline.cur_bucket_arn
  cur_bucket_name = module.data_pipeline.cur_bucket_name
  athena_workgroup = module.data_pipeline.athena_workgroup_name
  athena_database  = module.data_pipeline.glue_database_name

  # Cache
  cache_table_name = module.caching.table_name
  cache_table_arn  = module.caching.table_arn

  # Dashboard
  dashboard_bucket_arn  = module.dashboard.data_bucket_arn
  dashboard_bucket_name = module.dashboard.data_bucket_name

  # Slack
  slack_channel_id = var.slack_channel_id

  # Budget
  monthly_budget = var.monthly_budget
}

# ── Scheduling (EventBridge → Invoker Lambda → Runtime) ───────────────────

module "scheduling" {
  source       = "./modules/scheduling"
  project_name = var.project_name
  environment  = var.environment

  invoker_lambda_arn  = module.agentcore.invoker_lambda_arn
  invoker_lambda_name = module.agentcore.invoker_lambda_name
}

# ── Slack Integration (API Gateway → Invoker Lambda → Runtime) ────────────

module "slack_integration" {
  source       = "./modules/slack-integration"
  project_name = var.project_name
  environment  = var.environment

  invoker_lambda_arn        = module.agentcore.invoker_lambda_arn
  invoker_lambda_invoke_arn = module.agentcore.invoker_lambda_invoke_arn
  invoker_lambda_name       = module.agentcore.invoker_lambda_name
}

###############################################################################
# Phase 2 — Monitoring
###############################################################################

module "monitoring" {
  count        = var.deploy_phase >= 2 ? 1 : 0
  source       = "./modules/monitoring"
  project_name = var.project_name
  environment  = var.environment

  agentcore_runtime_arn = module.agentcore.runtime_arn
  monthly_budget        = var.monthly_budget
  alert_threshold_pct   = var.alert_threshold_pct
}
