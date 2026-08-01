"""Data models for the adaptive coordinator architecture."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TaskComplexity(str, Enum):
    """Task complexity classification."""
    SIMPLE = "simple"
    COMPLEX = "complex"
    HIGH_RISK = "high_risk"


@dataclass
class ComplexityAssessment:
    """Task complexity evaluation result."""
    level: TaskComplexity
    reasoning: str
    estimated_files: int
    needs_exploration: bool
    needs_critic: bool
    direct_execution_safe: bool
    required_tools: list[str] = field(default_factory=list)


@dataclass
class Evidence:
    """Single piece of evidence from exploration."""
    evidence_id: str
    source: str
    content: str
    relevance_score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Candidate:
    """Candidate node with complete information."""
    node_id: str
    path: str
    role: str
    summary: str
    confidence: float
    evidence_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidencePackage:
    """Structured evidence package returned by Explorer."""
    success: bool

    # Core evidence
    evidence_items: list[Evidence]
    candidate_nodes: list[Candidate]

    # Summary for Coordinator (200-300 words)
    summary: str

    # Metadata
    tokens_used: int
    rounds_used: int
    search_strategy: str

    # Failure information
    error: Optional[str] = None


@dataclass
class CriticReview:
    """Critic's review result."""
    approved: bool
    confidence: float
    issues_found: list[str]
    recommendations: list[str]
    reasoning: str


@dataclass
class MutationResult:
    """Result from MutationService."""
    success: bool
    transaction_id: str
    checkpoint_id: str
    changed_paths: list[str]
    error: Optional[str] = None


@dataclass
class ValidationResult:
    """Result from ValidationService."""
    success: bool
    failed_mode: Optional[str] = None
    error: Optional[str] = None
    completed_modes: list[str] = field(default_factory=list)


@dataclass
class ExplorationTask:
    """Task specification for Explorer."""
    query: str
    max_results: int = 15
    max_rounds: int = 10
    strategy: str = "adaptive"


@dataclass
class ExecutionMetrics:
    """Metrics for a single task execution."""
    task_id: str
    task_description: str
    complexity_level: TaskComplexity
    execution_path: str  # "simple_direct", "complex_delegated", "high_risk_with_critic"

    # Token usage
    complexity_assessment_tokens: int = 0
    exploration_tokens: int = 0
    coordinator_tokens: int = 0
    critic_tokens: int = 0
    service_tokens: int = 0  # Should always be 0
    total_tokens: int = 0

    # Rounds
    total_rounds: int = 0

    # Success
    exit_status: str = ""
    success: bool = False

    # Timing
    start_time: float = 0.0
    end_time: float = 0.0
    duration_seconds: float = 0.0
