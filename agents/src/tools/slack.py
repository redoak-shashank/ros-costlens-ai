"""
Slack messaging tool.

Handles sending messages to Slack channels and threads.
Retrieves bot tokens from AWS Secrets Manager.
"""

from __future__ import annotations

import json
import logging

import boto3
from botocore.exceptions import ClientError

from ..config.settings import get_settings

logger = logging.getLogger(__name__)

_slack_token: str | None = None


def _get_slack_token() -> str | None:
    """Retrieve the Slack bot token from Secrets Manager.
    
    Returns None (instead of raising) if the secret is missing or empty,
    so callers can gracefully skip Slack delivery.
    """
    global _slack_token
    if _slack_token:
        return _slack_token

    settings = get_settings()
    if not settings.slack_secret_arn:
        logger.warning("SLACK_SECRET_ARN not configured — Slack disabled")
        return None

    client = boto3.client("secretsmanager", region_name=settings.aws_region)

    try:
        response = client.get_secret_value(SecretId=settings.slack_secret_arn)
        secret = json.loads(response["SecretString"])
        _slack_token = secret.get("bot_token")
        if not _slack_token:
            logger.warning("Slack secret exists but 'bot_token' key is empty")
            return None
        return _slack_token
    except ClientError as e:
        logger.warning(f"Could not retrieve Slack token: {e}")
        return None
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Slack secret format error: {e}")
        return None


def send_slack_message(
    channel: str,
    text: str,
    thread_ts: str | None = None,
    blocks: list[dict] | None = None,
) -> dict:
    """
    Send a message to a Slack channel.

    Args:
        channel: Slack channel ID.
        text: Message text (used as fallback for blocks).
        thread_ts: Optional thread timestamp for threaded replies.
        blocks: Optional Block Kit blocks for rich formatting.

    Returns:
        Slack API response dict.
    """
    import urllib.request
    import urllib.error

    token = _get_slack_token()
    if not token:
        logger.warning("No Slack token available — skipping message send")
        return {"ok": False, "error": "no_token"}

    payload: dict = {
        "channel": channel,
        "text": text,
    }

    if thread_ts:
        payload["thread_ts"] = thread_ts

    if blocks:
        payload["blocks"] = blocks

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {token}",
    }

    try:
        req = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))

            if not result.get("ok"):
                logger.error(f"Slack API error: {result.get('error', 'unknown')}")
            else:
                logger.info(f"Slack message sent to {channel}")

            return result

    except urllib.error.URLError as e:
        logger.error(f"Failed to send Slack message: {e}")
        return {"ok": False, "error": str(e)}


def update_slack_message(
    channel: str,
    ts: str,
    text: str,
    blocks: list[dict] | None = None,
) -> dict:
    """
    Update an existing Slack message.

    Args:
        channel: Slack channel ID.
        ts: Timestamp of the message to update.
        text: New text content.
        blocks: Optional new Block Kit blocks.

    Returns:
        Slack API response dict.
    """
    import urllib.request
    import urllib.error

    token = _get_slack_token()

    payload: dict = {
        "channel": channel,
        "ts": ts,
        "text": text,
    }

    if blocks:
        payload["blocks"] = blocks

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {token}",
    }

    try:
        req = urllib.request.Request(
            "https://slack.com/api/chat.update",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    except urllib.error.URLError as e:
        logger.error(f"Failed to update Slack message: {e}")
        return {"ok": False, "error": str(e)}
