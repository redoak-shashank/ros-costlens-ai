"""
Tests for the Anomaly Detector agent.
"""

import pytest
from unittest.mock import patch


class TestAnomalyDetection:
    """Test anomaly detection helper functions."""

    def test_day_over_day_spike_detected(self):
        """Should detect a day-over-day spike above threshold."""
        from src.agents.anomaly_detector import _detect_day_over_day_anomalies

        # Normal baseline of ~1000/day, then a spike to 1500
        trend = [
            {"date": f"2026-02-{i+1:02d}", "cost": 1000 + (i * 5)}
            for i in range(7)
        ]
        trend.append({"date": "2026-02-08", "cost": 1500})  # 50% spike

        anomalies = _detect_day_over_day_anomalies(trend)

        assert len(anomalies) > 0
        spike_types = [a["type"] for a in anomalies]
        assert "day_over_day_spike" in spike_types

    def test_no_anomaly_on_normal_data(self):
        """Should not flag normal daily variation."""
        from src.agents.anomaly_detector import _detect_day_over_day_anomalies

        # Stable spend around $1000
        trend = [
            {"date": f"2026-02-{i+1:02d}", "cost": 1000 + (i % 3) * 10}
            for i in range(8)
        ]

        anomalies = _detect_day_over_day_anomalies(trend)

        # Should have no anomalies (variation is < 5%)
        spike_anomalies = [a for a in anomalies if a["type"] == "day_over_day_spike"]
        assert len(spike_anomalies) == 0

    def test_empty_trend_returns_empty(self):
        """Should handle empty trend data gracefully."""
        from src.agents.anomaly_detector import _detect_day_over_day_anomalies

        assert _detect_day_over_day_anomalies([]) == []
        assert _detect_day_over_day_anomalies([{"date": "2026-02-01", "cost": 100}]) == []

    def test_severity_classification(self):
        """Test severity assignment based on anomaly characteristics."""
        from src.agents.anomaly_detector import _determine_severity

        # Critical: >50% spike
        assert _determine_severity([{"pct_change": 55}]) == "critical"

        # Critical: statistical outlier
        assert _determine_severity([
            {"type": "statistical_outlier", "pct_change": 25}
        ]) == "critical"

        # High: 30-50%
        assert _determine_severity([{"pct_change": 35}]) == "high"

        # Medium: 15-30%
        assert _determine_severity([{"pct_change": 20}]) == "medium"

        # Low: <15%
        assert _determine_severity([{"pct_change": 10}]) == "low"

        # Empty
        assert _determine_severity([]) == ""
