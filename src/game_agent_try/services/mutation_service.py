"""MutationService: Zero-token deterministic mutation execution.

Wraps the existing ACI UnityMutationExecutor to provide a service interface
with checkpoint/rollback capabilities.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from game_agent_try.aci.mutation import AciConfig, UnityMutationExecutor
from game_agent_try.agents.models import MutationResult


class MutationService:
    """Service layer for deterministic Unity mutations.

    This service wraps the existing UnityMutationExecutor and provides:
    - Zero LLM token consumption
    - Checkpoint management
    - SHA verification
    - Authorized path enforcement
    - Rollback on failure
    """

    def __init__(
        self,
        project_root: Path,
        artifact_root: Path | None = None,
        config: AciConfig | dict[str, Any] | None = None,
    ) -> None:
        """Initialize the mutation service.

        Args:
            project_root: Unity project root directory
            artifact_root: Artifact storage directory
            config: ACI configuration
        """
        self.project_root = project_root.resolve()
        self.artifact_root = (
            artifact_root.resolve()
            if artifact_root is not None
            else self.project_root / ".game-agent-artifacts"
        )
        self.config = config if isinstance(config, AciConfig) else AciConfig(**(config or {}))

        # Initialize the underlying mutation executor
        self.executor = UnityMutationExecutor(
            project_root=self.project_root,
            artifact_root=self.artifact_root,
            config=self.config,
        )

        self.execution_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.rollback_count = 0

    def execute_mutation(
        self,
        action: dict[str, Any],
        authorized_paths: list[str],
    ) -> MutationResult:
        """Execute a mutation with checkpoint and authorization.

        Args:
            action: Mutation action dict with 'tool' and 'arguments'
            authorized_paths: List of paths authorized for modification

        Returns:
            MutationResult with success status and metadata
        """
        self.execution_count += 1

        # Inject authorized paths into the action
        action["_authorized_paths"] = authorized_paths

        try:
            # Execute through the existing mutation executor
            result = self.executor.execute(action)

            # Check if execution was successful
            if result.get("status") == "success":
                self.success_count += 1
                return MutationResult(
                    success=True,
                    transaction_id=result.get("transaction_id", ""),
                    checkpoint_id=result.get("checkpoint_id", ""),
                    changed_paths=result.get("changed_paths", []),
                    error=None,
                )
            else:
                self.failure_count += 1
                return MutationResult(
                    success=False,
                    transaction_id=result.get("transaction_id", ""),
                    checkpoint_id=result.get("checkpoint_id", ""),
                    changed_paths=[],
                    error=result.get("error", "Unknown mutation error"),
                )

        except Exception as e:
            self.failure_count += 1
            return MutationResult(
                success=False,
                transaction_id="",
                checkpoint_id="",
                changed_paths=[],
                error=f"Mutation exception: {str(e)}",
            )

    def rollback_transaction(self, transaction_id: str) -> bool:
        """Rollback a transaction by its ID.

        Args:
            transaction_id: Transaction to rollback

        Returns:
            True if rollback succeeded
        """
        try:
            self.rollback_count += 1
            result = self.executor.transaction_manager.rollback(transaction_id)
            return result.get("status") == "success"
        except Exception:
            return False

    def create_checkpoint(self, paths: list[str], operation: str = "mutation") -> dict[str, Any]:
        """Create a checkpoint for the given paths.

        Args:
            paths: List of file paths to checkpoint
            operation: Operation name for the checkpoint

        Returns:
            Checkpoint metadata
        """
        try:
            return self.executor.create_checkpoint(paths, operation=operation)
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
            }

    def get_stats(self) -> dict[str, int]:
        """Get execution statistics.

        Returns:
            Dict with execution counts
        """
        return {
            "total_executions": self.execution_count,
            "successes": self.success_count,
            "failures": self.failure_count,
            "rollbacks": self.rollback_count,
            "typed_mutations": self.executor.typed_mutation_count,
            "escape_hatch_uses": self.executor.escape_hatch_count,
        }
