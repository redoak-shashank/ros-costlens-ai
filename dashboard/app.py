"""
Streamlit Dashboard — AWS Billing Intelligence

Multi-page dashboard for viewing cost data, anomalies, recommendations,
and interacting with the billing intelligence agents via chat.
"""

import streamlit as st

st.set_page_config(
    page_title="AWS Billing Intelligence",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Define pages
overview = st.Page("pages/overview.py", title="Overview", icon=":material/dashboard:")
services = st.Page("pages/service_breakdown.py", title="Service Breakdown", icon=":material/stacked_bar_chart:")
anomalies = st.Page("pages/anomalies.py", title="Anomalies", icon=":material/warning:")
recommend = st.Page("pages/recommendations.py", title="Recommendations", icon=":material/lightbulb:")
tags = st.Page("pages/tag_analysis.py", title="Tag Analysis", icon=":material/label:")
ask = st.Page("pages/ask_question.py", title="Ask a Question", icon=":material/smart_toy:")

pg = st.navigation([overview, services, anomalies, recommend, tags, ask])
pg.run()
