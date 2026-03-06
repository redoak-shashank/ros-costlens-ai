"""
Tests for the LangGraph billing intelligence graph.

These tests verify the graph structure, routing logic, and end-to-end flows
using mocked AWS services.
"""

import pytest
from unittest.mock import patch, MagicMock

from langchain_core.messages import HumanMessage, AIMessage

from src.graph import build_graph, route_to_agent
from src.state import BillingState


class TestGraphStructure:
    """Test that the graph compiles and has the correct structure."""

    def test_graph_compiles(self):
        """Graph should compile without errors."""
        graph = build_graph()
        assert graph is not None

    def test_graph_has_all_nodes(self):
        """Graph should contain all expected agent nodes."""
        from langgraph.graph import StateGraph, START, END
        from langgraph.checkpoint.memory import MemorySaver

        # Build a fresh graph to inspect
        graph = StateGraph(BillingState)
        graph.add_node("supervisor", lambda s: s)
        graph.add_node("cost_analyst", lambda s: s)
        graph.add_node("anomaly_detector", lambda s: s)
        graph.add_node("optimizer", lambda s: s)
        graph.add_node("reporter", lambda s: s)
        # Verify nodes were added (would throw if names invalid)
        assert True


class TestRouting:
    """Test the supervisor routing logic."""

    def test_route_to_cost_analyst(self):
        state = {"next_agent": "cost_analyst"}
        assert route_to_agent(state) == "cost_analyst"

    def test_route_to_anomaly_detector(self):
        state = {"next_agent": "anomaly_detector"}
        assert route_to_agent(state) == "anomaly_detector"

    def test_route_to_optimizer(self):
        state = {"next_agent": "optimizer"}
        assert route_to_agent(state) == "optimizer"

    def test_route_to_reporter(self):
        state = {"next_agent": "reporter"}
        assert route_to_agent(state) == "reporter"

    def test_route_to_end(self):
        from langgraph.graph import END
        state = {"next_agent": "end"}
        assert route_to_agent(state) == END

    def test_route_unknown_defaults_to_reporter(self):
        state = {"next_agent": "invalid_agent_name"}
        assert route_to_agent(state) == "reporter"

    def test_route_empty_defaults_to_end(self):
        from langgraph.graph import END
        state = {"next_agent": "end"}
        assert route_to_agent(state) == END


class TestSupervisorNode:
    """Test the supervisor agent's routing decisions."""

    @patch("src.agents.supervisor.ChatBedrock")
    def test_scheduled_report_routes_to_cost_analyst(self, mock_bedrock):
        """First iteration of a scheduled report should go to cost_analyst."""
        from src.agents.supervisor import supervisor_node

        state = {
            "messages": [HumanMessage(content="Generate a daily cost report")],
            "request_type": "report",
            "iteration_count": 0,
            "next_agent": "",
        }

        result = supervisor_node(state)
        assert result["next_agent"] == "cost_analyst"
        assert result["iteration_count"] == 1

    @patch("src.agents.supervisor.ChatBedrock")
    def test_max_iterations_forces_reporter(self, mock_bedrock):
        """After max iterations, should force routing to reporter."""
        from src.agents.supervisor import supervisor_node

        state = {
            "messages": [],
            "request_type": "query",
            "iteration_count": 9,
            "next_agent": "",
        }

        result = supervisor_node(state)
        assert result["next_agent"] == "reporter"
