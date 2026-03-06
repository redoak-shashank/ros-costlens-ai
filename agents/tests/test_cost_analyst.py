"""
Tests for the Cost Analyst agent.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta


class TestCostAnalystHelpers:
    """Test cost analyst helper functions."""

    @patch("src.agents.cost_analyst.get_cost_and_usage")
    def test_get_yesterday_spend(self, mock_ce):
        """Should parse Cost Explorer response into clean format."""
        from src.agents.cost_analyst import _get_yesterday_spend

        mock_ce.side_effect = [
            # Total spend call
            {
                "ResultsByTime": [{
                    "TimePeriod": {"Start": "2026-02-12", "End": "2026-02-13"},
                    "Total": {"UnblendedCost": {"Amount": "1247.32", "Unit": "USD"}},
                }]
            },
            # Per-service call
            {
                "ResultsByTime": [{
                    "TimePeriod": {"Start": "2026-02-12", "End": "2026-02-13"},
                    "Groups": [
                        {"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "507.00"}}},
                        {"Keys": ["Amazon RDS"], "Metrics": {"UnblendedCost": {"Amount": "312.50"}}},
                        {"Keys": ["Amazon S3"], "Metrics": {"UnblendedCost": {"Amount": "42.80"}}},
                    ],
                }]
            },
        ]

        result = _get_yesterday_spend()

        assert result["total"] == 1247.32
        assert "Amazon EC2" in result["services"]
        assert result["services"]["Amazon EC2"] == 507.00

    @patch("src.agents.cost_analyst.get_cost_and_usage")
    def test_get_trend_data(self, mock_ce):
        """Should return a list of daily cost points."""
        from src.agents.cost_analyst import _get_trend_data

        mock_ce.return_value = {
            "ResultsByTime": [
                {
                    "TimePeriod": {"Start": f"2026-02-{10+i:02d}"},
                    "Total": {"UnblendedCost": {"Amount": str(1000 + i * 50)}},
                }
                for i in range(5)
            ]
        }

        result = _get_trend_data(days=5)

        assert len(result) == 5
        assert result[0]["cost"] == 1000.0
        assert result[4]["cost"] == 1200.0


class TestCostAnalystNode:
    """Test the full cost analyst node."""

    @patch("src.agents.cost_analyst._get_forecast")
    @patch("src.agents.cost_analyst._get_mtd_spend")
    @patch("src.agents.cost_analyst._get_yesterday_spend")
    @patch("src.agents.cost_analyst._get_trend_data")
    def test_report_mode_pulls_all_data(self, mock_trend, mock_yesterday, mock_mtd, mock_forecast):
        """In report mode, should pull all standard metrics."""
        from src.agents.cost_analyst import cost_analyst_node

        mock_yesterday.return_value = {"total": 1200, "services": {}, "date": "2026-02-12"}
        mock_mtd.return_value = {"total": 15000, "period_start": "2026-02-01", "period_end": "2026-02-12"}
        mock_forecast.return_value = {"forecast_total": 38000, "period_end": "2026-02-28"}
        mock_trend.return_value = [{"date": "2026-02-12", "cost": 1200}]

        state = {
            "messages": [],
            "request_type": "report",
        }

        result = cost_analyst_node(state)

        assert result["daily_spend"]["total"] == 1200
        assert result["mtd_spend"]["total"] == 15000
        assert result["forecast"]["forecast_total"] == 38000
