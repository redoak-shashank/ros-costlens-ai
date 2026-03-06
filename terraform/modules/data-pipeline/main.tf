###############################################################################
# Data Pipeline — CUR → S3 → Glue → Athena
###############################################################################

variable "project_name" { type = string }
variable "environment" { type = string }
variable "aws_region" { type = string }
variable "cur_s3_prefix" { type = string }
variable "cur_retention_months" { type = number }

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  bucket_name = "${local.name_prefix}-cur-${data.aws_caller_identity.current.account_id}"
}

data "aws_caller_identity" "current" {}
