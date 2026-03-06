###############################################################################
# Caching — DynamoDB Table for API Response Caching
###############################################################################

variable "project_name" { type = string }
variable "environment" { type = string }

locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

resource "aws_dynamodb_table" "cache" {
  name         = "${local.name_prefix}-api-cache"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "cache_key"

  attribute {
    name = "cache_key"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = { Name = "${local.name_prefix}-api-cache" }
}

# ---------- Outputs ----------

output "table_name" {
  value = aws_dynamodb_table.cache.name
}

output "table_arn" {
  value = aws_dynamodb_table.cache.arn
}
