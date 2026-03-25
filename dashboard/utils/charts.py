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


def rolling_weekday_range_chart(
    trend_data: list[dict],
    history_days: int = 56,
    height: int = 420,
) -> go.Figure:
    """
    Create a simple weekday range chart with current-week overlay.

    - Gray whiskers: min/max daily spend by weekday over the history window.
    - Green dots: latest observed spend for each weekday.
    - Dark green dot: most recent available day (no extra legend item).
    """
    if not trend_data:
        return go.Figure().update_layout(title="No data available")

    df = pd.DataFrame(trend_data)
    if "date" not in df.columns or "cost" not in df.columns:
        return go.Figure().update_layout(title="Invalid trend data")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["cost"] = pd.to_numeric(df["cost"], errors="coerce")
    df = df.dropna(subset=["date", "cost"]).sort_values("date")
    if df.empty:
        return go.Figure().update_layout(title="No data available")

    df = df.tail(history_days).copy()

    dow_order = [
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
    ]

    df["weekday"] = df["date"].dt.day_name()
    range_df = (
        df.groupby("weekday", as_index=False)["cost"]
        .agg(low="min", high="max")
    )
    range_df["weekday"] = pd.Categorical(range_df["weekday"], categories=dow_order, ordered=True)
    range_df = range_df.sort_values("weekday")

    # Latest observed value for each weekday (closest date to now per weekday).
    latest_per_weekday = (
        df.sort_values("date")
        .groupby("weekday", as_index=False)
        .tail(1)
        .copy()
    )
    latest_per_weekday["weekday"] = pd.Categorical(
        latest_per_weekday["weekday"], categories=dow_order, ordered=True
    )
    latest_per_weekday = latest_per_weekday.sort_values("weekday")

    latest_row = df.sort_values("date").tail(1).copy()
    latest_row["weekday"] = latest_row["date"].dt.day_name()
    latest_row["weekday"] = pd.Categorical(
        latest_row["weekday"], categories=dow_order, ordered=True
    )

    fig = go.Figure()

    # Build whiskers as one trace so spacing/hover stay consistent.
    wx: list[str | None] = []
    wy: list[float | None] = []
    for _, row in range_df.iterrows():
        wx.extend([row["weekday"], row["weekday"], None])
        wy.extend([float(row["low"]), float(row["high"]), None])

    fig.add_trace(go.Scatter(
        x=wx,
        y=wy,
        mode="lines",
        line=dict(color="rgba(75, 85, 99, 0.75)", width=5),
        hoverinfo="skip",
        showlegend=False,
    ))

    if not latest_per_weekday.empty:
        fig.add_trace(go.Scatter(
            x=latest_per_weekday["weekday"],
            y=latest_per_weekday["cost"],
            mode="markers",
            marker=dict(color="#16a34a", size=11),
            name="Latest by weekday",
            hovertemplate=(
                "%{x}<br>"
                "Spend: $%{y:,.2f}<extra>Latest by weekday</extra>"
            ),
        ))

    if not latest_row.empty:
        fig.add_trace(go.Scatter(
            x=latest_row["weekday"],
            y=latest_row["cost"],
            mode="markers",
            marker=dict(color="#f59e0b", size=11, line=dict(color="#b45309", width=1)),
            name="Latest",
            hovertemplate=(
                "%{x}<br>"
                "Spend: $%{y:,.2f}<extra>Most recent day</extra>"
            ),
            showlegend=True,
        ))

    y_candidates = []
    if not range_df.empty:
        y_candidates.extend(range_df["low"].tolist())
        y_candidates.extend(range_df["high"].tolist())
    if not latest_per_weekday.empty:
        y_candidates.extend(latest_per_weekday["cost"].tolist())

    if y_candidates:
        y_min = min(y_candidates)
        y_max = max(y_candidates)
        span = y_max - y_min
        pad = (span * 0.2) if span > 0 else max(1.0, y_max * 0.1)
        y_lower = max(0.0, y_min - pad)
        y_upper = y_max + pad
    else:
        y_lower = 0.0
        y_upper = 10.0

    def _nice_dollar_step(value_span: float) -> float:
        if value_span <= 2:
            return 0.25
        if value_span <= 5:
            return 0.5
        if value_span <= 15:
            return 1.0
        if value_span <= 40:
            return 2.0
        if value_span <= 100:
            return 5.0
        return 10.0

    y_step = _nice_dollar_step(max(y_upper - y_lower, 0.01))

    fig.update_layout(
        title="Weekday Spend Range (Rolling History)",
        title_x=0.0,
        title_xanchor="left",
        height=height,
        margin=dict(l=20, r=20, t=78, b=28),
        xaxis=dict(
            title="Day of Week",
            categoryorder="array",
            categoryarray=dow_order,
            tickmode="array",
            tickvals=dow_order,
            ticktext=dow_order,
        ),
        yaxis=dict(
            title="Spend (USD)",
            tickprefix="$",
            tickformat=",.2f",
            range=[y_lower, y_upper],
            dtick=y_step,
            automargin=True,
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.03,
            xanchor="left",
            x=0.0,
        ),
        hovermode="closest",
    )
    return fig
