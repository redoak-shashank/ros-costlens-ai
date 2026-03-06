###############################################################################
# AgentCore Runtime — Managed Agent Execution
#
# The Runtime is the single execution environment for all billing agents.
# It runs the LangGraph multi-agent graph (supervisor → specialists).
#
# Invoked by:
#   • EventBridge (scheduled reports)  → via invoker Lambda
#   • API Gateway  (Slack events)      → via invoker Lambda
#
# Uses tools via:
#   • AgentCore Gateway (MCP protocol) → cost_tools Lambda target
###############################################################################

# ── S3: Agent Code Bucket ─────────────────────────────────────────────────

resource "aws_s3_bucket" "agent_code" {
  bucket        = "${local.name_prefix}-agent-code-${data.aws_caller_identity.current.account_id}"
  force_destroy = var.environment != "prod"

  tags = { Name = "${local.name_prefix}-agent-code" }
}

resource "aws_s3_object" "agent_code_package" {
  bucket = aws_s3_bucket.agent_code.id
  key    = "agent-code/billing-agents.zip"
  source = "${path.module}/placeholder.zip"
  etag   = filemd5("${path.module}/placeholder.zip")
}

# ── IAM: Agent Execution Role ─────────────────────────────────────────────
#
# Shared by the Runtime, the cost_tools Lambda, and the invoker Lambda.

resource "aws_iam_role" "agent_role" {
  name = "${local.name_prefix}-agent-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = [
            "bedrock.amazonaws.com",
            "bedrock-agentcore.amazonaws.com",
            "lambda.amazonaws.com"
          ]
        }
      }
    ]
  })
}

# Bedrock model invocation
resource "aws_iam_role_policy" "agent_bedrock" {
  name = "${local.name_prefix}-agent-bedrock"
  role = aws_iam_role.agent_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ]
      Resource = [
        "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.bedrock_model_id}",
        "arn:aws:bedrock:*::foundation-model/*"
      ]
    }]
  })
}

# Cost Explorer
resource "aws_iam_role_policy" "agent_cost_explorer" {
  name = "${local.name_prefix}-agent-ce"
  role = aws_iam_role.agent_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ce:GetCostAndUsage",
        "ce:GetCostForecast",
        "ce:GetAnomalies",
        "ce:GetAnomalyMonitors",
        "ce:GetReservationUtilization",
        "ce:GetSavingsPlansCoverage",
        "ce:GetSavingsPlansUtilization",
        "ce:GetDimensionValues",
        "ce:GetTags"
      ]
      Resource = "*"
    }]
  })
}

# Athena + Glue
resource "aws_iam_role_policy" "agent_athena" {
  name = "${local.name_prefix}-agent-athena"
  role = aws_iam_role.agent_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "athena:StartQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:StopQueryExecution",
          "athena:GetNamedQuery",
          "athena:ListNamedQueries"
        ]
        Resource = "arn:aws:athena:${var.aws_region}:${data.aws_caller_identity.current.account_id}:workgroup/${var.athena_workgroup}"
      },
      {
        Effect = "Allow"
        Action = [
          "glue:GetTable",
          "glue:GetTables",
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:GetPartitions"
        ]
        Resource = [
          "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:catalog",
          "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:database/${var.athena_database}",
          "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.athena_database}/*"
        ]
      }
      ,
      {
        Effect = "Allow"
        Action = [
          "lakeformation:GetDataAccess"
        ]
        Resource = "*"
      }
    ]
  })
}

# S3 (CUR read + Athena results + dashboard data write)
resource "aws_iam_role_policy" "agent_s3" {
  name = "${local.name_prefix}-agent-s3"
  role = aws_iam_role.agent_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket", "s3:GetBucketLocation"]
        Resource = [var.cur_bucket_arn, "${var.cur_bucket_arn}/*"]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation"]
        Resource = ["*"] # Athena results — tighten in production
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = ["${var.dashboard_bucket_arn}/*"]
      }
    ]
  })
}

