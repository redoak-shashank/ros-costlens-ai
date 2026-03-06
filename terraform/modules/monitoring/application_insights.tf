###############################################################################
# CloudWatch Application Insights — Optional enhanced observability
###############################################################################

# This is OPTIONAL - provides deeper insights into Runtime performance
# Uncomment to enable if you want advanced monitoring

# resource "aws_applicationinsights_application" "agentcore" {
#   resource_group_name = aws_resourcegroups_group.agentcore.name
#   auto_config_enabled = true
#   auto_create         = true
# }

# resource "aws_resourcegroups_group" "agentcore" {
#   name = "${var.project_name}-${var.environment}-agentcore"
# 
#   resource_query {
#     query = jsonencode({
#       ResourceTypeFilters = ["AWS::BedrockAgentCore::AgentRuntime"]
#       TagFilters = [{
#         Key    = "Project"
#         Values = [var.project_name]
#       }]
#     })
#   }
# }
