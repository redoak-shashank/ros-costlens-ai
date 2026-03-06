###############################################################################
# AgentCore Gateway — MCP Tool Registry
#
# Provides a unified, secure entry point for agents to discover and invoke
# tools (Cost Explorer, Athena, CloudWatch, etc.) via the Model Context
# Protocol (MCP).
#
# Ref: https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagentcore_gateway
###############################################################################

# ---------- IAM role for the Gateway ----------

resource "aws_iam_role" "gateway_role" {
  name = "${local.name_prefix}-gateway-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "bedrock-agentcore.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = { Name = "${local.name_prefix}-gateway-role" }
}

# Allow the gateway to invoke Lambda-based tool targets
resource "aws_iam_role_policy" "gateway_lambda_invoke" {
  name = "${local.name_prefix}-gateway-lambda-invoke"
  role = aws_iam_role.gateway_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.cost_tools.arn
    }]
  })
}

# ---------- Gateway ----------

resource "aws_bedrockagentcore_gateway" "billing" {
  name            = "${local.name_prefix}-billing-gateway"
  description     = "MCP tool gateway for billing intelligence agents"
  protocol_type   = "MCP"
  authorizer_type = "NONE"
  role_arn        = aws_iam_role.gateway_role.arn

  protocol_configuration {
    mcp {
      instructions = "This gateway exposes AWS billing and cost optimisation tools. Use them to query costs, detect anomalies, and surface savings."
      search_type  = "SEMANTIC"
    }
  }

  tags = { Name = "${local.name_prefix}-billing-gateway" }

  timeouts {
    create = "10m"
    delete = "10m"
  }
}

# ---------- Gateway Target: Cost Tools Lambda ----------

resource "aws_lambda_function" "cost_tools" {
  function_name = "${local.name_prefix}-cost-tools"
  role          = aws_iam_role.agent_role.arn
  runtime       = "python3.12"
  handler       = "tools_handler.handler"
  timeout       = 300
  memory_size   = 512

  filename         = "${path.module}/placeholder.zip"
  source_code_hash = filebase64sha256("${path.module}/placeholder.zip")

  environment {
    variables = {
      ATHENA_WORKGROUP = var.athena_workgroup
      ATHENA_DATABASE  = var.athena_database
      CUR_BUCKET       = var.cur_bucket_name
      CACHE_TABLE      = var.cache_table_name
      AWS_REGION_NAME  = var.aws_region
    }
  }

  tags = { Name = "${local.name_prefix}-cost-tools" }
}

resource "aws_bedrockagentcore_gateway_target" "cost_tools" {
  gateway_identifier = aws_bedrockagentcore_gateway.billing.gateway_id
  name               = "${local.name_prefix}-cost-tools-target"
  description        = "Lambda target exposing billing cost tools via MCP"

  target_configuration {
    mcp {
      lambda {
        lambda_arn = aws_lambda_function.cost_tools.arn

        tool_schema {
          inline_payload {
            name        = "get_cost_and_usage"
            description = "Retrieve AWS cost and usage data for a date range, optionally grouped by service, account, or tag."

            input_schema {
              type = "object"

              property {
                name        = "start_date"
                type        = "string"
                description = "Start date in YYYY-MM-DD format"
                required    = true
              }

              property {
                name        = "end_date"
                type        = "string"
                description = "End date in YYYY-MM-DD format"
                required    = true
              }

              property {
                name        = "granularity"
                type        = "string"
                description = "DAILY or MONTHLY"
                required    = false
              }

              property {
                name        = "group_by"
                type        = "string"
                description = "Dimension to group by: SERVICE, LINKED_ACCOUNT, or a tag key"
                required    = false
              }
            }
          }

          inline_payload {
            name        = "get_cost_forecast"
            description = "Generate a cost forecast for a future date range using AWS Cost Explorer."

            input_schema {
              type = "object"

              property {
                name        = "start_date"
                type        = "string"
                description = "Forecast start date in YYYY-MM-DD format"
                required    = true
              }

              property {
                name        = "end_date"
                type        = "string"
                description = "Forecast end date in YYYY-MM-DD format"
                required    = true
              }
            }
          }

          inline_payload {
            name        = "get_cost_anomalies"
            description = "Retrieve detected cost anomalies from AWS Cost Explorer."

            input_schema {
              type = "object"

              property {
                name        = "lookback_days"
                type        = "number"
                description = "Number of days to look back for anomalies (default 30)"
                required    = false
              }
            }
          }

          inline_payload {
            name        = "run_athena_query"
            description = "Execute a SQL query against the CUR data in Athena and return results."

            input_schema {
              type = "object"

              property {
                name        = "query"
                type        = "string"
                description = "SQL query to execute against the CUR Athena database"
                required    = true
              }
            }
          }

          inline_payload {
            name        = "get_optimization_recommendations"
            description = "Retrieve cost optimisation recommendations from Trusted Advisor and Compute Optimizer."

            input_schema {
              type = "object"

              property {
                name        = "include_trusted_advisor"
                type        = "boolean"
                description = "Whether to include Trusted Advisor checks"
                required    = false
              }

              property {
                name        = "include_compute_optimizer"
                type        = "boolean"
                description = "Whether to include EC2/EBS right-sizing recommendations"
                required    = false
              }
            }
          }
        }
      }
    }
  }

  # Use the gateway IAM role for credential-less invocation
  credential_provider_configuration {
    gateway_iam_role {}
  }

  timeouts {
    create = "5m"
    delete = "5m"
  }
}

# ---------- Outputs ----------

output "gateway_id" {
  value = aws_bedrockagentcore_gateway.billing.gateway_id
}

output "gateway_url" {
  value = aws_bedrockagentcore_gateway.billing.gateway_url
}
