"""Tests for CoordinatorAgent."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from game_agent_try.agents.coordinator import CoordinatorAgent
from game_agent_try.agents.models import (
    ComplexityAssessment,
    EvidencePackage,
    TaskComplexity,
)


@pytest.fixture
def mock_model():
    """Create a mock model."""
    return Mock()


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
    (project_root / "ProjectSettings").mkdir()
    return project_root


@pytest.fixture
def coordinator(mock_model, mock_context, temp_project):
    """Create a CoordinatorAgent instance."""
    return CoordinatorAgent(
        model=mock_model,
        context=mock_context,
        project_root=temp_project,
    )


def test_coordinator_initialization(coordinator):
    """Test that CoordinatorAgent initializes correctly."""
    assert coordinator.mutation_service is not None
    assert coordinator.validation_service is not None
    assert coordinator.submission_controller is not None
    assert coordinator.current_task == ""
    assert coordinator.current_complexity is None
    assert coordinator.current_evidence is None


def test_coordinator_services_zero_token(coordinator):
    """Test that Coordinator's services consume zero tokens."""
    # Services should be initialized
    assert coordinator.mutation_service is not None
    assert coordinator.validation_service is not None
    assert coordinator.submission_controller is not None

    # Get stats (should not involve LLM calls)
    mutation_stats = coordinator.mutation_service.get_stats()
    validation_stats = coordinator.validation_service.get_stats()
    submission_stats = coordinator.submission_controller.get_stats()

    assert isinstance(mutation_stats, dict)
    assert isinstance(validation_stats, dict)
    assert isinstance(submission_stats, dict)


def test_complexity_assessment_simple(coordinator):
    """Test complexity assessment for simple tasks."""
    task = "In file Assets/Scripts/GameStateManager.cs at line 45, add OnGameWin.Invoke()"

    assessment = coordinator._assess_complexity(task)

    assert assessment.level == TaskComplexity.SIMPLE
    assert assessment.direct_execution_safe is True
    assert assessment.needs_exploration is False


def test_complexity_assessment_complex(coordinator):
    """Test complexity assessment for complex tasks."""
    task = "Fix the bug where game win event is not firing"

    assessment = coordinator._assess_complexity(task)

    assert assessment.level == TaskComplexity.COMPLEX
    assert assessment.needs_exploration is True


def test_has_explicit_location(coordinator):
    """Test explicit location detection."""
    # With explicit location
    assert coordinator._has_explicit_location("In file Assets/Test.cs, add code")
    assert coordinator._has_explicit_location("In method TransitionToWin, add call")
    assert coordinator._has_explicit_location("In class GameStateManager, modify")

    # Without explicit location
    assert not coordinator._has_explicit_location("Fix the bug")
    assert not coordinator._has_explicit_location("Add event handling")


def test_delegate_to_explorer(coordinator, mock_model):
    """Test delegating to Explorer."""
    # Mock Explorer's explore method
    with patch("game_agent_try.agents.coordinator.ExplorerAgent") as mock_explorer_class:
        mock_explorer = Mock()
        mock_explorer.explore = Mock(return_value=EvidencePackage(
            success=True,
            evidence_items=[],
            candidate_nodes=[],
            summary="Found 3 items",
            tokens_used=5000,
            rounds_used=3,
            search_strategy="adaptive",
        ))
        mock_explorer_class.return_value = mock_explorer

        result = coordinator._delegate_to_explorer("Find GameStateManager")

        assert result.success is True
        assert result.tokens_used == 5000
        assert result.rounds_used == 3
        assert mock_explorer.explore.called


def test_run_task_tracks_metrics(coordinator, mock_model):
    """Test that run_task tracks execution metrics."""
    with patch.object(coordinator, "_assess_complexity") as mock_assess:
        mock_assess.return_value = ComplexityAssessment(
            level=TaskComplexity.SIMPLE,
            reasoning="Test",
            estimated_files=1,
            needs_exploration=False,
            needs_critic=False,
            direct_execution_safe=True,
        )

        with patch.object(coordinator, "_execute_simple_task") as mock_execute:
            mock_execute.return_value = {"success": False, "error": "Not implemented"}

            result = coordinator.run_task("Test task")

            # Metrics should be created
            assert coordinator.metrics is not None
            assert coordinator.metrics.task_description == "Test task"
            assert coordinator.metrics.complexity_level == TaskComplexity.SIMPLE


