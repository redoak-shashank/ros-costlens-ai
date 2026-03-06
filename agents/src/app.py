"""
AgentCore Runtime entry point.

This is the main handler that AgentCore Runtime invokes. It accepts
incoming requests (scheduled reports, Slack messages, API queries)
and routes them through the LangGraph billing intelligence graph.
"""

from __future__ import annotations

import json
import logging
import os
import uuid

from langchain_core.messages import HumanMessage

from .graph import build_graph
from .memory import store_conversation_event, retrieve_memory_context
from .state import BillingState

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def handle_scheduled_report(report_type: str = "daily") -> dict:
    """
    Handle a scheduled report trigger from EventBridge.

    Args:
        report_type: One of "daily", "anomaly_check", "weekly"
    """
    graph = build_graph()

    initial_state = {
        "messages": [
            HumanMessage(content=f"Generate a {report_type} cost report")
        ],
        "request_type": "report" if report_type in ("daily", "weekly") else "alert",
        "next_agent": "",
        "iteration_count": 0,
    }

    config = {"configurable": {"thread_id": f"scheduled-{report_type}"}}

    result = graph.invoke(initial_state, config=config)

    return {
        "status": "ok",
        "slack_message": result.get("slack_message"),
        "dashboard_data": result.get("dashboard_data"),
    }


def handle_slack_message(user_message: str, thread_id: str = "default") -> dict:
    """
    Handle an interactive Slack message.

    Args:
        user_message: The user's question/message from Slack.
        thread_id: Slack thread timestamp for conversation context.
    """
    # Use unique thread_id for direct queries to avoid stale checkpoint state
    if thread_id == "direct-query":
        thread_id = f"direct-{uuid.uuid4().hex[:8]}"

    logger.info(f"handle_slack_message called: message='{user_message}', thread={thread_id}")
    print(f"[src.app] handle_slack_message: '{user_message}', thread={thread_id}", flush=True)

    # Retrieve relevant memory from previous sessions
    memory_context = retrieve_memory_context(
        session_id=thread_id,
        query=user_message,
    )

    # Build initial messages with memory context
    messages = []
    if memory_context:
        context_text = "\n".join(
            f"[Memory: {r['type']}] {r['content']}" for r in memory_context
        )
        messages.append(HumanMessage(
            content=f"[Previous context from memory]\n{context_text}\n\n[Current question]\n{user_message}"
        ))
        print(f"[src.app] Injected {len(memory_context)} memory records", flush=True)
    else:
        messages.append(HumanMessage(content=user_message))

    graph = build_graph()

    initial_state = {
        "messages": messages,
        "request_type": "query",
        "next_agent": "",
        "iteration_count": 0,
    }

    config = {"configurable": {"thread_id": f"slack-{thread_id}"}}

    logger.info("Invoking graph...")
    print("[src.app] Invoking graph...", flush=True)

    result = graph.invoke(initial_state, config=config)

    # Debug: log what the graph returned
    result_keys = list(result.keys()) if isinstance(result, dict) else "non-dict"
    logger.info(f"Graph result keys: {result_keys}")
    print(f"[src.app] Graph result keys: {result_keys}", flush=True)

    # Log key state fields for debugging
    debug_info = {
        "next_agent": result.get("next_agent"),
        "iteration_count": result.get("iteration_count"),
        "has_daily_spend": result.get("daily_spend") is not None,
        "has_mtd_spend": result.get("mtd_spend") is not None,
        "has_anomalies": result.get("anomalies") is not None,
        "has_recommendations": result.get("recommendations") is not None,
        "has_slack_message": bool(result.get("slack_message")),
        "has_error": bool(result.get("error")),
        "error": result.get("error"),
        "num_messages": len(result.get("messages", [])),
        "athena_auto_executed": result.get("athena_auto_executed"),
        "athena_auto_error": result.get("athena_auto_error"),
    }
    logger.info(f"Graph debug info: {json.dumps(debug_info, default=str)}")
    print(f"[src.app] Graph debug: {json.dumps(debug_info, default=str)}", flush=True)

    # Log last few messages
    for i, msg in enumerate(result.get("messages", [])[-5:]):
        content = msg.content[:200] if hasattr(msg, "content") else str(msg)[:200]
        msg_type = type(msg).__name__
        logger.info(f"  Message[{i}] ({msg_type}): {content}")
        print(f"[src.app]   Message[{i}] ({msg_type}): {content}", flush=True)

    # Extract the final response
    response_text = result.get("slack_message", "")
    if not response_text:
        # Fall back to the last AI message
        for msg in reversed(result.get("messages", [])):
            if hasattr(msg, "content") and not isinstance(msg, HumanMessage):
                response_text = msg.content
                break

    if not response_text:
        response_text = "No response generated. Debug: " + json.dumps(debug_info, default=str)

    # Store this conversation turn in AgentCore Memory for future context
    memory_store_ok = store_conversation_event(
        session_id=thread_id,
        user_message=user_message,
        agent_response=response_text[:2000],  # Truncate large responses
    )

    debug_info["memory_store"] = memory_store_ok
    debug_info["memory_context_count"] = len(memory_context) if memory_context else 0
    debug_info["memory_id"] = os.environ.get("MEMORY_ID", "<not set>")
    debug_info["memory_store_error"] = getattr(store_conversation_event, '_last_error', None)
    debug_info["memory_retrieve_error"] = getattr(retrieve_memory_context, '_last_error', None)

    return {"status": "ok", "response": response_text, "debug": debug_info}


