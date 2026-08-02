"""
手动执行单个测试任务

用法:
python scripts/execute_test_task.py A1
"""

import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv()

from game_agent_try.agents.coordinator import CoordinatorAgent
from game_agent_try.context import ContextAssembler
from game_agent_try.framework.models.litellm_model import LitellmModel
import json


# 测试任务定义
TEST_TASKS = {
    "A1": "在 Assets/Scripts/Player.cs 中，玩家的移动速度 moveSpeed 默认值是 5f，但这对于这个游戏来说太慢了。请将默认值改为 7f 以提供更好的游戏体验。",
}


def execute_task(task_id: str):
    """执行单个测试任务"""

    if task_id not in TEST_TASKS:
        print(f"❌ 未知任务: {task_id}")
        print(f"可用任务: {', '.join(TEST_TASKS.keys())}")
        return

    print("="*80)
    print(f"🎯 执行测试任务: {task_id}")
    print("="*80)

    task_description = TEST_TASKS[task_id]
    print(f"\n任务描述:\n{task_description}\n")

    # Configuration
    unity_project_root = Path(r"E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos")

    if not unity_project_root.exists():
        print(f"❌ Unity project not found: {unity_project_root}")
        return

    # Initialize model
    print("初始化模型...")
    model = LitellmModel(
        model_name="openai/deepseek-v3",
        temperature=0.3,
        cost_tracking="ignore_errors",
        api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
        drop_params=True,
    )

    # Initialize context
    graph_path = Path("E:/sysu-course/GameAgent/artifacts/project-graph/kitchen-chaos-causal-full/project-graph.json")

    if graph_path.exists():
        print(f"加载项目图: {graph_path.name}")
        context = ContextAssembler(
            project_root=unity_project_root,
            config={"enabled": True, "graph_path": str(graph_path)},
        )
    else:
        print("⚠️  项目图未找到，使用基础上下文")
        context = ContextAssembler(
            project_root=unity_project_root,
            config={"enabled": False},
        )

    # Create coordinator
    print("创建协调器...")
    coordinator = CoordinatorAgent(
        model=model,
        context=context,
        project_root=unity_project_root,
        artifact_root=unity_project_root / ".game-agent-artifacts",
    )

    # Execute
    print("\n" + "="*80)
    print("开始执行任务...")
    print("="*80 + "\n")

    import time
    start_time = time.time()

    try:
        result = coordinator.run_task(task_description)
        duration = time.time() - start_time

        # Print results
        print("\n" + "="*80)
        print("📊 执行结果")
        print("="*80)

        print(f"\n✅ 成功: {result.success}")
        print(f"⏱️  执行时间: {duration:.1f}秒")
        print(f"🎯 复杂度: {result.complexity_level}")
        print(f"🛤️  执行路径: {result.execution_path}")
        print(f"📊 Token使用: {result.total_tokens}")

        if hasattr(result, 'exit_status'):
            print(f"📝 退出状态: {result.exit_status}")

        # Check git status for changed files
        print("\n检查文件修改...")
        import subprocess
        git_result = subprocess.run(
            ["git", "status", "--short", "Assets/Scripts/"],
            cwd=unity_project_root,
            capture_output=True,
            text=True
        )

        if git_result.stdout.strip():
            print("\n📁 修改的文件:")
            print(git_result.stdout)
        else:
            print("\n⚠️  没有检测到文件修改")

        print("="*80 + "\n")

        return result

    except Exception as e:
        duration = time.time() - start_time
        print(f"\n❌ 执行失败: {e}")
        print(f"⏱️  执行时间: {duration:.1f}秒")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    if len(sys.argv) > 1:
        task_id = sys.argv[1]
    else:
        task_id = "A1"  # Default

    execute_task(task_id)
