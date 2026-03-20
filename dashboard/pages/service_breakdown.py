"""Service Breakdown page — Spend by service with treemap and table."""

import streamlit as st
import pandas as pd
from utils.data_loader import get_spend_by_service
from utils.charts import service_treemap, service_bar_chart

st.title("Service Breakdown")

# Date range selector
col1, col2 = st.columns(2)
with col1:
    days = st.selectbox("Time Period", [7, 14, 30, 60, 90], index=2, format_func=lambda d: f"Last {d} days")

services = get_spend_by_service(days=days)

if not services:
    st.info("No service data available for the selected period.")
    st.stop()

total = sum(services.values())
st.metric("Total Spend", f"${total:,.2f}", help=f"Sum of all services over the last {days} days")

st.divider()

# Treemap
st.plotly_chart(service_treemap(services), width="stretch")

# Bar chart
st.plotly_chart(service_bar_chart(services, top_n=15), width="stretch")

# Detail table
st.subheader("All Services")
df = pd.DataFrame([
    {"Service": svc, "Cost": cost, "% of Total": f"{cost / total * 100:.1f}%"}
    for svc, cost in services.items()
])
df["Cost"] = df["Cost"].map(lambda x: f"${x:,.2f}")
st.dataframe(df, width="stretch", hide_index=True)
