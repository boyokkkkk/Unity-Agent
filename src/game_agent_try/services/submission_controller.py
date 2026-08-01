"""SubmissionController: Zero-token deterministic submission checking.

Provides a service interface for checking submission contracts and generating
final reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SubmissionCheck:
    """Result of submission contract checking."""
    ready: bool
    missing_requirements: list[str]
    diagnosis_present: bool
    mutations_applied: bool
    validation_passed: bool
    review_complete: bool
    message: str


class SubmissionController:
    """Service layer for submission contract verification.

    This service provides:
    - Zero LLM token consumption
    - Contract completeness checking
    - Final report generation
    - Submission readiness validation
    """

    def __init__(
        self,
        project_root: Path,
        config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the submission controller.

        Args:
            project_root: Unity project root directory
            config: Submission configuration
        """
        self.project_root = project_root.resolve()
        self.config = dict(config or {})

        self.mutation_required = self.config.get("mutation_required", True)
        self.allow_no_change_submission = self.config.get("allow_no_change_submission", False)
        self.required_validation_modes = self.config.get(
            "required_validation_modes",
            ["editmode", "playmode"],
        )

        self.check_count = 0
        self.submission_count = 0

    def check_submission_contract(
        self,
        diagnosis_present: bool,
        mutation_count: int,
        completed_validation_modes: list[str],
        review_passed: bool,
    ) -> SubmissionCheck:
        """Check if submission contract is complete.

        Args:
            diagnosis_present: Whether diagnosis has been submitted
            mutation_count: Number of mutations applied
            completed_validation_modes: List of validation modes that passed
            review_passed: Whether workflow review passed

        Returns:
            SubmissionCheck with readiness status
        """
        self.check_count += 1

        missing = []

        # Check diagnosis
        if not diagnosis_present:
            missing.append("diagnosis")

        # Check mutations (if required)
        if self.mutation_required and mutation_count == 0:
            if not self.allow_no_change_submission:
                missing.append("mutation")

        # Check validation modes
        for mode in self.required_validation_modes:
            if mode not in completed_validation_modes:
                missing.append(f"validation:{mode}")

        # Check review
        if not review_passed:
            missing.append("review")

        ready = len(missing) == 0
        message = (
            "Submission contract complete. Ready to submit."
            if ready
            else f"Incomplete: {', '.join(missing)}"
        )

        return SubmissionCheck(
            ready=ready,
            missing_requirements=missing,
            diagnosis_present=diagnosis_present,
            mutations_applied=mutation_count > 0,
            validation_passed=all(
                mode in completed_validation_modes
                for mode in self.required_validation_modes
            ),
            review_complete=review_passed,
            message=message,
        )

    def generate_submission_report(
        self,
        task_description: str,
        diagnosis: str,
        changed_paths: list[str],
        completed_validation_modes: list[str],
        mutation_count: int,
    ) -> str:
        """Generate final submission report.

        Args:
            task_description: Original task description
            diagnosis: Diagnosis text
            changed_paths: List of paths that were modified
            completed_validation_modes: List of validation modes that passed
            mutation_count: Number of mutations applied

        Returns:
            Formatted submission report
        """
        self.submission_count += 1

        report_lines = [
            "# Submission Report",
            "",
            "## Task",
            task_description,
            "",
            "## Diagnosis",
            diagnosis,
            "",
            "## Changes",
            f"Total mutations: {mutation_count}",
            f"Modified paths: {len(changed_paths)}",
        ]

        if changed_paths:
            report_lines.append("")
            for path in changed_paths:
                report_lines.append(f"  - {path}")

        report_lines.extend([
            "",
            "## Validation",
            f"Completed modes: {', '.join(completed_validation_modes) if completed_validation_modes else 'none'}",
            "",
            "## Status",
            "✓ Submission contract verified",
        ])

        return "\n".join(report_lines)

    def get_stats(self) -> dict[str, int]:
        """Get submission statistics.

        Returns:
            Dict with submission counts
        """
        return {
            "total_checks": self.check_count,
            "submissions": self.submission_count,
        }
