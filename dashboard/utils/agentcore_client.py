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
    def _norm(v):
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    def _safe_get(mapping, key, default=None):
        try:
            return mapping.get(key, default)
        except Exception:
            return default

    try:
        secrets = st.secrets
        aws_secrets = _safe_get(secrets, "aws", {})
        cfg = {
            "aws_access_key_id": _norm(
                _safe_get(aws_secrets, "aws_access_key_id")
                or _safe_get(aws_secrets, "access_key_id")
                or _safe_get(secrets, "aws_access_key_id")
                or _safe_get(secrets, "AWS_ACCESS_KEY_ID")
                or os.environ.get("AWS_ACCESS_KEY_ID")
            ),
            "aws_secret_access_key": _norm(
                _safe_get(aws_secrets, "aws_secret_access_key")
                or _safe_get(aws_secrets, "secret_access_key")
                or _safe_get(secrets, "aws_secret_access_key")
                or _safe_get(secrets, "AWS_SECRET_ACCESS_KEY")
                or os.environ.get("AWS_SECRET_ACCESS_KEY")
            ),
            "aws_session_token": _norm(
                _safe_get(aws_secrets, "aws_session_token")
                or _safe_get(aws_secrets, "session_token")
                or _safe_get(secrets, "aws_session_token")
                or _safe_get(secrets, "AWS_SESSION_TOKEN")
                or os.environ.get("AWS_SESSION_TOKEN")
            ),
            "region_name": _norm(
                _safe_get(aws_secrets, "region")
                or _safe_get(aws_secrets, "aws_region")
                or _safe_get(secrets, "region")
                or _safe_get(secrets, "aws_region")
                or _safe_get(secrets, "AWS_REGION")
                or os.environ.get("AWS_REGION", "us-east-1")
            ),
        }
        return {k: v for k, v in cfg.items() if v is not None}
    except Exception:
        return {"region_name": os.environ.get("AWS_REGION", "us-east-1")}


def _get_agent_function_name() -> str:
    """Get the agent Lambda function name from st.secrets or env vars."""
    try:
        return (
            st.secrets.get("app", {}).get("agent_function_name")
            or st.secrets.get("agent_function_name")
            or st.secrets.get("AGENT_FUNCTION_NAME")
            or os.environ.get("AGENT_FUNCTION_NAME", "agentcore-billing-dev-runtime-invoker")
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
