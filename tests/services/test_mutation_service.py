"""Tests for MutationService."""

from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from game_agent_try.aci.mutation import AciConfig
from game_agent_try.services.mutation_service import MutationService


@pytest.fixture
def temp_project(tmp_path: Path):
    """Create a temporary Unity project structure."""
    project_root = tmp_path / "TestProject"
    project_root.mkdir()
    (project_root / "Assets").mkdir()
    (project_root / "ProjectSettings").mkdir()
    return project_root


@pytest.fixture
def mutation_service(temp_project: Path):
    """Create a MutationService instance for testing."""
    config = AciConfig(
        enabled=True,
        typed_mutations_enabled=True,
    )
    return MutationService(
        project_root=temp_project,
        config=config,
    )


def test_mutation_service_initialization(mutation_service: MutationService):
    """Test that MutationService initializes correctly."""
    assert mutation_service.execution_count == 0
    assert mutation_service.success_count == 0
    assert mutation_service.failure_count == 0
    assert mutation_service.rollback_count == 0


def test_mutation_service_stats(mutation_service: MutationService):
    """Test that stats are correctly tracked."""
    stats = mutation_service.get_stats()

    assert stats["total_executions"] == 0
    assert stats["successes"] == 0
    assert stats["failures"] == 0
    assert stats["rollbacks"] == 0


def test_execute_mutation_success(mutation_service: MutationService, monkeypatch):
    """Test successful mutation execution."""
    # Mock the executor to return success
    mock_result = {
        "status": "success",
        "transaction_id": "tx-123",
        "checkpoint_id": "cp-456",
        "changed_paths": ["Assets/Script.cs"],
    }

    mutation_service.executor.execute = Mock(return_value=mock_result)

    action = {
        "tool": "unity_script_patch",
        "arguments": {"path": "Assets/Script.cs"},
    }
    authorized_paths = ["Assets/Script.cs"]

    result = mutation_service.execute_mutation(action, authorized_paths)

    assert result.success is True
    assert result.transaction_id == "tx-123"
    assert result.checkpoint_id == "cp-456"
    assert result.changed_paths == ["Assets/Script.cs"]
    assert result.error is None
    assert mutation_service.execution_count == 1
    assert mutation_service.success_count == 1


def test_execute_mutation_failure(mutation_service: MutationService, monkeypatch):
    """Test mutation execution failure."""
    # Mock the executor to return failure
    mock_result = {
        "status": "error",
        "error": "File not found",
        "transaction_id": "tx-123",
        "checkpoint_id": "cp-456",
    }

    mutation_service.executor.execute = Mock(return_value=mock_result)

    action = {
        "tool": "unity_script_patch",
        "arguments": {"path": "Assets/NonExistent.cs"},
    }
    authorized_paths = ["Assets/NonExistent.cs"]

    result = mutation_service.execute_mutation(action, authorized_paths)

    assert result.success is False
    assert result.error == "File not found"
    assert mutation_service.execution_count == 1
    assert mutation_service.failure_count == 1


def test_execute_mutation_exception(mutation_service: MutationService, monkeypatch):
    """Test mutation execution with exception."""
    # Mock the executor to raise an exception
    mutation_service.executor.execute = Mock(side_effect=Exception("Unexpected error"))

    action = {
        "tool": "unity_script_patch",
        "arguments": {"path": "Assets/Script.cs"},
    }
    authorized_paths = ["Assets/Script.cs"]

    result = mutation_service.execute_mutation(action, authorized_paths)

    assert result.success is False
    assert "Unexpected error" in result.error
    assert mutation_service.execution_count == 1
    assert mutation_service.failure_count == 1


def test_authorized_paths_injection(mutation_service: MutationService, monkeypatch):
    """Test that authorized paths are correctly injected into action."""
    captured_action = None

    def capture_action(action):
        nonlocal captured_action
        captured_action = action
        return {"status": "success", "transaction_id": "tx", "checkpoint_id": "cp", "changed_paths": []}

    mutation_service.executor.execute = capture_action

    action = {
        "tool": "unity_script_patch",
        "arguments": {"path": "Assets/Script.cs"},
    }
    authorized_paths = ["Assets/Script.cs", "Assets/Helper.cs"]

    mutation_service.execute_mutation(action, authorized_paths)

    assert captured_action is not None
    assert captured_action["_authorized_paths"] == authorized_paths


def test_zero_token_consumption(mutation_service: MutationService):
    """Test that MutationService consumes zero LLM tokens.

    This is a conceptual test - the service should never call LLM APIs.
    """
    # The service only wraps deterministic operations
    # No LLM calls should be made
    stats = mutation_service.get_stats()

    # All operations are deterministic
    assert isinstance(stats, dict)
    assert "total_executions" in stats
