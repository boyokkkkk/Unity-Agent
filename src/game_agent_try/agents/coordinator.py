"""Coordinator Agent: Adaptive task routing and orchestration.

The Coordinator is responsible for:
- Understanding tasks
- Assessing complexity
- Routing to appropriate execution paths
- Delegating exploration to Explorer
- Making mutation decisions
- Orchestrating the overall workflow
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from game_agent_try.agents.explorer import ExplorerAgent
from game_agent_try.agents.models import (
    ComplexityAssessment,
    EvidencePackage,
    ExecutionMetrics,
    ExplorationTask,
    TaskComplexity,
)
from game_agent_try.context import ContextAssembler
from game_agent_try.framework import Model
from game_agent_try.services import (
    MutationService,
    SubmissionController,
    ValidationService,
)


class CoordinatorAgent:
    """Coordinator that routes tasks adaptively.

    Execution paths:
    1. Simple tasks → Direct execution
    2. Complex tasks → Delegate to Explorer → Decision → Services
    3. High-risk tasks → Above + Critic review
    """

    def __init__(
        self,
        model: Model,
        context: ContextAssembler,
        project_root: Path,
        artifact_root: Path | None = None,
        config: dict[str, Any] | None = None,
    ):
        """Initialize the Coordinator agent.

        Args:
            model: LLM model for reasoning
            context: Context assembler with project graph
            project_root: Unity project root
            artifact_root: Artifact storage directory
            config: Configuration dict
        """
        self.model = model
        self.context = context
        self.project_root = project_root.resolve()
        self.artifact_root = (
            artifact_root.resolve()
            if artifact_root is not None
            else self.project_root / ".game-agent-artifacts"
        )
        self.config = dict(config or {})

        # Initialize services
        self.mutation_service = MutationService(
            project_root=self.project_root,
            artifact_root=self.artifact_root,
            config=self.config.get("aci"),
        )

        self.validation_service = ValidationService(
            project_root=self.project_root,
            artifact_root=self.artifact_root,
            config=self.config.get("validation"),
        )

        self.submission_controller = SubmissionController(
            project_root=self.project_root,
            config=self.config.get("aci"),
        )

        # Current task state
        self.current_task: str = ""
        self.current_complexity: ComplexityAssessment | None = None
        self.current_evidence: EvidencePackage | None = None

        # Metrics
        self.metrics: ExecutionMetrics | None = None

        self.logger = logging.getLogger("coordinator")

    def run_task(self, task_description: str) -> dict[str, Any]:
        """Run a complete task from start to finish.

        Args:
            task_description: Task to execute

        Returns:
            Execution result dict
        """
        self.logger.info(f"Starting task: {task_description}")
        self.current_task = task_description

        # Initialize metrics
        task_id = f"task_{int(time.time())}"
        self.metrics = ExecutionMetrics(
            task_id=task_id,
            task_description=task_description,
            complexity_level=TaskComplexity.SIMPLE,  # Updated after assessment
            execution_path="unknown",
            start_time=time.time(),
        )

        try:
            # Step 1: Assess complexity
            self.logger.info("Assessing task complexity...")
            assessment = self._assess_complexity(task_description)
            self.current_complexity = assessment
            self.metrics.complexity_level = assessment.level

            self.logger.info(f"Complexity: {assessment.level.value}")
            self.logger.info(f"Reasoning: {assessment.reasoning}")

            # Step 2: Route based on complexity
            if assessment.level == TaskComplexity.SIMPLE and assessment.direct_execution_safe:
                result = self._execute_simple_task(task_description, assessment)
            elif assessment.level == TaskComplexity.COMPLEX:
                result = self._execute_complex_task(task_description, assessment)
            elif assessment.level == TaskComplexity.HIGH_RISK:
                result = self._execute_high_risk_task(task_description, assessment)
            else:
                result = {
                    "success": False,
                    "error": f"Unknown complexity level: {assessment.level}",
                }

            # Finalize metrics
            self.metrics.end_time = time.time()
            self.metrics.duration_seconds = self.metrics.end_time - self.metrics.start_time
            self.metrics.success = result.get("success", False)
            self.metrics.exit_status = result.get("exit_status", "unknown")

            return result

        except Exception as e:
            self.logger.error(f"Task execution failed: {e}", exc_info=True)
            if self.metrics:
                self.metrics.end_time = time.time()
                self.metrics.duration_seconds = self.metrics.end_time - self.metrics.start_time
                self.metrics.success = False
                self.metrics.exit_status = "error"

            return {
                "success": False,
                "error": str(e),
                "metrics": self.metrics,
            }

    def _assess_complexity(self, task: str) -> ComplexityAssessment:
        """Assess task complexity to determine execution path.

        Args:
            task: Task description

        Returns:
            Complexity assessment
        """
        # Step 1: Fast heuristic checks
        if self._has_explicit_location(task):
            # Task specifies exact file and location - very simple
            return ComplexityAssessment(
                level=TaskComplexity.SIMPLE,
                reasoning="Task has explicit file path and location",
                estimated_files=1,
                needs_exploration=False,
                needs_critic=False,
                direct_execution_safe=True,
                required_tools=["unity_script_patch"],
            )

        # Step 2: LLM-based assessment for ambiguous cases
        # TODO: Implement LLM-based complexity assessment
        # For now, default to COMPLEX to trigger exploration
        return ComplexityAssessment(
            level=TaskComplexity.COMPLEX,
            reasoning="Task requires exploration to locate relevant code",
            estimated_files=3,
            needs_exploration=True,
            needs_critic=False,
            direct_execution_safe=False,
            required_tools=[],
        )

    def _has_explicit_location(self, task: str) -> bool:
        """Check if task has explicit file/method/line location.

        Args:
            task: Task description

        Returns:
            True if location is explicit
        """
        # Heuristic: check for file paths or specific method names
        indicators = [
            ".cs:",  # File with line number
            "in file",  # "in file X"
            "method",  # "in method X"
            "class",  # "in class X"
        ]

        task_lower = task.lower()
        return any(indicator in task_lower for indicator in indicators)

    def _execute_simple_task(
        self,
        task: str,
        assessment: ComplexityAssessment,
    ) -> dict[str, Any]:
        """Execute a simple task directly without exploration.

        Args:
            task: Task description
            assessment: Complexity assessment

        Returns:
            Execution result
        """
        self.logger.info("Executing simple task (direct path)")
        if self.metrics:
            self.metrics.execution_path = "simple_direct"

        # TODO: Implement direct execution
        # For now, return placeholder
        return {
            "success": False,
            "error": "Simple task execution not yet implemented",
            "path": "simple_direct",
            "metrics": self.metrics,
        }

    def _execute_complex_task(
        self,
        task: str,
        assessment: ComplexityAssessment,
    ) -> dict[str, Any]:
        """Execute a complex task by delegating to Explorer.

        Args:
            task: Task description
            assessment: Complexity assessment

        Returns:
            Execution result
        """
        self.logger.info("Executing complex task (Explorer + decision)")
        if self.metrics:
            self.metrics.execution_path = "complex_delegated"

        # Step 1: Delegate to Explorer
        evidence_package = self._delegate_to_explorer(task)
        self.current_evidence = evidence_package

        if self.metrics:
            self.metrics.exploration_tokens = evidence_package.tokens_used

        if not evidence_package.success:
            return {
                "success": False,
                "error": f"Exploration failed: {evidence_package.error}",
                "path": "complex_delegated",
                "metrics": self.metrics,
            }

        self.logger.info(f"Exploration complete: {len(evidence_package.evidence_items)} evidence items")

        # Step 2: Make decision based on evidence
        # TODO: Implement decision-making
        # Step 3: Execute mutations via service
        # TODO: Implement mutation execution
        # Step 4: Validate via service
        # TODO: Implement validation

        return {
            "success": True,
            "path": "complex_delegated",
            "evidence_count": len(evidence_package.evidence_items),
            "exploration_tokens": evidence_package.tokens_used,
            "exploration_rounds": evidence_package.rounds_used,
            "metrics": self.metrics,
        }

    def _execute_high_risk_task(
        self,
        task: str,
        assessment: ComplexityAssessment,
    ) -> dict[str, Any]:
        """Execute a high-risk task with Critic review.

        Args:
            task: Task description
            assessment: Complexity assessment

        Returns:
            Execution result
        """
        self.logger.info("Executing high-risk task (with Critic)")
        if self.metrics:
            self.metrics.execution_path = "high_risk_with_critic"

        # TODO: Implement high-risk execution with Critic
        return {
            "success": False,
            "error": "High-risk task execution not yet implemented",
            "path": "high_risk_with_critic",
            "metrics": self.metrics,
        }

    def _delegate_to_explorer(self, task: str) -> EvidencePackage:
        """Delegate exploration to Explorer agent.

        Args:
            task: Task description

        Returns:
            Evidence package from Explorer
        """
        self.logger.info("Delegating to Explorer...")

        # Create Explorer instance
        explorer = ExplorerAgent(
            model=self.model,
            context=self.context,
            project_root=self.project_root,
            artifact_root=self.artifact_root,
            max_rounds=10,
            max_tokens=40_000,
        )

        # Create exploration task
        exploration_task = ExplorationTask(
            query=task,
            max_results=15,
            max_rounds=10,
            strategy="adaptive",
        )

        # Run exploration
        evidence_package = explorer.explore(exploration_task)

        self.logger.info(f"Explorer finished: {evidence_package.rounds_used} rounds, {evidence_package.tokens_used} tokens")

        return evidence_package

    def get_metrics(self) -> ExecutionMetrics | None:
        """Get execution metrics for the current task."""
        return self.metrics
