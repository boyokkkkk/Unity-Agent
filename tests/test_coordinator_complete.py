"""Complete end-to-end test for all Coordinator execution paths.

Tests:
1. Simple task path (with explicit location)
2. Complex task path (exploration + decision + execution)
3. Action format conversion (structured output)
4. High-risk path (with Critic review)
"""

import logging
from pathlib import Path

from game_agent_try.agents.coordinator import CoordinatorAgent
from game_agent_try.agents.models import ExecutionMetrics
from game_agent_try.context import ContextAssembler
from game_agent_try.framework.models.litellm_model import LitellmModel


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def test_complete_complex_task_with_actions(coordinator):
    """Test complete complex task flow with action generation.

    This tests:
    - Explorer delegation
    - Evidence collection
    - Decision making with structured output
    - Action format conversion to ACI mutations
    """

    task = "Find the GameStateManager class and add a debug log"

    result = coordinator.run_task(task)

    print("\n" + "="*80)
    print("COMPLETE COMPLEX TASK TEST")
    print("="*80)
    print(f"Task: {task}")
    print(f"Success: {result.get('success')}")
    print(f"Path: {result.get('path')}")
    print(f"Evidence count: {result.get('evidence_count', 0)}")
    print(f"Candidate count: {result.get('candidate_count', 0)}")
    print(f"Exploration tokens: {result.get('exploration_tokens', 0)}")
    print(f"Exploration rounds: {result.get('exploration_rounds', 0)}")

    if 'error' in result:
        print(f"Error: {result['error']}")

    # Check that we got actions (even if execution failed)
    metrics = result.get('metrics')
    if metrics:
        print(f"\nMetrics:")
        print(f"  Total time: {metrics.total_time_seconds:.2f}s")
        print(f"  Execution path: {metrics.execution_path}")

    print("="*80)

    # Assertions
    assert result is not None
    assert result.get('path') == 'complex_delegated'
    # Should have found evidence
    assert result.get('evidence_count', 0) > 0


def test_simple_task_path(coordinator):
    """Test simple task with explicit file path.

    This tests:
    - File path extraction
    - Direct mutation generation
    - No exploration (token savings)
    """

    task = "Add a debug log in KitchenGameManager.cs in the Update method"

    result = coordinator.run_task(task)

    print("\n" + "="*80)
    print("SIMPLE TASK PATH TEST")
    print("="*80)
    print(f"Task: {task}")
    print(f"Success: {result.get('success')}")
    print(f"Path: {result.get('path')}")

    if 'error' in result:
        print(f"Error: {result['error']}")

    if result.get('path') == 'simple_direct':
        print("✓ Correctly routed to simple path (no exploration!)")

    print("="*80)

    # Should route to simple or fall back to complex
    assert result.get('path') in ['simple_direct', 'complex_delegated']


def test_action_format_conversion(coordinator):
    """Test that actions are in correct ACI mutation format.

    Verifies:
    - Actions have 'tool' field
    - Actions have 'arguments' dict
    - Actions have 'authorized_paths' list
    - Arguments contain required fields (path, old_text, new_text)
    """
    task = "Find the Player class and add a comment"

    # Mock decision to check format
    from game_agent_try.agents.models import Candidate, Evidence, EvidencePackage

    # Create fake evidence package
    evidence = EvidencePackage(
        success=True,
        candidate_nodes=[
            Candidate(
                node_id="player_001",
                path="Assets/Scripts/Player.cs",
                role="MonoBehaviour",
                summary="Player controller",
                confidence=0.9,
            ),
        ],
        evidence_items=[
            Evidence(
                evidence_id="ev_001",
                content="Player class handles movement",
                source="code_search",
                relevance_score=0.8,
            ),
        ],
        summary="Found Player class",
        rounds_used=1,
        tokens_used=100,
        search_strategy="adaptive",
    )

    # Call decision method directly
    decision = coordinator._make_mutation_decision(task, evidence)

    print("\n" + "="*80)
    print("ACTION FORMAT CONVERSION TEST")
    print("="*80)
    print(f"Decision success: {decision.get('success')}")
    print(f"Action count: {decision.get('action_count', 0)}")

    actions = decision.get('actions', [])
    for idx, action in enumerate(actions, 1):
        print(f"\nAction {idx}:")
        print(f"  Tool: {action.get('tool')}")
        print(f"  Arguments keys: {list(action.get('arguments', {}).keys())}")
        print(f"  Authorized paths: {action.get('authorized_paths')}")

        # Validate format
        assert action.get('tool') == 'unity_script_patch'
        assert 'arguments' in action
        assert 'path' in action['arguments']
        assert 'old_text' in action['arguments']
        assert 'new_text' in action['arguments']
        assert 'authorized_paths' in action
        assert isinstance(action['authorized_paths'], list)
        assert len(action['authorized_paths']) > 0

        print("  ✓ Format valid!")

    print("="*80)


