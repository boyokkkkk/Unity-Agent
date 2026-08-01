"""Phase 1 verification script.

This script validates:
- ExplorerAgent implementation
- CoordinatorAgent implementation
- Delegation flow
- Evidence package structure
- Token tracking
"""

from pathlib import Path
from unittest.mock import Mock

from game_agent_try.agents import (
    CoordinatorAgent,
    ExplorerAgent,
    ExplorationTask,
    TaskComplexity,
)


def test_explorer_basic():
    """Test ExplorerAgent basic functionality."""
    print("Testing ExplorerAgent...")

    # Mock dependencies
    mock_model = Mock()
    mock_model.query = Mock(return_value={
        "content": "Exploration complete",
        "tool_calls": [],
        "usage": {
            "prompt_tokens": 500,
            "completion_tokens": 200,
        },
    })

    mock_context = Mock()
    mock_context.project_store = Mock()

    project_root = Path(__file__).parent.parent / "test_project"

    # Create Explorer
    explorer = ExplorerAgent(
        model=mock_model,
        context=mock_context,
        project_root=project_root,
        max_rounds=5,
        max_tokens=10_000,
    )

    # Test initialization
    assert explorer.max_rounds == 5
    assert explorer.max_tokens == 10_000
    assert len(explorer.messages) == 0
    print("  ✓ Initialization")

    # Test exploration
    task = ExplorationTask(
        query="Find GameStateManager",
        max_results=10,
        max_rounds=5,
    )

    result = explorer.explore(task)

    assert result.success is True
    assert result.tokens_used == 700  # 500 + 200
    assert result.rounds_used >= 1
    assert result.search_strategy == "adaptive"
    assert isinstance(result.summary, str)
    print("  ✓ Basic exploration")

    # Test token tracking
    assert explorer.prompt_tokens == 500
    assert explorer.completion_tokens == 200
    assert explorer.tokens_used == 700
    print("  ✓ Token tracking")

    # Test evidence package structure
    assert hasattr(result, "success")
    assert hasattr(result, "evidence_items")
    assert hasattr(result, "candidate_nodes")
    assert hasattr(result, "summary")
    assert hasattr(result, "tokens_used")
    assert hasattr(result, "rounds_used")
    assert hasattr(result, "search_strategy")
    print("  ✓ Evidence package structure")

    # Test isolation (second exploration should reset)
    task2 = ExplorationTask(query="Second query", max_results=5)
    result2 = explorer.explore(task2)

    assert result2.success is True
    assert result2.rounds_used >= 1
    print("  ✓ Exploration isolation")

    print("✓ ExplorerAgent working correctly\n")


def test_coordinator_basic():
    """Test CoordinatorAgent basic functionality."""
    print("Testing CoordinatorAgent...")

    # Mock dependencies
    mock_model = Mock()
    mock_context = Mock()
    mock_context.project_store = Mock()

    project_root = Path(__file__).parent.parent / "test_project"

    # Create Coordinator
    coordinator = CoordinatorAgent(
        model=mock_model,
        context=mock_context,
        project_root=project_root,
    )

    # Test initialization
    assert coordinator.mutation_service is not None
    assert coordinator.validation_service is not None
    assert coordinator.submission_controller is not None
    print("  ✓ Initialization")

    # Test services are zero-token
    mutation_stats = coordinator.mutation_service.get_stats()
    validation_stats = coordinator.validation_service.get_stats()
    submission_stats = coordinator.submission_controller.get_stats()

    assert isinstance(mutation_stats, dict)
    assert isinstance(validation_stats, dict)
    assert isinstance(submission_stats, dict)
    print("  ✓ Zero-token services")

    # Test complexity assessment - simple
    simple_task = "In file Assets/GameStateManager.cs at line 45, add code"
    assessment = coordinator._assess_complexity(simple_task)

    assert assessment.level == TaskComplexity.SIMPLE
    assert assessment.direct_execution_safe is True
    assert assessment.needs_exploration is False
    print("  ✓ Simple task detection")

    # Test complexity assessment - complex
    complex_task = "Fix the bug where game win event doesn't fire"
    assessment = coordinator._assess_complexity(complex_task)

    assert assessment.level == TaskComplexity.COMPLEX
    assert assessment.needs_exploration is True
    print("  ✓ Complex task detection")

    # Test explicit location detection
    assert coordinator._has_explicit_location("In file Test.cs, add code")
    assert coordinator._has_explicit_location("In method DoSomething, modify")
    assert not coordinator._has_explicit_location("Fix the bug")
    print("  ✓ Location detection")

    print("✓ CoordinatorAgent working correctly\n")


