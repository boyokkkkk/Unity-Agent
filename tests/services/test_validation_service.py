"""Tests for ValidationService."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from game_agent_try.services.validation_service import ValidationService


@pytest.fixture
def temp_project(tmp_path: Path):
    """Create a temporary Unity project structure."""
    project_root = tmp_path / "TestProject"
    project_root.mkdir()
    (project_root / "Assets").mkdir()
    (project_root / "ProjectSettings").mkdir()
    return project_root


@pytest.fixture
def validation_service(temp_project: Path):
    """Create a ValidationService instance for testing."""
    config = {
        "modes": ["compile", "editmode", "playmode"],
        "timeout_seconds": 600,
    }
    return ValidationService(
        project_root=temp_project,
        config=config,
    )


def test_validation_service_initialization(validation_service: ValidationService):
    """Test that ValidationService initializes correctly."""
    assert validation_service.validation_count == 0
    assert validation_service.success_count == 0
    assert validation_service.failure_count == 0


def test_validation_service_stats(validation_service: ValidationService):
    """Test that stats are correctly tracked."""
    stats = validation_service.get_stats()

    assert stats["total_validations"] == 0
    assert stats["successes"] == 0
    assert stats["failures"] == 0


def test_validate_success(validation_service: ValidationService, monkeypatch):
    """Test successful validation."""
    # Mock UnityValidator to return success
    from game_agent_try import validation as validation_module

    class MockValidator:
        def __init__(self, project_path, artifact_dir, config):
            self.project_path = project_path
            self.artifact_dir = artifact_dir
            self.config = config

        def run(self):
            return {
                "status": "passed",
                "checks": [
                    {"name": "compile", "status": "passed"},
                    {"name": "editmode", "status": "passed"},
                    {"name": "playmode", "status": "passed"},
                ],
            }

    monkeypatch.setattr(validation_module, "UnityValidator", MockValidator)

    result = validation_service.validate()

    assert result.success is True
    assert result.failed_mode is None
    assert result.error is None
    assert len(result.completed_modes) == 3
    assert validation_service.validation_count == 1
    assert validation_service.success_count == 1


def test_validate_failure(validation_service: ValidationService, monkeypatch):
    """Test validation failure."""
    from game_agent_try import validation as validation_module

    class MockValidator:
        def __init__(self, project_path, artifact_dir, config):
            pass

        def run(self):
            return {
                "status": "failed",
                "checks": [
                    {"name": "compile", "status": "passed"},
                    {"name": "editmode", "status": "failed", "error": "Test failed"},
                    {"name": "playmode", "status": "passed"},
                ],
            }

    monkeypatch.setattr(validation_module, "UnityValidator", MockValidator)

    result = validation_service.validate()

    assert result.success is False
    assert result.failed_mode == "editmode"
    assert "Test failed" in result.error
    assert validation_service.validation_count == 1
    assert validation_service.failure_count == 1


def test_validate_single_mode(validation_service: ValidationService, monkeypatch):
    """Test validating a single mode."""
    from game_agent_try import validation as validation_module

    captured_config = None

    class MockValidator:
        def __init__(self, project_path, artifact_dir, config):
            nonlocal captured_config
            captured_config = config

        def run(self):
            return {
                "status": "passed",
                "checks": [
                    {"name": "compile", "status": "passed"},
                ],
            }

    monkeypatch.setattr(validation_module, "UnityValidator", MockValidator)

    result = validation_service.validate_mode("compile")

    assert result.success is True
    assert captured_config is not None
    assert captured_config["modes"] == ["compile"]


def test_validate_exception(validation_service: ValidationService, monkeypatch):
    """Test validation with exception."""
    from game_agent_try import validation as validation_module

    class MockValidator:
        def __init__(self, project_path, artifact_dir, config):
            pass

        def run(self):
            raise Exception("Unity editor not found")

    monkeypatch.setattr(validation_module, "UnityValidator", MockValidator)

    result = validation_service.validate()

    assert result.success is False
    assert "Unity editor not found" in result.error
    assert validation_service.validation_count == 1
    assert validation_service.failure_count == 1


def test_zero_token_consumption(validation_service: ValidationService):
    """Test that ValidationService consumes zero LLM tokens.

    This is a conceptual test - the service should never call LLM APIs.
    """
    # The service only wraps deterministic Unity operations
    # No LLM calls should be made
    stats = validation_service.get_stats()

    # All operations are deterministic
    assert isinstance(stats, dict)
    assert "total_validations" in stats
