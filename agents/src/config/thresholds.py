"""
Anomaly detection thresholds.

These can be overridden via environment variables for per-environment tuning.
"""

import os

THRESHOLDS = {
    # Day-over-day percentage change to flag as anomaly
    "day_over_day_pct": float(os.environ.get("ANOMALY_DAY_PCT", "20")),

    # Day-over-day absolute dollar change
    "day_over_day_abs": float(os.environ.get("ANOMALY_DAY_ABS", "100")),

    # Week-over-week percentage change
    "week_over_week_pct": float(os.environ.get("ANOMALY_WEEK_PCT", "15")),

    # Forecasted spend exceeds budget by this percentage
    "forecast_over_budget_pct": float(os.environ.get("ANOMALY_FORECAST_PCT", "10")),

    # Per-service spike percentage
    "service_spike_pct": float(os.environ.get("ANOMALY_SERVICE_PCT", "25")),

    # Flag new services spending more than this amount
    "new_service_min_spend": float(os.environ.get("ANOMALY_NEW_SERVICE_MIN", "50")),
}
