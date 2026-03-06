###############################################################################
# Glue — Catalog + Crawler for CUR Data
###############################################################################

resource "aws_glue_catalog_database" "cur" {
  name = replace("${local.name_prefix}-cur-db", "-", "_")
}

resource "aws_iam_role" "glue_crawler" {
  name = "${local.name_prefix}-glue-crawler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "glue.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue_crawler.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_s3_access" {
  name = "${local.name_prefix}-glue-s3-access"
  role = aws_iam_role.glue_crawler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:ListBucket"
      ]
      Resource = [
        aws_s3_bucket.cur.arn,
        "${aws_s3_bucket.cur.arn}/*"
      ]
    }]
  })
}

resource "aws_glue_crawler" "cur" {
  name          = "${local.name_prefix}-cur-crawler"
  database_name = aws_glue_catalog_database.cur.name
  role          = aws_iam_role.glue_crawler.arn
  schedule      = "cron(0 1 * * ? *)" # Run daily at 1 AM UTC

  s3_target {
    path = "s3://${aws_s3_bucket.cur.id}/${var.cur_s3_prefix}/"
  }

  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }

  configuration = jsonencode({
    Version = 1.0
    Grouping = {
      TableGroupingPolicy = "CombineCompatibleSchemas"
    }
    CrawlerOutput = {
      Partitions = {
        AddOrUpdateBehavior = "InheritFromTable"
      }
    }
  })
}
