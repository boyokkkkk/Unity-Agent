"""Tests for ExplorerAgent."""

from pathlib import Path
from unittest.mock import Mock, MagicMock

import pytest

from game_agent_try.agents.explorer import ExplorerAgent
from game_agent_try.agents.models import ExplorationTask


@pytest.fixture
def mock_model():
    """Create a mock model."""
    model = Mock()
    model.query = Mock(return_value={
        "content": "Found relevant code",
        "tool_calls": [],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
        },
    })
    return model


@pytest.fixture
def mock_context():
    """Create a mock context assembler."""
    context = Mock()
    context.project_store = Mock()
    return context


@pytest.fixture
def temp_project(tmp_path: Path):
    """Create a temporary Unity project structure."""
    project_root = tmp_path / "TestProject"
    project_root.mkdir()
    (project_root / "Assets").mkdir()
    return project_root


def test_explorer_initialization(mock_model, mock_context, temp_project):
    """Test that ExplorerAgent initializes correctly."""
    explorer = ExplorerAgent(
        model=mock_model,
        context=mock_context,
        project_root=temp_project,
        max_rounds=10,
        max_tokens=40_000,
    )

    assert explorer.max_rounds == 10
    assert explorer.max_tokens == 40_000
    assert explorer.rounds_used == 0
    assert explorer.tokens_used == 0
    assert len(explorer.evidence_items) == 0
    assert len(explorer.candidate_nodes) == 0


def test_explorer_clean_context(mock_model, mock_context, temp_project):
    """Test that Explorer starts with clean message history."""
    explorer = ExplorerAgent(
        model=mock_model,
        context=mock_context,
        project_root=temp_project,
    )

    assert len(explorer.messages) == 0


def test_explorer_basic_exploration(mock_model, mock_context, temp_project):
    """Test basic exploration flow."""
    # Model returns no tool calls (finishes immediately)
    mock_model.query = Mock(return_value={
        "content": "Exploration complete",
        "tool_calls": [],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
        },
    })

    explorer = ExplorerAgent(
        model=mock_model,
        context=mock_context,
        project_root=temp_project,
        max_rounds=5,
    )

    task = ExplorationTask(
        query="Find GameStateManager",
        max_results=10,
        max_rounds=5,
    )

    result = explorer.explore(task)

    assert result.success is True
    assert result.rounds_used >= 1
    assert result.tokens_used > 0
    assert result.search_strategy == "adaptive"
    assert mock_model.query.called


def test_explorer_token_tracking(mock_model, mock_context, temp_project):
    """Test that Explorer tracks token usage correctly."""
    mock_model.query = Mock(return_value={
        "content": "Found it",
        "tool_calls": [],
        "usage": {
            "prompt_tokens": 500,
            "completion_tokens": 200,
        },
    })

    explorer = ExplorerAgent(
        model=mock_model,
        context=mock_context,
        project_root=temp_project,
    )

    task = ExplorationTask(query="Test query", max_results=5)
    result = explorer.explore(task)

    assert result.tokens_used == 700  # 500 + 200
    assert explorer.prompt_tokens == 500
    assert explorer.completion_tokens == 200


def test_explorer_token_budget_limit(mock_model, mock_context, temp_project):
    """Test that Explorer respects token budget."""
    # Model returns tool calls to continue exploration
    mock_model.query = Mock(return_value={
        "content": "Searching...",
        "tool_calls": [
            {
                "id": "call_1",
                "function": {
                    "name": "unity_asset_search",
                    "arguments": {"query": "test"},
                },
            }
        ],
        "usage": {
            "prompt_tokens": 15_000,
            "completion_tokens": 5_000,
        },
    })

    explorer = ExplorerAgent(
        model=mock_model,
        context=mock_context,
        project_root=temp_project,
        max_rounds=10,
        max_tokens=30_000,  # Will be exceeded after 2 calls
    )

    task = ExplorationTask(query="Test", max_results=20, max_rounds=10)
    result = explorer.explore(task)

    # Should stop due to token budget
    assert result.rounds_used < 10
    assert result.tokens_used >= 30_000 or result.rounds_used < 5


def test_explorer_round_limit(mock_model, mock_context, temp_project):
    """Test that Explorer respects round limit."""
    call_count = 0

    def mock_query_with_tools(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Always return tool calls to continue
        return {
            "content": f"Round {call_count}",
            "tool_calls": [
                {
                    "id": f"call_{call_count}",
                    "function": {
                        "name": "unity_asset_search",
                        "arguments": {"query": "test"},
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
            },
        }

    mock_model.query = mock_query_with_tools

    explorer = ExplorerAgent(
        model=mock_model,
        context=mock_context,
        project_root=temp_project,
        max_rounds=3,
        max_tokens=100_000,
    )

    task = ExplorationTask(query="Test", max_results=20, max_rounds=3)
    result = explorer.explore(task)

    # Should stop at max_rounds
    assert result.rounds_used == 3


def test_explorer_evidence_package_structure(mock_model, mock_context, temp_project):
    """Test that Explorer returns properly structured evidence package."""
    mock_model.query = Mock(return_value={
        "content": "Done",
        "tool_calls": [],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    })

    explorer = ExplorerAgent(
        model=mock_model,
        context=mock_context,
        project_root=temp_project,
    )

    task = ExplorationTask(query="Find code", max_results=10)
    result = explorer.explore(task)

    # Check structure
    assert hasattr(result, "success")
    assert hasattr(result, "evidence_items")
    assert hasattr(result, "candidate_nodes")
    assert hasattr(result, "summary")
    assert hasattr(result, "tokens_used")
    assert hasattr(result, "rounds_used")
    assert hasattr(result, "search_strategy")
    assert isinstance(result.evidence_items, list)
    assert isinstance(result.candidate_nodes, list)
    assert isinstance(result.summary, str)


def test_explorer_error_handling(mock_model, mock_context, temp_project):
    """Test that Explorer handles errors gracefully."""
    mock_model.query = Mock(side_effect=Exception("Model failure"))

    explorer = ExplorerAgent(
        model=mock_model,
        context=mock_context,
        project_root=temp_project,
    )

    task = ExplorationTask(query="Test", max_results=5)
    result = explorer.explore(task)

    assert result.success is False
    assert result.error is not None
    assert "Model failure" in result.error


def test_explorer_isolation(mock_model, mock_context, temp_project):
    """Test that Explorer maintains isolated state between explorations."""
    mock_model.query = Mock(return_value={
        "content": "Done",
        "tool_calls": [],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    })

    explorer = ExplorerAgent(
        model=mock_model,
        context=mock_context,
        project_root=temp_project,
    )

    # First exploration
    task1 = ExplorationTask(query="First query", max_results=5)
    result1 = explorer.explore(task1)

    # Second exploration
    task2 = ExplorationTask(query="Second query", max_results=5)
    result2 = explorer.explore(task2)

    # Each should start fresh (rounds reset)
    assert result1.rounds_used >= 1
    assert result2.rounds_used >= 1
    # State should be reset between explorations
    assert explorer.rounds_used >= 1  # From second exploration
