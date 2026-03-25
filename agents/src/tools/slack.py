"""
Slack messaging tool.

Handles sending messages to Slack channels and threads.
Retrieves bot tokens from AWS Secrets Manager.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse

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


def _slack_api_form_post(
    method: str,
    token: str,
    payload: dict[str, str],
) -> dict:
    """POST application/x-www-form-urlencoded payload to a Slack API method."""
    import urllib.request
    import urllib.error

    body = urllib.parse.urlencode(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Bearer {token}",
    }

    try:
        req = urllib.request.Request(
            f"https://slack.com/api/{method}",
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as e:
        logger.error(f"Slack API call failed ({method}): {e}")
        return {"ok": False, "error": str(e)}


def send_slack_file(
    channel: str,
    filename: str,
    file_bytes: bytes,
    title: str | None = None,
    thread_ts: str | None = None,
    initial_comment: str | None = None,
) -> dict:
    """
    Upload a file to Slack using external upload APIs and share it to a channel.

    Requires Slack app scope: files:write.
    """
    import urllib.request
    import urllib.error

    token = _get_slack_token()
    if not token:
        logger.warning("No Slack token available — skipping file upload")
        return {"ok": False, "error": "no_token"}

    if not channel:
        return {"ok": False, "error": "missing_channel"}

    if not file_bytes:
        return {"ok": False, "error": "empty_file"}

    # Step 1: Request upload URL + file ID.
    start_payload = {
        "filename": filename,
        "length": str(len(file_bytes)),
    }
    start = _slack_api_form_post("files.getUploadURLExternal", token, start_payload)
    if not start.get("ok"):
        logger.error(f"Slack file upload start failed: {start}")
        return start

    upload_url = start.get("upload_url")
    file_id = start.get("file_id")
    if not upload_url or not file_id:
        return {"ok": False, "error": "missing_upload_url_or_file_id", "response": start}

    # Step 2: Upload bytes directly to Slack's upload URL.
    try:
        upload_req = urllib.request.Request(
            upload_url,
            data=file_bytes,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(file_bytes)),
            },
            method="POST",
        )
        with urllib.request.urlopen(upload_req, timeout=30) as upload_response:
            status = getattr(upload_response, "status", 200)
            if status < 200 or status >= 300:
                return {"ok": False, "error": f"upload_http_{status}"}
    except urllib.error.URLError as e:
        logger.error(f"Slack raw upload failed: {e}")
        return {"ok": False, "error": str(e)}

    # Step 3: Complete upload and share to channel (optionally thread).
    file_title = title or filename
    files_arg = json.dumps([{"id": file_id, "title": file_title}])
    complete_payload = {
        "files": files_arg,
        "channel_id": channel,
    }
    if thread_ts:
        complete_payload["thread_ts"] = thread_ts
    if initial_comment:
        complete_payload["initial_comment"] = _to_slack_mrkdwn(initial_comment)

    complete = _slack_api_form_post("files.completeUploadExternal", token, complete_payload)

    # Compatibility fallback for orgs expecting "channels" instead of "channel_id".
    if (
        not complete.get("ok")
        and complete.get("error") in {"invalid_arguments", "invalid_arg_name", "missing_scope"}
    ):
        alt_payload = dict(complete_payload)
        alt_payload.pop("channel_id", None)
        alt_payload["channels"] = channel
        complete = _slack_api_form_post("files.completeUploadExternal", token, alt_payload)

    if not complete.get("ok"):
        logger.error(f"Slack file upload complete failed: {complete}")
    else:
        logger.info(f"Slack file uploaded: {filename} to {channel}")
    return complete
