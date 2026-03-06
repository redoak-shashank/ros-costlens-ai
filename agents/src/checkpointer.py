"""
LangGraph checkpointer — uses in-memory MemorySaver.

Each AgentCore Runtime invocation runs the full graph from scratch.
There's no need to persist LangGraph's internal graph state across
invocations — that's what caused session bleed via DynamoDB.

Cross-session conversation context is handled by AgentCore Memory
(a managed AWS service), NOT by the LangGraph checkpointer.
"""

from __future__ import annotations

import logging

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)


def get_checkpointer() -> MemorySaver:
    """Return an in-memory checkpointer for LangGraph graph execution."""
    return MemorySaver()
