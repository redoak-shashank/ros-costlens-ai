"""
Slack messaging tool.

Handles sending messages to Slack channels and threads.
Retrieves bot tokens from AWS Secrets Manager.
"""

from __future__ import annotations

import json
import logging
import re

import boto3
from botocore.exceptions import ClientError

from ..config.settings import get_settings

logger = logging.getLogger(__name__)

_slack_token: str | None = None
_slack_bot_user_id: str | None = None


def _to_slack_mrkdwn(text: str) -> str:
    """
    Convert generic Markdown-style output into Slack-friendly mrkdwn.

    Slack does not support # heading syntax, so convert headings to bold lines.
    """
    if not text:
        return text

    converted_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+)$", line)
        if heading:
            converted_lines.append(f"*{heading.group(1).strip()}*")
        else:
            converted_lines.append(line)

    converted = "\n".join(converted_lines)
    # Translate Markdown bold to Slack mrkdwn bold.
    converted = re.sub(r"\*\*(.+?)\*\*", r"*\1*", converted)
    return converted


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


def _get_bot_user_id() -> str | None:
    """Resolve bot user ID for the configured bot token."""
    global _slack_bot_user_id
    if _slack_bot_user_id:
        return _slack_bot_user_id

    import urllib.request
    import urllib.error

    token = _get_slack_token()
    if not token:
        return None

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {token}",
    }
    try:
        req = urllib.request.Request(
            "https://slack.com/api/auth.test",
            data=b"{}",
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
            if result.get("ok"):
                _slack_bot_user_id = result.get("user_id")
                return _slack_bot_user_id
    except urllib.error.URLError as e:
        logger.warning(f"Failed to resolve Slack bot user id: {e}")
    return None


def thread_has_bot_reply(channel: str, thread_ts: str) -> bool:
    """
    Return True if this bot has already posted in the given Slack thread.

    Used to allow @mention-free follow-ups once a thread is already established.
    """
    import urllib.parse
    import urllib.request
    import urllib.error

    token = _get_slack_token()
    if not token or not channel or not thread_ts:
        return False

    bot_user_id = _get_bot_user_id()
    headers = {
        "Authorization": f"Bearer {token}",
    }
    query = urllib.parse.urlencode({"channel": channel, "ts": thread_ts, "limit": 50})
    url = f"https://slack.com/api/conversations.replies?{query}"

    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
            if not result.get("ok"):
                logger.warning(
                    f"Slack conversations.replies error: {result.get('error', 'unknown')}"
                )
                return False
            for msg in result.get("messages", []):
                if bot_user_id and msg.get("user") == bot_user_id:
                    return True
                if msg.get("bot_id"):
                    return True
            return False
    except urllib.error.URLError as e:
        logger.warning(f"Failed to inspect Slack thread replies: {e}")
        return False


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
        "text": _to_slack_mrkdwn(text),
        "mrkdwn": True,
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
        "text": _to_slack_mrkdwn(text),
        "mrkdwn": True,
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