# DynamoDB cache
resource "aws_iam_role_policy" "agent_dynamodb" {
  name = "${local.name_prefix}-agent-dynamodb"
  role = aws_iam_role.agent_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:Query",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem"
      ]
      Resource = var.cache_table_arn
    }]
  })
}

# CloudWatch + EC2 + Trusted Advisor + Compute Optimizer
resource "aws_iam_role_policy" "agent_optimizer" {
  name = "${local.name_prefix}-agent-optimizer"
  role = aws_iam_role.agent_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["cloudwatch:GetMetricData", "cloudwatch:GetMetricStatistics", "cloudwatch:ListMetrics"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ec2:DescribeInstances", "ec2:DescribeRegions"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "support:DescribeTrustedAdvisorChecks",
          "support:DescribeTrustedAdvisorCheckResult",
          "support:DescribeTrustedAdvisorCheckSummaries",
          "support:DescribeTrustedAdvisorCheckRefreshStatuses",
          "support:RefreshTrustedAdvisorCheck"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "compute-optimizer:GetEC2InstanceRecommendations",
          "compute-optimizer:GetAutoScalingGroupRecommendations",
          "compute-optimizer:GetEBSVolumeRecommendations"
        ]
        Resource = "*"
      }
    ]
  })
}

# Secrets Manager (Slack token)
resource "aws_iam_role_policy" "agent_secrets" {
  name = "${local.name_prefix}-agent-secrets"
  role = aws_iam_role.agent_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = aws_secretsmanager_secret.slack.arn
    }]
  })
}

# AgentCore Runtime invocation (for the invoker Lambda)
resource "aws_iam_role_policy" "agent_invoke_runtime" {
  name = "${local.name_prefix}-agent-invoke-runtime"
  role = aws_iam_role.agent_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:InvokeAgentRuntime"
        ]
        Resource = [
          "arn:aws:bedrock-agentcore:${var.aws_region}:${data.aws_caller_identity.current.account_id}:runtime/*"
        ]
      },
      {
        Sid    = "LambdaSelfInvoke"
        Effect = "Allow"
        Action = "lambda:InvokeFunction"
        Resource = aws_lambda_function.runtime_invoker.arn
      }
    ]
  })
}

# CloudWatch Logs
resource "aws_iam_role_policy_attachment" "agent_logs" {
  role       = aws_iam_role.agent_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# X-Ray and CloudWatch for AgentCore Observability (Sessions & Traces)
resource "aws_iam_role_policy" "observability" {
  name = "${local.name_prefix}-observability"
  role = aws_iam_role.agent_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords",
          "cloudwatch:PutMetricData"
        ]
        Resource = "*"
      }
    ]
  })
}

# ── AgentCore Runtime ──────────────────────────────────────────────────────

resource "aws_bedrockagentcore_agent_runtime" "billing" {
  agent_runtime_name = replace("${local.name_prefix}_billing_runtime", "-", "_")
  description        = "Billing intelligence multi-agent system (LangGraph)"
  role_arn           = aws_iam_role.agent_role.arn

  environment_variables = {
    BEDROCK_MODEL_ID  = var.bedrock_model_id
    ATHENA_WORKGROUP  = var.athena_workgroup
    ATHENA_DATABASE   = var.athena_database
    CUR_BUCKET        = var.cur_bucket_name
    DATA_BUCKET       = var.dashboard_bucket_name
    CACHE_TABLE       = var.cache_table_name
    MEMORY_ID         = aws_bedrockagentcore_memory.billing.id
    SLACK_SECRET_ARN  = aws_secretsmanager_secret.slack.arn
    SLACK_CHANNEL_ID  = var.slack_channel_id
    MONTHLY_BUDGET    = tostring(var.monthly_budget)
    GATEWAY_URL       = aws_bedrockagentcore_gateway.billing.gateway_url
    LOG_LEVEL         = var.environment == "prod" ? "WARNING" : "INFO"
  }

  agent_runtime_artifact {
    code_configuration {
      runtime     = "PYTHON_3_12"
      entry_point = ["app.py"]

      code {
        s3 {
          bucket = aws_s3_bucket.agent_code.bucket
          prefix = aws_s3_object.agent_code_package.key
        }
      }
    }
  }

  network_configuration {
    network_mode = "PUBLIC"
  }

  protocol_configuration {
    server_protocol = "HTTP"
  }

  # lifecycle {
  #   ignore_changes = [
  #     # Code is deployed externally via CI/CD
  #     agent_runtime_artifact,
  #   ]
  # }

  tags = { Name = "${local.name_prefix}-billing-runtime" }

  timeouts {
    create = "10m"
    update = "10m"
    delete = "10m"
  }

  depends_on = [aws_s3_object.agent_code_package]
}

