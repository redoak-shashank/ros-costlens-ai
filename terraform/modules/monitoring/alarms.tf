###############################################################################
# CloudWatch Alarms + AWS Budgets
###############################################################################

# ---------- Lambda Error Alarms ----------

resource "aws_cloudwatch_metric_alarm" "slack_handler_errors" {
  alarm_name          = "${local.name_prefix}-slack-handler-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  alarm_description   = "Slack handler Lambda errors exceeded threshold"

  dimensions = {
    FunctionName = "${local.name_prefix}-slack-handler"
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "daily_report_errors" {
  alarm_name          = "${local.name_prefix}-daily-report-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Daily report Lambda failed"

  dimensions = {
    FunctionName = "${local.name_prefix}-daily-report-invoker"
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}

# ---------- SNS Topic for Alarms ----------

resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-system-alerts"
  tags = { Name = "${local.name_prefix}-system-alerts" }
}

# ---------- AWS Budget (meta: budget for this billing system itself) ----------

resource "aws_budgets_budget" "monthly" {
  name         = "${local.name_prefix}-monthly-budget"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = var.alert_threshold_pct
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_sns_topic_arns  = [aws_sns_topic.alerts.arn]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_sns_topic_arns  = [aws_sns_topic.alerts.arn]
  }
}
