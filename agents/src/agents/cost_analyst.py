"""
Cost Analyst Agent — Queries spend data, computes trends, answers cost questions.

Uses both Cost Explorer API (quick summaries) and Athena/CUR (deep analysis)
depending on the complexity of the request.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

import boto3
from langchain_aws import ChatBedrock
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..state import BillingState
from ..config.settings import get_settings
from ..tracing import trace_operation
from ..tools.cost_explorer import (
    get_cost_and_usage,
    get_cost_forecast,
    get_dimension_values,
)
from ..tools.athena_query import run_athena_query

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "cost_analyst.md").read_text()
_cur_table_cache: str | None = None


def _extract_current_question(message: str) -> str:
    """Extract raw user question when memory context is prepended by app.py."""
    if not message:
        return ""
    marker = "[Current question]"
    if marker in message:
        return message.split(marker, 1)[1].strip()
    return message.strip()


def _resolve_cur_table_name() -> str:
    """
    Resolve CUR table name in Athena database.

    Prefers common names like `cur`, otherwise picks a table containing
    `cur`/`cost` in its name. Cached per runtime process.
    """
    global _cur_table_cache
    if _cur_table_cache:
        return _cur_table_cache

    settings = get_settings()
    glue = boto3.client("glue", region_name=settings.aws_region)
    names: list[str] = []

    paginator = glue.get_paginator("get_tables")
    for page in paginator.paginate(DatabaseName=settings.athena_database):
        for tbl in page.get("TableList", []):
            name = tbl.get("Name")
            if name:
                names.append(name)

    if not names:
        # Conservative fallback used throughout this project.
        _cur_table_cache = "cur"
        return _cur_table_cache

    lowered = {n.lower(): n for n in names}
    if "cur" in lowered:
        _cur_table_cache = lowered["cur"]
    else:
        preferred = next(
            (n for n in names if "cur" in n.lower() or "cost" in n.lower()),
            names[0],
        )
        _cur_table_cache = preferred

    logger.info(f"Resolved CUR table: {_cur_table_cache}")
    return _cur_table_cache


def _detect_service_code(question: str) -> str | None:
    """Best-effort mapping of service mentions to CUR product codes."""
    q = question.lower()
    mappings = {
        "security hub": "AWSSecurityHub",
        "guardduty": "AmazonGuardDuty",
        "bedrock": "AmazonBedrock",
        "ec2": "AmazonEC2",
        "rds": "AmazonRDS",
        "s3": "AmazonS3",
        "lambda": "AWSLambda",
        "vpc": "AmazonVPC",
    }
    for phrase, code in mappings.items():
        if phrase in q:
            return code
    return None


def _extract_top_n(question: str, default: int = 10, max_limit: int = 50) -> int:
    """Extract requested top-N from prompt, clamped to a safe limit."""
    m = re.search(r"\btop\s+(\d{1,2})\b", question.lower())
    if not m:
        return default
    return max(1, min(int(m.group(1)), max_limit))


def _extract_date(question: str) -> str | None:
    """Extract ISO date from a question (YYYY-MM-DD)."""
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", question)
    return m.group(1) if m else None


def _time_filter_sql(question: str, explicit_date: str | None = None) -> str:
    """
    Build Athena SQL time predicate from natural language.

    Priority:
    1) explicit ISO date
    2) yesterday/today
    3) last 7 days / last week
    4) default: last 30 days
    """
    if explicit_date:
        return f"date(line_item_usage_start_date) = DATE '{explicit_date}'"

    q = question.lower()
    if "yesterday" in q:
        return "date(line_item_usage_start_date) = date_add('day', -1, current_date)"
    if "today" in q:
        return "date(line_item_usage_start_date) = current_date"
    if any(s in q for s in ("last 7 days", "past 7 days", "last week", "past week")):
        return "line_item_usage_start_date >= date_add('day', -7, current_date)"

    return "line_item_usage_start_date >= date_add('day', -30, current_date)"


def _looks_like_athena_deep_dive(question: str) -> bool:
    """Heuristic to decide if we should auto-run Athena deep-dive SQL."""
    q = question.lower()
    signals = (
        "account", "accounts", "region", "regions", "resource", "resources",
        "group by", "root cause", "break down", "breakdown", "by account",
        "by region", "usage type", "line item",
    )
    return any(s in q for s in signals)


def _format_athena_result(title: str, rows: list[dict], max_rows: int = 10) -> str:
    """Readable markdown formatting for Athena result rows."""
    if not rows:
        return f"{title}\n\nNo matching rows found in CUR for this filter."

    def _to_float(v) -> float | None:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _shorten(value: str, limit: int = 70) -> str:
        if len(value) <= limit:
            return value
        return value[: limit - 3] + "..."

    def _pretty_key(key: str) -> str:
        return key.replace("_", " ").title()

    def _fmt_cell(key: str, value) -> str:
        if value is None:
            return "-"
        if key == "cost":
            n = _to_float(value)
            return f"${n:,.2f}" if n is not None else str(value)
        if "percent" in key or key.endswith("_pct") or key.endswith("_share"):
            n = _to_float(value)
            return f"{n:.2f}%" if n is not None else str(value)
        text = str(value)
        if key in ("resource_id", "arn"):
            return _shorten(text, 90)
        return _shorten(text, 50)

    shown = rows[:max_rows]

    # Stable, readable column order when available.
    preferred = ["account_id", "region", "service", "resource_id", "cost"]
    sample_cols = list(rows[0].keys())
    ordered_cols = [c for c in preferred if c in sample_cols] + [
        c for c in sample_cols if c not in preferred
    ]
    # Keep table compact for chat.
    ordered_cols = ordered_cols[:6]

    lines = [title, "", f"Returned {len(rows)} rows (showing up to {len(shown)})."]

    costs = [_to_float(r.get("cost")) for r in shown if "cost" in r]
    costs = [c for c in costs if c is not None]
    if costs:
        lines.append(f"- Total cost in shown rows: **${sum(costs):,.2f}**")
        top_row = max(
            (r for r in shown if _to_float(r.get("cost")) is not None),
            key=lambda r: _to_float(r.get("cost")) or 0,
            default=None,
        )
        if top_row:
            top_service = top_row.get("service", "unknown service")
            top_cost = _to_float(top_row.get("cost")) or 0.0
            lines.append(f"- Biggest cost driver: **{top_service}** at **${top_cost:,.2f}**")

    lines.append("")
    lines.append("| " + " | ".join(_pretty_key(c) for c in ordered_cols) + " |")
    lines.append("| " + " | ".join("---" for _ in ordered_cols) + " |")
    for row in shown:
        lines.append("| " + " | ".join(_fmt_cell(c, row.get(c)) for c in ordered_cols) + " |")

    return "\n".join(lines)


def _run_athena_deep_dive_if_needed(question: str) -> str | None:
    """
    Execute curated Athena templates for deep-dive prompts.

    Returns formatted text on success, otherwise None (caller falls back).
    """
    if not _looks_like_athena_deep_dive(question):
        return None

    table_name = _resolve_cur_table_name()
    service_code = _detect_service_code(question)
    top_n = _extract_top_n(question)
    specific_date = _extract_date(question)
    ql = question.lower()

    # Template 1: account/region breakdown (last 30 days)
    if "account" in ql and "region" in ql:
        service_filter = (
            f"AND line_item_product_code = '{service_code}'" if service_code else ""
        )
        sql = f"""
            SELECT
                line_item_usage_account_id AS account_id,
                product_region AS region,
                ROUND(SUM(line_item_unblended_cost), 2) AS cost
            FROM {table_name}
            WHERE line_item_usage_start_date >= date_add('day', -30, current_date)
              AND line_item_unblended_cost > 0
              {service_filter}
            GROUP BY 1, 2
            ORDER BY 3 DESC
            LIMIT {top_n}
        """
        rows = run_athena_query(query=sql, max_results=top_n)
        return _format_athena_result(
            "Athena deep-dive: account/region cost breakdown (last 30 days)", rows
        )

    # Template 2: top resources for a specific day (or recent spike day)
    if "resource" in ql or "root cause" in ql:
        date_filter = _time_filter_sql(question, specific_date)
        service_filter = (
            f"AND line_item_product_code = '{service_code}'" if service_code else ""
        )
        sql = f"""
            SELECT
                COALESCE(line_item_resource_id, '(no-resource-id)') AS resource_id,
                line_item_product_code AS service,
                ROUND(SUM(line_item_unblended_cost), 2) AS cost
            FROM {table_name}
            WHERE {date_filter}
              AND line_item_unblended_cost > 0
              {service_filter}
            GROUP BY 1, 2
            ORDER BY 3 DESC
            LIMIT {top_n}
        """
        rows = run_athena_query(query=sql, max_results=top_n)
        return _format_athena_result(
            "Athena deep-dive: top cost-driving resources", rows
        )

    return None


def _get_yesterday_spend() -> dict:
    """Pull yesterday's total spend and per-service breakdown."""
    yesterday = datetime.utcnow().date() - timedelta(days=1)
    start = yesterday.isoformat()
    end = datetime.utcnow().date().isoformat()

    # Total spend
    total_result = get_cost_and_usage(
        start_date=start,
        end_date=end,
        granularity="DAILY",
        metrics=["UnblendedCost", "UsageQuantity"],
    )

    # Per-service breakdown
    service_result = get_cost_and_usage(
        start_date=start,
        end_date=end,
        granularity="DAILY",
        metrics=["UnblendedCost"],
        group_by=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    total_amount = 0.0
    services = {}

    if total_result and "ResultsByTime" in total_result:
        for period in total_result["ResultsByTime"]:
            total_amount = float(
                period.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0)
            )

    if service_result and "ResultsByTime" in service_result:
        for period in service_result["ResultsByTime"]:
            for group in period.get("Groups", []):
                svc_name = group["Keys"][0]
                svc_cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
                if svc_cost > 0.01:
                    services[svc_name] = round(svc_cost, 2)

    return {
        "date": start,
        "total": round(total_amount, 2),
        "services": dict(sorted(services.items(), key=lambda x: x[1], reverse=True)),
    }


