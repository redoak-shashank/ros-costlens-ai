"""
Reporter Agent — Formats outputs into Slack messages and dashboard data.

Takes the collected cost data, anomalies, and recommendations from state
and produces formatted Slack messages (Block Kit) and JSON for the dashboard.
Persists dashboard data to S3 so the Streamlit dashboard can read it.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from langchain_core.messages import AIMessage

from ..state import BillingState
from ..config.settings import get_settings
from ..tracing import trace_operation
from ..tools.slack import send_slack_message

logger = logging.getLogger(__name__)

_s3_client = None


def _get_s3_client():
    global _s3_client
    if _s3_client is None:
        settings = get_settings()
        _s3_client = boto3.client("s3", region_name=settings.aws_region)
    return _s3_client


def _persist_dashboard_data(dashboard_data: dict) -> bool:
    """
    Write dashboard data to S3 so the Streamlit dashboard can read it.

    Writes to two keys:
    - dashboard/latest.json  (what the dashboard reads on load)
    - dashboard/{date}.json  (historical archive)

    Returns True if write succeeded, False otherwise.
    """
    settings = get_settings()
    bucket = settings.dashboard_data_bucket

    if not bucket:
        logger.warning("DATA_BUCKET not configured — skipping S3 dashboard write")
        return False

    s3 = _get_s3_client()
    payload = json.dumps(dashboard_data, default=str, indent=2)
    today = datetime.utcnow().strftime("%Y-%m-%d")

    try:
        # Write latest (what the dashboard reads)
        s3.put_object(
            Bucket=bucket,
            Key="dashboard/latest.json",
            Body=payload.encode("utf-8"),
            ContentType="application/json",
        )

        # Write dated archive copy
        s3.put_object(
            Bucket=bucket,
            Key=f"dashboard/{today}.json",
            Body=payload.encode("utf-8"),
            ContentType="application/json",
        )

        logger.info(f"Dashboard data written to s3://{bucket}/dashboard/latest.json")
        return True

    except ClientError as e:
        logger.error(f"Failed to write dashboard data to S3: {e}")
        return False


def _format_daily_report(state: BillingState) -> str:
    """Format the daily cost report as a Slack message."""
    daily = state.get("daily_spend", {})
    mtd = state.get("mtd_spend", {})
    forecast = state.get("forecast", {})
    anomalies = state.get("anomalies", [])
    recommendations = state.get("recommendations", [])
    trend_data = state.get("trend_data", [])
    settings = get_settings()

    today = datetime.utcnow().strftime("%b %d, %Y")

    # Calculate day-over-day change
    dod_indicator = ""
    if trend_data and len(trend_data) >= 2:
        sorted_trend = sorted(trend_data, key=lambda x: x["date"])
        yesterday = sorted_trend[-1]["cost"]
        day_before = sorted_trend[-2]["cost"]
        if day_before > 0:
            pct = ((yesterday - day_before) / day_before) * 100
            arrow = "\u25b2" if pct > 0 else "\u25bc"
            dod_indicator = f" ({arrow} {abs(pct):.1f}% vs prior day)"

    # Build the message
    lines = [
        f":chart_with_upwards_trend: *Daily AWS Cost Report — {today}*",
        "",
    ]

    # Spend summary
    if daily:
        lines.append(
            f":moneybag: *Yesterday's Spend:* ${daily.get('total', 0):,.2f}{dod_indicator}"
        )

    if mtd:
        forecast_str = ""
        if forecast:
            forecast_total = forecast.get("forecast_total", 0)
            budget = settings.monthly_budget
            budget_pct = (forecast_total / budget * 100) if budget > 0 else 0
            forecast_str = f" | Forecast: ${forecast_total:,.0f} ({budget_pct:.0f}% of budget)"
        lines.append(
            f":calendar: *MTD Spend:* ${mtd.get('total', 0):,.2f}{forecast_str}"
        )

    # Top services
    service_breakdown = state.get("service_breakdown", {})
    wow = service_breakdown.get("week_over_week") if service_breakdown else None
    services = daily.get("services", {}) if daily else {}

    if wow:
        # Weekly deep-dive: show week-over-week changes
        lines.append("")
        lines.append(":building_construction: *Service Breakdown (Week-over-Week):*")
        for svc, data in list(sorted(
            wow.items(), key=lambda x: x[1].get("this_week", 0), reverse=True
        ))[:10]:
            this_w = data.get("this_week", 0)
            pct = data.get("change_pct", 0)
            arrow = "\u25b2" if pct > 0 else "\u25bc" if pct < 0 else "\u2014"
            lines.append(f"  \u2022 {svc}: ${this_w:,.2f} ({arrow} {abs(pct):.1f}% WoW)")
    elif services:
        lines.append("")
        lines.append(":building_construction: *Top Services:*")
        for svc, cost in list(services.items())[:5]:
            lines.append(f"  \u2022 {svc}: ${cost:,.2f}")

    # Anomalies
    if anomalies:
        lines.append("")
        severity = state.get("severity", "")
        severity_emoji = {
            "critical": ":rotating_light:",
            "high": ":warning:",
            "medium": ":large_yellow_circle:",
            "low": ":information_source:",
        }.get(severity, ":warning:")
        lines.append(f"{severity_emoji} *Anomalies Detected:*")
        for a in anomalies[:5]:
            lines.append(f"  \u2022 {a.get('description', 'Unknown anomaly')}")

    # Recommendations
    if recommendations:
        total_savings = state.get("total_potential_savings", 0)
        lines.append("")
        lines.append(f":bulb: *Savings Opportunities* (~${total_savings:,.2f}/mo):")
        for r in recommendations[:5]:
            savings = r.get("estimated_monthly_savings", 0)
            lines.append(f"  \u2022 {r.get('description', '')} — save ~${savings:,.2f}/mo")

    # Footer
    lines.append("")
    lines.append("_Reply in thread to ask questions about your spend_ :robot_face:")

    return "\n".join(lines)


def _format_anomaly_alert(state: BillingState) -> str:
    """Format an anomaly alert for Slack."""
    anomalies = state.get("anomalies", [])
    severity = state.get("severity", "")

    # When no anomalies: send a friendly all-clear message instead of a scary alert
    if not anomalies:
        return (
            ":white_check_mark: *Cost Anomaly Check — All Clear*\n\n"
            "No anomalies found in the latest analysis. Your spend looks normal.\n\n"
            "_Reply in thread to ask questions_ :robot_face:"
        )

    severity_emoji = {
        "critical": ":rotating_light:",
        "high": ":warning:",
        "medium": ":large_yellow_circle:",
        "low": ":information_source:",
    }.get(severity, ":warning:")

    severity_label = f" ({severity.upper()})" if severity else ""
    lines = [
        f"{severity_emoji} *Cost Anomaly Alert*{severity_label}",
        "",
    ]

    for a in anomalies:
        lines.append(f"\u2022 {a.get('description', 'Unknown anomaly')}")

    lines.append("")
    lines.append("_Reply in thread for more details_ :robot_face:")

    return "\n".join(lines)


def _format_interactive_response(state: BillingState) -> str:
    """Format a response to an interactive Slack query."""
    # Use the last AI message as the response
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            return msg.content

    return "I wasn't able to find an answer. Could you try rephrasing your question?"


def _build_dashboard_data(state: BillingState) -> dict:
    """Build JSON payload for the Streamlit dashboard."""
    data = {
        "updated_at": datetime.utcnow().isoformat(),
        "daily_spend": state.get("daily_spend"),
        "mtd_spend": state.get("mtd_spend"),
        "forecast": state.get("forecast"),
        "trend_data": state.get("trend_data"),
        "service_breakdown": state.get("service_breakdown"),
        "anomalies": state.get("anomalies"),
        "severity": state.get("severity"),
        "recommendations": state.get("recommendations"),
        "total_potential_savings": state.get("total_potential_savings"),
    }

    # Include tag breakdown if present (populated by weekly deep-dive)
    dashboard_extra = state.get("dashboard_data")
    if dashboard_extra and isinstance(dashboard_extra, dict):
        tag_breakdown = dashboard_extra.get("tag_breakdown")
        if tag_breakdown:
            data["tag_breakdown"] = tag_breakdown

    return data


@trace_operation("reporter_formatting_and_delivery")
def reporter_node(state: BillingState) -> dict:
    """Format and send the report via Slack and prepare dashboard data."""
    settings = get_settings()
    request_type = state.get("request_type", "query")
    print(f"[reporter] Starting. request_type={request_type}", flush=True)
    print(f"[reporter] State messages count: {len(state.get('messages', []))}", flush=True)

    # Log all messages for debugging
    for i, msg in enumerate(state.get("messages", [])):
        msg_type = type(msg).__name__
        content = msg.content[:150] if hasattr(msg, "content") else str(msg)[:150]
        print(f"[reporter]   msg[{i}] ({msg_type}): {content}", flush=True)

    try:
        # Format message based on request type
        if request_type == "report":
            message = _format_daily_report(state)
        elif request_type == "alert":
            message = _format_anomaly_alert(state)
        else:
            message = _format_interactive_response(state)
            print(f"[reporter] Interactive response length: {len(message)}", flush=True)
            print(f"[reporter] Interactive response preview: {message[:200]}", flush=True)

        # Send to Slack — only for scheduled reports/alerts, NOT interactive queries.
        # Interactive queries get their reply posted by the Slack event handler in app.py.
        slack_sent = False
        if request_type in ("report", "alert") and settings.slack_channel_id and settings.slack_secret_arn:
            try:
                send_result = send_slack_message(
                    channel=settings.slack_channel_id,
                    text=message,
                )
                slack_sent = send_result.get("ok", False)
                if not slack_sent:
                    logger.warning(f"Slack send failed: {send_result}")
            except Exception as slack_err:
                logger.warning(f"Slack delivery skipped: {slack_err}")
        else:
            logger.info(f"Skipping Slack send (request_type={request_type})")

        # Build and persist dashboard data (for scheduled reports)
        dashboard_data = None
        if request_type in ("report", "alert"):
            dashboard_data = _build_dashboard_data(state)
            _persist_dashboard_data(dashboard_data)

        return {
            "slack_message": message,
            "dashboard_data": dashboard_data,
            "messages": [AIMessage(content=message)],
        }

    except Exception as e:
        logger.error(f"Reporter error: {e}", exc_info=True)
        # Still return the best response we have, don't swallow the analysis
        fallback = _format_interactive_response(state)
        return {
            "slack_message": fallback or f"Reporter error: {e}",
            "messages": [AIMessage(content=fallback or f"Reporter error: {e}")],
        }
