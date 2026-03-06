"""
Optimizer Agent — Recommends EC2 cost savings opportunities.

Current scope intentionally focuses on EC2 only:
- idle/underutilized EC2 detection (CloudWatch metrics)
- right-sizing recommendations (Compute Optimizer)
"""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_aws import ChatBedrock
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..state import BillingState
from ..config.settings import get_settings
from ..tracing import trace_operation
from ..tools.cost_explorer import get_reservation_utilization, get_savings_plans_coverage
from ..tools.cloudwatch import get_low_utilization_instances
from ..tools.trusted_advisor import get_cost_optimization_checks
from ..tools.compute_optimizer import get_ec2_recommendations

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (Path(__file__).parent.parent / "prompts" / "optimizer.md").read_text()


def _check_idle_resources() -> list[dict]:
    """Find EC2 instances with consistently low CPU utilization."""
    recommendations = []

    try:
        low_util_instances = get_low_utilization_instances(
            cpu_threshold=5.0,
            period_days=7,
        )

        for instance in low_util_instances:
            recommendations.append({
                "type": "idle_instance",
                "resource_id": instance["instance_id"],
                "resource_type": instance.get("instance_type", "EC2"),
                "region": instance.get("region", "unknown"),
                "avg_cpu": instance.get("avg_cpu", 0),
                "estimated_monthly_savings": instance.get("monthly_cost", 0),
                "action": "Consider stopping or downsizing this instance",
                "description": (
                    f"{instance['instance_id']} ({instance.get('instance_type', '?')}) "
                    f"in {instance.get('region', '?')} — avg CPU {instance.get('avg_cpu', 0):.1f}% "
                    f"over 7 days"
                ),
            })
    except Exception as e:
        logger.warning(f"Failed to check idle resources: {e}")

    return recommendations


def _check_trusted_advisor() -> list[dict]:
    """Pull cost optimization recommendations from Trusted Advisor."""
    recommendations = []

    try:
        ta_checks = get_cost_optimization_checks()

        for check in ta_checks:
            recommendations.append({
                "type": "trusted_advisor",
                "check_name": check["name"],
                "status": check.get("status", "unknown"),
                "flagged_resources": check.get("flagged_count", 0),
                "estimated_monthly_savings": check.get("estimated_savings", 0),
                "description": check.get("description", ""),
                "action": check.get("recommended_action", "Review in Trusted Advisor"),
            })
    except Exception as e:
        logger.warning(f"Failed to check Trusted Advisor: {e}")

    return recommendations


def _check_savings_plans_coverage() -> list[dict]:
    """Check for Savings Plan/RI coverage gaps."""
    recommendations = []

    try:
        coverage = get_savings_plans_coverage()

        if coverage:
            coverage_pct = coverage.get("coverage_percentage", 100)
            on_demand_cost = coverage.get("on_demand_cost", 0)

            if coverage_pct < 80 and on_demand_cost > 100:
                estimated_savings = on_demand_cost * 0.30  # ~30% savings estimate

                recommendations.append({
                    "type": "savings_plan_gap",
                    "coverage_percentage": round(coverage_pct, 1),
                    "on_demand_cost": round(on_demand_cost, 2),
                    "estimated_monthly_savings": round(estimated_savings, 2),
                    "description": (
                        f"Savings Plan coverage is {coverage_pct:.1f}% — "
                        f"${on_demand_cost:.2f}/mo on-demand spend could be reduced "
                        f"~30% with a Compute Savings Plan"
                    ),
                    "action": (
                        "Consider purchasing a 1-year Compute Savings Plan "
                        "to cover on-demand workloads"
                    ),
                })
    except Exception as e:
        logger.warning(f"Failed to check savings plans: {e}")

    return recommendations


def _check_compute_optimizer() -> list[dict]:
    """Get right-sizing recommendations from Compute Optimizer."""
    recommendations = []

    try:
        ec2_recs = get_ec2_recommendations()

        for rec in ec2_recs:
            if rec.get("finding") in ("OVER_PROVISIONED", "Overprovisioned"):
                current = rec.get("current_instance_type", "unknown")
                recommended = rec.get("recommended_instance_type", "unknown")
                savings = rec.get("estimated_monthly_savings", 0)

                recommendations.append({
                    "type": "right_sizing",
                    "resource_id": rec.get("instance_id", ""),
                    "current_type": current,
                    "recommended_type": recommended,
                    "estimated_monthly_savings": round(savings, 2),
                    "description": (
                        f"{rec.get('instance_id', '?')}: right-size from {current} "
                        f"to {recommended} — save ~${savings:.2f}/mo"
                    ),
                    "action": f"Resize from {current} to {recommended}",
                })
    except Exception as e:
        logger.warning(f"Failed to check Compute Optimizer: {e}")

    return recommendations


@trace_operation("optimizer_analysis")
def optimizer_node(state: BillingState) -> dict:
    """Gather optimization recommendations (EC2-focused only)."""
    try:
        all_recommendations = []

        # EC2-only optimization scope:
        # - Idle/underutilized instances from CloudWatch
        # - Rightsizing findings from Compute Optimizer
        all_recommendations.extend(_check_idle_resources())
        all_recommendations.extend(_check_compute_optimizer())

        # Sort by potential savings (highest first)
        all_recommendations.sort(
            key=lambda r: r.get("estimated_monthly_savings", 0),
            reverse=True,
        )

        total_savings = sum(
            r.get("estimated_monthly_savings", 0)
            for r in all_recommendations
        )

        by_type = {}
        for rec in all_recommendations:
            rec_type = rec.get("type", "unknown")
            by_type[rec_type] = by_type.get(rec_type, 0) + 1

        if all_recommendations:
            summary = (
                f"Found {len(all_recommendations)} EC2 optimization opportunities "
                f"with ~${total_savings:.2f}/mo potential savings "
                f"({by_type})"
        )
        else:
            summary = "No EC2 optimization opportunities found right now."
            logger.info(summary)

        return {
            "recommendations": all_recommendations,
            "total_potential_savings": round(total_savings, 2),
            "messages": [AIMessage(content=summary)],
        }

    except Exception as e:
        logger.error(f"Optimizer error: {e}", exc_info=True)
        return {
            "error": f"Optimizer failed: {str(e)}",
            "recommendations": [],
            "total_potential_savings": 0,
            "messages": [AIMessage(content=f"Optimization analysis encountered an error: {e}")],
        }
