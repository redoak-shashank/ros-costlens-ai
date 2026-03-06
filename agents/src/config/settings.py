"""
Application settings loaded from environment variables.

All configuration is read from environment variables set by Terraform
(via Lambda env vars or ECS task environment).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    """Application settings."""

    # AWS
    aws_region: str = field(default_factory=lambda: os.environ.get("AWS_REGION", "us-east-1"))

    # Bedrock
    bedrock_model_id: str = field(
        default_factory=lambda: os.environ.get(
            "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0"
        )
    )

    # Athena
    athena_workgroup: str = field(
        default_factory=lambda: os.environ.get("ATHENA_WORKGROUP", "agentcore-billing-dev-cur")
    )
    athena_database: str = field(
        default_factory=lambda: os.environ.get("ATHENA_DATABASE", "agentcore_billing_dev_cur_db")
    )

    # S3
    cur_bucket: str = field(
        default_factory=lambda: os.environ.get("CUR_BUCKET", "")
    )
    dashboard_data_bucket: str = field(
        default_factory=lambda: os.environ.get("DATA_BUCKET", "")
    )

    # DynamoDB
    cache_table_name: str = field(
        default_factory=lambda: os.environ.get("CACHE_TABLE", "")
    )

    # AgentCore Memory
    memory_id: str = field(
        default_factory=lambda: os.environ.get("MEMORY_ID", "")
    )

    # Slack
    slack_secret_arn: str = field(
        default_factory=lambda: os.environ.get("SLACK_SECRET_ARN", "")
    )
    slack_channel_id: str = field(
        default_factory=lambda: os.environ.get("SLACK_CHANNEL_ID", "")
    )

    # Budget
    monthly_budget: float = field(
        default_factory=lambda: float(os.environ.get("MONTHLY_BUDGET", "42000"))
    )

    # Logging
    log_level: str = field(
        default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO")
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()


def reset_settings():
    """Clear cached settings (useful for testing)."""
    get_settings.cache_clear()