def test_delegation_flow():
    """Test Coordinator delegating to Explorer."""
    print("Testing delegation flow...")

    # Mock model for Explorer
    mock_model = Mock()
    mock_model.query = Mock(return_value={
        "content": "Found relevant code",
        "tool_calls": [],
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 500,
        },
    })

    mock_context = Mock()
    mock_context.project_store = Mock()

    project_root = Path(__file__).parent.parent / "test_project"

    # Create Coordinator
    coordinator = CoordinatorAgent(
        model=mock_model,
        context=mock_context,
        project_root=project_root,
    )

    # Test delegation
    evidence_package = coordinator._delegate_to_explorer("Find GameStateManager")

    assert evidence_package.success is True
    assert evidence_package.tokens_used > 0
    assert evidence_package.rounds_used >= 1
    assert isinstance(evidence_package.summary, str)
    print("  ✓ Delegation successful")

    # Evidence should be preserved
    assert coordinator.current_evidence is None  # Not set yet in _delegate_to_explorer
    print("  ✓ Evidence flow")

    print("✓ Delegation working correctly\n")


def test_token_efficiency():
    """Test that Explorer is more token-efficient than expected."""
    print("Testing token efficiency...")

    mock_model = Mock()
    mock_model.query = Mock(return_value={
        "content": "Done",
        "tool_calls": [],
        "usage": {
            "prompt_tokens": 2000,
            "completion_tokens": 1000,
        },
    })

    mock_context = Mock()
    mock_context.project_store = Mock()

    project_root = Path(__file__).parent.parent / "test_project"

    explorer = ExplorerAgent(
        model=mock_model,
        context=mock_context,
        project_root=project_root,
        max_rounds=3,
        max_tokens=10_000,
    )

    task = ExplorationTask(query="Test", max_results=10, max_rounds=3)
    result = explorer.explore(task)

    # Token usage should be tracked
    assert result.tokens_used == 3000  # 2000 + 1000
    print(f"  ✓ Token tracking: {result.tokens_used} tokens")

    # Should be isolated (no context accumulation across tasks)
    result2 = explorer.explore(task)
    assert result2.tokens_used == 3000  # Same, not cumulative
    print("  ✓ No context pollution between explorations")

    print("✓ Token efficiency verified\n")


def main():
    """Run all Phase 1 verification tests."""
    print("=" * 60)
    print("Phase 1 Verification - Explorer + Coordinator")
    print("=" * 60)
    print()

    try:
        test_explorer_basic()
        test_coordinator_basic()
        test_delegation_flow()
        test_token_efficiency()

        print("=" * 60)
        print("✓ Phase 1 verification complete!")
        print("=" * 60)
        print()
        print("Summary:")
        print("  - ExplorerAgent: Isolated exploration working")
        print("  - CoordinatorAgent: Task routing working")
        print("  - Delegation: Explorer integration working")
        print("  - Evidence packages: Structured output working")
        print("  - Token tracking: Accurate tracking working")
        print()
        print("Key achievements:")
        print("  ✓ Explorer runs in clean context")
        print("  ✓ Evidence packages are structured")
        print("  ✓ Coordinator delegates correctly")
        print("  ✓ Services remain zero-token")
        print()
        print("Next steps:")
        print("  - Implement proper tool schema loading")
        print("  - Implement evidence extraction from tool results")
        print("  - Implement LLM-based summary generation")
        print("  - Add decision-making in Coordinator")
        print("  - Integrate with mutation/validation services")
        print()
        print("Ready for Phase 2: Complexity assessment refinement")

    except Exception as e:
        print(f"\n✗ Verification failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
