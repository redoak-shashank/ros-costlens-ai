"""
AgentCore Memory integration — managed short-term + long-term memory.

Uses the AgentCore Memory API to:
- Store conversation events (user question + agent response) per session
- Retrieve relevant memory records for context in new sessions
- Automatically extract long-term insights via memory strategies

Replaces the custom DynamoDB checkpointer. LangGraph uses in-memory
MemorySaver for graph execution; this module handles cross-session context.

Docs: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from botocore.exceptions import ParamValidationError

from .config.settings import get_settings

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    """Lazy-init the bedrock-agentcore client."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = boto3.client(
            "bedrock-agentcore",
            region_name=settings.aws_region,
        )
    return _client


def _candidate_namespaces(base_namespace: str, session_id: str) -> list[str]:
    """
    Build namespace candidates for retrieval.

    Strategies may persist records either into a session-scoped namespace
    (e.g. billing/<session_id>) or a shared namespace (e.g. billing).
    """
    return [f"{base_namespace}/{session_id}", base_namespace]


def store_conversation_event(
    session_id: str,
    user_message: str,
    agent_response: str,
    namespace: str = "billing",
) -> bool:
    """
    Store a conversation turn (user→agent) as a memory event.

    Args:
        session_id: Unique session identifier (e.g., Slack thread_ts, UUID).
        user_message: The user's question.
        agent_response: The agent's response.
        namespace: Memory namespace for filtering.

    Returns:
        True if stored successfully, False otherwise.
    """
    settings = get_settings()
    if not settings.memory_id:
        logger.debug("MEMORY_ID not configured — skipping event storage")
        return False

    client = _get_client()

    # Reset stale debug state from previous invocations.
    store_conversation_event._last_error = None

    try:
        # payload is a list of event items, each with a conversational message
        # Shape: [{conversational: {content: {text: "..."}, role: "user|assistant"}}]
        payload_items = [
            {
                "conversational": {
                    "content": {"text": user_message},
                    "role": "USER",
                }
            },
            {
                "conversational": {
                    "content": {"text": agent_response},
                    "role": "ASSISTANT",
                }
            },
        ]

        # Current SDK shape does not accept "namespace" for create_event.
        # Keep call minimal and schema-compatible.
        client.create_event(
            memoryId=settings.memory_id,
            actorId=session_id,
            sessionId=session_id,
            eventTimestamp=str(int(time.time())),
            payload=payload_items,
        )

        logger.info(f"Stored memory event for session {session_id}")
        print(f"[memory] Stored event for session {session_id}", flush=True)
        store_conversation_event._last_error = None
        return True

    except (ClientError, ParamValidationError) as e:
        logger.warning(f"Failed to store memory event: {e}")
        print(f"[memory] Failed to store event: {e}", flush=True)
        # Store error for debugging
        store_conversation_event._last_error = str(e)
        return False
    except Exception as e:
        logger.warning(f"Memory event storage error: {e}")
        print(f"[memory] Error: {e}", flush=True)
        store_conversation_event._last_error = str(e)
        return False


def retrieve_memory_context(
    session_id: str,
    query: str,
    namespace: str = "billing",
    max_records: int = 5,
) -> list[dict]:
    """
    Retrieve relevant memory records for conversation context.

    Uses the memory strategies (summarization, user preferences) to
    find relevant past context for the current session.

    Args:
        session_id: Current session identifier.
        query: The user's current question (used for relevance matching).
        namespace: Memory namespace to search.
        max_records: Maximum number of records to retrieve.

    Returns:
        List of memory record dicts with 'content' and 'type' keys.
    """
    settings = get_settings()
    if not settings.memory_id:
        return []

    client = _get_client()
    records: list[dict] = []

    # Reset stale debug state from previous invocations.
    retrieve_memory_context._last_error = None

    last_error = None
    seen = set()
    namespaces = _candidate_namespaces(namespace, session_id)

    for ns in namespaces:
        try:
            # Preferred API shape.
            response = client.retrieve_memory_records(
                memoryId=settings.memory_id,
                namespace=ns,
                searchCriteria={"searchQuery": query},
                maxResults=max_records,
            )
        except ClientError as e:
            # Backward-compatible fallback for older API shape.
            err = str(e)
            if "Unknown parameter" in err or "Invalid type for parameter searchCriteria" in err:
                try:
                    response = client.retrieve_memory_records(
                        memoryId=settings.memory_id,
                        namespace=ns,
                        searchCriteria={
                            "searchQuery": query,
                            "topK": max_records,
                        },
                    )
                except Exception as fallback_err:
                    last_error = fallback_err
                    continue
            else:
                last_error = e
                continue
        except Exception as e:
            last_error = e
            continue

        for record in response.get("memoryRecords", []):
            content = record.get("content", {}).get("text", "")
            record_type = record.get("memoryStrategyId", "unknown")
            if not content:
                continue
            key = (content, record_type)
            if key in seen:
                continue
            seen.add(key)
            records.append({
                "content": content,
                "type": record_type,
                "score": record.get("score", 0),
            })

    if records:
        logger.info(f"Retrieved {len(records)} memory records for session {session_id}")
        print(f"[memory] Retrieved {len(records)} records", flush=True)
        retrieve_memory_context._last_error = None
    else:
        # Fallback: read raw recent session events for immediate continuity.
        # Strategy-based records can lag; events are available immediately.
        try:
            events_resp = client.list_events(
                memoryId=settings.memory_id,
                sessionId=session_id,
                actorId=session_id,
                includePayloads=True,
                maxResults=max_records,
            )
            for event in events_resp.get("events", []):
                for item in event.get("payload", []):
                    conv = item.get("conversational", {})
                    role = conv.get("role", "")
                    text = conv.get("content", {}).get("text", "")
                    if not text:
                        continue
                    # Prior assistant outputs are most useful as context.
                    if role == "ASSISTANT":
                        records.append({
                            "content": text,
                            "type": "recent_session_event",
                            "score": 1.0,
                        })
            if records:
                logger.info(
                    f"Retrieved {len(records)} fallback event records for session {session_id}"
                )
                print(f"[memory] Retrieved {len(records)} fallback event records", flush=True)
                retrieve_memory_context._last_error = None
        except Exception as fallback_error:
            last_error = fallback_error

        if last_error and not records:
            logger.warning(f"Failed to retrieve memory records: {last_error}")
            print(f"[memory] Retrieve failed: {last_error}", flush=True)
            retrieve_memory_context._last_error = str(last_error)

    return records
