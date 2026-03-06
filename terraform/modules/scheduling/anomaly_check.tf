###############################################################################
# Anomaly Check — Every 4 Hours
###############################################################################

resource "aws_cloudwatch_event_rule" "anomaly_check" {
  name                = "${local.name_prefix}-anomaly-check"
  description         = "Check for cost anomalies every 4 hours"
  schedule_expression = "rate(4 hours)"

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
