"""
Reporter Agent — Formats outputs into Slack messages and dashboard data.

Takes the collected cost data, anomalies, and recommendations from state
and produces formatted Slack messages (Block Kit) and JSON for the dashboard.
Persists dashboard data to S3 so the Streamlit dashboard can read it.
"""

from __future__ import annotations

import json
import logging
import math
import os
import struct
import zlib
from io import BytesIO
from datetime import datetime
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from langchain_core.messages import AIMessage

from ..state import BillingState
from ..config.settings import get_settings
from ..tracing import trace_operation
from ..tools.slack import send_slack_file, send_slack_message

logger = logging.getLogger(__name__)

_s3_client = None


def _safe_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_s3_client():
    global _s3_client
    if _s3_client is None:
        settings = get_settings()
        _s3_client = boto3.client("s3", region_name=settings.aws_region)
    return _s3_client


def _persist_dashboard_data(dashboard_data: dict) -> bool:
    """
    Write dashboard data to S3 so the Streamlit dashboard can read it.

    Writes to two keys:
    - dashboard/latest.json  (what the dashboard reads on load)
    - dashboard/{date}.json  (historical archive)

    Returns True if write succeeded, False otherwise.
    """
    settings = get_settings()
    bucket = settings.dashboard_data_bucket

    if not bucket:
        logger.warning("DATA_BUCKET not configured — skipping S3 dashboard write")
        return False

    s3 = _get_s3_client()
    payload = json.dumps(dashboard_data, default=str, indent=2)
    today = datetime.utcnow().strftime("%Y-%m-%d")

    try:
        # Write latest (what the dashboard reads)
        s3.put_object(
            Bucket=bucket,
            Key="dashboard/latest.json",
            Body=payload.encode("utf-8"),
            ContentType="application/json",
        )

        # Write dated archive copy
        s3.put_object(
            Bucket=bucket,
            Key=f"dashboard/{today}.json",
            Body=payload.encode("utf-8"),
            ContentType="application/json",
        )

        logger.info(f"Dashboard data written to s3://{bucket}/dashboard/latest.json")
        return True

    except ClientError as e:
        logger.error(f"Failed to write dashboard data to S3: {e}")
        return False


