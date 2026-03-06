###############################################################################
# Weekly Deep Dive — Sundays at 9 AM UTC
###############################################################################

resource "aws_cloudwatch_event_rule" "weekly_digest" {
  name                = "${local.name_prefix}-weekly-digest"
  description         = "Weekly deep-dive cost report on Sundays"
  schedule_expression = "cron(0 9 ? * SUN *)"

  tags = { Name = "${local.name_prefix}-weekly-digest" }
}

resource "aws_cloudwatch_event_target" "weekly_digest" {
  rule      = aws_cloudwatch_event_rule.weekly_digest.name
  target_id = "weekly-digest"
  arn       = var.invoker_lambda_arn

  input = jsonencode({
    action      = "scheduled_report"
    report_type = "weekly"
  })
}

resource "aws_lambda_permission" "weekly_digest_eventbridge" {
  statement_id  = "AllowEventBridgeWeeklyDigest"
  action        = "lambda:InvokeFunction"
  function_name = var.invoker_lambda_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.weekly_digest.arn
}
