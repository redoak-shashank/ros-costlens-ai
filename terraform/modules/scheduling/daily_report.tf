###############################################################################
# Daily Cost Report — 2 PM UTC
###############################################################################

resource "aws_cloudwatch_event_rule" "daily_report" {
  name                = "${local.name_prefix}-daily-cost-report"
  description         = "Trigger daily cost report at 2 PM UTC"
  schedule_expression = "cron(0 14 * * ? *)"

  tags = { Name = "${local.name_prefix}-daily-report" }
}

resource "aws_cloudwatch_event_target" "daily_report" {
  rule      = aws_cloudwatch_event_rule.daily_report.name
  target_id = "daily-report"
  arn       = var.invoker_lambda_arn

  input = jsonencode({
    action      = "scheduled_report"
    report_type = "daily"
  })
}

resource "aws_lambda_permission" "daily_report_eventbridge" {
  statement_id  = "AllowEventBridgeDailyReport"
  action        = "lambda:InvokeFunction"
  function_name = var.invoker_lambda_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_report.arn
}
