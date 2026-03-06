"""
Shared state definition for the billing intelligence LangGraph.

All agents read from and write to this state. The Supervisor uses it for
routing decisions; specialist agents populate their respective sections.
"""

from __future__ import annotations

from typing import Annotated, Literal

from langgraph.graph import MessagesState
from langchain_core.messages import BaseMessage


def _merge_dicts(left: dict | None, right: dict | None) -> dict | None:
    """Reducer that merges two dicts (right overwrites left keys)."""
    if left is None:
        return right
    if right is None:
        return left
    return {**left, **right}


def _merge_lists(left: list | None, right: list | None) -> list | None:
    """Reducer that concatenates two lists."""
    if left is None:
        return right
    if right is None:
        return left
    return left + right


class BillingState(MessagesState):
    """Shared state across all agents in the billing intelligence graph."""

    # ── Routing ──────────────────────────────────────────────────────────
    next_agent: str = ""
    request_type: Literal["report", "query", "alert", ""] = ""

    # ── Cost data (populated by Cost Analyst) ────────────────────────────
    daily_spend: Annotated[dict | None, _merge_dicts] = None
    mtd_spend: Annotated[dict | None, _merge_dicts] = None
    forecast: Annotated[dict | None, _merge_dicts] = None
    trend_data: Annotated[list[dict] | None, _merge_lists] = None
    service_breakdown: Annotated[dict | None, _merge_dicts] = None

    # ── Anomaly data (populated by Anomaly Detector) ─────────────────────
    anomalies: Annotated[list[dict] | None, _merge_lists] = None
    severity: Literal["low", "medium", "high", "critical", ""] = ""

    # ── Optimization data (populated by Optimizer) ───────────────────────
    recommendations: Annotated[list[dict] | None, _merge_lists] = None
    total_potential_savings: float | None = None

    # ── Output ───────────────────────────────────────────────────────────
    slack_message: str | None = None
    dashboard_data: Annotated[dict | None, _merge_dicts] = None

    # ── Metadata ─────────────────────────────────────────────────────────
    athena_auto_executed: bool | None = None
    athena_auto_error: str | None = None
    error: str | None = None
    iteration_count: int = 0
