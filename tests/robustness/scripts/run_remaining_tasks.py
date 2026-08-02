"""
运行剩余任务来收集完整的token数据
"""
import subprocess
import time
from pathlib import Path

# 需要重新运行的任务（token=0的任务）
TASKS = ["B2", "B3", "C1", "C2", "C3", "D1", "D2", "D3", "E1"]

script_path = Path("E:/sysu-course/GameAgent/tests/robustness/run_task.py")

print("="*80)
print(f"运行剩余{len(TASKS)}个任务来收集完整token数据")
print("="*80)
print()

completed = 0
failed = 0

for i, task_id in enumerate(TASKS, 1):
    print(f"\n[{i}/{len(TASKS)}] 运行任务 {task_id}...")

    try:
        result = subprocess.run(
            ["python", str(script_path), task_id],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=120,
        )

        if result.returncode == 0:
            completed += 1
            print(f"✓ 任务 {task_id} 完成")
        else:
            failed += 1
            print(f"✗ 任务 {task_id} 失败")
            if result.stderr:
                print(f"错误: {result.stderr[:200]}")

    except subprocess.TimeoutExpired:
        failed += 1
        print(f"✗ 任务 {task_id} 超时")
    except Exception as e:
        failed += 1
        print(f"✗ 任务 {task_id} 异常: {e}")

    # 短暂延迟
    time.sleep(1)

print(f"\n{'='*80}")
print(f"完成: {completed}/{len(TASKS)}, 失败: {failed}/{len(TASKS)}")
print(f"{'='*80}")
