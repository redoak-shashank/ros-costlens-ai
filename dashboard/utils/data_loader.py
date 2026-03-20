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

from .account_context import get_account_config, get_account_value, get_selected_account, get_selected_profile


def _get_aws_config() -> dict:
    """Get AWS credentials and region from st.secrets or env vars."""
    def _norm(v):
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    def _safe_get(mapping, key, default=None):
        try:
            return mapping.get(key, default)
        except Exception:
            return default

    try:
        secrets = st.secrets
        aws_secrets = get_account_config("aws")
        profile_name = get_selected_profile()
        cfg = {
            "aws_access_key_id": _norm(
                _safe_get(aws_secrets, "aws_access_key_id")
                or _safe_get(aws_secrets, "access_key_id")
                or _safe_get(secrets, "aws_access_key_id")
                or _safe_get(secrets, "AWS_ACCESS_KEY_ID")
                or os.environ.get("AWS_ACCESS_KEY_ID")
            ),
            "aws_secret_access_key": _norm(
                _safe_get(aws_secrets, "aws_secret_access_key")
                or _safe_get(aws_secrets, "secret_access_key")
                or _safe_get(secrets, "aws_secret_access_key")
                or _safe_get(secrets, "AWS_SECRET_ACCESS_KEY")
                or os.environ.get("AWS_SECRET_ACCESS_KEY")
            ),
            "aws_session_token": _norm(
                _safe_get(aws_secrets, "aws_session_token")
                or _safe_get(aws_secrets, "session_token")
                or _safe_get(secrets, "aws_session_token")
                or _safe_get(secrets, "AWS_SESSION_TOKEN")
                or os.environ.get("AWS_SESSION_TOKEN")
            ),
            "region_name": _norm(
                _safe_get(aws_secrets, "region")
                or _safe_get(aws_secrets, "aws_region")
                or _safe_get(secrets, "region")
                or _safe_get(secrets, "aws_region")
                or _safe_get(secrets, "AWS_REGION")
                or os.environ.get("AWS_REGION", "us-east-1")
            ),
        }
        if profile_name:
            cfg["profile_name"] = profile_name
        # Drop empty credential fields so boto3 can use default credential chain
        return {k: v for k, v in cfg.items() if v is not None}
    except Exception:
        return {"region_name": os.environ.get("AWS_REGION", "us-east-1")}


def _get_app_config(key: str, default: str = "") -> str:
    """Get an app config value from st.secrets[app] or env vars."""
    try:
        app_cfg = get_account_config("app")
        return (
            app_cfg.get(key)
            or st.secrets.get(key)
            or st.secrets.get(key.upper())
            or os.environ.get(key.upper(), default)
        )
    except Exception:
        return os.environ.get(key.upper(), default)


def _make_boto3_client(service_name: str):
    """Create boto3 client honoring selected profile and explicit credentials."""
    cfg = dict(_get_aws_config())
    profile_name = cfg.pop("profile_name", None)

    has_explicit_creds = bool(
        cfg.get("aws_access_key_id") and cfg.get("aws_secret_access_key")
    )
    if profile_name and not has_explicit_creds:
        session = boto3.session.Session(profile_name=profile_name)
        return session.client(service_name, **cfg)
    return boto3.client(service_name, **cfg)


@st.cache_resource
def _get_s3_client(account_key: str):
    """Get an S3 client (cached across reruns)."""
    del account_key
    return _make_boto3_client("s3")


@st.cache_resource
def _get_ce_client(account_key: str):
    """Get a Cost Explorer client (cached across reruns)."""
    del account_key
    return _make_boto3_client("ce")


def get_runtime_config_diagnostics() -> dict:
    """
    Return non-sensitive config diagnostics for deployment troubleshooting.

    Intentionally exposes only booleans and non-secret values.
    """
    cfg = _get_aws_config()
    return {
        "selected_account": get_selected_account(),
        "selected_profile": get_selected_profile(),
        "aws_access_key_id_present": bool(cfg.get("aws_access_key_id")),
        "aws_secret_access_key_present": bool(cfg.get("aws_secret_access_key")),
        "aws_session_token_present": bool(cfg.get("aws_session_token")),
        "region_name": cfg.get("region_name", "us-east-1"),
        "data_bucket_configured": bool(_get_app_config("data_bucket")),
        "agent_function_name_configured": bool(_get_app_config("agent_function_name")),
    }


def test_aws_credentials() -> tuple[bool, str]:
    """
    Validate AWS credentials by calling STS GetCallerIdentity.

    Returns:
        (True, message) when credentials are valid, else (False, error message).
    """
    try:
        sts = _make_boto3_client("sts")
        identity = sts.get_caller_identity()
        account = identity.get("Account", "unknown")
        arn = identity.get("Arn", "unknown")
        return True, f"Account={account}, Arn={arn}"
    except Exception as e:
        return False, str(e)


@st.cache_data(ttl=300)
def load_dashboard_data() -> dict:
    """Load the latest pre-computed dashboard data from S3."""
    bucket = _get_app_config("data_bucket")
    if not bucket:
        return {}

    s3 = _get_s3_client(get_selected_account())

    try:
        response = s3.get_object(Bucket=bucket, Key="dashboard/latest.json")
        return json.loads(response["Body"].read().decode("utf-8"))
    except Exception:
        return {}


@st.cache_data(ttl=300)
def get_daily_spend(days: int = 30) -> list[dict]:
    """Fetch daily spend from Cost Explorer."""
    ce = _get_ce_client(get_selected_account())
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
    ce = _get_ce_client(get_selected_account())
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
    ce = _get_ce_client(get_selected_account())
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
    ce = _get_ce_client(get_selected_account())
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
