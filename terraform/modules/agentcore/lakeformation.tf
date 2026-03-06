###############################################################################
# Lake Formation Permissions — Grant agent role access to CUR Glue database
###############################################################################

# Register the CUR S3 bucket as a Lake Formation data location
resource "aws_lakeformation_resource" "cur_bucket" {
  arn = var.cur_bucket_arn
}

# Grant data location permissions for the CUR bucket
resource "aws_lakeformation_permissions" "agent_data_location" {
  principal   = aws_iam_role.agent_role.arn
  permissions = ["DATA_LOCATION_ACCESS"]

  data_location {
    arn = var.cur_bucket_arn
  }
}

# Grant database-level ALL permissions (includes DESCRIBE, ALTER, CREATE_TABLE)
resource "aws_lakeformation_permissions" "agent_database" {
  principal   = aws_iam_role.agent_role.arn
  permissions = ["ALL"]

  database {
    name = var.athena_database
  }
}

# Grant table-level ALL permissions (includes SELECT, INSERT, DELETE, etc.)
resource "aws_lakeformation_permissions" "agent_tables" {
  principal   = aws_iam_role.agent_role.arn
  permissions = ["ALL"]

  table {
    database_name = var.athena_database
    wildcard      = true
  }
}
