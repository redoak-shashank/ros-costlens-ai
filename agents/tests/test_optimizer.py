"""
Tests for the Optimizer agent.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestOptimizer:
    """Test optimizer helper functions and node."""

    @patch("src.agents.optimizer._check_compute_optimizer")
    @patch("src.agents.optimizer._check_savings_plans_coverage")
    @patch("src.agents.optimizer._check_trusted_advisor")
    @patch("src.agents.optimizer._check_idle_resources")
    def test_optimizer_aggregates_all_sources(
        self, mock_idle, mock_ta, mock_sp, mock_co
    ):
        """Optimizer should aggregate recommendations from all sources."""
        from src.agents.optimizer import optimizer_node

        mock_idle.return_value = [
            {
                "type": "idle_instance",
                "resource_id": "i-abc123",
                "estimated_monthly_savings": 65.00,
                "description": "i-abc123 idle",
            }
        ]
        mock_ta.return_value = [
            {
                "type": "trusted_advisor",
                "check_name": "Idle ELBs",
                "estimated_monthly_savings": 18.00,
                "description": "2 idle load balancers",
            }
        ]
        mock_sp.return_value = [
            {
                "type": "savings_plan_gap",
                "estimated_monthly_savings": 890.00,
                "description": "SP coverage gap",
            }
        ]
        mock_co.return_value = [
            {
                "type": "right_sizing",
                "resource_id": "i-def456",
                "estimated_monthly_savings": 45.00,
                "description": "Right-size i-def456",
            }
        ]

        state = {"messages": [], "request_type": "report"}
        result = optimizer_node(state)

        assert len(result["recommendations"]) == 4
        assert result["total_potential_savings"] == 1018.00

        # Should be sorted by savings (highest first)
        savings = [r["estimated_monthly_savings"] for r in result["recommendations"]]
        assert savings == sorted(savings, reverse=True)

    @patch("src.agents.optimizer._check_compute_optimizer")
    @patch("src.agents.optimizer._check_savings_plans_coverage")
    @patch("src.agents.optimizer._check_trusted_advisor")
    @patch("src.agents.optimizer._check_idle_resources")
    def test_optimizer_handles_empty_results(
        self, mock_idle, mock_ta, mock_sp, mock_co
    ):
        """Should return empty recommendations gracefully."""
        from src.agents.optimizer import optimizer_node

        mock_idle.return_value = []
        mock_ta.return_value = []
        mock_sp.return_value = []
        mock_co.return_value = []

        state = {"messages": [], "request_type": "report"}
        result = optimizer_node(state)

        assert result["recommendations"] == []
        assert result["total_potential_savings"] == 0

    @patch("src.agents.optimizer._check_compute_optimizer")
    @patch("src.agents.optimizer._check_savings_plans_coverage")
    @patch("src.agents.optimizer._check_trusted_advisor")
    @patch("src.agents.optimizer._check_idle_resources")
    def test_optimizer_handles_errors_gracefully(
        self, mock_idle, mock_ta, mock_sp, mock_co
    ):
        """Should handle errors from individual sources without failing entirely."""
        from src.agents.optimizer import optimizer_node

        mock_idle.side_effect = Exception("CloudWatch error")
        mock_ta.return_value = [
            {
                "type": "trusted_advisor",
                "check_name": "Test",
                "estimated_monthly_savings": 50.0,
                "description": "Test rec",
            }
        ]
        mock_sp.return_value = []
        mock_co.return_value = []

        state = {"messages": [], "request_type": "report"}
        result = optimizer_node(state)

        # Should still return TA results despite CloudWatch failure
        assert len(result["recommendations"]) == 1
