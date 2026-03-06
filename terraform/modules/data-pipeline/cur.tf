###############################################################################
# Cost & Usage Report Definition
###############################################################################

resource "aws_cur_report_definition" "main" {
  report_name                = "${local.name_prefix}-cur"
  time_unit                  = "HOURLY"
  format                     = "Parquet"
  compression                = "Parquet"
  s3_bucket                  = aws_s3_bucket.cur.id
  s3_region                  = var.aws_region
  s3_prefix                  = var.cur_s3_prefix
  additional_schema_elements = ["RESOURCES", "SPLIT_COST_ALLOCATION_DATA"]
  report_versioning          = "OVERWRITE_REPORT"
  refresh_closed_reports     = true

  # CUR reports can only be created in us-east-1
  # If deploying to another region, use a provider alias
}
