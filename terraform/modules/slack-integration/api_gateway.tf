###############################################################################
# API Gateway — Slack Events Endpoint → Invoker Lambda → Runtime
###############################################################################

resource "aws_apigatewayv2_api" "slack" {
  name          = "${local.name_prefix}-slack-events"
  protocol_type = "HTTP"
  description   = "HTTP API for Slack event subscriptions → AgentCore Runtime"

  cors_configuration {
    allow_origins = ["https://slack.com"]
    allow_methods = ["POST"]
    allow_headers = ["Content-Type", "X-Slack-Signature", "X-Slack-Request-Timestamp"]
  }
}

resource "aws_apigatewayv2_stage" "slack" {
  api_id      = aws_apigatewayv2_api.slack.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gw.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      requestTime    = "$context.requestTime"
      httpMethod     = "$context.httpMethod"
      path           = "$context.path"
      status         = "$context.status"
      responseLength = "$context.responseLength"
    })
  }
}

resource "aws_cloudwatch_log_group" "api_gw" {
  name              = "/aws/apigateway/${local.name_prefix}-slack-events"
  retention_in_days = 14
}

resource "aws_apigatewayv2_integration" "slack_runtime" {
  api_id                 = aws_apigatewayv2_api.slack.id
  integration_type       = "AWS_PROXY"
  integration_uri        = var.invoker_lambda_invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "slack_events" {
  api_id    = aws_apigatewayv2_api.slack.id
  route_key = "POST /slack/events"
  target    = "integrations/${aws_apigatewayv2_integration.slack_runtime.id}"
}

resource "aws_lambda_permission" "api_gw" {
  statement_id  = "AllowAPIGatewaySlack"
  action        = "lambda:InvokeFunction"
  function_name = var.invoker_lambda_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.slack.execution_arn}/*/*"
}

# ---------- Output ----------

output "api_endpoint" {
  value = "${aws_apigatewayv2_api.slack.api_endpoint}/slack/events"
}
