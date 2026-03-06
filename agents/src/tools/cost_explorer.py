"""
Cost Explorer API wrapper.

Provides functions for querying AWS Cost Explorer with caching
to avoid rate limits (25 req/s) and redundant calls.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from ..config.settings import get_settings

logger = logging.getLogger(__name__)

_ce_client = None
_dynamodb_resource = None


def _get_ce_client():
    global _ce_client
    if _ce_client is None:
        settings = get_settings()
        _ce_client = boto3.client("ce", region_name=settings.aws_region)
    return _ce_client


def _get_cache_table():
    global _dynamodb_resource
    settings = get_settings()
    if not settings.cache_table_name:
        return None
    if _dynamodb_resource is None:
        _dynamodb_resource = boto3.resource("dynamodb", region_name=settings.aws_region)
    return _dynamodb_resource.Table(settings.cache_table_name)


def _cache_key(func_name: str, **kwargs) -> str:
    """Generate a deterministic cache key."""
    payload = json.dumps({"func": func_name, **kwargs}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _get_cached(key: str, ttl_seconds: int = 300) -> dict | None:
    """Try to get a cached result from DynamoDB."""
    table = _get_cache_table()
    if table is None:
        return None

    try:
        response = table.get_item(Key={"cache_key": key})
        item = response.get("Item")
        if item and item.get("ttl", 0) > int(time.time()):
            return json.loads(item["data"])
    except Exception as e:
        logger.debug(f"Cache miss: {e}")

    return None


def _set_cached(key: str, data: dict, ttl_seconds: int = 300):
    """Store a result in the DynamoDB cache."""
    table = _get_cache_table()
    if table is None:
        return

    try:
        table.put_item(
            Item={
                "cache_key": key,
                "data": json.dumps(data, default=str),
                "ttl": int(time.time()) + ttl_seconds,
                "created_at": datetime.utcnow().isoformat(),
            }
        )
    except Exception as e:
        logger.debug(f"Cache write failed: {e}")


def get_cost_and_usage(
    start_date: str,
    end_date: str,
    granularity: str = "DAILY",
    metrics: list[str] | None = None,
    group_by: list[dict] | None = None,
    filter_expr: dict | None = None,
    cache_ttl: int = 300,
) -> dict:
    """
    Query AWS Cost Explorer GetCostAndUsage.

    Args:
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD), exclusive.
        granularity: DAILY, MONTHLY, or HOURLY.
        metrics: List of metrics (e.g. ["UnblendedCost"]).
        group_by: Optional grouping dimensions.
        filter_expr: Optional filter expression.
        cache_ttl: Cache TTL in seconds.

    Returns:
        Raw Cost Explorer API response.
    """
    if metrics is None:
        metrics = ["UnblendedCost"]

    cache_k = _cache_key(
        "get_cost_and_usage",
        start=start_date,
        end=end_date,
        gran=granularity,
        metrics=metrics,
        group_by=group_by,
        filter_expr=filter_expr,
    )

    cached = _get_cached(cache_k, cache_ttl)
    if cached:
        logger.debug("Cache hit for get_cost_and_usage")
        return cached

    client = _get_ce_client()
    kwargs: dict[str, Any] = {
        "TimePeriod": {"Start": start_date, "End": end_date},
        "Granularity": granularity,
        "Metrics": metrics,
    }

    if group_by:
        kwargs["GroupBy"] = group_by
    if filter_expr:
        kwargs["Filter"] = filter_expr

    try:
        result = client.get_cost_and_usage(**kwargs)
        _set_cached(cache_k, result, cache_ttl)
        return result
    except ClientError as e:
        logger.error(f"Cost Explorer API error: {e}")
        raise


def get_cost_forecast(
    start_date: str,
    end_date: str,
    granularity: str = "MONTHLY",
    metric: str = "UNBLENDED_COST",
    cache_ttl: int = 3600,
) -> dict:
    """
    Get cost forecast from Cost Explorer.

    Args:
        start_date: Forecast start date (must be in the future).
        end_date: Forecast end date.
        granularity: DAILY or MONTHLY.
        metric: Cost metric to forecast.
        cache_ttl: Cache TTL in seconds.

    Returns:
        Cost Explorer forecast response.
    """
    cache_k = _cache_key(
        "get_cost_forecast",
        start=start_date,
        end=end_date,
        gran=granularity,
        metric=metric,
    )

    cached = _get_cached(cache_k, cache_ttl)
    if cached:
        return cached

    client = _get_ce_client()

    try:
        result = client.get_cost_forecast(
            TimePeriod={"Start": start_date, "End": end_date},
            Granularity=granularity,
            Metric=metric,
        )
        _set_cached(cache_k, result, cache_ttl)
        return result
    except ClientError as e:
        # Forecasting can fail if there's not enough historical data
        logger.warning(f"Cost forecast failed: {e}")
        return {}


def get_reservation_utilization(
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Get Reserved Instance utilization data."""
    from datetime import timedelta

    if not start_date:
        today = datetime.utcnow().date()
        start_date = (today - timedelta(days=30)).isoformat()
        end_date = today.isoformat()

    client = _get_ce_client()

    try:
        return client.get_reservation_utilization(
            TimePeriod={"Start": start_date, "End": end_date},
            Granularity="MONTHLY",
        )
    except ClientError as e:
        logger.warning(f"RI utilization query failed: {e}")
        return {}


def get_savings_plans_coverage(
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Get Savings Plans coverage data."""
    from datetime import timedelta

    if not start_date:
        today = datetime.utcnow().date()
        start_date = (today - timedelta(days=30)).isoformat()
        end_date = today.isoformat()

    client = _get_ce_client()

    try:
        result = client.get_savings_plans_coverage(
            TimePeriod={"Start": start_date, "End": end_date},
            Granularity="MONTHLY",
        )

        # Extract the coverage summary
        coverages = result.get("SavingsPlansCoverages", [])
        if coverages:
            coverage = coverages[0].get("Coverage", {})
            return {
                "coverage_percentage": float(
                    coverage.get("CoveragePercentage", 0)
                ),
                "on_demand_cost": float(
                    coverage.get("OnDemandCost", 0)
                ),
                "spend_covered": float(
                    coverage.get("SpendCoveredBySavingsPlans", 0)
                ),
            }
        return {}
    except ClientError as e:
        logger.warning(f"Savings Plans coverage query failed: {e}")
        return {}


def get_dimension_values(
    dimension: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[str]:
    """Get available values for a Cost Explorer dimension (e.g. SERVICE, REGION)."""
    from datetime import timedelta

    if not start_date:
        today = datetime.utcnow().date()
        start_date = (today - timedelta(days=30)).isoformat()
        end_date = today.isoformat()

    client = _get_ce_client()

    try:
        result = client.get_dimension_values(
            TimePeriod={"Start": start_date, "End": end_date},
            Dimension=dimension,
        )
        return [d["Value"] for d in result.get("DimensionValues", [])]
    except ClientError as e:
        logger.warning(f"Dimension values query failed: {e}")
        return []
