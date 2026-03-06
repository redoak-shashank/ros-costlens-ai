"""
Supervisor Agent — Routes incoming requests to the appropriate specialist agent.

The supervisor is the entry point for all interactions (scheduled reports,
Slack Q&A, anomaly alerts). It analyzes the request/state and decides which
specialist to invoke next, or whether to finalize via the Reporter.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, SystemMessage

from ..state import BillingState
from ..config.settings import get_settings
from ..tracing import trace_operation

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "supervisor.md").read_text()

ROUTING_PROMPT = """
Based on the current state, decide the next agent to invoke.

Available agents:
- cost_analyst: For retrieving spend data, trends, forecasts, service breakdowns
- anomaly_detector: For detecting cost spikes and anomalies
- optimizer: For finding savings opportunities and idle resources
- reporter: For formatting and sending the final output to Slack/dashboard
- end: When all required data is collected and reported

Current state:
- Request type: {request_type}
- Has daily spend data: {has_daily}
- Has MTD spend data: {has_mtd}
- Has anomaly data: {has_anomalies}
- Has recommendations: {has_recommendations}
- Has slack message: {has_slack}
- Iteration count: {iteration_count}
- Latest user message: {latest_message}

Respond with ONLY a JSON object: {{"next_agent": "<agent_name>", "reasoning": "<brief reason>"}}
"""


@trace_operation("supervisor_routing")
def supervisor_node(state: BillingState) -> dict:
    """Route to the next specialist agent based on current state."""
    settings = get_settings()
    print(f"[supervisor] Starting. model={settings.bedrock_model_id}, region={settings.aws_region}", flush=True)

    llm = ChatBedrock(
        model_id=settings.bedrock_model_id,
        region_name=settings.aws_region,
        model_kwargs={"temperature": 0, "max_tokens": 256},
    )

    # Guard against infinite loops
    iteration_count = state.get("iteration_count", 0)
    print(f"[supervisor] iteration_count={iteration_count}", flush=True)
    if iteration_count > 8:
        logger.warning("Max iterations reached, forcing reporter")
        return {"next_agent": "reporter", "iteration_count": iteration_count + 1}

    # Extract the latest human message for context
    latest_message = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            # Do NOT truncate here: with memory injection, the
            # "[Current question]" marker may appear after 500 chars.
            latest_message = msg.content
            break

    request_type = state.get("request_type", "")

    def _extract_current_question(message: str) -> str:
        """
        Extract only the current user question when memory context is prepended.

        app.py formats message as:
          [Previous context from memory] ... [Current question] <user text>
        We should route on <user text>, not the injected memory blob.
        """
        if not message:
            return ""
        marker = "[Current question]"
        if marker in message:
            return message.split(marker, 1)[1].strip()
        return message.strip()

    def _query_intent_flags(message: str) -> tuple[bool, bool]:
        text = _extract_current_question(message).lower()
        deep_dive_keywords = (
            "account", "accounts", "region", "regions", "resource", "resources",
            "root cause", "group by", "breakdown", "break down",
        )
        wants_deep_dive = any(k in text for k in deep_dive_keywords)

        anomaly_keywords = (
            "anomaly", "spike", "spikes", "unusual", "increase", "increased",
            "jump", "surge", "why did", "went up", "cost up",
        )
        optimization_keywords = (
            "optimize", "optimization", "save", "savings", "reduce", "cut cost",
            "rightsizing", "right-size", "idle", "recommendation",
        )
        # Deep-dive prompts should stay in cost_analyst (Athena path),
        # not be redirected to anomaly/optimizer by keyword overlap.
        wants_anomaly = any(k in text for k in anomaly_keywords) and not wants_deep_dive
        wants_optimization = any(k in text for k in optimization_keywords)
        return wants_anomaly, wants_optimization

    # Deterministic pipeline for scheduled reports:
    # cost_analyst -> anomaly_detector -> optimizer -> reporter
    if request_type == "report":
        if state.get("daily_spend") is None:
            return {"next_agent": "cost_analyst", "iteration_count": iteration_count + 1}
        if state.get("anomalies") is None:
            return {"next_agent": "anomaly_detector", "iteration_count": iteration_count + 1}
        if state.get("recommendations") is None:
            return {"next_agent": "optimizer", "iteration_count": iteration_count + 1}
        return {"next_agent": "reporter", "iteration_count": iteration_count + 1}

    # Deterministic pipeline for anomaly alerts:
    # cost_analyst -> anomaly_detector -> reporter
    if request_type == "alert":
        if state.get("trend_data") is None:
            return {"next_agent": "cost_analyst", "iteration_count": iteration_count + 1}
        if state.get("anomalies") is None:
            return {"next_agent": "anomaly_detector", "iteration_count": iteration_count + 1}
        return {"next_agent": "reporter", "iteration_count": iteration_count + 1}

    # For simple greetings / non-billing messages, go straight to reporter
    if request_type == "query" and iteration_count == 0 and latest_message:
        current_question = _extract_current_question(latest_message)
        simple_greeting = current_question.lower().rstrip("!?.,")
        greetings = {"hi", "hello", "hey", "yo", "sup", "hola", "good morning",
                     "good afternoon", "good evening", "thanks", "thank you", "bye"}
        if simple_greeting in greetings or len(simple_greeting) < 4:
            print(f"[supervisor] Simple greeting detected: '{simple_greeting}' → reporter", flush=True)
            from langchain_core.messages import AIMessage
            return {
                "next_agent": "reporter",
                "iteration_count": iteration_count + 1,
                "messages": [AIMessage(content=(
                    "Hello! I'm your AWS Billing Intelligence Agent. "
                    "I can help you with:\n"
                    "• **Cost analysis** — \"What's my AWS spend this month?\"\n"
                    "• **Anomaly detection** — \"Are there any cost spikes?\"\n"
                    "• **Optimization** — \"Where can I save money?\"\n"
                    "• **Forecasting** — \"What will my bill be this month?\"\n\n"
                    "What would you like to know?"
                ))],
            }

    # Deterministic baseline for interactive queries:
    # always gather cost context first, then optionally fan-out to anomaly/optimizer.
    if request_type == "query":
        wants_anomaly, wants_optimization = _query_intent_flags(latest_message)

        if state.get("daily_spend") is None:
            return {"next_agent": "cost_analyst", "iteration_count": iteration_count + 1}
        if wants_anomaly and state.get("anomalies") is None:
            return {"next_agent": "anomaly_detector", "iteration_count": iteration_count + 1}
        if wants_optimization and state.get("recommendations") is None:
            return {"next_agent": "optimizer", "iteration_count": iteration_count + 1}
        return {"next_agent": "reporter", "iteration_count": iteration_count + 1}

    # Fallback: LLM dynamic routing for any unknown request type.
    routing_input = ROUTING_PROMPT.format(
        request_type=request_type or "query",
        has_daily=state.get("daily_spend") is not None,
        has_mtd=state.get("mtd_spend") is not None,
        has_anomalies=state.get("anomalies") is not None,
        has_recommendations=state.get("recommendations") is not None,
        has_slack=state.get("slack_message") is not None,
        iteration_count=iteration_count,
        latest_message=latest_message,
    )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=routing_input),
    ]

    print(f"[supervisor] Calling LLM for routing...", flush=True)
    try:
        response = llm.invoke(messages)
        print(f"[supervisor] LLM response: {response.content[:300]}", flush=True)
    except Exception as e:
        print(f"[supervisor] LLM ERROR: {type(e).__name__}: {e}", flush=True)
        logger.error(f"Supervisor LLM call failed: {e}", exc_info=True)
        # Fallback: route to cost_analyst if no data, else reporter
        next_agent = "reporter" if state.get("daily_spend") else "cost_analyst"
        print(f"[supervisor] Fallback routing to: {next_agent}", flush=True)
        return {"next_agent": next_agent, "iteration_count": iteration_count + 1}

    try:
        decision = json.loads(response.content)
        next_agent = decision.get("next_agent", "reporter")
        reasoning = decision.get('reasoning', '')
        logger.info(f"Supervisor routing to: {next_agent} — {reasoning}")
        print(f"[supervisor] Routing to: {next_agent} — {reasoning}", flush=True)
    except (json.JSONDecodeError, AttributeError):
        logger.warning(f"Failed to parse supervisor response: {response.content}")
        print(f"[supervisor] PARSE ERROR, response: {response.content[:300]}", flush=True)
        # Fallback: if we have data, go to reporter; otherwise cost_analyst
        next_agent = "reporter" if state.get("daily_spend") else "cost_analyst"

    # Validate the agent name
    valid_agents = {"cost_analyst", "anomaly_detector", "optimizer", "reporter", "end"}
    if next_agent not in valid_agents:
        print(f"[supervisor] Invalid agent '{next_agent}', defaulting to reporter", flush=True)
        next_agent = "reporter"

    return {"next_agent": next_agent, "iteration_count": iteration_count + 1}
