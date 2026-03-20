###############################################################################
# Anomaly Check — 3 Times Daily (starting 1 PM UTC, every 8 hours)
###############################################################################

resource "aws_cloudwatch_event_rule" "anomaly_check" {
  name                = "${local.name_prefix}-anomaly-check"
  description         = "Check for cost anomalies three times per day"
  schedule_expression = "cron(0 13,21 * * ? *)"

  tags = { Name = "${local.name_prefix}-anomaly-check" }
}

resource "aws_cloudwatch_event_target" "anomaly_check" {
  rule      = aws_cloudwatch_event_rule.anomaly_check.name
  target_id = "anomaly-check"
  arn       = var.invoker_lambda_arn

  input = jsonencode({
    action      = "scheduled_report"
    report_type = "anomaly_check"
  })
}

resource "aws_lambda_permission" "anomaly_check_eventbridge" {
  statement_id  = "AllowEventBridgeAnomalyCheck"
  action        = "lambda:InvokeFunction"
  function_name = var.invoker_lambda_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.anomaly_check.arn
}
