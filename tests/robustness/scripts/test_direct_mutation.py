"""
手动测试单个mutation - 测试Player.cs的moveSpeed修改
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from game_agent_try.aci.mutation import UnityMutationExecutor, AciConfig
import hashlib

# Unity项目路径
unity_project = Path("E:/Unity_project/Kitchen_Chaos/Kitchen_Chaos")
target_file = unity_project / "Assets/Scripts/Player.cs"

# 读取当前文件内容
file_bytes = target_file.read_bytes()
file_content = file_bytes.decode("utf-8")
file_sha = hashlib.sha256(file_bytes).hexdigest()

print(f"文件: {target_file}")
print(f"SHA: {file_sha}")
print(f"大小: {len(file_content)} chars")
print()

# 查找moveSpeed定义
import re
matches = list(re.finditer(r'.*moveSpeed.*=.*5f.*', file_content))
print(f"找到 {len(matches)} 个匹配:")
for i, match in enumerate(matches, 1):
    line = match.group(0)
    print(f"  {i}. {repr(line)}")
print()

# 测试mutation
if matches:
    old_line = matches[0].group(0)
    print(f"旧代码: {repr(old_line)}")

    # 生成新代码
    new_line = old_line.replace('5f', '7f')
    print(f"新代码: {repr(new_line)}")
    print()

    # 检查old_line是否在文件中
    if old_line in file_content:
        print("✓ old_text存在于文件中")
    else:
        print("✗ old_text不存在于文件中")
        print(f"  正在尝试不同的换行符...")

        # 尝试不同的换行符
        variants = [
            ('LF (\\n)', old_line),
            ('CRLF (\\r\\n)', old_line.replace('\n', '\r\n')),
            ('CR (\\r)', old_line.replace('\n', '\r')),
        ]

        for name, variant in variants:
            if variant in file_content:
                print(f"  ✓ 找到匹配: {name}")
                old_line = variant
                new_line = variant.replace('5f', '7f')
                break
    print()

    # 创建mutation executor
    executor = UnityMutationExecutor(
        project_root=unity_project,
        artifact_root=project_root / "artifacts" / "test",
        config=AciConfig(),
    )

    # 执行mutation
    action = {
        "tool": "unity_script_patch",
        "arguments": {
            "path": "Assets/Scripts/Player.cs",
            "old_text": old_line,
            "new_text": new_line,
            "expected_sha256": file_sha,
        },
        "_authorized_paths": ["Assets/Scripts/Player.cs"],
    }

    print("执行mutation...")
    result = executor.execute(action)

    print(f"返回码: {result.get('returncode')}")
    print(f"输出: {result.get('output', '')[:200]}")

    if result.get('returncode') == 0:
        print("✓ Mutation成功!")
    else:
        print("✗ Mutation失败!")
        print(f"异常: {result.get('exception_info', '')[:500]}")

else:
    print("未找到匹配的行")