def handler(event: dict, context=None) -> dict:
    """
    Unified Lambda/AgentCore handler.

    Dispatches based on event source:
    - EventBridge scheduled events → handle_scheduled_report
    - API Gateway (Slack) events → handle_slack_message
    - Direct invocations → handle based on 'action' field
    """
    logger.info(f"Received event: {json.dumps(event, default=str)[:500]}")

    try:
        # EventBridge scheduled trigger
        if event.get("source") == "aws.events" or event.get("detail-type"):
            report_type = event.get("detail", {}).get("report_type", "daily")
            return handle_scheduled_report(report_type)

        # Direct invocation with explicit action
        action = event.get("action")
        if action == "scheduled_report":
            return handle_scheduled_report(event.get("report_type", "daily"))
        elif action == "slack_message":
            return handle_slack_message(
                user_message=event.get("message", ""),
                thread_id=event.get("thread_id", "default"),
            )
        elif action == "query":
            return handle_slack_message(
                user_message=event.get("prompt", event.get("message", "")),
                thread_id=event.get("thread_id", "direct-query"),
            )
        elif action == "health_check":
            return {"status": "ok", "message": "Billing Intelligence System is running"}

        # If there's a "prompt" field, treat as a direct query
        if event.get("prompt"):
            return handle_slack_message(
                user_message=event["prompt"],
                thread_id=event.get("thread_id", "direct-query"),
            )

        # Slack event (from API Gateway)
        body = event.get("body")
        if body:
            if isinstance(body, str):
                body = json.loads(body)

            # Slack URL verification challenge
            if body.get("type") == "url_verification":
                return {
                    "statusCode": 200,
                    "body": json.dumps({"challenge": body["challenge"]}),
                }

            # Slack event callback
            if body.get("type") == "event_callback":
                slack_event = body.get("event", {})
                event_type = slack_event.get("type", "")

                # Skip message events that contain a bot mention — the
                # app_mention event will also fire and we handle it there.
                # This prevents duplicate replies.
                if event_type == "message" and "<@" in slack_event.get("text", ""):
                    logger.info("Skipping message event with bot mention (handled by app_mention)")
                    print("[src.app] Skipping message event (app_mention will handle it)", flush=True)
                    return {"statusCode": 200, "body": "ok"}

                # Handle app_mention events and DM messages (no bot mention)
                if event_type in ("message", "app_mention") and not slack_event.get("bot_id"):
                    user_text = slack_event.get("text", "")
                    channel = slack_event.get("channel", "")
                    thread_ts = slack_event.get("thread_ts", slack_event.get("ts", ""))

                    # Strip bot mention from text (e.g., "<@U12345> Hi" → "Hi")
                    import re
                    user_text = re.sub(r"<@[A-Z0-9]+>\s*", "", user_text).strip()
                    if not user_text:
                        user_text = "Hi"

                    logger.info(f"Slack event: channel={channel}, text='{user_text}', thread={thread_ts}")
                    print(f"[src.app] Slack event: channel={channel}, text='{user_text}', thread={thread_ts}", flush=True)

                    result = handle_slack_message(
                        user_message=user_text,
                        thread_id=thread_ts or "default",
                    )

                    # Post the response back to Slack
                    response_text = result.get("response", "Sorry, I couldn't process that.")
                    if channel and response_text:
                        from .tools.slack import send_slack_message
                        slack_result = send_slack_message(
                            channel=channel,
                            text=response_text,
                            thread_ts=thread_ts,
                        )
                        logger.info(f"Slack reply sent: ok={slack_result.get('ok')}")
                        print(f"[src.app] Slack reply sent: {slack_result}", flush=True)

                    return {"statusCode": 200, "body": json.dumps({"ok": True})}

            return {"statusCode": 200, "body": "ok"}

        # Unknown event type
        logger.warning(f"Unknown event type: {event.get('action', 'none')}")
        return {"status": "error", "message": "Unknown event type"}

    except Exception as e:
        logger.error(f"Handler error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
