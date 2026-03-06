###############################################################################
# Lake Formation Permissions — Grant Glue crawler role access to create tables
###############################################################################

# Note: S3 bucket registration is done in the agentcore module to avoid duplication

# Grant data location permissions for the CUR bucket
resource "aws_lakeformation_permissions" "glue_crawler_data_location" {
  principal   = aws_iam_role.glue_crawler.arn
  permissions = ["DATA_LOCATION_ACCESS"]

  data_location {
    arn = aws_s3_bucket.cur.arn
  }

  depends_on = [
    aws_glue_catalog_database.cur
  ]
}

# Grant database-level ALL permissions for crawler
resource "aws_lakeformation_permissions" "glue_crawler_database" {
  principal   = aws_iam_role.glue_crawler.arn
  permissions = ["ALL"]

  database {
    name = aws_glue_catalog_database.cur.name
  }
}

# Grant table-level ALL permissions for crawler
resource "aws_lakeformation_permissions" "glue_crawler_tables" {
  principal   = aws_iam_role.glue_crawler.arn
  permissions = ["ALL"]

  table {
    database_name = aws_glue_catalog_database.cur.name
    wildcard      = true
  }
}
