"""Weekday Spend page — rolling week view with weekday high/low context."""

import pandas as pd
import streamlit as st

from utils import charts as chart_utils
from utils.data_loader import get_daily_spend

st.title("Weekday Spend Pattern")
st.caption(
    "Simple weekday range view: gray whiskers show high/low from recent history, "
    "green dots show the latest value for each weekday, and dark green marks the most recent day."
)

# Use 8 weeks of history for stable weekday high/low context.
trend = get_daily_spend(days=56)
if not trend:
    st.info("No daily spend data available yet.")
    st.stop()

df = pd.DataFrame(trend)
if df.empty or "date" not in df.columns or "cost" not in df.columns:
    st.info("Daily spend data is not in the expected format.")
    st.stop()

df["date"] = pd.to_datetime(df["date"], errors="coerce")
df["cost"] = pd.to_numeric(df["cost"], errors="coerce")
df = df.dropna(subset=["date", "cost"]).sort_values("date")
if df.empty:
    st.info("No valid daily spend points found.")
    st.stop()

latest_week = df.tail(7).copy()
latest_day = latest_week.tail(1).iloc[0]

col1, col2, col3 = st.columns(3)
with col1:
    st.metric(
        "Most Recent Day",
        f"${latest_day['cost']:,.2f}",
        help=f"Date: {latest_day['date'].date()}",
    )
with col2:
    st.metric("Rolling 7-Day Total", f"${latest_week['cost'].sum():,.2f}")
with col3:
    st.metric("Rolling 7-Day Avg", f"${latest_week['cost'].mean():,.2f}")

st.divider()
chart_fn = getattr(chart_utils, "rolling_weekday_range_chart", None)
if chart_fn:
    st.plotly_chart(chart_fn(trend, history_days=56), width="stretch")
else:
    st.warning(
        "Using fallback chart for this run. Restart Streamlit to load the new weekday range chart."
    )
    st.plotly_chart(chart_utils.daily_spend_chart(trend, height=420), width="stretch")

st.subheader("Latest Rolling Week")
latest_week["weekday"] = latest_week["date"].dt.day_name()
latest_week["date"] = latest_week["date"].dt.date.astype(str)
latest_week["cost"] = latest_week["cost"].map(lambda x: f"${x:,.2f}")

display = latest_week.rename(
    columns={
        "date": "Date",
        "weekday": "Day",
        "cost": "Spend",
    }
)[["Date", "Day", "Spend"]]

st.dataframe(display, width="stretch", hide_index=True)
