###############################################################################
# Terraform State
#
# Using local state for initial development. Migrate to S3 backend when
# the project is ready for team collaboration / CI-CD.
#
# To migrate later, uncomment the s3 block below and run:
#   terraform init -migrate-state
###############################################################################

# terraform {
#   backend "s3" {
#     bucket         = "agentcore-billing-tfstate"
#     key            = "terraform.tfstate"
#     region         = "us-east-1"
#     encrypt        = true
#     dynamodb_table = "agentcore-billing-tflock"
#   }
# }
