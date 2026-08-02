"""Phase 1 Real Task Test - Kitchen Chaos State Transition Bug

This script tests the Phase 1 implementation on a real Unity bug:
"Game should enter countdown after player presses interact key at start screen,
but tutorial UI doesn't close and countdown UI doesn't appear."

Expected: Complex path with Explorer + Decision + Mutation + Validation
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

from game_agent_try.agents.coordinator import CoordinatorAgent
from game_agent_try.context import ContextAssembler
from game_agent_try.framework.models.litellm_model import LitellmModel


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main():
    print("\n" + "="*80)
    print("🎮 Phase 1 Real Task Test - Kitchen Chaos")
    print("="*80)

    # Configuration
    project_root = Path(r"E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos")

    if not project_root.exists():
        print(f"\n❌ Project not found: {project_root}")
        print("Please update the path in this script.")
        return

    print(f"\n✓ Project: {project_root}")

    # Real task from baseline
    task = """玩家在开始界面按下交互键后，游戏应进入倒计时；
目前教程界面没有关闭，倒计时界面也没有出现。
问题可能位于游戏状态切换与 UI 刷新链路。
请定位根因，进行最小修复，并通过相关 Unity 测试验证。"""

    print(f"\n📋 Task Description:")
    print(f"{task}")
    print()

    # Initialize components
    print("="*80)
    print("1. Initializing Phase 1 System")
    print("="*80)

    try:
        start_time = time.time()

        print("\n  → Loading context...")
        # Use the correct path to project graph (relative to GameAgent root)
        graph_path = Path("E:/sysu-course/GameAgent/artifacts/project-graph/kitchen-chaos-causal-full/project-graph.json")

        if not graph_path.exists():
            print(f"\n❌ Error: Project graph not found at {graph_path}")
            return

        print(f"    ✓ Found project graph: {graph_path.name} ({graph_path.stat().st_size // 1024} KB)")

        context = ContextAssembler(
            project_root=project_root,
            config={
                "enabled": True,
                "graph_path": str(graph_path),
            },
        )
        print("    ✓ Context loaded with project graph")

        print("  → Initializing model...")
        # Use DashScope with proper configuration (matching kitchen_chaos.json)
        model = LitellmModel(
            model_name="openai/deepseek-v3",  # Test deepseek-v3 first
            temperature=0.3,
            cost_tracking="ignore_errors",
            api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",  # DashScope endpoint
            drop_params=True,  # Drop unsupported params
        )
        print("    ✓ Model initialized (deepseek-v3 via DashScope)")

        print("  → Creating coordinator...")
        coordinator = CoordinatorAgent(
            model=model,
            context=context,
            project_root=project_root,
        )
        print("    ✓ Coordinator ready")

        init_time = time.time() - start_time
        print(f"\n✓ System initialized in {init_time:.1f}s")

    except Exception as e:
        print(f"\n❌ Initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # Execute task
    print("\n" + "="*80)
    print("2. Executing Real Task")
    print("="*80)
    print("\nThis may take 2-3 minutes...")
    print("Watch for:")
    print("  - Complexity assessment (should be COMPLEX)")
    print("  - Explorer delegation")
    print("  - Evidence collection")
    print("  - Mutation generation")
    print("  - Validation\n")

    try:
        exec_start = time.time()
        result = coordinator.run_task(task)
        exec_time = time.time() - exec_start

        print("\n" + "="*80)
        print("3. Result Analysis")
        print("="*80)

        success = result.get('success', False)
        path = result.get('path', 'unknown')
        error = result.get('error')

        print(f"\n{'='*80}")
        print(f"Status: {'✅ SUCCESS' if success else '❌ FAILED'}")
        print(f"{'='*80}")

        print(f"\n📊 Execution Metrics:")
        print(f"  Path taken: {path}")
        print(f"  Execution time: {exec_time:.1f}s")

        if 'exploration_tokens' in result:
            tokens = result['exploration_tokens']
            print(f"  Exploration tokens: {tokens:,}")
            savings = (1 - tokens / 80000) * 100 if tokens < 80000 else 0
            print(f"  Token savings: {savings:.1f}% vs baseline")

        if 'exploration_rounds' in result:
            print(f"  Exploration rounds: {result['exploration_rounds']}")

        if 'evidence_count' in result:
            print(f"  Evidence collected: {result['evidence_count']}")

        if 'candidate_count' in result:
            print(f"  Candidates found: {result['candidate_count']}")

        if 'mutations_applied' in result:
            print(f"  Mutations applied: {result['mutations_applied']}")

        if 'changed_paths' in result and result['changed_paths']:
            print(f"\n📝 Changed Files:")
            for path_item in result['changed_paths']:
                print(f"    - {path_item}")

        if error:
            print(f"\n❌ Error Details:")
            print(f"  {error}")

        if 'metrics' in result:
            metrics = result['metrics']
            print(f"\n📈 Detailed Metrics:")
            print(f"  Complexity level: {metrics.complexity_level}")
            print(f"  Execution path: {metrics.execution_path}")

        # Save detailed result
        output_dir = Path("artifacts/phase1-tests")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"real_task_{int(time.time())}.json"

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)

        print(f"\n💾 Full result saved to:")
        print(f"  {output_file}")

        # Summary
        print("\n" + "="*80)
        print("4. Summary")
        print("="*80)

        if success:
            print("\n🎉 Task completed successfully!")
            print("\nNext steps:")
            print("  1. Check changed files above")
            print("  2. Review the mutations in the saved JSON")
            print("  3. Manually test the game to verify fix")
            print("  4. Compare with baseline implementation")
        else:
            print("\n⚠️  Task did not complete successfully")
            print("\nDebug steps:")
            print("  1. Check error message above")
            print("  2. Review the saved JSON for details")
            print("  3. Check if Explorer found relevant files")
            print("  4. Verify decision generated actions")
            print("  5. Check validation logs")

        print("\n" + "="*80)
        print("Phase 1 Real Task Test Complete")
        print("="*80)

        return result

    except Exception as e:
        print(f"\n❌ Execution failed: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    result = main()

    if result:
        sys.exit(0 if result.get('success') else 1)
    else:
        sys.exit(2)
