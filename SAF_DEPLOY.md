## SAF Account Isolation (No Slack Changes)

This setup keeps your code unchanged and isolates deployment to the SAF AWS account
using profile-scoped credentials and account-specific config files.

### 1) Configure AWS profile

Create/verify profile `saf`:

```bash
aws configure --profile saf
AWS_PROFILE=saf aws sts get-caller-identity
```

### 2) Create SAF Terraform vars

```bash
cd terraform
cp terraform.saf.tfvars.example terraform.saf.tfvars
```

Edit `terraform.saf.tfvars` values for region/environment/model/budget.
Slack can remain empty for now.

### 3) Plan/apply using SAF profile

Create backend bucket once (S3-only state):

```bash
AWS_PROFILE=saf aws s3api create-bucket \
  --bucket agentcore-billing-saf-tfstate \
  --region us-east-1
```

Initialize backend and migrate local state:

```bash
cd terraform
AWS_PROFILE=saf terraform init -reconfigure -backend-config=backend.saf.hcl -migrate-state
AWS_PROFILE=saf terraform plan -var-file=terraform.saf.tfvars
AWS_PROFILE=saf terraform apply -var-file=terraform.saf.tfvars
```

If the bucket already exists, the create command can be skipped.

### 4) Optional local agent env template

If you run/test agents locally:

```bash
cp agents/env.saf.example agents/.env
```

Fill values (Athena workgroup/database, buckets, cache table, memory ID) from
Terraform outputs in the SAF account.

### 5) Run deployment script with SAF profile

```bash
AWS_PROFILE_NAME=saf \
TF_BACKEND_CONFIG=backend.saf.hcl \
TF_VARS_FILE=terraform.saf.tfvars \
bash run.txt
```

`run.txt` defaults (current account) are:
- `TF_BACKEND_CONFIG=backend.default.hcl`
- `TF_VARS_FILE=terraform.tfvars`
