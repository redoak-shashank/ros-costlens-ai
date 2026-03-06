###############################################################################
# AgentCore Memory — Managed short-term + long-term memory
###############################################################################
#
# Replaces the custom DynamoDB checkpointer tables with AWS-managed
# AgentCore Memory. Provides:
#   - Short-term: turn-by-turn events within a session
#   - Long-term: auto-extracted insights via memory strategies
#     (summarization, semantic search, user preferences)
#
# Docs: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html

# ── IAM Role for Memory ──────────────────────────────────────────────────────

resource "aws_iam_role" "memory_role" {
  name = "${local.name_prefix}-memory-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "bedrock-agentcore.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${local.name_prefix}-memory-role" }
}

resource "aws_iam_role_policy" "memory_policy" {
  name = "${local.name_prefix}-memory-policy"
  role = aws_iam_role.memory_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = ["*"]
      }
    ]
  })
}

# ── AgentCore Memory Resource ────────────────────────────────────────────────

resource "aws_bedrockagentcore_memory" "billing" {
  name                      = replace("${local.name_prefix}_billing_memory", "-", "_")
  description               = "Memory for billing intelligence agent conversations"
  memory_execution_role_arn = aws_iam_role.memory_role.arn

  # Keep events for 30 days (value is in DAYS, range: 7–365)
  event_expiry_duration = 30

  tags = { Name = "${local.name_prefix}-billing-memory" }

  timeouts {
    create = "10m"
    delete = "10m"
  }
}

# ── Memory Strategy: Summarization ──────────────────────────────────────────
#
# Automatically summarizes conversations for long-term retention.
# Non-CUSTOM strategies use built-in defaults (no configuration block).
# Valid types: SEMANTIC, SUMMARIZATION, USER_PREFERENCE, CUSTOM, EPISODIC

resource "aws_bedrockagentcore_memory_strategy" "summarization" {
  memory_id                 = aws_bedrockagentcore_memory.billing.id
  name                      = replace("${local.name_prefix}_summarization", "-", "_")
  description               = "Summarize billing conversations for long-term context"
  type                      = "SUMMARIZATION"
  memory_execution_role_arn = aws_iam_role.memory_role.arn
  namespaces                = ["billing/{sessionId}"]

  timeouts {
    create = "10m"
    update = "10m"
    delete = "10m"
  }
}

# ── Memory Strategy: User Preferences ────────────────────────────────────────
#
# Extracts user preferences (e.g., preferred reporting format, focus areas)
# from conversations for personalized responses.

resource "aws_bedrockagentcore_memory_strategy" "user_preferences" {
  memory_id                 = aws_bedrockagentcore_memory.billing.id
  name                      = replace("${local.name_prefix}_user_prefs", "-", "_")
  description               = "Extract user preferences from billing conversations"
  type                      = "USER_PREFERENCE"
  memory_execution_role_arn = aws_iam_role.memory_role.arn
  namespaces                = ["billing"]

  timeouts {
    create = "10m"
    update = "10m"
    delete = "10m"
  }
}

# ── IAM policy for agent to access Memory ────────────────────────────────────

resource "aws_iam_role_policy" "agent_memory" {
  name = "${local.name_prefix}-agent-memory"
  role = aws_iam_role.agent_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "bedrock-agentcore:CreateEvent",
        "bedrock-agentcore:GetEvent",
        "bedrock-agentcore:ListEvents",
        "bedrock-agentcore:DeleteEvent",
        "bedrock-agentcore:GetMemoryRecord",
        "bedrock-agentcore:ListMemoryRecords",
        "bedrock-agentcore:RetrieveMemoryRecords",
        "bedrock-agentcore:DeleteMemoryRecord",
        "bedrock-agentcore:ListSessions"
      ]
      Resource = [
        aws_bedrockagentcore_memory.billing.arn,
        "${aws_bedrockagentcore_memory.billing.arn}/*"
      ]
    }]
  })
}

# ── Outputs ──────────────────────────────────────────────────────────────────

output "memory_id" {
  description = "AgentCore Memory ID"
  value       = aws_bedrockagentcore_memory.billing.id
}

output "memory_arn" {
  description = "AgentCore Memory ARN"
  value       = aws_bedrockagentcore_memory.billing.arn
}
