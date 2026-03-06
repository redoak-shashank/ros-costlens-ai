"""
AgentCore client for the dashboard's "Ask a Question" feature.

Invokes the billing intelligence graph via Lambda for interactive queries.
Reads configuration from st.secrets (Streamlit Community Cloud) with
fallback to environment variables for local dev.
"""

from __future__ import annotations

import json
import os

import boto3
import streamlit as st


def _get_aws_config() -> dict:
    """Get AWS credentials and region from st.secrets or env vars."""
    try:
        aws_secrets = st.secrets.get("aws", {})
        return {
            "aws_access_key_id": aws_secrets.get(
                "aws_access_key_id", os.environ.get("AWS_ACCESS_KEY_ID")
            ),
            "aws_secret_access_key": aws_secrets.get(
                "aws_secret_access_key", os.environ.get("AWS_SECRET_ACCESS_KEY")
            ),
            "region_name": aws_secrets.get(
                "region", os.environ.get("AWS_REGION", "us-east-1")
            ),
        }
    except Exception:
        return {"region_name": os.environ.get("AWS_REGION", "us-east-1")}


def _get_agent_function_name() -> str:
    """Get the agent Lambda function name from st.secrets or env vars."""
    try:
        return st.secrets.get("app", {}).get(
            "agent_function_name",
            os.environ.get("AGENT_FUNCTION_NAME", "agentcore-billing-dev-runtime-invoker"),
        )
    except Exception:
        return os.environ.get("AGENT_FUNCTION_NAME", "agentcore-billing-dev-runtime-invoker")


def ask_billing_question(question: str, thread_id: str = "dashboard") -> str:
    """
    Send a question to the billing intelligence agents.

    Args:
        question: Natural language question about AWS costs.
        thread_id: Conversation thread ID for context.

    Returns:
        Agent's text response.
    """
    client = boto3.client("lambda", **_get_aws_config())

    payload = {
        "action": "slack_message",
        "message": question,
        "thread_id": f"dashboard-{thread_id}",
    }

    try:
        response = client.invoke(
            FunctionName=_get_agent_function_name(),
            InvocationType="RequestResponse",
            Payload=json.dumps(payload),
        )

        result = json.loads(response["Payload"].read().decode("utf-8"))
        return result.get("response", "I wasn't able to process that question.")

    except Exception as e:
        return f"Error connecting to billing agents: {e}"
