"""Tests for SubmissionController."""

from pathlib import Path

import pytest

from game_agent_try.services.submission_controller import SubmissionController


@pytest.fixture
def temp_project(tmp_path: Path):
    """Create a temporary Unity project structure."""
    project_root = tmp_path / "TestProject"
    project_root.mkdir()
    return project_root


@pytest.fixture
def submission_controller(temp_project: Path):
    """Create a SubmissionController instance for testing."""
    config = {
        "mutation_required": True,
        "allow_no_change_submission": False,
        "required_validation_modes": ["editmode", "playmode"],
    }
    return SubmissionController(
        project_root=temp_project,
        config=config,
    )


def test_submission_controller_initialization(submission_controller: SubmissionController):
    """Test that SubmissionController initializes correctly."""
    assert submission_controller.check_count == 0
    assert submission_controller.submission_count == 0
    assert submission_controller.mutation_required is True
    assert submission_controller.allow_no_change_submission is False


def test_submission_controller_stats(submission_controller: SubmissionController):
    """Test that stats are correctly tracked."""
    stats = submission_controller.get_stats()

    assert stats["total_checks"] == 0
    assert stats["submissions"] == 0


def test_check_submission_contract_complete(submission_controller: SubmissionController):
    """Test submission contract check when all requirements are met."""
    check = submission_controller.check_submission_contract(
        diagnosis_present=True,
        mutation_count=1,
        completed_validation_modes=["editmode", "playmode"],
        review_passed=True,
    )

    assert check.ready is True
    assert len(check.missing_requirements) == 0
    assert check.diagnosis_present is True
    assert check.mutations_applied is True
    assert check.validation_passed is True
    assert check.review_complete is True
    assert "complete" in check.message.lower()


def test_check_submission_contract_missing_diagnosis(submission_controller: SubmissionController):
    """Test submission contract check with missing diagnosis."""
    check = submission_controller.check_submission_contract(
        diagnosis_present=False,
        mutation_count=1,
        completed_validation_modes=["editmode", "playmode"],
        review_passed=True,
    )

    assert check.ready is False
    assert "diagnosis" in check.missing_requirements
    assert check.diagnosis_present is False


def test_check_submission_contract_missing_mutation(submission_controller: SubmissionController):
    """Test submission contract check with missing mutation."""
    check = submission_controller.check_submission_contract(
        diagnosis_present=True,
        mutation_count=0,
        completed_validation_modes=["editmode", "playmode"],
        review_passed=True,
    )

    assert check.ready is False
    assert "mutation" in check.missing_requirements
    assert check.mutations_applied is False


def test_check_submission_contract_missing_validation(submission_controller: SubmissionController):
    """Test submission contract check with incomplete validation."""
    check = submission_controller.check_submission_contract(
        diagnosis_present=True,
        mutation_count=1,
        completed_validation_modes=["editmode"],  # Missing playmode
        review_passed=True,
    )

    assert check.ready is False
    assert any("playmode" in req for req in check.missing_requirements)
    assert check.validation_passed is False


def test_check_submission_contract_missing_review(submission_controller: SubmissionController):
    """Test submission contract check with missing review."""
    check = submission_controller.check_submission_contract(
        diagnosis_present=True,
        mutation_count=1,
        completed_validation_modes=["editmode", "playmode"],
        review_passed=False,
    )

    assert check.ready is False
    assert "review" in check.missing_requirements
    assert check.review_complete is False


def test_check_submission_contract_no_change_allowed(temp_project: Path):
    """Test submission contract when no-change is allowed."""
    config = {
        "mutation_required": True,
        "allow_no_change_submission": True,
        "required_validation_modes": ["editmode", "playmode"],
    }
    controller = SubmissionController(project_root=temp_project, config=config)

    check = controller.check_submission_contract(
        diagnosis_present=True,
        mutation_count=0,
        completed_validation_modes=["editmode", "playmode"],
        review_passed=True,
    )

    # Should be ready even with 0 mutations if allow_no_change_submission is True
    assert check.ready is True


def test_generate_submission_report(submission_controller: SubmissionController):
    """Test generating submission report."""
    report = submission_controller.generate_submission_report(
        task_description="Fix the game win event",
        diagnosis="GameStateManager is missing OnGameWin.Invoke() call",
        changed_paths=["Assets/Scripts/GameStateManager.cs"],
        completed_validation_modes=["compile", "editmode", "playmode"],
        mutation_count=1,
    )

    assert "Fix the game win event" in report
    assert "GameStateManager" in report
    assert "Assets/Scripts/GameStateManager.cs" in report
    assert "compile, editmode, playmode" in report
    assert "Total mutations: 1" in report
    assert submission_controller.submission_count == 1


def test_generate_submission_report_no_changes(submission_controller: SubmissionController):
    """Test generating submission report with no changes."""
    report = submission_controller.generate_submission_report(
        task_description="Investigate the bug",
        diagnosis="No code changes needed",
        changed_paths=[],
        completed_validation_modes=[],
        mutation_count=0,
    )

    assert "Investigate the bug" in report
    assert "No code changes needed" in report
    assert "Total mutations: 0" in report
    assert "Modified paths: 0" in report


def test_zero_token_consumption(submission_controller: SubmissionController):
    """Test that SubmissionController consumes zero LLM tokens.

    This is a conceptual test - the controller should never call LLM APIs.
    """
    # All operations are deterministic checks
    stats = submission_controller.get_stats()

    # All operations are deterministic
    assert isinstance(stats, dict)
    assert "total_checks" in stats
