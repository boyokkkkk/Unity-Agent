"""
测试MutationService完整流程
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from game_agent_try.services.mutation_service import MutationService
from game_agent_try.aci.mutation import AciConfig
import hashlib

# Unity项目路径
unity_project = Path("E:/Unity_project/Kitchen_Chaos/Kitchen_Chaos")
target_file = unity_project / "Assets/Scripts/Player.cs"

print("测试MutationService")
print("=" * 80)

# 读取文件
file_bytes = target_file.read_bytes()
file_sha = hashlib.sha256(file_bytes).hexdigest()

print(f"文件: {target_file}")
print(f"SHA: {file_sha}")
print()

# 创建MutationService
service = MutationService(
    project_root=unity_project,
    config=AciConfig(),
)

print("创建MutationService成功")
print()

# 准备mutation action
action = {
    "tool": "unity_script_patch",
    "arguments": {
        "path": "Assets/Scripts/Player.cs",
        "old_text": "    [SerializeField] private float moveSpeed = 5f;\r",
        "new_text": "    [SerializeField] private float moveSpeed = 7f;\r",
        "expected_sha256": file_sha,
    },
}

authorized_paths = ["Assets/Scripts/Player.cs"]

print("执行mutation...")
result = service.execute_mutation(action, authorized_paths)

print()
print("=" * 80)
print("结果:")
print(f"  success: {result.success}")
print(f"  changed_paths: {result.changed_paths}")
print(f"  checkpoint_id: {result.checkpoint_id}")
print(f"  transaction_id: {result.transaction_id}")
print(f"  error: {result.error}")
print()

print(f"服务统计:")
print(f"  execution_count: {service.execution_count}")
print(f"  success_count: {service.success_count}")
print(f"  failure_count: {service.failure_count}")
print()

if result.success:
    print("✓ Mutation成功!")

    # 验证文件是否真的被修改
    new_content = target_file.read_text(encoding="utf-8")
    if "moveSpeed = 7f" in new_content:
        print("✓ 文件内容已确认修改")
    else:
        print("✗ 文件内容未修改")

    # 恢复文件
    print()
    print("恢复文件...")
    import subprocess
    subprocess.run(
        ["git", "checkout", "Assets/Scripts/Player.cs"],
        cwd=unity_project,
        capture_output=True
    )
    print("✓ 文件已恢复")
else:
    print(f"✗ Mutation失败: {result.error}")

print("=" * 80)
