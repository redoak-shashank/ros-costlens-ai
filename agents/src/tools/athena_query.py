"""
Athena query tool for deep CUR analysis.

Executes SQL queries against the CUR data in Athena and returns results.
Handles query lifecycle: start → poll → get results.
"""

from __future__ import annotations

import logging
import os
import time

import boto3
from botocore.exceptions import ClientError

from ..config.settings import get_settings
from ..tracing import trace_event

logger = logging.getLogger(__name__)

_athena_client = None


def _get_athena_client():
    global _athena_client
    if _athena_client is None:
        settings = get_settings()
        _athena_client = boto3.client("athena", region_name=settings.aws_region)
    return _athena_client


def run_athena_query(
    query: str,
    database: str | None = None,
    workgroup: str | None = None,
    timeout_seconds: int = 45,  # Reduced from 120 to fit within Runtime timeout
    max_results: int = 100,
) -> list[dict]:
    """
    Execute a SQL query on Athena and return results as a list of dicts.

    Args:
        query: SQL query string.
        database: Glue database name. Defaults to settings.
        workgroup: Athena workgroup. Defaults to settings.
        timeout_seconds: Max time to wait for query completion.
        max_results: Max rows to return.

    Returns:
        List of dictionaries, one per row, keyed by column name.
    """
    settings = get_settings()
    database = database or settings.athena_database
    workgroup = workgroup or settings.athena_workgroup
    client = _get_athena_client()

    logger.info(f"Executing Athena query on {database}: {query[:200]}...")
    print(f"[athena] Starting query on {database}, timeout={timeout_seconds}s", flush=True)

    try:
        trace_event("athena.start", database=database, workgroup=workgroup)
        # Start the query
        start_kwargs = {
            "QueryString": query,
            "QueryExecutionContext": {"Database": database},
            "WorkGroup": workgroup,
        }

        # Ensure Athena has a valid output location.
        # If not explicitly provided via env, default to the dashboard bucket.
        output_location = os.environ.get("ATHENA_OUTPUT_LOCATION")
        if not output_location and settings.dashboard_data_bucket:
            output_location = f"s3://{settings.dashboard_data_bucket}/athena-results/"

        if output_location:
            start_kwargs["ResultConfiguration"] = {"OutputLocation": output_location}

        start_response = client.start_query_execution(**start_kwargs)
        query_id = start_response["QueryExecutionId"]
        trace_event("athena.query_id", query_id=query_id)
        logger.info(f"Athena query started: {query_id}")
        print(f"[athena] Query ID: {query_id}", flush=True)

        # Poll for completion
        elapsed = 0
        poll_interval = 2
        while elapsed < timeout_seconds:
            status_response = client.get_query_execution(QueryExecutionId=query_id)
            state = status_response["QueryExecution"]["Status"]["State"]

            if state == "SUCCEEDED":
                trace_event("athena.succeeded", query_id=query_id)
                break
            elif state in ("FAILED", "CANCELLED"):
                reason = status_response["QueryExecution"]["Status"].get(
                    "StateChangeReason", "Unknown"
                )
                trace_event("athena.failed", query_id=query_id, state=state, reason=reason)
                raise RuntimeError(f"Athena query {state}: {reason}")

            time.sleep(poll_interval)
            elapsed += poll_interval
            poll_interval = min(poll_interval * 1.5, 10)

        else:
            # Timeout — cancel the query
            client.stop_query_execution(QueryExecutionId=query_id)
            trace_event("athena.timeout", query_id=query_id, timeout_seconds=timeout_seconds)
            raise TimeoutError(f"Athena query timed out after {timeout_seconds}s")

        # Get results
        results_response = client.get_query_results(
            QueryExecutionId=query_id,
            MaxResults=max_results + 1,  # +1 for header row
        )

        rows = results_response.get("ResultSet", {}).get("Rows", [])
        if not rows:
            return []

        # First row is column headers
        headers = [col.get("VarCharValue", f"col_{i}") for i, col in enumerate(rows[0]["Data"])]

        # Parse data rows
        results = []
        for row in rows[1 : max_results + 1]:
            record = {}
            for i, cell in enumerate(row["Data"]):
                col_name = headers[i] if i < len(headers) else f"col_{i}"
                record[col_name] = cell.get("VarCharValue", None)
            results.append(record)

        logger.info(f"Athena query returned {len(results)} rows")
        trace_event("athena.rows", query_id=query_id, row_count=len(results))
        print(f"[athena] Query complete, returning {len(results)} rows", flush=True)
        return results

    except ClientError as e:
        logger.error(f"Athena query error: {e}")
        trace_event("athena.client_error", error=str(e))
        raise
    except Exception as e:
        logger.error(f"Athena query failed: {e}")
        trace_event("athena.exception", error_type=type(e).__name__, error=str(e))
        raise


def run_named_query(query_name: str, max_results: int = 100) -> list[dict]:
    """
    Execute a named query saved in Athena (created by Terraform).

    Args:
        query_name: Name of the saved query.
        max_results: Max rows to return.

    Returns:
        Query results as a list of dicts.
    """
    settings = get_settings()
    client = _get_athena_client()

    try:
        # List named queries to find the one we want
        paginator = client.get_paginator("list_named_queries")
        query_id = None

        for page in paginator.paginate(WorkGroup=settings.athena_workgroup):
            for nq_id in page.get("NamedQueryIds", []):
                nq = client.get_named_query(NamedQueryId=nq_id)
                if nq["NamedQuery"]["Name"] == query_name:
                    query_id = nq_id
                    query_string = nq["NamedQuery"]["QueryString"]
                    break
            if query_id:
                break

        if not query_id:
            raise ValueError(f"Named query '{query_name}' not found")

        return run_athena_query(query=query_string, max_results=max_results)

    except Exception as e:
        logger.error(f"Named query '{query_name}' failed: {e}")
        raise