def _format_daily_report(state: BillingState) -> str:
    """Format the daily cost report as a Slack message."""
    daily = state.get("daily_spend", {})
    mtd = state.get("mtd_spend", {})
    forecast = state.get("forecast", {})
    anomalies = state.get("anomalies", [])
    recommendations = state.get("recommendations", [])
    trend_data = state.get("trend_data", [])
    settings = get_settings()

    today = datetime.utcnow().strftime("%b %d, %Y")

    # Calculate day-over-day change
    dod_indicator = ""
    if trend_data and len(trend_data) >= 2:
        sorted_trend = sorted(trend_data, key=lambda x: x["date"])
        yesterday = sorted_trend[-1]["cost"]
        day_before = sorted_trend[-2]["cost"]
        if day_before > 0:
            pct = ((yesterday - day_before) / day_before) * 100
            arrow = "\u25b2" if pct > 0 else "\u25bc"
            dod_indicator = f" ({arrow} {abs(pct):.1f}% vs prior day)"

    # Build the message
    lines = [
        f":chart_with_upwards_trend: *Daily AWS Cost Report — {today}*",
        "",
    ]

    # Spend summary
    if daily:
        lines.append(
            f":moneybag: *Yesterday's Spend:* ${daily.get('total', 0):,.2f}{dod_indicator}"
        )

    if mtd:
        forecast_str = ""
        if forecast:
            forecast_total = forecast.get("forecast_total", 0)
            budget = settings.monthly_budget
            budget_pct = (forecast_total / budget * 100) if budget > 0 else 0
            forecast_str = f" | Forecast: ${forecast_total:,.0f} ({budget_pct:.0f}% of budget)"
        lines.append(
            f":calendar: *MTD Spend:* ${mtd.get('total', 0):,.2f}{forecast_str}"
        )

    # Top services
    service_breakdown = state.get("service_breakdown", {})
    wow = service_breakdown.get("week_over_week") if service_breakdown else None
    services = daily.get("services", {}) if daily else {}

    if wow:
        # Weekly deep-dive: show week-over-week changes
        lines.append("")
        lines.append(":building_construction: *Service Breakdown (Week-over-Week):*")
        for svc, data in list(sorted(
            wow.items(), key=lambda x: x[1].get("this_week", 0), reverse=True
        ))[:10]:
            this_w = data.get("this_week", 0)
            pct = data.get("change_pct", 0)
            arrow = "\u25b2" if pct > 0 else "\u25bc" if pct < 0 else "\u2014"
            lines.append(f"  \u2022 {svc}: ${this_w:,.2f} ({arrow} {abs(pct):.1f}% WoW)")
    elif services:
        lines.append("")
        lines.append(":building_construction: *Top Services:*")
        for svc, cost in list(services.items())[:5]:
            lines.append(f"  \u2022 {svc}: ${cost:,.2f}")

    # Anomalies
    if anomalies:
        lines.append("")
        severity = state.get("severity", "")
        severity_emoji = {
            "critical": ":rotating_light:",
            "high": ":warning:",
            "medium": ":large_yellow_circle:",
            "low": ":information_source:",
        }.get(severity, ":warning:")
        lines.append(f"{severity_emoji} *Anomalies Detected:*")
        for a in anomalies[:5]:
            lines.append(f"  \u2022 {a.get('description', 'Unknown anomaly')}")

    # Recommendations
    if recommendations:
        total_savings = state.get("total_potential_savings", 0)
        lines.append("")
        lines.append(f":bulb: *Savings Opportunities* (~${total_savings:,.2f}/mo):")
        for r in recommendations[:5]:
            savings = r.get("estimated_monthly_savings", 0)
            lines.append(f"  \u2022 {r.get('description', '')} — save ~${savings:,.2f}/mo")

    # Footer
    lines.append("")
    lines.append("_Reply in thread to ask questions about your spend_ :robot_face:")

    return "\n".join(lines)


def _format_anomaly_alert(state: BillingState) -> str:
    """Format an anomaly alert for Slack."""
    anomalies = state.get("anomalies", [])
    severity = state.get("severity", "")

    # When no anomalies: send a friendly all-clear message instead of a scary alert
    if not anomalies:
        return (
            ":white_check_mark: *Cost Anomaly Check — All Clear*\n\n"
            "No anomalies found in the latest analysis. Your spend looks normal.\n\n"
            "_Reply in thread to ask questions_ :robot_face:"
        )

    severity_emoji = {
        "critical": ":rotating_light:",
        "high": ":warning:",
        "medium": ":large_yellow_circle:",
        "low": ":information_source:",
    }.get(severity, ":warning:")

    severity_label = f" ({severity.upper()})" if severity else ""
    lines = [
        f"{severity_emoji} *Cost Anomaly Alert*{severity_label}",
        "",
    ]

    for a in anomalies:
        lines.append(f"\u2022 {a.get('description', 'Unknown anomaly')}")

    lines.append("")
    lines.append("_Reply in thread for more details_ :robot_face:")

    return "\n".join(lines)


def _format_interactive_response(state: BillingState) -> str:
    """Format a response to an interactive Slack query."""
    # Use the last AI message as the response
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            return msg.content

    return "I wasn't able to find an answer. Could you try rephrasing your question?"


