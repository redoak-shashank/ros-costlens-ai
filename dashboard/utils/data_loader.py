"""
Data loading utilities for the Streamlit dashboard.

Fetches pre-computed data from S3 and live data from Cost Explorer,
with Streamlit caching. Reads configuration from st.secrets (Streamlit
Community Cloud) with fallback to environment variables for local dev.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

import boto3
import streamlit as st


def _get_aws_config() -> dict:
    """Get AWS credentials and region from st.secrets or env vars."""
    def _norm(v):
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    try:
        aws_secrets = st.secrets.get("aws", {})
        cfg = {
            "aws_access_key_id": _norm(
                aws_secrets.get("aws_access_key_id", os.environ.get("AWS_ACCESS_KEY_ID"))
            ),
            "aws_secret_access_key": _norm(
                aws_secrets.get("aws_secret_access_key", os.environ.get("AWS_SECRET_ACCESS_KEY"))
            ),
            "aws_session_token": _norm(
                aws_secrets.get("aws_session_token", os.environ.get("AWS_SESSION_TOKEN"))
            ),
            "region_name": _norm(aws_secrets.get("region", os.environ.get("AWS_REGION", "us-east-1"))),
        }
        # Drop empty credential fields so boto3 can use default credential chain
        return {k: v for k, v in cfg.items() if v is not None}
    except Exception:
        return {"region_name": os.environ.get("AWS_REGION", "us-east-1")}


def _get_app_config(key: str, default: str = "") -> str:
    """Get an app config value from st.secrets[app] or env vars."""
    try:
        return st.secrets.get("app", {}).get(key, os.environ.get(key.upper(), default))
    except Exception:
        return os.environ.get(key.upper(), default)


@st.cache_resource
def _get_s3_client():
    """Get an S3 client (cached across reruns)."""
    return boto3.client("s3", **_get_aws_config())


@st.cache_resource
def _get_ce_client():
    """Get a Cost Explorer client (cached across reruns)."""
    return boto3.client("ce", **_get_aws_config())


@st.cache_data(ttl=300)
def load_dashboard_data() -> dict:
    """Load the latest pre-computed dashboard data from S3."""
    bucket = _get_app_config("data_bucket")
    if not bucket:
        return {}

    s3 = _get_s3_client()

    try:
        response = s3.get_object(Bucket=bucket, Key="dashboard/latest.json")
        return json.loads(response["Body"].read().decode("utf-8"))
    except Exception:
        return {}


@st.cache_data(ttl=300)
def get_daily_spend(days: int = 30) -> list[dict]:
    """Fetch daily spend from Cost Explorer."""
    ce = _get_ce_client()
    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=days)

    try:
        result = ce.get_cost_and_usage(
            TimePeriod={"Start": start_date.isoformat(), "End": end_date.isoformat()},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
        )

        trend = []
        for period in result.get("ResultsByTime", []):
            trend.append({
                "date": period["TimePeriod"]["Start"],
                "cost": round(
                    float(period.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0)),
                    2,
                ),
            })
        return trend
    except Exception as e:
        st.error(f"Failed to load spend data: {e}")
        return []


@st.cache_data(ttl=300)
def get_spend_by_service(days: int = 30) -> dict[str, float]:
    """Fetch spend by service from Cost Explorer."""
    ce = _get_ce_client()
    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=days)

    try:
        result = ce.get_cost_and_usage(
            TimePeriod={"Start": start_date.isoformat(), "End": end_date.isoformat()},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )

        services = {}
        for period in result.get("ResultsByTime", []):
            for group in period.get("Groups", []):
                svc = group["Keys"][0]
                cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
                services[svc] = services.get(svc, 0) + cost

        # Round and sort
        services = {k: round(v, 2) for k, v in services.items() if v > 0.01}
        return dict(sorted(services.items(), key=lambda x: x[1], reverse=True))
    except Exception as e:
        st.error(f"Failed to load service data: {e}")
        return {}


@st.cache_data(ttl=300)
def get_mtd_spend() -> float:
    """Get month-to-date spend."""
    ce = _get_ce_client()
    today = datetime.utcnow().date()
    first_of_month = today.replace(day=1)

    try:
        result = ce.get_cost_and_usage(
            TimePeriod={"Start": first_of_month.isoformat(), "End": today.isoformat()},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
        )

        for period in result.get("ResultsByTime", []):
            return round(
                float(period.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0)),
                2,
            )
        return 0.0
    except Exception:
        return 0.0


@st.cache_data(ttl=3600)
def get_forecast() -> float:
    """Get end-of-month cost forecast."""
    ce = _get_ce_client()
    today = datetime.utcnow().date()

    import calendar
    last_day = calendar.monthrange(today.year, today.month)[1]
    end_of_month = today.replace(day=last_day) + timedelta(days=1)
    start = (today + timedelta(days=1)).isoformat()

    try:
        result = ce.get_cost_forecast(
            TimePeriod={"Start": start, "End": end_of_month.isoformat()},
            Granularity="MONTHLY",
            Metric="UNBLENDED_COST",
        )
        return round(float(result.get("Total", {}).get("Amount", 0)), 2)
    except Exception:
        return 0.0