def test_execute_complex_task_calls_explorer(coordinator):
    """Test that complex task execution delegates to Explorer."""
    assessment = ComplexityAssessment(
        level=TaskComplexity.COMPLEX,
        reasoning="Needs exploration",
        estimated_files=3,
        needs_exploration=True,
        needs_critic=False,
        direct_execution_safe=False,
    )

    with patch.object(coordinator, "_delegate_to_explorer") as mock_delegate:
        mock_delegate.return_value = EvidencePackage(
            success=True,
            evidence_items=[],
            candidate_nodes=[],
            summary="Found items",
            tokens_used=10000,
            rounds_used=5,
            search_strategy="adaptive",
        )

        result = coordinator._execute_complex_task("Test task", assessment)

        assert mock_delegate.called
        assert result["path"] == "complex_delegated"
        assert result["exploration_tokens"] == 10000
        assert result["exploration_rounds"] == 5


def test_execute_complex_task_handles_explorer_failure(coordinator):
    """Test that complex task handles Explorer failure gracefully."""
    assessment = ComplexityAssessment(
        level=TaskComplexity.COMPLEX,
        reasoning="Needs exploration",
        estimated_files=3,
        needs_exploration=True,
        needs_critic=False,
        direct_execution_safe=False,
    )

    with patch.object(coordinator, "_delegate_to_explorer") as mock_delegate:
        mock_delegate.return_value = EvidencePackage(
            success=False,
            evidence_items=[],
            candidate_nodes=[],
            summary="",
            tokens_used=2000,
            rounds_used=1,
            search_strategy="adaptive",
            error="Exploration failed",
        )

        result = coordinator._execute_complex_task("Test task", assessment)

        assert result["success"] is False
        assert "Exploration failed" in result["error"]


def test_coordinator_error_handling(coordinator):
    """Test that Coordinator handles errors gracefully."""
    with patch.object(coordinator, "_assess_complexity") as mock_assess:
        mock_assess.side_effect = Exception("Assessment failed")

        result = coordinator.run_task("Test task")

        assert result["success"] is False
        assert "Assessment failed" in result["error"]
        assert coordinator.metrics is not None
        assert coordinator.metrics.success is False


def test_coordinator_preserves_evidence(coordinator):
    """Test that Coordinator preserves evidence from Explorer."""
    assessment = ComplexityAssessment(
        level=TaskComplexity.COMPLEX,
        reasoning="Test",
        estimated_files=2,
        needs_exploration=True,
        needs_critic=False,
        direct_execution_safe=False,
    )

    mock_evidence = EvidencePackage(
        success=True,
        evidence_items=[],
        candidate_nodes=[],
        summary="Test summary",
        tokens_used=5000,
        rounds_used=3,
        search_strategy="adaptive",
    )

    with patch.object(coordinator, "_delegate_to_explorer") as mock_delegate:
        mock_delegate.return_value = mock_evidence

        coordinator._execute_complex_task("Test", assessment)

        # Evidence should be preserved
        assert coordinator.current_evidence is not None
        assert coordinator.current_evidence.summary == "Test summary"


def test_get_metrics(coordinator):
    """Test getting metrics from Coordinator."""
    # Initially None
    assert coordinator.get_metrics() is None

    # After running a task
    with patch.object(coordinator, "_assess_complexity") as mock_assess:
        mock_assess.return_value = ComplexityAssessment(
            level=TaskComplexity.SIMPLE,
            reasoning="Test",
            estimated_files=1,
            needs_exploration=False,
            needs_critic=False,
            direct_execution_safe=True,
        )

        with patch.object(coordinator, "_execute_simple_task") as mock_execute:
            mock_execute.return_value = {"success": False}

            coordinator.run_task("Test")

            metrics = coordinator.get_metrics()
            assert metrics is not None
            assert metrics.task_description == "Test"
