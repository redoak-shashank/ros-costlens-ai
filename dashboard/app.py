"""
Streamlit Dashboard — AWS Billing Intelligence

Multi-page dashboard for viewing cost data, anomalies, recommendations,
and interacting with the billing intelligence agents via chat.
"""

import streamlit as st
from utils.account_context import ACCOUNT_SESSION_KEY, get_available_accounts, get_selected_account

st.set_page_config(
    page_title="AWS Billing Intelligence",
    page_icon=":chart_with_upwards_trend:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _switch_account():
    """Clear Streamlit caches when account selection changes."""
    st.cache_data.clear()
    st.cache_resource.clear()


accounts = get_available_accounts()
current = get_selected_account()
default_index = accounts.index(current) if current in accounts else 0
st.sidebar.selectbox(
    "Account",
    options=accounts,
    index=default_index,
    key=ACCOUNT_SESSION_KEY,
    on_change=_switch_account,
)

# Define pages
overview = st.Page("pages/overview.py", title="Overview", icon=":material/dashboard:")
services = st.Page("pages/service_breakdown.py", title="Service Breakdown", icon=":material/stacked_bar_chart:")
anomalies = st.Page("pages/anomalies.py", title="Anomalies", icon=":material/warning:")
weekday_spend = st.Page(
    "pages/weekday_spend.py",
    title="Weekday Spend",
    icon=":material/finance:",
)
recommend = st.Page("pages/recommendations.py", title="Recommendations", icon=":material/lightbulb:")
tags = st.Page("pages/tag_analysis.py", title="Tag Analysis", icon=":material/label:")
ask = st.Page("pages/ask_question.py", title="Ask a Question", icon=":material/smart_toy:")

pg = st.navigation([overview, services, anomalies, weekday_spend, recommend, tags, ask])
pg.run()
