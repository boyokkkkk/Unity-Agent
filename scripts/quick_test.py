"""Quick start script for testing Phase 1 implementation.

Usage:
    python scripts/quick_test.py

This will run a simple test to verify the system is working.
"""

import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from game_agent_try.agents.coordinator import CoordinatorAgent
from game_agent_try.context import ContextAssembler
from game_agent_try.framework.models.litellm_model import LitellmModel


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main():
    print("\n" + "="*80)
    print("Phase 1 Quick Test")
    print("="*80)

    # Configuration
    project_root = Path(r"E:\sysu-course\SeriousGame")

    if not project_root.exists():
        print(f"\n❌ Project root not found: {project_root}")
        print("Please update the path in this script.")
        return

    print(f"\n✓ Project root: {project_root}")

    # Initialize components
    print("\n1. Initializing components...")
    try:
        context = ContextAssembler(project_root=project_root)
        print("   ✓ Context assembled")

        model = LitellmModel(model_name="gpt-4o-mini", temperature=0.3)
        print("   ✓ Model initialized")

        coordinator = CoordinatorAgent(
            model=model,
            context=context,
            project_root=project_root,
        )
        print("   ✓ Coordinator created")
    except Exception as e:
        print(f"\n❌ Initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # Test tasks
    test_tasks = [
        {
            "name": "Simple Task Test",
            "task": "Add a debug log in KitchenGameManager.cs",
            "expected_path": "simple_direct",
        },
        {
            "name": "Complex Task Test",
            "task": "Find the GameStateManager class and add logging",
            "expected_path": "complex_delegated",
        },
    ]

    # Run tests
    results = []
    for idx, test in enumerate(test_tasks, 1):
        print(f"\n{'='*80}")
        print(f"Test {idx}: {test['name']}")
        print(f"{'='*80}")
        print(f"Task: {test['task']}")
        print()

        try:
            result = coordinator.run_task(test['task'])

            success = result.get('success', False)
            path = result.get('path', 'unknown')
            error = result.get('error')

            print(f"\n{'='*80}")
            print(f"Result: {'✅ SUCCESS' if success else '❌ FAILED'}")
            print(f"{'='*80}")
            print(f"Execution path: {path}")

            if 'exploration_tokens' in result:
                print(f"Exploration tokens: {result['exploration_tokens']:,}")

            if 'exploration_rounds' in result:
                print(f"Exploration rounds: {result['exploration_rounds']}")

            if 'evidence_count' in result:
                print(f"Evidence collected: {result['evidence_count']}")

            if 'mutations_applied' in result:
                print(f"Mutations applied: {result['mutations_applied']}")

            if error:
                print(f"\nError: {error}")

            results.append({
                'name': test['name'],
                'success': success,
                'path': path,
                'error': error,
            })

        except Exception as e:
            print(f"\n❌ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()

            results.append({
                'name': test['name'],
                'success': False,
                'path': 'error',
                'error': str(e),
            })

    # Summary
    print(f"\n{'='*80}")
    print("Test Summary")
    print(f"{'='*80}")

    for result in results:
        status = "✅" if result['success'] else "❌"
        print(f"{status} {result['name']}: {result['path']}")
        if result['error']:
            print(f"   Error: {result['error'][:100]}...")

    success_count = sum(1 for r in results if r['success'])
    total = len(results)
    print(f"\nSuccess rate: {success_count}/{total} ({success_count/total*100:.0f}%)")

    print(f"\n{'='*80}")
    if success_count == total:
        print("🎉 All tests passed! System is ready for real tasks.")
    elif success_count > 0:
        print("⚠️  Some tests passed. Review failures and adjust.")
    else:
        print("❌ All tests failed. Check configuration and API key.")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
