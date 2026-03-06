"""
Main LangGraph StateGraph definition for the billing intelligence system.

Defines the supervisor + specialist agent topology with conditional routing.
"""

from __future__ import annotations

import logging

from langgraph.graph import StateGraph, START, END

from .state import BillingState
from .checkpointer import get_checkpointer
from .agents import (
    supervisor_node,
    cost_analyst_node,
    anomaly_detector_node,
    optimizer_node,
    reporter_node,
)

logger = logging.getLogger(__name__)


def route_to_agent(state: BillingState) -> str:
    """Read the supervisor's routing decision from state."""
    next_agent = state.get("next_agent", "end")

    if next_agent == "end":
        return END

    valid_agents = {"cost_analyst", "anomaly_detector", "optimizer", "reporter"}
    if next_agent not in valid_agents:
        logger.warning(f"Unknown agent '{next_agent}', defaulting to reporter")
        return "reporter"

    return next_agent


def build_graph(checkpointer=None) -> StateGraph:
    """
    Build and compile the billing intelligence LangGraph.

    Args:
        checkpointer: Optional LangGraph checkpointer for state persistence.
                      Use MemorySaver for testing, AgentCoreSaver for production.

    Returns:
        Compiled LangGraph application.
    """
    graph = StateGraph(BillingState)

    # ── Add agent nodes ──────────────────────────────────────────────────
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("cost_analyst", cost_analyst_node)
    graph.add_node("anomaly_detector", anomaly_detector_node)
    graph.add_node("optimizer", optimizer_node)
    graph.add_node("reporter", reporter_node)

    # ── Entry point ──────────────────────────────────────────────────────
    graph.add_edge(START, "supervisor")

    # ── Supervisor routes conditionally ──────────────────────────────────
    graph.add_conditional_edges(
        "supervisor",
        route_to_agent,
        {
            "cost_analyst": "cost_analyst",
            "anomaly_detector": "anomaly_detector",
            "optimizer": "optimizer",
            "reporter": "reporter",
            END: END,
        },
    )

    # ── Specialist agents return to supervisor for next decision ─────────
    graph.add_edge("cost_analyst", "supervisor")
    graph.add_edge("anomaly_detector", "supervisor")
    graph.add_edge("optimizer", "supervisor")

    # ── Reporter is terminal ─────────────────────────────────────────────
    graph.add_edge("reporter", END)

    # ── Compile ──────────────────────────────────────────────────────────
    # Uses in-memory MemorySaver — each invocation starts fresh.
    # Cross-session context is handled by AgentCore Memory (src/memory.py).
    if checkpointer is None:
        checkpointer = get_checkpointer()

    app = graph.compile(checkpointer=checkpointer)

    logger.info("Billing intelligence graph compiled successfully")
    return app