def _get_mtd_spend() -> dict:
    """Pull month-to-date spend."""
    today = datetime.utcnow().date()
    first_of_month = today.replace(day=1)

    result = get_cost_and_usage(
        start_date=first_of_month.isoformat(),
        end_date=today.isoformat(),
        granularity="MONTHLY",
        metrics=["UnblendedCost"],
    )

    mtd_total = 0.0
    if result and "ResultsByTime" in result:
        for period in result["ResultsByTime"]:
            mtd_total = float(
                period.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0)
            )

    return {
        "period_start": first_of_month.isoformat(),
        "period_end": today.isoformat(),
        "total": round(mtd_total, 2),
    }


def _get_forecast() -> dict:
    """Get end-of-month cost forecast."""
    today = datetime.utcnow().date()
    # Forecast from tomorrow to end of month
    import calendar

    last_day = calendar.monthrange(today.year, today.month)[1]
    end_of_month = today.replace(day=last_day)

    start = (today + timedelta(days=1)).isoformat()
    end = (end_of_month + timedelta(days=1)).isoformat()

    result = get_cost_forecast(
        start_date=start,
        end_date=end,
        granularity="MONTHLY",
        metric="UNBLENDED_COST",
    )

    forecast_amount = 0.0
    if result and "Total" in result:
        forecast_amount = float(result["Total"].get("Amount", 0))

    return {
        "forecast_total": round(forecast_amount, 2),
        "period_end": end_of_month.isoformat(),
    }


