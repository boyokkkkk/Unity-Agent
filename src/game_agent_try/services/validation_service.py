"""ValidationService: Zero-token deterministic validation execution.

Wraps the existing UnityValidator to provide a service interface for
compile/EditMode/PlayMode validation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from game_agent_try.validation import UnityValidator
from game_agent_try.agents.models import ValidationResult


class ValidationService:
    """Service layer for deterministic Unity validation.

    This service wraps the existing UnityValidator and provides:
    - Zero LLM token consumption
    - Compile validation
    - EditMode test validation
    - PlayMode test validation
    - Structured result reporting
    """

    def __init__(
        self,
        project_root: Path,
        artifact_root: Path | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the validation service.

        Args:
            project_root: Unity project root directory
            artifact_root: Artifact storage directory
            config: Validation configuration
        """
        self.project_root = project_root.resolve()
        self.artifact_root = (
            artifact_root.resolve()
            if artifact_root is not None
            else self.project_root / ".game-agent-artifacts"
        )
        self.config = dict(config or {})

        self.validation_count = 0
        self.success_count = 0
        self.failure_count = 0

    def validate(
        self,
        required_modes: list[str] | None = None,
    ) -> ValidationResult:
        """Run Unity validation checks.

        Args:
            required_modes: List of modes to validate (compile/editmode/playmode)
                          If None, uses config or defaults to all modes

        Returns:
            ValidationResult with success status and details
        """
        self.validation_count += 1

        # Determine which modes to run
        modes = required_modes or self.config.get("modes", ["compile", "editmode", "playmode"])

        # Create validator with the specified modes
        validator_config = dict(self.config)
        validator_config["modes"] = modes

        try:
            # Create and run the validator
            validator = UnityValidator(
                project_path=self.project_root,
                artifact_dir=self.artifact_root / "validation",
                config=validator_config,
            )

            summary = validator.run()

            # Check overall status
            overall_status = summary.get("status", "failed")

            if overall_status == "passed":
                self.success_count += 1
                return ValidationResult(
                    success=True,
                    failed_mode=None,
                    error=None,
                    completed_modes=modes,
                )
            else:
                self.failure_count += 1

                # Find which mode failed
                failed_mode = None
                error_message = None
                checks = summary.get("checks", [])

                for check in checks:
                    if check.get("status") in ["failed", "timed_out"]:
                        failed_mode = check.get("name", "unknown")
                        error_message = check.get("error", f"Validation failed in {failed_mode} mode")
                        break

                if not error_message:
                    error_message = f"Validation failed with status: {overall_status}"

                return ValidationResult(
                    success=False,
                    failed_mode=failed_mode,
                    error=error_message,
                    completed_modes=[
                        check["name"]
                        for check in checks
                        if check.get("status") == "passed"
                    ],
                )

        except Exception as e:
            self.failure_count += 1
            return ValidationResult(
                success=False,
                failed_mode="unknown",
                error=f"Validation exception: {str(e)}",
                completed_modes=[],
            )

    def validate_mode(self, mode: str) -> ValidationResult:
        """Validate a single mode.

        Args:
            mode: Mode to validate (compile/editmode/playmode)

        Returns:
            ValidationResult for the specific mode
        """
        return self.validate(required_modes=[mode])

    def get_stats(self) -> dict[str, int]:
        """Get validation statistics.

        Returns:
            Dict with validation counts
        """
        return {
            "total_validations": self.validation_count,
            "successes": self.success_count,
            "failures": self.failure_count,
        }
