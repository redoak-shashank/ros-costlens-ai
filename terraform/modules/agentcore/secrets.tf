###############################################################################
# Secrets Manager — Slack Bot Tokens
#
# Lives in agentcore module because the Runtime is the primary consumer.
# This avoids circular dependencies between agentcore ↔ slack-integration.
###############################################################################

resource "aws_secretsmanager_secret" "slack" {
  name        = "${local.name_prefix}/slack-bot-tokens"
  description = "Slack bot OAuth token and signing secret for BillingBot"

  tags = { Name = "${local.name_prefix}-slack-secrets" }
}

# The actual secret value must be set manually after deployment:
#
#   aws secretsmanager put-secret-value \
#     --secret-id agentcore-billing-dev/slack-bot-tokens \
#     --secret-string '{"bot_token":"xoxb-...","signing_secret":"..."}'

output "slack_secret_arn" {
  value = aws_secretsmanager_secret.slack.arn
}
