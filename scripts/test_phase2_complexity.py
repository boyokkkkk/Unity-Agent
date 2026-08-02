"""Test Phase 2: Coordinator complexity assessment.

This script tests the enhanced complexity assessment with:
1. Fast heuristic checks (explicit locations)
2. High-risk keyword detection
3. LLM-based assessment for ambiguous cases
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from game_agent_try.agents.coordinator import CoordinatorAgent
from game_agent_try.agents.models import TaskComplexity
from game_agent_try.context import ContextAssembler
from game_agent_try.framework.models.litellm_model import LitellmModel


def test_complexity_assessment():
    """Test complexity assessment on various task types."""

    # Initialize (minimal setup for testing)
    unity_project = Path(r"E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos")
    if not unity_project.exists():
        print(f"❌ Unity project not found: {unity_project}")
        return

    context = ContextAssembler(project_root=unity_project)

    # Use DashScope deepseek-v3 model (via 阿里云百炼)
    model = LitellmModel(
        model_name="openai/deepseek-v3",
        temperature=0.0,
        cost_tracking="ignore_errors",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        drop_params=True,
    )

    coordinator = CoordinatorAgent(
        model=model,
        context=context,
        project_root=unity_project,
    )

    # Test cases
    test_cases = [
        # SIMPLE tasks (explicit location)
        {
            "task": "Add a debug log in KitchenGameManager.cs at line 45",
            "expected": TaskComplexity.SIMPLE,
            "description": "Explicit file + line number",
        },
        {
            "task": "Add null check in PlayerController.cs Update method",
            "expected": TaskComplexity.SIMPLE,
            "description": "Explicit file + method",
        },
        {
            "task": "In file GameStateManager.cs, add OnGameWin.Invoke() in TransitionToWin",
            "expected": TaskComplexity.SIMPLE,
            "description": "Explicit file + method with 'in file'",
        },

        # COMPLEX tasks (need exploration)
        {
            "task": "Fix the bug where the tutorial UI doesn't close",
            "expected": TaskComplexity.COMPLEX,
            "description": "Bug fix without location",
        },
        {
            "task": "Find where player input is processed and add validation",
            "expected": TaskComplexity.COMPLEX,
            "description": "Need to locate code first",
        },
        {
            "task": "Add error handling to the scoring system",
            "expected": TaskComplexity.COMPLEX,
            "description": "Vague system reference",
        },

        # HIGH_RISK tasks (architectural changes)
        {
            "task": "Refactor the event system to use a custom event bus",
            "expected": TaskComplexity.HIGH_RISK,
            "description": "System refactoring",
        },
        {
            "task": "Redesign the state machine architecture",
            "expected": TaskComplexity.HIGH_RISK,
            "description": "Architecture redesign",
        },
        {
            "task": "Rewrite all UI managers to use dependency injection",
            "expected": TaskComplexity.HIGH_RISK,
            "description": "System-wide changes",
        },
    ]

    print("=" * 80)
    print("Phase 2: Complexity Assessment Test")
    print("=" * 80)
    print()

    results = []

    for i, test_case in enumerate(test_cases, 1):
        task = test_case["task"]
        expected = test_case["expected"]
        description = test_case["description"]

        print(f"Test {i}/{len(test_cases)}: {description}")
        print(f"  Task: {task}")
        print(f"  Expected: {expected.value}")

        try:
            assessment = coordinator._assess_complexity(task)
            actual = assessment.level

            print(f"  Actual: {actual.value}")
            print(f"  Reasoning: {assessment.reasoning}")
            print(f"  Files: {assessment.estimated_files}")
            print(f"  Exploration: {assessment.needs_exploration}")
            print(f"  Critic: {assessment.needs_critic}")

            # Check result
            passed = actual == expected
            results.append({
                "test": i,
                "description": description,
                "expected": expected.value,
                "actual": actual.value,
                "passed": passed,
            })

            if passed:
                print(f"  ✅ PASS")
            else:
                print(f"  ❌ FAIL (expected {expected.value}, got {actual.value})")

        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            results.append({
                "test": i,
                "description": description,
                "expected": expected.value,
                "actual": "error",
                "passed": False,
            })

        print()

    # Summary
    print("=" * 80)
    print("Summary")
    print("=" * 80)

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    accuracy = (passed / total * 100) if total > 0 else 0

    print(f"Total tests: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {total - passed}")
    print(f"Accuracy: {accuracy:.1f}%")
    print()

    if accuracy >= 80:
        print("✅ Phase 2 complexity assessment is working well!")
    elif accuracy >= 60:
        print("⚠️ Phase 2 complexity assessment needs tuning")
    else:
        print("❌ Phase 2 complexity assessment needs significant improvement")

    print()
    print("Detailed Results:")
    for r in results:
        status = "✅" if r["passed"] else "❌"
        print(f"  {status} Test {r['test']}: {r['description']}")
        print(f"      Expected: {r['expected']}, Actual: {r['actual']}")

    return accuracy >= 80


if __name__ == "__main__":
    success = test_complexity_assessment()
    sys.exit(0 if success else 1)
