"""Anomalies page — Timeline and detail cards for detected cost anomalies."""

import streamlit as st
from utils.data_loader import load_dashboard_data
from utils.charts import anomaly_timeline

st.title("Anomalies")

data = load_dashboard_data()
anomalies = data.get("anomalies", [])
severity = data.get("severity", "")

if not anomalies:
    st.success("No anomalies detected in the latest analysis.")
    st.info("Anomaly checks run every 4 hours via EventBridge.")
    st.stop()

# Severity banner
severity_config = {
    "critical": ("error", ":rotating_light: Critical anomalies detected"),
    "high": ("warning", ":warning: High-severity anomalies detected"),
    "medium": ("info", "Medium-severity anomalies detected"),
    "low": ("info", "Low-severity anomalies detected"),
}
banner_type, banner_text = severity_config.get(severity, ("info", "Anomalies detected"))
getattr(st, banner_type)(banner_text)

# Timeline chart
st.plotly_chart(anomaly_timeline(anomalies), width="stretch")

st.divider()

# Detail cards
st.subheader(f"Detected Anomalies ({len(anomalies)})")

for i, anomaly in enumerate(anomalies):
    with st.expander(
        f"{anomaly.get('type', 'unknown').replace('_', ' ').title()} — "
        f"{anomaly.get('date', 'N/A')}",
        expanded=(i < 3),
    ):
        cols = st.columns(3)
        with cols[0]:
            st.metric("Current", f"${anomaly.get('current_value', 0):,.2f}")
        with cols[1]:
            st.metric("Baseline", f"${anomaly.get('baseline_value', 0):,.2f}")
        with cols[2]:
            pct = anomaly.get("pct_change", 0)
            st.metric("Change", f"{pct:+.1f}%")

        if anomaly.get("service"):
            st.caption(f"Service: {anomaly['service']}")

        st.write(anomaly.get("description", ""))
