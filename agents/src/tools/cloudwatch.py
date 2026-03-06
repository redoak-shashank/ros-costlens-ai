"""
CloudWatch metrics tool for resource utilization analysis.

Used by the Optimizer agent to identify underutilized EC2 instances
and other idle resources.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import boto3
from botocore.exceptions import ClientError

from ..config.settings import get_settings

logger = logging.getLogger(__name__)

_cw_client = None
_ec2_client = None


def _get_cw_client():
    global _cw_client
    if _cw_client is None:
        settings = get_settings()
        _cw_client = boto3.client("cloudwatch", region_name=settings.aws_region)
    return _cw_client


def _get_ec2_client():
    global _ec2_client
    if _ec2_client is None:
        settings = get_settings()
        _ec2_client = boto3.client("ec2", region_name=settings.aws_region)
    return _ec2_client


def get_low_utilization_instances(
    cpu_threshold: float = 5.0,
    period_days: int = 7,
) -> list[dict]:
    """
    Find EC2 instances with average CPU utilization below a threshold.

    Args:
        cpu_threshold: CPU percentage threshold (instances below this are flagged).
        period_days: Number of days to average over.

    Returns:
        List of dicts with instance details and utilization info.
    """
    ec2 = _get_ec2_client()
    cw = _get_cw_client()

    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=period_days)

    low_util = []

    try:
        # Get all running instances
        paginator = ec2.get_paginator("describe_instances")
        instances = []

        for page in paginator.paginate(
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
        ):
            for reservation in page["Reservations"]:
                for instance in reservation["Instances"]:
                    instances.append(instance)

        logger.info(f"Checking CPU utilization for {len(instances)} running instances")

        for instance in instances:
            instance_id = instance["InstanceId"]
            instance_type = instance.get("InstanceType", "unknown")

            try:
                # Get average CPU for the period
                response = cw.get_metric_statistics(
                    Namespace="AWS/EC2",
                    MetricName="CPUUtilization",
                    Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=86400,  # 1 day
                    Statistics=["Average"],
                )

                datapoints = response.get("Datapoints", [])
                if not datapoints:
                    continue

                avg_cpu = sum(dp["Average"] for dp in datapoints) / len(datapoints)

                if avg_cpu < cpu_threshold:
                    # Get instance name from tags
                    name = ""
                    for tag in instance.get("Tags", []):
                        if tag["Key"] == "Name":
                            name = tag["Value"]
                            break

                    # Estimate monthly cost (rough, based on instance type)
                    monthly_cost = _estimate_instance_monthly_cost(instance_type)

                    region = instance.get("Placement", {}).get("AvailabilityZone", "")[:-1]

                    low_util.append({
                        "instance_id": instance_id,
                        "instance_type": instance_type,
                        "name": name,
                        "region": region,
                        "avg_cpu": round(avg_cpu, 2),
                        "monthly_cost": monthly_cost,
                        "launch_time": instance.get("LaunchTime", "").isoformat()
                        if instance.get("LaunchTime")
                        else "",
                    })

            except ClientError as e:
                logger.debug(f"Failed to get metrics for {instance_id}: {e}")
                continue

    except ClientError as e:
        logger.error(f"Failed to list EC2 instances: {e}")
        raise

    # Sort by monthly cost (highest first = highest savings potential)
    low_util.sort(key=lambda x: x["monthly_cost"], reverse=True)

    logger.info(f"Found {len(low_util)} instances below {cpu_threshold}% CPU")
    return low_util


def _estimate_instance_monthly_cost(instance_type: str) -> float:
    """
    Rough monthly cost estimate for an instance type.
    In production, use the AWS Pricing API or a lookup table.
    """
    # Simplified cost tiers (us-east-1 Linux on-demand, approximate)
    cost_map = {
        "t3.micro": 7.60,
        "t3.small": 15.18,
        "t3.medium": 30.37,
        "t3.large": 60.74,
        "t3.xlarge": 121.47,
        "m5.large": 69.12,
        "m5.xlarge": 138.24,
        "m5.2xlarge": 276.48,
        "c5.large": 61.20,
        "c5.xlarge": 122.40,
        "c5.2xlarge": 244.80,
        "r5.large": 90.72,
        "r5.xlarge": 181.44,
        "r5.2xlarge": 362.88,
    }

    # Try exact match, then family match
    if instance_type in cost_map:
        return cost_map[instance_type]

    # Rough estimate by size suffix
    if "nano" in instance_type:
        return 3.50
    elif "micro" in instance_type:
        return 7.50
    elif "small" in instance_type:
        return 15.00
    elif "medium" in instance_type:
        return 30.00
    elif "xlarge" in instance_type and "2x" not in instance_type:
        return 120.00
    elif "2xlarge" in instance_type:
        return 250.00
    elif "4xlarge" in instance_type:
        return 500.00
    elif "large" in instance_type:
        return 65.00

    return 50.00  # Default guess
