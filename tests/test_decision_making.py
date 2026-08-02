"""Test Coordinator decision-making logic."""

from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)

from game_agent_try.agents import CoordinatorAgent
from game_agent_try.context import ContextAssembler, ContextConfig
from game_agent_try.framework.models import get_model


def test_decision_making():
    """Test that Coordinator makes decisions based on Explorer evidence."""
    print("=" * 70)
    print("Testing Coordinator Decision Making")
    print("=" * 70)
    print()

    # Setup
    project_root = Path("E:/Unity_project/Kitchen_Chaos/Kitchen_Chaos")
    graph_path = Path("E:/sysu-course/GameAgent/artifacts/project-graph/kitchen-chaos-full/project-graph.json")

    if not project_root.exists():
        print(f"✗ Project not found: {project_root}")
        return

    print(f"✓ Project: {project_root}")
    print(f"✓ Graph: {graph_path}")
    print()

    # Create model
    model_config = {
        "model_class": "litellm",
        "cost_tracking": "ignore_errors",
        "model_kwargs": {
            "drop_params": True,
            "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "temperature": 0.0,
            "max_tokens": 2048,
        },
    }

    try:
        model = get_model("openai/qwen-plus", model_config)
        print("✓ Model initialized")
    except Exception as e:
        print(f"✗ Model failed: {e}")
        return

    # Create context
    context_config = ContextConfig(
        enabled=True,
        graph_path=str(graph_path),
    )

    try:
        context = ContextAssembler(
            context_config,
            project_root=project_root,
        )
        print("✓ Context assembled")
    except Exception as e:
        print(f"✗ Context failed: {e}")
        return

    # Create coordinator
    try:
        coordinator = CoordinatorAgent(
            model=model,
            context=context,
            project_root=project_root,
        )
        print("✓ Coordinator initialized")
        print()
    except Exception as e:
        print(f"✗ Coordinator failed: {e}")
        return

    # Run task
    task = "找到 KitchenGameManager 类及其状态转换相关的方法"
    print(f"Task: {task}")
    print("-" * 70)

    try:
        result = coordinator.run_task(task)

        print()
        print("-" * 70)
        print("Results:")
        print(f"  Success: {result.get('success')}")
        print(f"  Path: {result.get('path')}")

        if result.get('error'):
            print(f"  Error: {result['error']}")

        if result.get('evidence_count'):
            print(f"  Evidence collected: {result['evidence_count']}")

        if result.get('candidate_count'):
            print(f"  Candidates found: {result['candidate_count']}")

        if result.get('exploration_tokens'):
            print(f"  Exploration tokens: {result['exploration_tokens']}")

        if result.get('mutations_applied'):
            print(f"  Mutations applied: {result['mutations_applied']}")

        if result.get('changed_paths'):
            print(f"  Changed files:")
            for path in result['changed_paths']:
                print(f"    - {path}")

        if result.get('validated'):
            print(f"  Validation: {'passed' if result.get('success') else 'failed'}")

        # Check if decision was made
        if coordinator.current_evidence:
            print(f"\n  Decision Making:")
            print(f"    - Evidence items: {len(coordinator.current_evidence.evidence_items)}")
            print(f"    - Candidates: {len(coordinator.current_evidence.candidate_nodes)}")

        print()

        if result.get('success'):
            print("✓ Task completed successfully!")
        else:
            print("✗ Task failed, but decision logic executed")

    except Exception as e:
        print(f"\n✗ Task execution failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_decision_making()
