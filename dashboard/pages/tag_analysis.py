"""Tag Analysis page — Cost allocation by tags (team, project, environment)."""

import os
import streamlit as st
import pandas as pd
import plotly.express as px
from utils.data_loader import load_dashboard_data

st.title("Tag Analysis")

st.info(
    "Tag-based cost allocation requires CUR data with resource tags enabled. "
    "Ensure your AWS resources are tagged with `team`, `project`, and `environment` tags."
)

data = load_dashboard_data()

# For demonstration, try to pull tag data from the dashboard payload
# In production, this queries Athena directly
tag_data = data.get("tag_breakdown", None)

if not tag_data:
    # Show a placeholder with instructions
    st.warning("Tag data is not available yet. It will populate after the weekly deep-dive report runs.")

    st.subheader("Setup Instructions")
    st.markdown("""
    1. **Tag your resources** with consistent keys: `team`, `project`, `environment`
    2. **Activate cost allocation tags** in the AWS Billing Console
    3. **Enable tags in CUR** — our Terraform already includes `SPLIT_COST_ALLOCATION_DATA`
    4. **Wait for CUR refresh** — tags appear in CUR data within 24-48 hours
    """)

    # Show example of what the page will look like
    st.subheader("Example View")
    example_data = {
        "Team": ["Engineering", "Engineering", "Data", "Data", "DevOps", "DevOps"],
        "Service": ["EC2", "RDS", "S3", "EMR", "EC2", "CloudWatch"],
        "Cost": [8500, 3200, 1800, 4500, 2100, 450],
    }
    df = pd.DataFrame(example_data)
    fig = px.bar(
        df, x="Team", y="Cost", color="Service",
        title="Spend by Team and Service (Example Data)",
        labels={"Cost": "Cost (USD)"},
    )
    st.plotly_chart(fig, use_container_width=True)
    st.stop()

# ── Real tag data visualization ──────────────────────────────────────
# Assuming tag_data is a list of dicts: [{team, project, environment, service, cost}, ...]
df = pd.DataFrame(tag_data)

# Team breakdown
if "team" in df.columns:
    st.subheader("Spend by Team")
    team_spend = df.groupby("team")["cost"].sum().sort_values(ascending=False)
    fig = px.bar(
        x=team_spend.index, y=team_spend.values,
        title="Total Spend by Team",
        labels={"x": "Team", "y": "Cost (USD)"},
    )
    st.plotly_chart(fig, use_container_width=True)

# Project breakdown
if "project" in df.columns:
    st.subheader("Spend by Project")
    project_spend = df.groupby("project")["cost"].sum().sort_values(ascending=False).head(15)
    fig = px.bar(
        x=project_spend.index, y=project_spend.values,
        title="Top Projects by Spend",
        labels={"x": "Project", "y": "Cost (USD)"},
    )
    st.plotly_chart(fig, use_container_width=True)

# Environment breakdown
if "environment" in df.columns:
    st.subheader("Spend by Environment")
    env_spend = df.groupby("environment")["cost"].sum()
    fig = px.pie(
        names=env_spend.index, values=env_spend.values,
        title="Spend Distribution by Environment",
    )
    st.plotly_chart(fig, use_container_width=True)

# Detail table
st.subheader("Detailed Tag Breakdown")
st.dataframe(df, use_container_width=True, hide_index=True)
