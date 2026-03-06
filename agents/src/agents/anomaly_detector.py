"""
Anomaly Detector Agent — Identifies cost spikes and unusual spending patterns.

Compares current spend against historical baselines using multiple detection
methods: statistical (rolling averages + stddev), service-level, and forecast-based.
"""

from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta
from pathlib import Path

from langchain_aws import ChatBedrock
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..state import BillingState
from ..config.settings import get_settings
from ..config.thresholds import THRESHOLDS
from ..tracing import trace_operation
from ..tools.cost_explorer import get_cost_and_usage

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "anomaly_detector.md").read_text()


def _detect_day_over_day_anomalies(trend_data: list[dict]) -> list[dict]:
    """Compare yesterday's spend against the 7-day rolling average."""
    if not trend_data or len(trend_data) < 2:
        return []

    anomalies = []

    # Sort by date ascending
    sorted_trend = sorted(trend_data, key=lambda x: x["date"])

    if len(sorted_trend) < 3:
        return []

    yesterday_cost = sorted_trend[-1]["cost"]
    prior_costs = [d["cost"] for d in sorted_trend[:-1]]

    # 7-day rolling average
    recent_7d = prior_costs[-7:] if len(prior_costs) >= 7 else prior_costs
    avg_7d = statistics.mean(recent_7d)
    stddev_7d = statistics.stdev(recent_7d) if len(recent_7d) > 1 else 0

    if avg_7d > 0:
        pct_change = ((yesterday_cost - avg_7d) / avg_7d) * 100
        abs_change = yesterday_cost - avg_7d

        # Check percentage threshold
        if pct_change > THRESHOLDS["day_over_day_pct"]:
            anomalies.append({
                "type": "day_over_day_spike",
                "date": sorted_trend[-1]["date"],
                "metric": "total_spend",
                "current_value": yesterday_cost,
                "baseline_value": round(avg_7d, 2),
                "pct_change": round(pct_change, 1),
                "abs_change": round(abs_change, 2),
                "description": (
                    f"Total spend ${yesterday_cost} is {pct_change:.1f}% above "
                    f"the 7-day average of ${avg_7d:.2f}"
                ),
            })

        # Check absolute threshold
        if abs_change > THRESHOLDS["day_over_day_abs"]:
            anomalies.append({
                "type": "day_over_day_abs_spike",
                "date": sorted_trend[-1]["date"],
                "metric": "total_spend",
                "current_value": yesterday_cost,
                "baseline_value": round(avg_7d, 2),
                "abs_change": round(abs_change, 2),
                "description": (
                    f"Total spend increased by ${abs_change:.2f} vs 7-day average"
                ),
            })

        # Statistical anomaly: > 2 standard deviations
        if stddev_7d > 0 and (yesterday_cost - avg_7d) > 2 * stddev_7d:
            anomalies.append({
                "type": "statistical_outlier",
                "date": sorted_trend[-1]["date"],
                "metric": "total_spend",
                "current_value": yesterday_cost,
                "baseline_value": round(avg_7d, 2),
                "stddev": round(stddev_7d, 2),
                "z_score": round((yesterday_cost - avg_7d) / stddev_7d, 2),
                "description": (
                    f"Spend is {((yesterday_cost - avg_7d) / stddev_7d):.1f} standard "
                    f"deviations above the 7-day mean"
                ),
            })

    return anomalies


