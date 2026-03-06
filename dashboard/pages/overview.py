"""Overview page — MTD spend, daily trends, budget gauge, forecast."""

import os
import streamlit as st
from utils.data_loader import (
    get_daily_spend,
    get_forecast,
    get_mtd_spend,
    get_runtime_config_diagnostics,
    get_spend_by_service,
    test_aws_credentials,
)
from utils.charts import daily_spend_chart, budget_gauge


def _get_monthly_budget() -> float:
    """Read monthly budget from Streamlit secrets first, then env fallback."""
    try:
        val = st.secrets.get("app", {}).get(
            "monthly_budget",
            os.environ.get("MONTHLY_BUDGET", "1000"),
        )
    except Exception:
        val = os.environ.get("MONTHLY_BUDGET", "1000")

    try:
        return float(val)
    except (TypeError, ValueError):
        return 1000.0


def _debug_enabled() -> bool:
    """Enable diagnostics via app.debug_config in secrets or DASHBOARD_DEBUG env."""
    try:
        app_cfg = st.secrets.get("app", {})
        if app_cfg.get("debug_config", False):
            return True
    except Exception:
        pass

    return os.environ.get("DASHBOARD_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


MONTHLY_BUDGET = _get_monthly_budget()

st.title("Overview")

if _debug_enabled():
    with st.expander("Deployment diagnostics", expanded=True):
        st.caption("Safe checks only - no secret values are displayed.")
        st.json(get_runtime_config_diagnostics())
        ok, message = test_aws_credentials()
        if ok:
            st.success(f"AWS credential check passed: {message}")
        else:
            st.error(f"AWS credential check failed: {message}")

# ── Metric cards ─────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)

mtd = get_mtd_spend()
forecast = get_forecast()
trend = get_daily_spend(days=30)

yesterday_cost = trend[-1]["cost"] if trend else 0
day_before_cost = trend[-2]["cost"] if len(trend) >= 2 else 0
dod_delta = yesterday_cost - day_before_cost

with col1:
    st.metric("Yesterday's Spend", f"${yesterday_cost:,.2f}", f"${dod_delta:+,.2f}")

with col2:
    st.metric("MTD Spend", f"${mtd:,.2f}")

with col3:
    st.metric("Forecast (EOM)", f"${forecast:,.2f}")

with col4:
    budget_pct = (mtd / MONTHLY_BUDGET * 100) if MONTHLY_BUDGET > 0 else 0
    st.metric("Budget Used", f"{budget_pct:.1f}%", f"${MONTHLY_BUDGET - mtd:,.0f} remaining")

st.divider()

# ── Charts ───────────────────────────────────────────────────────────
left, right = st.columns([2, 1])

with left:
    st.plotly_chart(daily_spend_chart(trend), use_container_width=True)

with right:
    st.plotly_chart(budget_gauge(mtd, MONTHLY_BUDGET), use_container_width=True)

# ── Top services summary ────────────────────────────────────────────
st.subheader("Top Services (Last 30 Days)")
services = get_spend_by_service(days=30)
if services:
    for svc, cost in list(services.items())[:8]:
        pct = (cost / sum(services.values())) * 100 if services else 0
        st.progress(min(pct / 100, 1.0), text=f"{svc}: ${cost:,.2f} ({pct:.1f}%)")
else:
    st.info("No service data available yet.")
