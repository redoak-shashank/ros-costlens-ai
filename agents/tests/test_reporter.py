"""
Tests for the Reporter agent.
"""

import json
from unittest.mock import patch, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage


class TestReporterFormatting:
    """Test report formatting functions."""

    def test_format_daily_report_basic(self):
        """Should format a basic daily report with spend data."""
        from src.agents.reporter import _format_daily_report

        state = {
            "daily_spend": {"date": "2026-02-12", "total": 1234.56, "services": {
                "Amazon EC2": 500.00,
                "Amazon RDS": 300.00,
                "Amazon S3": 100.00,
            }},
            "mtd_spend": {"total": 8500.00},
            "forecast": {"forecast_total": 18000},
            "trend_data": [
                {"date": "2026-02-11", "cost": 1100.00},
                {"date": "2026-02-12", "cost": 1234.56},
            ],
            "anomalies": [],
            "recommendations": [],
            "service_breakdown": {},
        }

        result = _format_daily_report(state)

        assert "Daily AWS Cost Report" in result
        assert "$1,234.56" in result
        assert "$8,500.00" in result
        assert "Amazon EC2" in result
        assert "Amazon RDS" in result

    def test_format_daily_report_with_anomalies(self):
        """Should include anomaly alerts in the report."""
        from src.agents.reporter import _format_daily_report

        state = {
            "daily_spend": {"total": 2000.00, "services": {}},
            "mtd_spend": {"total": 10000.00},
            "forecast": {},
            "trend_data": [],
            "anomalies": [
                {"description": "EC2 spend up 45% day-over-day"},
                {"description": "New service detected: Amazon Bedrock"},
            ],
            "severity": "high",
            "recommendations": [],
            "service_breakdown": {},
        }

        result = _format_daily_report(state)

        assert "Anomalies Detected" in result
        assert "EC2 spend up 45%" in result
        assert "Amazon Bedrock" in result

    def test_format_daily_report_with_recommendations(self):
        """Should include savings opportunities."""
        from src.agents.reporter import _format_daily_report

        state = {
            "daily_spend": {"total": 1500.00, "services": {}},
            "mtd_spend": {"total": 9000.00},
            "forecast": {},
            "trend_data": [],
            "anomalies": [],
            "recommendations": [
                {"description": "Right-size i-abc123", "estimated_monthly_savings": 120.00},
                {"description": "Delete idle ELB", "estimated_monthly_savings": 18.00},
            ],
            "total_potential_savings": 138.00,
            "service_breakdown": {},
        }

        result = _format_daily_report(state)

        assert "Savings Opportunities" in result
        assert "$138.00" in result
        assert "Right-size i-abc123" in result

    def test_format_daily_report_wow(self):
        """Should show week-over-week changes when available."""
        from src.agents.reporter import _format_daily_report

        state = {
            "daily_spend": {"total": 1500.00, "services": {"Amazon EC2": 800.0}},
            "mtd_spend": {"total": 9000.00},
            "forecast": {},
            "trend_data": [],
            "anomalies": [],
            "recommendations": [],
            "service_breakdown": {
                "services": {"Amazon EC2": 5600.00},
                "week_over_week": {
                    "Amazon EC2": {"this_week": 5600.00, "prior_week": 5000.00, "change_pct": 12.0},
                },
            },
        }

        result = _format_daily_report(state)

        assert "Week-over-Week" in result
        assert "12.0% WoW" in result


class TestReporterFormatAnomalyAlert:
    """Test anomaly alert formatting."""

    def test_format_anomaly_alert(self):
        """Should format anomaly alerts with severity."""
        from src.agents.reporter import _format_anomaly_alert

        state = {
            "anomalies": [
                {"description": "RDS spend spiked 80%"},
            ],
            "severity": "critical",
        }

        result = _format_anomaly_alert(state)

        assert "Cost Anomaly Alert" in result
        assert "CRITICAL" in result
        assert "RDS spend spiked 80%" in result


class TestReporterBuildDashboardData:
    """Test dashboard data payload construction."""

    def test_build_dashboard_data(self):
        """Should build a complete dashboard payload."""
        from src.agents.reporter import _build_dashboard_data

        state = {
            "daily_spend": {"total": 1000.00},
            "mtd_spend": {"total": 5000.00},
            "forecast": {"forecast_total": 15000},
            "trend_data": [{"date": "2026-02-12", "cost": 1000.00}],
            "service_breakdown": {"services": {"EC2": 500}},
            "anomalies": [{"description": "test anomaly"}],
            "severity": "medium",
            "recommendations": [{"description": "test rec"}],
            "total_potential_savings": 100.00,
        }

        result = _build_dashboard_data(state)

        assert "updated_at" in result
        assert result["daily_spend"]["total"] == 1000.00
        assert result["forecast"]["forecast_total"] == 15000
        assert len(result["anomalies"]) == 1

    def test_build_dashboard_data_includes_tag_breakdown(self):
        """Should include tag_breakdown when present in state."""
        from src.agents.reporter import _build_dashboard_data

        tag_data = [{"team": "platform", "cost": 500.0}]
        state = {
            "daily_spend": None,
            "mtd_spend": None,
            "forecast": None,
            "trend_data": None,
            "service_breakdown": None,
            "anomalies": None,
            "severity": "",
            "recommendations": None,
            "total_potential_savings": None,
            "dashboard_data": {"tag_breakdown": tag_data},
        }

        result = _build_dashboard_data(state)

        assert result["tag_breakdown"] == tag_data