# ── Runtime Endpoint ──────────────────────────────────────────────────────

resource "aws_bedrockagentcore_agent_runtime_endpoint" "billing" {
  agent_runtime_id = aws_bedrockagentcore_agent_runtime.billing.agent_runtime_id
  name             = replace("${local.name_prefix}_billing_endpoint", "-", "_")
  description      = "Invocable endpoint for the billing intelligence runtime"

  tags = { Name = "${local.name_prefix}-billing-endpoint" }

  timeouts {
    create = "10m"
    delete = "10m"
  }
}

# ── Invoker Lambda (thin bridge) ──────────────────────────────────────────
#
# A minimal Lambda that forwards events from EventBridge / API Gateway
# to the AgentCore Runtime. Contains ZERO business logic — all agent code,
# Slack verification, report generation etc. runs inside the Runtime.

resource "aws_lambda_function" "runtime_invoker" {
  function_name = "${local.name_prefix}-runtime-invoker"
  role          = aws_iam_role.agent_role.arn
  runtime       = "python3.12"
  handler       = "invoker.handler"
  timeout       = 900
  memory_size   = 256

  filename         = "${path.module}/invoker.zip"
  source_code_hash = filebase64sha256("${path.module}/invoker.zip")

  environment {
    variables = {
      RUNTIME_ARN       = aws_bedrockagentcore_agent_runtime.billing.agent_runtime_arn
      RUNTIME_QUALIFIER = aws_bedrockagentcore_agent_runtime_endpoint.billing.name
      INVOKER_FUNCTION_NAME = "${local.name_prefix}-runtime-invoker"
    }
  }

  tags = { Name = "${local.name_prefix}-runtime-invoker" }
}

# ── Outputs ───────────────────────────────────────────────────────────────

output "runtime_arn" {
  description = "AgentCore Runtime ARN"
  value       = aws_bedrockagentcore_agent_runtime.billing.agent_runtime_arn
}

output "runtime_id" {
  description = "AgentCore Runtime ID"
  value       = aws_bedrockagentcore_agent_runtime.billing.agent_runtime_id
}

output "runtime_endpoint_arn" {
  description = "AgentCore Runtime Endpoint ARN"
  value       = aws_bedrockagentcore_agent_runtime_endpoint.billing.agent_runtime_endpoint_arn
}

output "invoker_lambda_arn" {
  description = "ARN of the thin invoker Lambda (bridge for EventBridge/API GW)"
  value       = aws_lambda_function.runtime_invoker.arn
}

output "invoker_lambda_invoke_arn" {
  description = "Invoke ARN for API Gateway integration"
  value       = aws_lambda_function.runtime_invoker.invoke_arn
}

output "invoker_lambda_name" {
  description = "Name of the thin invoker Lambda"
  value       = aws_lambda_function.runtime_invoker.function_name
}

output "agent_role_arn" {
  value = aws_iam_role.agent_role.arn
}

output "agent_code_bucket" {
  description = "S3 bucket for agent code packages"
  value       = aws_s3_bucket.agent_code.bucket
}
