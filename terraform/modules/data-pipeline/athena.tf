###############################################################################
# Athena — Workgroup + Named Queries for CUR Analysis
###############################################################################

resource "aws_athena_workgroup" "cur" {
  name = "${local.name_prefix}-cur"

  configuration {
    enforce_workgroup_configuration = true
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.athena_results.id}/results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }

    engine_version {
      selected_engine_version = "Athena engine version 3"
    }
  }
}

# ---------- Named Queries (reusable by agents) ----------

resource "aws_athena_named_query" "daily_spend_by_service" {
  name      = "daily-spend-by-service"
  workgroup = aws_athena_workgroup.cur.name
  database  = aws_glue_catalog_database.cur.name

  query = <<-SQL
    SELECT
      line_item_usage_start_date AS usage_date,
      line_item_product_code AS service,
      SUM(line_item_unblended_cost) AS cost
    FROM ${aws_glue_catalog_database.cur.name}.cur
    WHERE line_item_usage_start_date >= date_add('day', -30, current_date)
    GROUP BY 1, 2
    ORDER BY 1 DESC, 3 DESC
  SQL
}

resource "aws_athena_named_query" "cost_by_tag" {
  name      = "cost-by-tag"
  workgroup = aws_athena_workgroup.cur.name
  database  = aws_glue_catalog_database.cur.name

  query = <<-SQL
    SELECT
      resource_tags_user_team AS team,
      resource_tags_user_project AS project,
      resource_tags_user_environment AS environment,
      line_item_product_code AS service,
      SUM(line_item_unblended_cost) AS cost
    FROM ${aws_glue_catalog_database.cur.name}.cur
    WHERE line_item_usage_start_date >= date_add('day', -30, current_date)
    GROUP BY 1, 2, 3, 4
    ORDER BY 5 DESC
  SQL
}

resource "aws_athena_named_query" "top_resources_by_cost" {
  name      = "top-resources-by-cost"
  workgroup = aws_athena_workgroup.cur.name
  database  = aws_glue_catalog_database.cur.name

  query = <<-SQL
    SELECT
      line_item_resource_id AS resource_id,
      line_item_product_code AS service,
      product_region AS region,
      SUM(line_item_unblended_cost) AS cost
    FROM ${aws_glue_catalog_database.cur.name}.cur
    WHERE line_item_usage_start_date >= date_add('day', -7, current_date)
      AND line_item_resource_id != ''
    GROUP BY 1, 2, 3
    ORDER BY 4 DESC
    LIMIT 50
  SQL
}

# ---------- Outputs ----------

output "athena_workgroup_name" {
  value = aws_athena_workgroup.cur.name
}

output "glue_database_name" {
  value = aws_glue_catalog_database.cur.name
}

output "cur_bucket_arn" {
  value = aws_s3_bucket.cur.arn
}

output "cur_bucket_name" {
  value = aws_s3_bucket.cur.id
}
