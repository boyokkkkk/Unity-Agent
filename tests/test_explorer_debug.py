"""Simplified test to debug Explorer directly."""

from pathlib import Path
from unittest.mock import Mock
import logging

# Enable INFO logging
logging.basicConfig(level=logging.INFO)

from game_agent_try.agents import ExplorerAgent, ExplorationTask
from game_agent_try.context import ContextAssembler, ContextConfig
from game_agent_try.framework.models import get_model


def test_explorer_with_real_model():
    """Test Explorer with real model and project."""
    print("Testing Explorer with real model...")
    print("=" * 70)

    # Setup
    project_root = Path("E:/Unity_project/Kitchen_Chaos/Kitchen_Chaos")
    graph_path = Path("E:/sysu-course/GameAgent/artifacts/project-graph/kitchen-chaos-full/project-graph.json")

    if not project_root.exists():
        print(f"✗ Project not found: {project_root}")
        return

    if not graph_path.exists():
        print(f"✗ Graph not found: {graph_path}")
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
        import traceback
        traceback.print_exc()
        return

    # Create Explorer
    try:
        explorer = ExplorerAgent(
            model=model,
            context=context,
            project_root=project_root,
            max_rounds=3,  # Only 3 rounds for quick test
            max_tokens=10_000,
        )
        print("✓ Explorer initialized")
        print()
    except Exception as e:
        print(f"✗ Explorer failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # Check tools
    print(f"Explorer has {len(explorer._get_tool_schemas())} tools available")
    print()

    # Run exploration
    task = ExplorationTask(
        query="Find GameStateManager class",
        max_results=5,
        max_rounds=3,
    )

    print(f"Running exploration: {task.query}")
    print("-" * 70)

    # Monkey patch _call_model to see what's happening
    original_call_model = explorer._call_model
    call_count = [0]

    def debug_call_model():
        call_count[0] += 1
        print(f"\n  [Call {call_count[0]}] Calling model...")
        result = original_call_model()
        if result:
            print(f"  [Call {call_count[0]}] Got response:")
            print(f"    - content length: {len(result.get('content', ''))}")
            print(f"    - tool_calls: {len(result.get('tool_calls', []))}")
            extra = result.get('extra', {})
            print(f"    - prompt_tokens: {extra.get('prompt_tokens', 0)}")
            print(f"    - completion_tokens: {extra.get('completion_tokens', 0)}")
            if result.get('tool_calls'):
                for tc in result.get('tool_calls', [])[:2]:
                    func_name = tc.get('function', {}).get('name', '')
                    print(f"      * {func_name}")
                    print(f"        args: {tc.get('function', {}).get('arguments', '')[:80]}...")
        else:
            print(f"  [Call {call_count[0]}] No response!")
        return result

    explorer._call_model = debug_call_model

    try:
        result = explorer.explore(task)

        print()
        print("-" * 70)
        print("Results:")
        print(f"  Success: {result.success}")
        print(f"  Rounds used: {result.rounds_used}")
        print(f"  Tokens used: {result.tokens_used}")
        print(f"  Evidence items: {len(result.evidence_items)}")
        print(f"  Candidate nodes: {len(result.candidate_nodes)}")

        if result.error:
            print(f"  Error: {result.error}")

        if result.evidence_items:
            print(f"\n  Evidence:")
            for idx, evidence in enumerate(result.evidence_items[:3], 1):
                print(f"    {idx}. [{evidence.source}] score={evidence.relevance_score:.2f}")
                print(f"       {evidence.content[:100]}...")

        if result.candidate_nodes:
            print(f"\n  Candidates:")
            for idx, candidate in enumerate(result.candidate_nodes[:3], 1):
                print(f"    {idx}. {candidate.role}: {candidate.path}")

        print(f"\n  Summary:")
        print(f"    {result.summary[:200]}...")

    except Exception as e:
        print(f"\n✗ Exploration failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_explorer_with_real_model()
