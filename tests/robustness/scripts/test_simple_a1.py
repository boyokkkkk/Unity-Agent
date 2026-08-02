"""
简化测试 - 直接执行任务A1并打印详细日志
"""
import sys
import logging
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

# 设置详细日志
logging.basicConfig(
    level=logging.INFO,
    format='%(name)s - %(levelname)s - %(message)s'
)

from game_agent_try.agents import CoordinatorAgent
from game_agent_try.context import ContextAssembler, ContextConfig
from game_agent_try.framework.models import get_model

print("=" * 80)
print("简化测试 - 任务A1")
print("=" * 80)

# Unity项目路径
unity_project_root = Path("E:/Unity_project/Kitchen_Chaos/Kitchen_Chaos")
graph_path = Path("E:/sysu-course/GameAgent/artifacts/project-graph/kitchen-chaos-full/project-graph.json")

# 初始化模型
model_config = {
    "model_class": "litellm",
    "cost_tracking": "ignore_errors",
    "model_kwargs": {
        "drop_params": True,
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "temperature": 0.0,
        "max_tokens": 8192,
    },
}

model = get_model("openai/qwen-plus", model_config)
print("✓ 模型初始化")

# 初始化上下文
context_config = ContextConfig(
    enabled=True,
    graph_path=str(graph_path),
)

context = ContextAssembler(
    context_config,
    project_root=unity_project_root,
)
print("✓ 上下文初始化")

# 初始化Coordinator
coordinator = CoordinatorAgent(
    model=model,
    context=context,
    project_root=unity_project_root,
)
print("✓ Coordinator初始化")
print()

# 任务描述
task = "在 Assets/Scripts/Player.cs 中，玩家的移动速度 moveSpeed 默认值是 5f，但这对于这个游戏来说太慢了。请将默认值改为 7f 以提供更好的游戏体验。"

print(f"任务: {task}")
print()
print("开始执行...")
print("-" * 80)

result = coordinator.run_task(task)

print("-" * 80)
print()
print("结果:")
print(f"  success: {result.get('success')}")
print(f"  mutations_applied: {result.get('mutations_applied')}")
print(f"  changed_paths: {result.get('changed_paths')}")
print(f"  path: {result.get('path')}")
print(f"  error: {result.get('error')}")
print()

# 检查文件
import subprocess
check_result = subprocess.run(
    ["git", "diff", "Assets/Scripts/Player.cs"],
    cwd=unity_project_root,
    capture_output=True,
    text=True
)

if check_result.stdout:
    print("✓ 文件已修改:")
    print(check_result.stdout[:500])
else:
    print("✗ 文件未修改")

print()
print("=" * 80)