def _build_dashboard_data(state: BillingState) -> dict:
    """Build JSON payload for the Streamlit dashboard."""
    data = {
        "updated_at": datetime.utcnow().isoformat(),
        "daily_spend": state.get("daily_spend"),
        "mtd_spend": state.get("mtd_spend"),
        "forecast": state.get("forecast"),
        "trend_data": state.get("trend_data"),
        "service_breakdown": state.get("service_breakdown"),
        "anomalies": state.get("anomalies"),
        "severity": state.get("severity"),
        "recommendations": state.get("recommendations"),
        "total_potential_savings": state.get("total_potential_savings"),
    }

    # Include tag breakdown if present (populated by weekly deep-dive)
    dashboard_extra = state.get("dashboard_data")
    if dashboard_extra and isinstance(dashboard_extra, dict):
        tag_breakdown = dashboard_extra.get("tag_breakdown")
        if tag_breakdown:
            data["tag_breakdown"] = tag_breakdown

    return data


def _build_weekday_spend_series(
    trend_data: list[dict] | None,
    history_days: int = 56,
) -> dict | None:
    """Build weekday low/high + latest point series for charting."""
    if not trend_data:
        return None

    dow_order = [
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
    ]

    rows: list[tuple[datetime, float, str]] = []
    for point in trend_data:
        date_raw = point.get("date")
        cost = _safe_float(point.get("cost"))
        if not date_raw or cost is None:
            continue
        try:
            dt = datetime.fromisoformat(str(date_raw))
        except ValueError:
            continue

        weekday = dow_order[(dt.weekday() + 1) % 7]  # Python Monday=0; we want Sunday first.
        rows.append((dt, cost, weekday))

    if not rows:
        return None

    rows.sort(key=lambda x: x[0])
    rows = rows[-history_days:]

    low_high: dict[str, dict[str, float]] = {}
    latest_by_weekday: dict[str, tuple[datetime, float]] = {}
    for dt, cost, weekday in rows:
        if weekday not in low_high:
            low_high[weekday] = {"low": cost, "high": cost}
        else:
            low_high[weekday]["low"] = min(low_high[weekday]["low"], cost)
            low_high[weekday]["high"] = max(low_high[weekday]["high"], cost)

        prev = latest_by_weekday.get(weekday)
        if prev is None or dt > prev[0]:
            latest_by_weekday[weekday] = (dt, cost)

    latest_points = [
        {"weekday": day, "cost": latest_by_weekday[day][1]}
        for day in dow_order
        if day in latest_by_weekday
    ]

    latest_dt, latest_cost, latest_weekday = rows[-1]

    return {
        "dow_order": dow_order,
        "low_high": low_high,
        "latest_points": latest_points,
        "most_recent": {
            "date": latest_dt.date().isoformat(),
            "weekday": latest_weekday,
            "cost": latest_cost,
        },
    }


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


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack("!I", len(data))
        + chunk_type
        + data
        + struct.pack("!I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def _encode_png_rgb(width: int, height: int, pixels: bytearray) -> bytes:
    """Encode raw RGB pixels into a PNG byte stream."""
    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # Filter method 0 for each scanline.
        start = y * stride
        raw.extend(pixels[start : start + stride])

    png = bytearray(b"\x89PNG\r\n\x1a\n")
    ihdr = struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png.extend(_png_chunk(b"IHDR", ihdr))
    png.extend(_png_chunk(b"IDAT", zlib.compress(bytes(raw), level=6)))
    png.extend(_png_chunk(b"IEND", b""))
    return bytes(png)


def _draw_pixel(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    color: tuple[int, int, int],
):
    if 0 <= x < width and 0 <= y < height:
        i = (y * width + x) * 3
        pixels[i] = color[0]
        pixels[i + 1] = color[1]
        pixels[i + 2] = color[2]


def _draw_line(
    pixels: bytearray,
    width: int,
    height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
    thickness: int = 1,
):
    dx = x1 - x0
    dy = y1 - y0
    steps = max(abs(dx), abs(dy), 1)
    radius = max(0, thickness // 2)

    for i in range(steps + 1):
        t = i / steps
        x = int(round(x0 + dx * t))
        y = int(round(y0 + dy * t))
        for ox in range(-radius, radius + 1):
            for oy in range(-radius, radius + 1):
                _draw_pixel(pixels, width, height, x + ox, y + oy, color)


def _draw_circle(
    pixels: bytearray,
    width: int,
    height: int,
    cx: int,
    cy: int,
    radius: int,
    color: tuple[int, int, int],
):
    r2 = radius * radius
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy <= r2:
                _draw_pixel(pixels, width, height, cx + dx, cy + dy, color)


_FONT_5X7: dict[str, list[str]] = {
    "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01110"],
    "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    "I": ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
    "J": ["00001", "00001", "00001", "00001", "10001", "10001", "01110"],
    "K": ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "O": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    "Q": ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10001", "10101", "10101", "10101", "01010"],
    "X": ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    "Y": ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    "Z": ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
    "0": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "10000", "11110", "00001", "00001", "11110"],
    "6": ["01110", "10000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],
    ".": ["00000", "00000", "00000", "00000", "00000", "00110", "00110"],
    ",": ["00000", "00000", "00000", "00000", "00000", "00110", "00100"],
    "$": ["00100", "01111", "10100", "01110", "00101", "11110", "00100"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    "(": ["00010", "00100", "01000", "01000", "01000", "00100", "00010"],
    ")": ["01000", "00100", "00010", "00010", "00010", "00100", "01000"],
    " ": ["00000", "00000", "00000", "00000", "00000", "00000", "00000"],
}


def _draw_char_5x7(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    char: str,
    color: tuple[int, int, int],
    scale: int = 1,
):
    glyph = _FONT_5X7.get(char, _FONT_5X7[" "])
    for gy, row in enumerate(glyph):
        for gx, bit in enumerate(row):
            if bit != "1":
                continue
            for sy in range(scale):
                for sx in range(scale):
                    _draw_pixel(
                        pixels,
                        width,
                        height,
                        x + gx * scale + sx,
                        y + gy * scale + sy,
                        color,
                    )


def _draw_text_5x7(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    text: str,
    color: tuple[int, int, int],
    scale: int = 1,
    letter_spacing: int = 1,
):
    cursor = x
    for char in text:
        normalized = char.upper()
        if normalized not in _FONT_5X7:
            normalized = " "
        _draw_char_5x7(
            pixels, width, height, cursor, y, normalized, color, scale=scale
        )
        cursor += (5 * scale) + letter_spacing


def _draw_vertical_text_5x7(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    text: str,
    color: tuple[int, int, int],
    scale: int = 1,
    line_gap: int = 2,
):
    cursor_y = y
    for char in text:
        _draw_text_5x7(
            pixels,
            width,
            height,
            x=x,
            y=cursor_y,
            text=char,
            color=color,
            scale=scale,
            letter_spacing=1,
        )
        cursor_y += (7 * scale) + line_gap


def _build_weekday_spend_chart_png_fallback(series: dict) -> bytes | None:
    """
    Fallback PNG renderer when matplotlib is unavailable.

    Draws whiskers, points, and basic axis labels without external font dependencies.
    """
    dow_order: list[str] = series["dow_order"]
    low_high: dict = series["low_high"]
    latest_points: list[dict] = series["latest_points"]
    most_recent: dict = series["most_recent"]
    x_pos = {day: i for i, day in enumerate(dow_order)}

    y_values: list[float] = []
    for bounds in low_high.values():
        y_values.extend([float(bounds["low"]), float(bounds["high"])])
    for p in latest_points:
        y_values.append(float(p["cost"]))
    if most_recent:
        y_values.append(float(most_recent["cost"]))
    if not y_values:
        return None

    y_min = min(y_values)
    y_max = max(y_values)
    span = y_max - y_min
    pad = (span * 0.2) if span > 0 else max(1.0, y_max * 0.1)
    y_lower = max(0.0, y_min - pad)
    y_upper = y_max + pad
    step = _nice_dollar_step(max(y_upper - y_lower, 0.01))
    y_lower = math.floor(y_lower / step) * step
    y_upper = math.ceil(y_upper / step) * step

    width = 1200
    height = 700
    plot_left = 118
    plot_right = width - 50
    plot_top = 118
    plot_bottom = height - 130
    plot_width = plot_right - plot_left
    plot_height = plot_bottom - plot_top

    pixels = bytearray([255, 255, 255] * width * height)

    def _x(day: str) -> int:
        idx = x_pos[day]
        return int(round(plot_left + (idx / 6) * plot_width))

    def _y(value: float) -> int:
        if y_upper <= y_lower:
            return plot_bottom
        return int(round(plot_top + ((y_upper - value) / (y_upper - y_lower)) * plot_height))

    # Grid lines (horizontal) + y tick labels.
    grid_color = (229, 231, 235)
    tick_label_color = (55, 65, 81)
    t = y_lower
    while t <= y_upper + 1e-9:
        yv = _y(t)
        _draw_line(pixels, width, height, plot_left, yv, plot_right, yv, grid_color, thickness=1)
        label = f"${t:.2f}"
        _draw_text_5x7(
            pixels,
            width,
            height,
            x=16,
            y=max(0, yv - 5),
            text=label,
            color=tick_label_color,
            scale=2,
            letter_spacing=1,
        )
        t += step

    # Axis lines.
    axis_color = (156, 163, 175)
    _draw_line(
        pixels,
        width,
        height,
        plot_left,
        plot_top,
        plot_left,
        plot_bottom,
        axis_color,
        thickness=1,
    )
    _draw_line(
        pixels,
        width,
        height,
        plot_left,
        plot_bottom,
        plot_right,
        plot_bottom,
        axis_color,
        thickness=1,
    )

    text_color = (17, 24, 39)
    title = "WEEKDAY SPEND RANGE (ROLLING HISTORY)"
    _draw_text_5x7(
        pixels,
        width,
        height,
        x=plot_left,
        y=22,
        text=title,
        color=text_color,
        scale=3,
        letter_spacing=1,
    )

    # Legend
    legend_y = 78
    _draw_circle(pixels, width, height, plot_left + 10, legend_y + 8, 7, (22, 163, 74))
    _draw_text_5x7(
        pixels,
        width,
        height,
        x=plot_left + 30,
        y=legend_y,
        text="LATEST BY WEEKDAY",
        color=text_color,
        scale=2,
        letter_spacing=1,
    )
    _draw_circle(pixels, width, height, plot_left + 330, legend_y + 8, 7, (245, 158, 11))
    _draw_text_5x7(
        pixels,
        width,
        height,
        x=plot_left + 350,
        y=legend_y,
        text="LATEST",
        color=text_color,
        scale=2,
        letter_spacing=1,
    )

    # Range whiskers.
    whisker_color = (107, 114, 128)
    for day in dow_order:
        bounds = low_high.get(day)
        if not bounds:
            continue
        _draw_line(
            pixels,
            width,
            height,
            _x(day),
            _y(float(bounds["low"])),
            _x(day),
            _y(float(bounds["high"])),
            whisker_color,
            thickness=4,
        )

    # Latest by weekday (green).
    for p in latest_points:
        _draw_circle(
            pixels,
            width,
            height,
            _x(p["weekday"]),
            _y(float(p["cost"])),
            radius=7,
            color=(22, 163, 74),
        )

    # Most recent (yellow).
    if most_recent:
        _draw_circle(
            pixels,
            width,
            height,
            _x(most_recent["weekday"]),
            _y(float(most_recent["cost"])),
            radius=8,
            color=(245, 158, 11),
        )

    day_labels = {
        "Sunday": "SUN",
        "Monday": "MON",
        "Tuesday": "TUE",
        "Wednesday": "WED",
        "Thursday": "THU",
        "Friday": "FRI",
        "Saturday": "SAT",
    }
    for day in dow_order:
        label = day_labels.get(day, day[:3].upper())
        x_label = _x(day) - 10
        y_label = plot_bottom + 20
        _draw_text_5x7(
            pixels,
            width,
            height,
            x=x_label,
            y=y_label,
            text=label,
            color=tick_label_color,
            scale=2,
            letter_spacing=1,
        )

    _draw_text_5x7(
        pixels,
        width,
        height,
        x=(plot_left + plot_right) // 2 - 60,
        y=height - 46,
        text="DAY OF WEEK",
        color=tick_label_color,
        scale=2,
        letter_spacing=1,
    )

    return _encode_png_rgb(width, height, pixels)


def _build_weekday_spend_chart_png(
    trend_data: list[dict] | None,
    history_days: int = 56,
) -> bytes | None:
    """
    Render weekday spend range chart as PNG bytes for Slack upload.

    Uses matplotlib when available. Returns None if chart cannot be rendered.
    """
    series = _build_weekday_spend_series(trend_data, history_days=history_days)
    if not series:
        return None

    try:
        os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
        os.environ.setdefault("XDG_CACHE_HOME", "/tmp")
        os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.ticker import FuncFormatter
    except Exception as e:
        logger.warning(f"Matplotlib unavailable; using fallback Slack chart renderer: {e}")
        return _build_weekday_spend_chart_png_fallback(series)

    dow_order: list[str] = series["dow_order"]
    low_high: dict = series["low_high"]
    latest_points: list[dict] = series["latest_points"]
    most_recent: dict = series["most_recent"]
    x_pos = {day: i for i, day in enumerate(dow_order)}

    y_values: list[float] = []
    for day, bounds in low_high.items():
        y_values.extend([bounds["low"], bounds["high"]])
    for p in latest_points:
        y_values.append(float(p["cost"]))
    if most_recent:
        y_values.append(float(most_recent["cost"]))
    if not y_values:
        return None

    y_min = min(y_values)
    y_max = max(y_values)
    span = y_max - y_min
    pad = (span * 0.2) if span > 0 else max(1.0, y_max * 0.1)
    y_lower = max(0.0, y_min - pad)
    y_upper = y_max + pad
    step = _nice_dollar_step(max(y_upper - y_lower, 0.01))

    # Align y-axis bounds to clean currency tick steps.
    y_lower = math.floor(y_lower / step) * step
    y_upper = math.ceil(y_upper / step) * step

    fig, ax = plt.subplots(figsize=(10, 5), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # Weekday whiskers (low/high ranges).
    for day in dow_order:
        bounds = low_high.get(day)
        if not bounds:
            continue
        ax.vlines(
            x_pos[day],
            bounds["low"],
            bounds["high"],
            colors="#6b7280",
            linewidth=3,
            alpha=0.9,
            zorder=1,
        )

    if latest_points:
        ax.scatter(
            [x_pos[p["weekday"]] for p in latest_points],
            [p["cost"] for p in latest_points],
            color="#16a34a",
            s=54,
            label="Latest by weekday",
            zorder=3,
        )

    if most_recent:
        ax.scatter(
            [x_pos[most_recent["weekday"]]],
            [most_recent["cost"]],
            color="#f59e0b",
            edgecolors="#b45309",
            linewidths=0.8,
            s=58,
            label="Latest",
            zorder=4,
        )

    ticks = []
    t = y_lower
    while t <= y_upper + 1e-9:
        ticks.append(round(t, 6))
        t += step
    ax.set_yticks(ticks)
    ax.set_ylim(y_lower, y_upper)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.2f}"))

    ax.set_xticks(list(range(len(dow_order))))
    ax.set_xticklabels(dow_order)

    ax.set_title(
        "Weekday Spend Range (Rolling History)",
        loc="left",
        fontsize=13,
        fontweight="bold",
    )
    ax.set_xlabel("Day of Week", labelpad=10)
    ax.set_ylabel("Spend (USD)", labelpad=10)
    ax.grid(axis="y", color="#e5e7eb", linewidth=1)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper left", frameon=False, ncol=2)

    # Keep a clean card-like style.
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#d1d5db")
    ax.spines["bottom"].set_color("#d1d5db")

    fig.tight_layout()
    png_buffer = BytesIO()
    fig.savefig(png_buffer, format="png")
    plt.close(fig)
    return png_buffer.getvalue()


@trace_operation("reporter_formatting_and_delivery")
def reporter_node(state: BillingState) -> dict:
    """Format and send the report via Slack and prepare dashboard data."""
    settings = get_settings()
    request_type = state.get("request_type", "query")
    print(f"[reporter] Starting. request_type={request_type}", flush=True)
    print(f"[reporter] State messages count: {len(state.get('messages', []))}", flush=True)

    # Log all messages for debugging
    for i, msg in enumerate(state.get("messages", [])):
        msg_type = type(msg).__name__
        content = msg.content[:150] if hasattr(msg, "content") else str(msg)[:150]
        print(f"[reporter]   msg[{i}] ({msg_type}): {content}", flush=True)

    try:
        # Format message based on request type
        if request_type == "report":
            message = _format_daily_report(state)
        elif request_type == "alert":
            message = _format_anomaly_alert(state)
        else:
            message = _format_interactive_response(state)
            print(f"[reporter] Interactive response length: {len(message)}", flush=True)
            print(f"[reporter] Interactive response preview: {message[:200]}", flush=True)

        # Send to Slack — only for scheduled reports/alerts, NOT interactive queries.
        # Interactive queries get their reply posted by the Slack event handler in app.py.
        slack_sent = False
        send_result = {}
        if (
            request_type in ("report", "alert")
            and settings.slack_channel_id
            and settings.slack_secret_arn
        ):
            try:
                send_result = send_slack_message(
                    channel=settings.slack_channel_id,
                    text=message,
                )
                slack_sent = send_result.get("ok", False)
                if not slack_sent:
                    logger.warning(f"Slack send failed: {send_result}")
                elif request_type == "report":
                    chart_png = _build_weekday_spend_chart_png(state.get("trend_data"))
                    if chart_png:
                        try:
                            report_date = datetime.utcnow().strftime("%Y-%m-%d")
                            chart_result = send_slack_file(
                                channel=settings.slack_channel_id,
                                filename=f"weekday-spend-{report_date}.png",
                                title="Weekday Spend Range (Rolling History)",
                                file_bytes=chart_png,
                                thread_ts=send_result.get("ts"),
                                initial_comment=(
                                    "Weekday spend range chart (rolling history): "
                                    "gray whiskers = low/high, green = latest by weekday, "
                                    "yellow = latest available day."
                                ),
                            )
                            if not chart_result.get("ok"):
                                logger.warning(f"Slack chart upload failed: {chart_result}")
                        except Exception as chart_err:
                            logger.warning(f"Slack chart upload skipped: {chart_err}")
                    else:
                        logger.info("Skipped Slack chart upload (no chart bytes generated)")
            except Exception as slack_err:
                logger.warning(f"Slack delivery skipped: {slack_err}")
        else:
            logger.info(f"Skipping Slack send (request_type={request_type})")

        # Build and persist dashboard data (for scheduled reports)
        dashboard_data = None
        if request_type in ("report", "alert"):
            dashboard_data = _build_dashboard_data(state)
            _persist_dashboard_data(dashboard_data)

        return {
            "slack_message": message,
            "dashboard_data": dashboard_data,
            "messages": [AIMessage(content=message)],
        }

    except Exception as e:
        logger.error(f"Reporter error: {e}", exc_info=True)
        # Still return the best response we have, don't swallow the analysis
        fallback = _format_interactive_response(state)
        return {
            "slack_message": fallback or f"Reporter error: {e}",
            "messages": [AIMessage(content=fallback or f"Reporter error: {e}")],
        }
