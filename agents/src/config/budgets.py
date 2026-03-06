"""
Budget configuration for cost monitoring.

Defines monthly budget targets at the account level and optionally
per-service or per-team. Used by the Reporter to show budget gauges
and by the Anomaly Detector for forecast-based alerts.
"""

import os
import json


# Default monthly budget (USD)
DEFAULT_MONTHLY_BUDGET = float(os.environ.get("MONTHLY_BUDGET", "42000"))

# Optional per-service budgets (set via env var as JSON)
# Example: {"Amazon EC2": 15000, "Amazon RDS": 5000, "Amazon S3": 2000}
_service_budgets_raw = os.environ.get("SERVICE_BUDGETS", "{}")
SERVICE_BUDGETS: dict[str, float] = json.loads(_service_budgets_raw)

# Optional per-team budgets (requires tag-based cost allocation)
# Example: {"engineering": 25000, "data": 10000, "devops": 7000}
_team_budgets_raw = os.environ.get("TEAM_BUDGETS", "{}")
TEAM_BUDGETS: dict[str, float] = json.loads(_team_budgets_raw)

# Alert thresholds as percentage of budget
ALERT_THRESHOLDS = {
    "warning": float(os.environ.get("BUDGET_WARNING_PCT", "80")),   # 80% of budget
    "critical": float(os.environ.get("BUDGET_CRITICAL_PCT", "95")), # 95% of budget
    "exceeded": 100.0,
}


def get_budget_status(current_spend: float, budget: float | None = None) -> dict:
    """
    Calculate budget status for a given spend amount.

    Args:
        current_spend: Current spend in USD.
        budget: Budget target. Defaults to DEFAULT_MONTHLY_BUDGET.

    Returns:
        Dict with budget details and status.
    """
    budget = budget or DEFAULT_MONTHLY_BUDGET

    if budget <= 0:
        return {"status": "no_budget", "percentage": 0}

    pct = (current_spend / budget) * 100

    if pct >= ALERT_THRESHOLDS["exceeded"]:
        status = "exceeded"
    elif pct >= ALERT_THRESHOLDS["critical"]:
        status = "critical"
    elif pct >= ALERT_THRESHOLDS["warning"]:
        status = "warning"
    else:
        status = "ok"

    return {
        "status": status,
        "percentage": round(pct, 1),
        "current_spend": current_spend,
        "budget": budget,
        "remaining": round(budget - current_spend, 2),
    }
