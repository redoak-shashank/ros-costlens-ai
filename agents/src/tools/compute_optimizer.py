"""
Compute Optimizer tool for right-sizing recommendations.

Retrieves EC2, Auto Scaling, and EBS optimization recommendations
from AWS Compute Optimizer.
"""

from __future__ import annotations

import logging

import boto3
from botocore.exceptions import ClientError

from ..config.settings import get_settings

logger = logging.getLogger(__name__)

_co_client = None


def _get_co_client():
    global _co_client
    if _co_client is None:
        settings = get_settings()
        _co_client = boto3.client("compute-optimizer", region_name=settings.aws_region)
    return _co_client


def get_ec2_recommendations(max_results: int = 50) -> list[dict]:
    """
    Get EC2 instance right-sizing recommendations.

    Returns:
        List of recommendation dicts with instance details and suggested changes.
    """
    client = _get_co_client()
    recommendations = []

    try:
        response = client.get_ec2_instance_recommendations(
            maxResults=max_results,
            filters=[
                {
                    "name": "Finding",
                    "values": ["OVER_PROVISIONED"],
                }
            ],
        )

        for rec in response.get("instanceRecommendations", []):
            instance_arn = rec.get("instanceArn", "")
            instance_id = instance_arn.split("/")[-1] if "/" in instance_arn else instance_arn
            current_type = rec.get("currentInstanceType", "unknown")
            finding = rec.get("finding", "unknown")

            # Get the top recommendation option
            options = rec.get("recommendationOptions", [])
            recommended_type = current_type
            estimated_savings = 0.0

            if options:
                top_option = options[0]
                recommended_type = top_option.get("instanceType", current_type)

                # Calculate savings from projected utilization metrics
                projected_metrics = top_option.get("projectedUtilizationMetrics", [])
                savings_opportunity = top_option.get("savingsOpportunity", {})
                estimated_savings = float(
                    savings_opportunity.get("estimatedMonthlySavings", {}).get("value", 0)
                )

            recommendations.append({
                "instance_id": instance_id,
                "instance_arn": instance_arn,
                "current_instance_type": current_type,
                "recommended_instance_type": recommended_type,
                "finding": finding,
                "estimated_monthly_savings": estimated_savings,
            })

        logger.info(f"Found {len(recommendations)} EC2 right-sizing recommendations")

    except ClientError as e:
        if "OptInRequiredException" in str(e):
            logger.info("Compute Optimizer not enabled — opt in via AWS Console")
            return []
        logger.error(f"Compute Optimizer error: {e}")
        raise

    return recommendations


def get_ebs_recommendations(max_results: int = 50) -> list[dict]:
    """
    Get EBS volume optimization recommendations.

    Returns:
        List of recommendation dicts for over-provisioned EBS volumes.
    """
    client = _get_co_client()
    recommendations = []

    try:
        response = client.get_ebs_volume_recommendations(
            maxResults=max_results,
            filters=[
                {
                    "name": "Finding",
                    "values": ["Overprovisioned"],
                }
            ],
        )

        for rec in response.get("volumeRecommendations", []):
            volume_arn = rec.get("volumeArn", "")
            current_config = rec.get("currentConfiguration", {})
            finding = rec.get("finding", "unknown")

            options = rec.get("volumeRecommendationOptions", [])
            estimated_savings = 0.0
            recommended_config = {}

            if options:
                top_option = options[0]
                recommended_config = top_option.get("configuration", {})
                savings_opportunity = top_option.get("savingsOpportunity", {})
                estimated_savings = float(
                    savings_opportunity.get("estimatedMonthlySavings", {}).get("value", 0)
                )

            recommendations.append({
                "volume_arn": volume_arn,
                "current_type": current_config.get("volumeType", "unknown"),
                "current_size_gb": current_config.get("volumeSize", 0),
                "recommended_type": recommended_config.get("volumeType", ""),
                "recommended_size_gb": recommended_config.get("volumeSize", 0),
                "finding": finding,
                "estimated_monthly_savings": estimated_savings,
            })

    except ClientError as e:
        if "OptInRequiredException" in str(e):
            logger.info("Compute Optimizer not enabled for EBS")
            return []
        logger.error(f"Compute Optimizer EBS error: {e}")
        raise

    return recommendations