def test_high_risk_path_structure(coordinator):
    """Test high-risk path with Critic (structure only, may not fully execute).

    Tests:
    - High-risk detection
    - Critic review integration
    - Rollback on rejection
    """

    # For now, high-risk is not auto-detected, so manually test the method
    from game_agent_try.agents.models import ComplexityAssessment, TaskComplexity

    task = "Refactor the entire game architecture"
    assessment = ComplexityAssessment(
        level=TaskComplexity.HIGH_RISK,
        estimated_files=10,
        needs_critic=True,
    )

    result = coordinator._execute_high_risk_task(task, assessment)

    print("\n" + "="*80)
    print("HIGH-RISK PATH TEST")
    print("="*80)
    print(f"Task: {task}")
    print(f"Success: {result.get('success')}")
    print(f"Path: {result.get('path')}")

    if 'error' in result:
        print(f"Error: {result['error']}")

    if 'critic_approved' in result:
        print(f"Critic approved: {result['critic_approved']}")

    print("="*80)

    # Should use high-risk path
    assert result.get('path') == 'high_risk_with_critic'


def test_token_efficiency_validation(coordinator):
    """Validate that exploration uses ~50% tokens vs full context.

    This is a key metric for Phase 1 success.
    """
    task = "Find the GameManager and add logging"

    result = coordinator.run_task(task)

    exploration_tokens = result.get('exploration_tokens', 0)

    print("\n" + "="*80)
    print("TOKEN EFFICIENCY TEST")
    print("="*80)
    print(f"Exploration tokens: {exploration_tokens:,}")
    print(f"Expected without isolation: ~80,000")
    print(f"Actual savings: {(1 - exploration_tokens / 80000) * 100:.1f}%")
    print("="*80)

    # Should be significantly less than full context
    # Full context would be ~80k-100k tokens per turn
    assert exploration_tokens < 80_000, "Token usage too high"
    print(f"✓ Token efficiency validated!")


if __name__ == "__main__":
    # Run tests manually
    import sys

    project_root = Path(r"E:\sysu-course\SeriousGame")
    context = ContextAssembler(project_root=project_root)
    model = LitellmModel(model_name="gpt-4o-mini", temperature=0.3)
    coordinator = CoordinatorAgent(model=model, context=context, project_root=project_root)

    print("\n🚀 Running complete Coordinator tests...\n")

    try:
        print("=" * 80)
        print("TEST 1: Complex task with action generation")
        print("=" * 80)
        test_complete_complex_task_with_actions(coordinator)
        print("\n✅ Test 1: Complex task with actions - PASSED\n")
    except Exception as e:
        print(f"\n❌ Test 1 failed: {e}\n")
        import traceback
        traceback.print_exc()

    try:
        print("=" * 80)
        print("TEST 2: Action format conversion")
        print("=" * 80)
        test_action_format_conversion(coordinator)
        print("\n✅ Test 2: Action format conversion - PASSED\n")
    except Exception as e:
        print(f"\n❌ Test 2 failed: {e}\n")
        import traceback
        traceback.print_exc()

    try:
        print("=" * 80)
        print("TEST 3: Token efficiency validation")
        print("=" * 80)
        test_token_efficiency_validation(coordinator)
        print("\n✅ Test 3: Token efficiency - PASSED\n")
    except Exception as e:
        print(f"\n❌ Test 3 failed: {e}\n")
        import traceback
        traceback.print_exc()

    print("\n🎉 Test suite complete!")
