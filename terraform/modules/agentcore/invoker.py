"""
Thin bridge Lambda: forwards events from EventBridge / API Gateway to AgentCore Runtime.

Handles Slack URL verification quickly and supports async self-invoke for Slack
event callbacks to avoid retries on cold starts.
"""
import json
import os

import boto3

client = boto3.client("bedrock-agentcore", region_name=os.environ.get("AWS_REGION", "us-east-1"))
lambda_client = boto3.client("lambda", region_name=os.environ.get("AWS_REGION", "us-east-1"))

RUNTIME_ARN = os.environ["RUNTIME_ARN"]
QUALIFIER = os.environ.get("RUNTIME_QUALIFIER", "DEFAULT")
INVOKER_FUNCTION_NAME = os.environ.get("INVOKER_FUNCTION_NAME", "")


def _decode_runtime_body(response_obj):
    body = response_obj.get("response", b"")
    if isinstance(body, bytes):
        return body.decode("utf-8")
    if hasattr(body, "read"):
        return body.read().decode("utf-8")
    return str(body)


def handler(event, context):
    """Forward incoming event to AgentCore Runtime with lightweight protocol handling."""
    print(f"[invoker] Received event: {json.dumps(event, default=str)[:500]}")

    # Handle API Gateway payload wrapper.
    body_str = event.get("body", "")
    if body_str and isinstance(body_str, str):
        try:
            slack_body = json.loads(body_str)
            if slack_body.get("type") == "url_verification":
                challenge = slack_body.get("challenge", "")
                return {
                    "statusCode": 200,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"challenge": challenge}),
                }

            if slack_body.get("type") == "event_callback":
                # Ack quickly, process async to avoid Slack retries.
                if INVOKER_FUNCTION_NAME:
                    lambda_client.invoke(
                        FunctionName=INVOKER_FUNCTION_NAME,
                        InvocationType="Event",
                        Payload=json.dumps(
                            {"action": "slack_event_async", "original_event": event}
                        ),
                    )
                    return {"statusCode": 200, "body": "ok"}
        except (json.JSONDecodeError, TypeError):
            pass

    if event.get("action") == "slack_event_async":
        original_event = event.get("original_event", {})
        payload = json.dumps(original_event, default=str).encode("utf-8")
    else:
        payload = json.dumps(event, default=str).encode("utf-8")

    response = client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        qualifier=QUALIFIER,
        payload=payload,
    )

    body = _decode_runtime_body(response)
    print(f"[invoker] Response: {body[:500]}")

    try:
        result = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        result = {"status": "ok", "response": body}

    # If runtime already returned API GW format, pass through.
    if isinstance(result, dict) and "statusCode" in result:
        return result

    # Non-API callers: return raw runtime result.
    if event.get("source") == "aws.events" or event.get("prompt") or event.get("action"):
        return result

    # API GW callers: wrap in HTTP response shape.
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(result, default=str),
    }