def _get_trend_data(days: int = 14) -> list[dict]:
    """Pull daily spend for the last N days for trend analysis."""
    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=days)

    result = get_cost_and_usage(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        granularity="DAILY",
        metrics=["UnblendedCost"],
    )

    trend = []
    if result and "ResultsByTime" in result:
        for period in result["ResultsByTime"]:
            trend.append({
                "date": period["TimePeriod"]["Start"],
                "cost": round(
                    float(period.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0)),
                    2,
                ),
            })

    return trend


def _get_weekly_service_breakdown() -> dict:
    """Pull per-service spend for the last 7 days using Cost Explorer."""
    today = datetime.utcnow().date()
    week_ago = today - timedelta(days=7)

    this_week = get_cost_and_usage(
        start_date=week_ago.isoformat(),
        end_date=today.isoformat(),
        granularity="DAILY",
        metrics=["UnblendedCost"],
        group_by=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    prior_week = get_cost_and_usage(
        start_date=(week_ago - timedelta(days=7)).isoformat(),
        end_date=week_ago.isoformat(),
        granularity="DAILY",
        metrics=["UnblendedCost"],
        group_by=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    def _sum_by_service(result: dict) -> dict[str, float]:
        services: dict[str, float] = {}
        if result and "ResultsByTime" in result:
            for period in result["ResultsByTime"]:
                for group in period.get("Groups", []):
                    svc = group["Keys"][0]
                    cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
                    services[svc] = services.get(svc, 0) + cost
        return {k: round(v, 2) for k, v in services.items() if v > 0.01}

    this_week_svc = _sum_by_service(this_week)
    prior_week_svc = _sum_by_service(prior_week)

    # Calculate week-over-week changes
    wow = {}
    for svc, cost in this_week_svc.items():
        prev = prior_week_svc.get(svc, 0)
        pct_change = ((cost - prev) / prev * 100) if prev > 0 else 0
        wow[svc] = {
            "this_week": cost,
            "prior_week": round(prev, 2),
            "change_pct": round(pct_change, 1),
        }

    return {
        "services": dict(sorted(this_week_svc.items(), key=lambda x: x[1], reverse=True)),
        "week_over_week": wow,
    }


def _get_tag_breakdown() -> list[dict]:
    """
    Pull tag-based cost allocation from CUR via Athena.

    Queries for team, project, and environment tags over the last 30 days.
    Returns a list of dicts suitable for the dashboard tag_analysis page.
    """
    settings = get_settings()

    if not settings.athena_database or not settings.athena_workgroup:
        logger.warning("Athena not configured — skipping tag breakdown")
        return []

    query = f"""
        SELECT
            COALESCE(resource_tags_user_team, 'untagged') AS team,
            COALESCE(resource_tags_user_project, 'untagged') AS project,
            COALESCE(resource_tags_user_environment, 'untagged') AS environment,
            line_item_product_code AS service,
            ROUND(SUM(line_item_unblended_cost), 2) AS cost
        FROM {settings.athena_database}.cur
        WHERE line_item_usage_start_date >= date_add('day', -30, current_date)
          AND line_item_unblended_cost > 0
        GROUP BY 1, 2, 3, 4
        HAVING SUM(line_item_unblended_cost) > 1.0
        ORDER BY 5 DESC
        LIMIT 200
    """

    try:
        results = run_athena_query(query=query, max_results=200)
        # Convert string costs to floats
        for row in results:
            if "cost" in row and row["cost"] is not None:
                row["cost"] = float(row["cost"])
        return results
    except Exception as e:
        logger.warning(f"Tag breakdown query failed: {e}")
        return []


@trace_operation("cost_analyst_data_gathering")
def cost_analyst_node(state: BillingState) -> dict:
    """
    Gather cost data based on the request type.

    For daily reports: pull all standard metrics via Cost Explorer.
    For weekly reports: pull everything + CUR deep-dive via Athena.
    For interactive queries: use LLM to determine what data to pull.
    """
    settings = get_settings()
    request_type = state.get("request_type", "query")
    print(f"[cost_analyst] Starting. request_type={request_type}", flush=True)

    # Check if this is a weekly report by inspecting the user message
    is_weekly = False
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage) and "weekly" in msg.content.lower():
            is_weekly = True
            break

    try:
        if request_type == "report":
            # Scheduled report — pull everything
            daily = _get_yesterday_spend()
            mtd = _get_mtd_spend()
            forecast = _get_forecast()
            trend = _get_trend_data(days=14 if not is_weekly else 30)

            result = {
                "daily_spend": daily,
                "mtd_spend": mtd,
                "forecast": forecast,
                "trend_data": trend,
                "service_breakdown": {"services": daily.get("services", {})},
            }

            summary = (
                f"Cost analysis complete. Yesterday: ${daily['total']}, "
                f"MTD: ${mtd['total']}, Forecast: ${forecast['forecast_total']}"
            )

            # Weekly deep-dive: add week-over-week and tag breakdown
            if is_weekly:
                wow = _get_weekly_service_breakdown()
                result["service_breakdown"] = wow

                tag_data = _get_tag_breakdown()
                if tag_data:
                    result["dashboard_data"] = {"tag_breakdown": tag_data}

                summary += (
                    f". Weekly deep-dive: {len(wow.get('services', {}))} services analysed, "
                    f"{len(tag_data)} tag allocation rows"
                )

            result["messages"] = [AIMessage(content=summary)]
            return result

        else:
            # Interactive query — use LLM to decide what to pull
            print("[cost_analyst] Interactive query mode — pulling data + LLM", flush=True)
            llm = ChatBedrock(
                model_id=settings.bedrock_model_id,
                region_name=settings.aws_region,
                model_kwargs={"temperature": 0, "max_tokens": 1024},
            )

            # Get the user's question
            user_question = ""
            for msg in reversed(state.get("messages", [])):
                if isinstance(msg, HumanMessage):
                    user_question = _extract_current_question(msg.content)
                    break

            # Pull basic data and let the LLM interpret
            print("[cost_analyst] Pulling yesterday spend...", flush=True)
            daily = _get_yesterday_spend()
            print(f"[cost_analyst] Yesterday: ${daily.get('total', '?')}", flush=True)
            mtd = _get_mtd_spend()
            print(f"[cost_analyst] MTD: ${mtd.get('total', '?')}", flush=True)
            trend = _get_trend_data(days=30)
            print(f"[cost_analyst] Trend: {len(trend)} data points", flush=True)

            # If this is clearly a deep-dive request, attempt curated Athena execution.
            # On any failure we fall back to existing CE + LLM path.
            athena_auto_error = None
            try:
                athena_answer = _run_athena_deep_dive_if_needed(user_question)
                if athena_answer:
                    print("[cost_analyst] Athena deep-dive executed successfully", flush=True)
                    return {
                        "daily_spend": daily,
                        "mtd_spend": mtd,
                        "trend_data": trend,
                        "athena_auto_executed": True,
                        "athena_auto_error": None,
                        "messages": [AIMessage(content=athena_answer)],
                    }
            except Exception as athena_err:
                logger.warning(f"Athena deep-dive fallback to LLM: {athena_err}")
                print(f"[cost_analyst] Athena deep-dive failed, fallback: {athena_err}", flush=True)
                athena_auto_error = str(athena_err)

            context = json.dumps(
                {"yesterday": daily, "mtd": mtd, "trend_last_30d": trend},
                indent=2,
            )

            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(
                    content=(
                        f"User question: {user_question}\n\n"
                        f"Available cost data:\n{context}\n\n"
                        "Analyze this data to answer the user's question. "
                        "If you need more granular data (like per-resource or tag-based), "
                        "mention what Athena query would help."
                    )
                ),
            ]

            print("[cost_analyst] Calling LLM for analysis...", flush=True)
            response = llm.invoke(messages)
            print(f"[cost_analyst] LLM response length: {len(response.content)}", flush=True)
            print(f"[cost_analyst] LLM response preview: {response.content[:200]}", flush=True)

            return {
                "daily_spend": daily,
                "mtd_spend": mtd,
                "trend_data": trend,
                "athena_auto_executed": False,
                "athena_auto_error": athena_auto_error,
                "messages": [AIMessage(content=response.content)],
            }

    except Exception as e:
        logger.error(f"Cost analyst error: {e}", exc_info=True)
        print(f"[cost_analyst] ERROR: {type(e).__name__}: {e}", flush=True)
        return {
            "error": f"Cost analyst failed: {str(e)}",
            "messages": [AIMessage(content=f"I encountered an error pulling cost data: {e}")],
        }
