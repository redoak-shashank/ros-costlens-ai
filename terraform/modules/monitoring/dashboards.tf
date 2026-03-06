###############################################################################
# CloudWatch Dashboard — System Health Overview
###############################################################################

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${local.name_prefix}-system-health"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "Lambda Invocations (Agent Handlers)"
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", "${local.name_prefix}-slack-handler"],
            ["AWS/Lambda", "Invocations", "FunctionName", "${local.name_prefix}-daily-report-invoker"],
            ["AWS/Lambda", "Invocations", "FunctionName", "${local.name_prefix}-anomaly-check-invoker"],
          ]
          period = 300
          region = "us-east-1"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title   = "Lambda Errors"
          view    = "timeSeries"
          stacked = false
          metrics = [
            ["AWS/Lambda", "Errors", "FunctionName", "${local.name_prefix}-slack-handler"],
            ["AWS/Lambda", "Errors", "FunctionName", "${local.name_prefix}-daily-report-invoker"],
            ["AWS/Lambda", "Errors", "FunctionName", "${local.name_prefix}-anomaly-check-invoker"],
          ]
          period = 300
          region = "us-east-1"
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Lambda Duration (p50 / p99)"
          view   = "timeSeries"
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", "${local.name_prefix}-slack-handler", { stat = "p50" }],
            ["AWS/Lambda", "Duration", "FunctionName", "${local.name_prefix}-slack-handler", { stat = "p99" }],
          ]
          period = 300
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 24
        height = 6
        properties = {
          title  = "DynamoDB Cache — Read/Write Capacity"
          view   = "timeSeries"
          metrics = [
            ["AWS/DynamoDB", "ConsumedReadCapacityUnits", "TableName", "${local.name_prefix}-api-cache"],
            ["AWS/DynamoDB", "ConsumedWriteCapacityUnits", "TableName", "${local.name_prefix}-api-cache"],
          ]
          period = 300
        }
      }
    ]
  })
}