class TestReporterNode:
    """Test the main reporter_node function."""

    @patch("src.agents.reporter._persist_dashboard_data")
    @patch("src.agents.reporter.send_slack_message")
    def test_reporter_node_daily_report(self, mock_slack, mock_s3):
        """Should format + send a daily report and persist dashboard data."""
        from src.agents.reporter import reporter_node

        mock_slack.return_value = {"ok": True}
        mock_s3.return_value = True

        state = {
            "request_type": "report",
            "daily_spend": {"total": 1200.00, "services": {"EC2": 800}},
            "mtd_spend": {"total": 6000.00},
            "forecast": {"forecast_total": 15000},
            "trend_data": [],
            "anomalies": [],
            "recommendations": [],
            "service_breakdown": {},
            "messages": [],
        }

        result = reporter_node(state)

        assert result["slack_message"] is not None
        assert "Daily AWS Cost Report" in result["slack_message"]
        assert result["dashboard_data"] is not None
        mock_slack.assert_called_once()
        mock_s3.assert_called_once()

    @patch("src.agents.reporter._persist_dashboard_data")
    @patch("src.agents.reporter._build_weekday_spend_chart_png")
    @patch("src.agents.reporter.send_slack_file")
    @patch("src.agents.reporter.send_slack_message")
    def test_reporter_node_uploads_chart_for_report(
        self,
        mock_slack_message,
        mock_slack_file,
        mock_chart_png,
        mock_s3,
    ):
        """Scheduled daily reports should upload weekday spend chart image to Slack."""
        from src.agents.reporter import reporter_node

        mock_slack_message.return_value = {"ok": True, "ts": "1710000000.000100"}
        mock_chart_png.return_value = b"fake_png_bytes"
        mock_slack_file.return_value = {"ok": True, "file": {"id": "F123"}}
        mock_s3.return_value = True

        state = {
            "request_type": "report",
            "daily_spend": {"total": 1200.00, "services": {"EC2": 800}},
            "mtd_spend": {"total": 6000.00},
            "forecast": {"forecast_total": 15000},
            "trend_data": [{"date": "2026-03-19", "cost": 1200.00}],
            "anomalies": [],
            "recommendations": [],
            "service_breakdown": {},
            "messages": [],
        }

        reporter_node(state)

        mock_slack_message.assert_called_once()
        mock_chart_png.assert_called_once()
        mock_slack_file.assert_called_once()
        kwargs = mock_slack_file.call_args.kwargs
        assert kwargs["thread_ts"] == "1710000000.000100"

    @patch("src.agents.reporter._persist_dashboard_data")
    @patch("src.agents.reporter.send_slack_message")
    def test_reporter_node_interactive_query(self, mock_slack, mock_s3):
        """Should format interactive response without persisting to S3."""
        from src.agents.reporter import reporter_node

        mock_slack.return_value = {"ok": True}

        state = {
            "request_type": "query",
            "messages": [
                HumanMessage(content="What did EC2 cost yesterday?"),
                AIMessage(content="EC2 cost $800 yesterday."),
            ],
        }

        result = reporter_node(state)

        assert result["slack_message"] == "EC2 cost $800 yesterday."
        assert result["dashboard_data"] is None
        mock_s3.assert_not_called()

    @patch("src.agents.reporter.send_slack_message")
    def test_reporter_node_handles_slack_failure(self, mock_slack):
        """Should handle Slack send failure gracefully."""
        from src.agents.reporter import reporter_node

        mock_slack.return_value = {"ok": False, "error": "channel_not_found"}

        state = {
            "request_type": "query",
            "messages": [AIMessage(content="test response")],
        }

        # Should not raise
        result = reporter_node(state)
        assert result["slack_message"] is not None


class TestPersistDashboardData:
    """Test S3 persistence of dashboard data."""

    @patch("src.agents.reporter._get_s3_client")
    @patch("src.agents.reporter.get_settings")
    def test_persist_dashboard_data_success(self, mock_settings, mock_s3_client):
        """Should write to both latest.json and dated archive."""
        from src.agents.reporter import _persist_dashboard_data

        settings = MagicMock()
        settings.dashboard_data_bucket = "my-dashboard-bucket"
        settings.aws_region = "us-east-1"
        mock_settings.return_value = settings

        s3 = MagicMock()
        mock_s3_client.return_value = s3

        data = {"updated_at": "2026-02-13T00:00:00", "daily_spend": {"total": 100}}

        result = _persist_dashboard_data(data)

        assert result is True
        assert s3.put_object.call_count == 2

        # Verify the keys written
        calls = s3.put_object.call_args_list
        keys = [call.kwargs.get("Key") or call[1].get("Key") for call in calls]
        assert "dashboard/latest.json" in keys

    @patch("src.agents.reporter.get_settings")
    def test_persist_dashboard_data_no_bucket(self, mock_settings):
        """Should skip S3 write when bucket is not configured."""
        from src.agents.reporter import _persist_dashboard_data

        settings = MagicMock()
        settings.dashboard_data_bucket = ""
        mock_settings.return_value = settings

        result = _persist_dashboard_data({"test": True})

        assert result is False
