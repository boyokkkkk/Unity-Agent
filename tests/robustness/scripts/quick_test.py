"""
快速验证测试 - 运行一个简单任务验证系统

这个脚本运行最简单的任务A1来快速验证系统是否正常工作。
"""

import sys
from pathlib import Path

# Add project to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

from dotenv import load_dotenv
load_dotenv()

from game_agent_try.agents.coordinator import CoordinatorAgent
from game_agent_try.context import ContextAssembler
from game_agent_try.framework.models.litellm_model import LitellmModel


def quick_test():
    """运行快速验证测试"""

    print("="*80)
    print("🚀 Quick Verification Test")
    print("="*80)
    print("\nTesting Task A1: Simple Bug Fix")
    print("Description: Fix movement speed calculation")
    print()

    # Configuration
    unity_project_root = Path(r"E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos")

    if not unity_project_root.exists():
        print(f"❌ Unity project not found: {unity_project_root}")
        return {"success": False, "error": "Project not found"}

    # Task description
    task = """在 Assets/Scripts/Player/Player.cs 的 HandleMovement() 方法中，
玩家移动速度计算有误，应该是 moveSpeed * Time.deltaTime * 2f，
但当前只有 moveSpeed * Time.deltaTime。
请修复这个系数错误。"""

    # Initialize model
    model = LitellmModel(
        model_name="openai/deepseek-v3",
        temperature=0.3,
        cost_tracking="ignore_errors",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        drop_params=True,
    )

    # Initialize context
    graph_path = project_root.parent.parent.parent / "GameAgent" / "artifacts" / "project-graph" / "kitchen-chaos-causal-full" / "project-graph.json"

    if not graph_path.exists():
        print(f"⚠️  Warning: Project graph not found at {graph_path}")
        print("Continuing without project graph...")
        context = ContextAssembler(
            project_root=unity_project_root,
            config={"enabled": False},
        )
    else:
        print(f"✓ Loading project graph: {graph_path.name}")
        context = ContextAssembler(
            project_root=unity_project_root,
            config={
                "enabled": True,
                "graph_path": str(graph_path),
            },
        )

    # Create coordinator
    artifact_root = unity_project_root / ".game-agent-artifacts"
    coordinator = CoordinatorAgent(
        model=model,
        context=context,
        project_root=unity_project_root,
        artifact_root=artifact_root,
    )

    # Execute
    print("Executing task...")
    result = coordinator.run_task(task)

    # Print results
    print("\n" + "="*80)
    print("📊 Results")
    print("="*80)

    print(f"\n✅ Success: {result.get('success', False)}")
    print(f"📁 Files changed: {len(result.get('changed_paths', []))}")
    print(f"🔧 Mutations applied: {result.get('mutations_applied', 0)}")

    if result.get('changed_paths'):
        print(f"\nChanged files:")
        for path in result['changed_paths']:
            print(f"  - {path}")

    if result.get('error'):
        print(f"\n❌ Error: {result['error']}")

    print("\n" + "="*80)

    return result


if __name__ == "__main__":
    try:
        result = quick_test()
        sys.exit(0 if result.get('success') else 1)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
