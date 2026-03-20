###############################################################################
# Terraform State
#
# Backend values are supplied at init time via:
#   terraform init -backend-config=<file>
#
# This makes account switching easy without editing this file.
# Use backend config files like:
# - backend.default.hcl
# - backend.saf.hcl
###############################################################################

terraform {
  backend "s3" {}
}
