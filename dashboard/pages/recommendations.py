"""Recommendations page — Cost optimization recommendations sorted by impact."""

import streamlit as st
import pandas as pd
from utils.data_loader import load_dashboard_data

st.title("Recommendations")

data = load_dashboard_data()
recommendations = data.get("recommendations", [])
total_savings = data.get("total_potential_savings", 0)

if not recommendations:
    st.info("No optimization recommendations available yet. Run the optimizer agent to generate recommendations.")
    st.stop()

# Summary metrics
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Total Potential Savings", f"${total_savings:,.2f}/mo")
with col2:
    st.metric("Recommendations", len(recommendations))
with col3:
    annual = total_savings * 12
    st.metric("Annual Impact", f"${annual:,.0f}")

st.divider()

# Type filter
all_types = sorted(set(r.get("type", "unknown") for r in recommendations))
selected_types = st.multiselect(
    "Filter by type",
    options=all_types,
    default=all_types,
    format_func=lambda t: t.replace("_", " ").title(),
)

filtered = [r for r in recommendations if r.get("type", "unknown") in selected_types]

# Recommendation cards
for rec in filtered:
    savings = rec.get("estimated_monthly_savings", 0)
    rec_type = rec.get("type", "unknown").replace("_", " ").title()

    with st.container(border=True):
        cols = st.columns([3, 1, 1])

        with cols[0]:
            st.markdown(f"**{rec_type}**")
            st.write(rec.get("description", ""))
            if rec.get("action"):
                st.caption(f"Action: {rec['action']}")

        with cols[1]:
            st.metric("Monthly Savings", f"${savings:,.2f}")

        with cols[2]:
            if rec.get("resource_id"):
                st.caption(f"Resource: `{rec['resource_id']}`")
            if rec.get("region"):
                st.caption(f"Region: {rec['region']}")

# Summary table
st.divider()
st.subheader("Summary Table")

df = pd.DataFrame([
    {
        "Type": r.get("type", "").replace("_", " ").title(),
        "Description": r.get("description", "")[:80],
        "Savings/mo": f"${r.get('estimated_monthly_savings', 0):,.2f}",
        "Action": r.get("action", ""),
    }
    for r in filtered
])
st.dataframe(df, width="stretch", hide_index=True)