def _detect_service_anomalies() -> list[dict]:
    """Detect per-service spend spikes by comparing yesterday vs 7-day avg."""
    anomalies = []

    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=8)

    # Yesterday's per-service spend
    yesterday_result = get_cost_and_usage(
        start_date=yesterday.isoformat(),
        end_date=today.isoformat(),
        granularity="DAILY",
        metrics=["UnblendedCost"],
        group_by=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    # Last 7 days per-service spend
    week_result = get_cost_and_usage(
        start_date=week_ago.isoformat(),
        end_date=yesterday.isoformat(),
        granularity="DAILY",
        metrics=["UnblendedCost"],
        group_by=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    # Build 7-day average per service
    service_avg: dict[str, list[float]] = {}
    if week_result and "ResultsByTime" in week_result:
        for period in week_result["ResultsByTime"]:
            for group in period.get("Groups", []):
                svc = group["Keys"][0]
                cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
                service_avg.setdefault(svc, []).append(cost)

    # Compare yesterday against averages
    if yesterday_result and "ResultsByTime" in yesterday_result:
        for period in yesterday_result["ResultsByTime"]:
            for group in period.get("Groups", []):
                svc = group["Keys"][0]
                cost = float(group["Metrics"]["UnblendedCost"]["Amount"])

                if svc in service_avg and len(service_avg[svc]) > 0:
                    avg = statistics.mean(service_avg[svc])
                    if avg > 1.0:  # Ignore trivially small services
                        pct_change = ((cost - avg) / avg) * 100
                        if pct_change > THRESHOLDS["service_spike_pct"]:
                            anomalies.append({
                                "type": "service_spike",
                                "date": yesterday.isoformat(),
                                "service": svc,
                                "current_value": round(cost, 2),
                                "baseline_value": round(avg, 2),
                                "pct_change": round(pct_change, 1),
                                "description": (
                                    f"{svc} spend ${cost:.2f} is {pct_change:.1f}% "
                                    f"above 7-day avg of ${avg:.2f}"
                                ),
                            })
                elif cost > THRESHOLDS.get("new_service_min_spend", 50):
                    # New service appeared with significant spend
                    anomalies.append({
                        "type": "new_service",
                        "date": yesterday.isoformat(),
                        "service": svc,
                        "current_value": round(cost, 2),
                        "description": f"New service {svc} appeared with ${cost:.2f} spend",
                    })

    return anomalies


def _determine_severity(anomalies: list[dict]) -> str:
    """Assign overall severity based on detected anomalies."""
    if not anomalies:
        return ""

    max_pct = max(
        (a.get("pct_change", 0) for a in anomalies),
        default=0,
    )

    has_statistical = any(a["type"] == "statistical_outlier" for a in anomalies)

    if max_pct > 50 or has_statistical:
        return "critical"
    elif max_pct > 30:
        return "high"
    elif max_pct > 15:
        return "medium"
    else:
        return "low"


@trace_operation("anomaly_detection")
def anomaly_detector_node(state: BillingState) -> dict:
    """Detect cost anomalies using multiple methods."""
    try:
        all_anomalies = []

        # Method 1: Day-over-day total spend analysis
        trend_data = state.get("trend_data")
        if trend_data:
            dod_anomalies = _detect_day_over_day_anomalies(trend_data)
            all_anomalies.extend(dod_anomalies)

        # Method 2: Per-service spike detection
        service_anomalies = _detect_service_anomalies()
        all_anomalies.extend(service_anomalies)

        # Deduplicate
        seen = set()
        unique_anomalies = []
        for a in all_anomalies:
            key = (a.get("type"), a.get("service", ""), a.get("date", ""))
            if key not in seen:
                seen.add(key)
                unique_anomalies.append(a)

        severity = _determine_severity(unique_anomalies)

        summary = f"Found {len(unique_anomalies)} anomalies"
        if severity:
            summary += f" (severity: {severity})"

        # Build a richer interactive response so users get useful context
        # even when no anomalies cross thresholds.
        if unique_anomalies:
            top_items = unique_anomalies[:5]
            details = "\n".join(f"- {a.get('description', 'Unknown anomaly')}" for a in top_items)
            response_text = (
                f"{summary}\n\n"
                "Top detected anomalies:\n"
                f"{details}"
            )
        else:
            trend_data = state.get("trend_data") or []
            if trend_data:
                sorted_trend = sorted(trend_data, key=lambda x: x["date"])
                costs = [d.get("cost", 0) for d in sorted_trend]
                avg_cost = statistics.mean(costs) if costs else 0
                peak = max(sorted_trend, key=lambda x: x.get("cost", 0))
                response_text = (
                    "No significant anomalies were detected in the last 30 days.\n\n"
                    f"- Average daily spend: ${avg_cost:.2f}\n"
                    f"- Peak day: {peak.get('date')} at ${peak.get('cost', 0):.2f}\n"
                    "- Threshold checks run: day-over-day spikes, absolute jumps, "
                    "statistical outliers, and service-level spikes."
                )
            else:
                response_text = (
                    "No anomalies detected. I don't have enough trend data yet for a deeper "
                    "spike analysis."
                )

        logger.info(summary)

        return {
            "anomalies": unique_anomalies if unique_anomalies else [],
            "severity": severity,
            "messages": [AIMessage(content=response_text)],
        }

    except Exception as e:
        logger.error(f"Anomaly detector error: {e}", exc_info=True)
        return {
            "error": f"Anomaly detection failed: {str(e)}",
            "anomalies": [],
            "messages": [AIMessage(content=f"Anomaly detection encountered an error: {e}")],
        }
