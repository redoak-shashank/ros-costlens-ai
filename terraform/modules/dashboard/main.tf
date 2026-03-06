###############################################################################
# Dashboard — S3 Data Bucket
#
# The Streamlit dashboard is deployed on Streamlit Community Cloud (free)
# directly from the GitHub repo. No ECS/ALB/VPC needed.
#
# This module only provisions the S3 bucket where the agent reporter
# writes pre-computed dashboard JSON data.
###############################################################################

variable "project_name" { type = string }
variable "environment" { type = string }

locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

data "aws_caller_identity" "current" {}

# ---------- S3 Data Bucket (pre-computed dashboard data) ----------

resource "aws_s3_bucket" "dashboard_data" {
  bucket        = "${local.name_prefix}-dashboard-data-${data.aws_caller_identity.current.account_id}"
  force_destroy = var.environment != "prod"

  tags = { Name = "${local.name_prefix}-dashboard-data" }
}

# ---------- Outputs ----------

output "data_bucket_arn" {
  value = aws_s3_bucket.dashboard_data.arn
}

output "data_bucket_name" {
  value = aws_s3_bucket.dashboard_data.id
}
