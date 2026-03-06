"""
Trusted Advisor tool for cost optimization checks.

Retrieves cost optimization recommendations including low-utilization
EC2 instances, idle load balancers, underutilized EBS volumes, etc.
"""

from __future__ import annotations

import logging

import boto3
from botocore.exceptions import ClientError

from ..config.settings import get_settings

logger = logging.getLogger(__name__)

_support_client = None

# Trusted Advisor cost optimization check IDs (well-known)
COST_CHECK_IDS = {
    "Qch7DwouX1": "Low Utilization Amazon EC2 Instances",
    "hjLMh88uM8": "Idle Load Balancers",
    "DAvU99Dc4C": "Underutilized Amazon EBS Volumes",
    "Z4AUBRNSmz": "Unassociated Elastic IP Addresses",
    "1iG5NDGVre": "Amazon RDS Idle DB Instances",
    "Ti39halfu8": "Underutilized Amazon Redshift Clusters",
}


def _get_support_client():
    global _support_client
    if _support_client is None:
        settings = get_settings()
        # Trusted Advisor API is only available in us-east-1
        _support_client = boto3.client("support", region_name="us-east-1")
    return _support_client


def get_cost_optimization_checks() -> list[dict]:
    """
    Get all cost optimization check results from Trusted Advisor.

    Returns:
        List of check results with name, status, flagged resources, and
        estimated savings.
    """
    client = _get_support_client()
    results = []

    try:
        # Get all checks and filter for cost optimization category
        checks_response = client.describe_trusted_advisor_checks(language="en")
        cost_checks = [
            c
            for c in checks_response.get("checks", [])
            if c.get("category") == "cost_optimizing"
        ]

        logger.info(f"Found {len(cost_checks)} cost optimization checks")

        for check in cost_checks:
            check_id = check["id"]
            check_name = check["name"]

            try:
                result = client.describe_trusted_advisor_check_result(
                    checkId=check_id, language="en"
                )

                check_result = result.get("result", {})
                status = check_result.get("status", "not_available")
                flagged = check_result.get("flaggedResources", [])

                # Try to extract estimated savings from the result
                estimated_savings = _extract_savings(check_result, flagged)

                results.append({
                    "check_id": check_id,
                    "name": check_name,
                    "status": status,
                    "flagged_count": len(flagged),
                    "estimated_savings": estimated_savings,
                    "description": check.get("description", ""),
                    "recommended_action": _get_recommended_action(check_name, flagged),
                })

            except ClientError as e:
                if "SubscriptionRequiredException" in str(e):
                    logger.info(
                        "Trusted Advisor requires Business or Enterprise support plan"
                    )
                    return []
                logger.warning(f"Failed to get check {check_name}: {e}")
                continue

    except ClientError as e:
        if "SubscriptionRequiredException" in str(e):
            logger.info("Trusted Advisor requires Business or Enterprise support plan")
            return []
        logger.error(f"Failed to list Trusted Advisor checks: {e}")
        raise

    return results


def _extract_savings(check_result: dict, flagged_resources: list) -> float:
    """Try to extract monthly savings estimate from check results."""
    total_savings = 0.0

    for resource in flagged_resources:
        metadata = resource.get("metadata", [])
        # The savings amount is typically in the last metadata field
        for value in reversed(metadata):
            if value and "$" in str(value):
                try:
                    amount = float(str(value).replace("$", "").replace(",", ""))
                    total_savings += amount
                    break
                except (ValueError, TypeError):
                    continue

    return round(total_savings, 2)


def _get_recommended_action(check_name: str, flagged_resources: list) -> str:
    """Generate a recommended action based on the check type."""
    count = len(flagged_resources)

    actions = {
        "Low Utilization Amazon EC2 Instances": (
            f"Review and consider stopping/downsizing {count} low-utilization EC2 instances"
        ),
        "Idle Load Balancers": (
            f"Delete {count} idle load balancers with no active connections"
        ),
        "Underutilized Amazon EBS Volumes": (
            f"Review {count} underutilized EBS volumes for deletion or downsizing"
        ),
        "Unassociated Elastic IP Addresses": (
            f"Release {count} unassociated Elastic IP addresses"
        ),
        "Amazon RDS Idle DB Instances": (
            f"Review {count} idle RDS instances for deletion or snapshotting"
        ),
    }

    return actions.get(check_name, f"Review {count} flagged resources in Trusted Advisor")
