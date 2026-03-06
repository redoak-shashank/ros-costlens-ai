"""
Reusable Plotly chart builders for the dashboard.
"""

from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import pandas as pd


def daily_spend_chart(trend_data: list[dict], height: int = 350) -> go.Figure:
    """Create a daily spend line chart."""
    if not trend_data:
        return go.Figure().update_layout(title="No data available")

    df = pd.DataFrame(trend_data)
    df["date"] = pd.to_datetime(df["date"])

    fig = px.line(
        df,
        x="date",
        y="cost",
        title="Daily Spend Trend",
        labels={"cost": "Cost (USD)", "date": "Date"},
    )
    fig.update_layout(
        height=height,
        margin=dict(l=20, r=20, t=40, b=20),
        hovermode="x unified",
    )
    fig.update_traces(
        line=dict(color="#2563eb", width=2),
        fill="tozeroy",
        fillcolor="rgba(37, 99, 235, 0.1)",
    )
    return fig


def service_treemap(services: dict[str, float], height: int = 400) -> go.Figure:
    """Create a treemap of spend by service."""
    if not services:
        return go.Figure().update_layout(title="No data available")

    labels = list(services.keys())
    values = list(services.values())

    fig = go.Figure(go.Treemap(
        labels=labels,
        parents=[""] * len(labels),
        values=values,
        textinfo="label+value",
        texttemplate="%{label}<br>$%{value:,.2f}",
        hovertemplate="%{label}: $%{value:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        title="Spend by Service",
        height=height,
        margin=dict(l=10, r=10, t=40, b=10),
    )
    return fig


def service_bar_chart(services: dict[str, float], top_n: int = 10, height: int = 350) -> go.Figure:
    """Create a horizontal bar chart of top services by spend."""
    if not services:
        return go.Figure().update_layout(title="No data available")

    # Take top N
    items = list(services.items())[:top_n]
    labels = [item[0] for item in reversed(items)]
    values = [item[1] for item in reversed(items)]

    fig = go.Figure(go.Bar(
        x=values,
        y=labels,
        orientation="h",
        marker_color="#2563eb",
        text=[f"${v:,.2f}" for v in values],
        textposition="outside",
    ))
    fig.update_layout(
        title=f"Top {top_n} Services by Spend",
        height=height,
        margin=dict(l=20, r=80, t=40, b=20),
        xaxis_title="Cost (USD)",
    )
    return fig


def budget_gauge(current: float, budget: float, height: int = 250) -> go.Figure:
    """Create a budget gauge chart."""
    pct = (current / budget * 100) if budget > 0 else 0

    color = "#22c55e" if pct < 80 else "#eab308" if pct < 95 else "#ef4444"

    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=current,
        number={"prefix": "$", "valueformat": ",.0f"},
        delta={"reference": budget, "relative": False, "valueformat": ",.0f"},
        gauge={
            "axis": {"range": [0, budget * 1.2]},
            "bar": {"color": color},
            "steps": [
                {"range": [0, budget * 0.8], "color": "rgba(34, 197, 94, 0.1)"},
                {"range": [budget * 0.8, budget], "color": "rgba(234, 179, 8, 0.1)"},
                {"range": [budget, budget * 1.2], "color": "rgba(239, 68, 68, 0.1)"},
            ],
            "threshold": {
                "line": {"color": "red", "width": 2},
                "thickness": 0.75,
                "value": budget,
            },
        },
        title={"text": "MTD vs Budget"},
    ))
    fig.update_layout(height=height, margin=dict(l=20, r=20, t=60, b=20))
    return fig


def anomaly_timeline(anomalies: list[dict], height: int = 300) -> go.Figure:
    """Create a timeline of detected anomalies."""
    if not anomalies:
        return go.Figure().update_layout(title="No anomalies detected")

    df = pd.DataFrame(anomalies)
    if "date" not in df.columns:
        return go.Figure().update_layout(title="No date data in anomalies")

    df["date"] = pd.to_datetime(df["date"])

    severity_colors = {
        "critical": "#ef4444",
        "high": "#f97316",
        "medium": "#eab308",
        "low": "#3b82f6",
    }

    fig = go.Figure()

    for _, row in df.iterrows():
        sev = row.get("type", "medium")
        color = severity_colors.get(sev, "#3b82f6")
        fig.add_trace(go.Scatter(
            x=[row["date"]],
            y=[row.get("pct_change", row.get("abs_change", 0))],
            mode="markers+text",
            marker=dict(size=12, color=color),
            text=[row.get("description", "")[:40]],
            textposition="top center",
            hovertext=row.get("description", ""),
            showlegend=False,
        ))

    fig.update_layout(
        title="Anomaly Timeline",
        height=height,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis_title="Date",
        yaxis_title="Change (%)",
    )
    return fig
