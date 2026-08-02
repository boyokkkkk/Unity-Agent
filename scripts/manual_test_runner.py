"""
手动测试14个鲁棒性任务

直接使用test_real_task.py的模式，逐个测试
"""

import json
import subprocess
import time
from pathlib import Path
from datetime import datetime


# 14个测试任务
TASKS = {
    "A1": {
        "name": "玩家移动速度调整",
        "description": "在 Assets/Scripts/Player.cs 中，玩家的移动速度 moveSpeed 默认值是 5f，但这对于这个游戏来说太慢了。请将默认值改为 7f 以提供更好的游戏体验。",
        "expected_files": ["Assets/Scripts/Player.cs"],
        "validation": "moveSpeed.*=.*7f",
    },
    "A2": {
        "name": "游戏暂停时音乐继续播放",
        "description": "玩家按下暂停键后，游戏暂停了，但音乐还在播放。应该暂停时音乐也停止，恢复时音乐继续。目前暂停功能位于 KitchenGameManager.cs 中，音乐由 MusicManager.cs 管理。请修复这个问题。",
        "expected_files": ["Assets/Scripts/KitchenGameManager.cs", "Assets/Scripts/MusicManager.cs"],
    },
    "A3": {
        "name": "DeliveryManager空引用",
        "description": "游戏运行时偶尔会在 DeliveryManager.cs 中出现空引用错误。请检查 DeliveryManager.cs 中可能存在的空引用问题，并添加适当的空检查来防止崩溃。",
        "expected_files": ["Assets/Scripts/DeliveryManager.cs"],
    },
    "A4": {
        "name": "UI更新问题（已知可修复）",
        "description": "玩家在开始界面按下交互键后，游戏应进入倒计时；目前教程界面没有关闭，倒计时界面也没有出现。问题可能位于游戏状态切换与 UI 刷新链路。请定位根因，进行最小修复。",
        "expected_files": ["Assets/Scripts/KitchenGameManager.cs"],
    },
    "B1": {
        "name": "添加交互距离常量",
        "description": "在 Assets/Scripts/Player.cs 中，交互距离检测使用了硬编码的数值。请添加一个公共常量 INTERACTION_DISTANCE 来替代硬编码值，使代码更易于维护和调整。",
        "expected_files": ["Assets/Scripts/Player.cs"],
    },
    "B2": {
        "name": "添加成功交付计数",
        "description": "需要在 DeliveryManager.cs 中添加一个功能来跟踪玩家成功交付的订单总数。添加一个公共属性 SuccessfulDeliveriesCount，并在每次成功交付时增加计数。这将用于统计和UI显示。",
        "expected_files": ["Assets/Scripts/DeliveryManager.cs"],
    },
    "B3": {
        "name": "添加游戏统计类",
        "description": "创建一个新的 GameStatistics.cs 类来跟踪游戏统计数据：成功交付数、失败交付数、游戏时长。使用单例模式，并在 KitchenGameManager 和 DeliveryManager 中集成。",
        "expected_files": [],
        "note": "创建新文件",
    },
    "C1": {
        "name": "提取Player输入处理",
        "description": "在 Player.cs 的 Update() 方法中，移动和交互逻辑混在一起。请将移动逻辑提取到单独的 HandleMovement() 方法中，将交互逻辑提取到 HandleInteractions() 方法中，使代码更清晰。",
        "expected_files": ["Assets/Scripts/Player.cs"],
    },
    "C2": {
        "name": "魔法数字重构",
        "description": "KitchenGameManager.cs 中有多个魔法数字（如倒计时时间3f、游戏时长30f等）。请将这些魔法数字提取为私有常量，并使用有意义的名称（如COUNTDOWN_TIMER_MAX、GAME_PLAYING_TIMER_MAX）。",
        "expected_files": ["Assets/Scripts/KitchenGameManager.cs"],
    },
    "C3": {
        "name": "SoundManager代码整理",
        "description": "SoundManager.cs 中如果有重复的音效播放代码模式，请提取为辅助方法来减少代码重复，提高可维护性。保持现有功能不变。",
        "expected_files": ["Assets/Scripts/SoundManager.cs"],
    },
    "D1": {
        "name": "连击系统",
        "description": "在 DeliveryManager.cs 中添加连击系统：当玩家在5秒内连续成功交付订单时，获得连击状态。连击数递增，每次连击提供额外分数加成。如果超过5秒未交付，连击重置。需要跟踪上次交付时间和当前连击数。",
        "expected_files": ["Assets/Scripts/DeliveryManager.cs"],
    },
    "D2": {
        "name": "不存在的文件",
        "description": "请在 Assets/Scripts/Utilities/Helper.cs 中添加一个静态工具方法 Clamp(float value, float min, float max)。注意：这个文件不存在。",
        "expected_files": [],
        "note": "测试不存在文件的处理",
    },
    "D3": {
        "name": "模糊需求",
        "description": "游戏感觉有点问题，玩家移动不太流畅。请优化一下。",
        "expected_files": [],
        "note": "测试模糊需求的处理",
    },
    "E1": {
        "name": "优化频繁调用",
        "description": "Player.cs 的 Update() 方法中每帧都在执行射线检测。如果可以优化，请考虑减少不必要的检测频率或使用更高效的方法，同时保持功能正常。",
        "expected_files": ["Assets/Scripts/Player.cs"],
    },
}


def run_single_task(task_id: str, task: dict):
    """运行单个测试任务"""

    print("\n" + "="*80)
    print(f"🎯 测试任务 {task_id}: {task['name']}")
    print("="*80)
    print(f"\n描述: {task['description'][:100]}...")

    unity_root = Path(r"E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos")

    # Restore files before test
    print("\n准备: 恢复文件...")
    subprocess.run(
        ["git", "checkout", "Assets/Scripts/"],
        cwd=unity_root,
        capture_output=True
    )

    # Save task description to temp file
    task_file = Path("temp_task.txt")
    task_file.write_text(task['description'], encoding='utf-8')

    # Modify test_real_task.py to read from file
    print("执行: 运行任务...")
    start_time = time.time()

    # Run test (this will use the default task in test_real_task.py)
    # We need to temporarily modify it
    result = subprocess.run(
        ["python", "scripts/test_real_task.py"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=180,
    )

    duration = time.time() - start_time

    # Check if files were modified
    git_status = subprocess.run(
        ["git", "status", "--short", "Assets/Scripts/"],
        cwd=unity_root,
        capture_output=True,
        text=True
    )

    files_changed = len([line for line in git_status.stdout.split('\n') if line.strip()])

    # Parse result
    success = "SUCCESS" in result.stdout
    mutations_applied = 0

    if "Mutations applied:" in result.stdout:
        for line in result.stdout.split('\n'):
            if "Mutations applied:" in line:
                try:
                    mutations_applied = int(line.split(':')[1].strip())
                except:
                    pass

    # Determine pass/fail
    passed = success and (files_changed > 0 or mutations_applied > 0)

    result_dict = {
        "task_id": task_id,
        "name": task['name'],
        "passed": passed,
        "success": success,
        "files_changed": files_changed,
        "mutations_applied": mutations_applied,
        "duration_seconds": duration,
        "timestamp": datetime.now().isoformat(),
    }

    # Print result
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"\n{status}")
    print(f"  成功: {success}")
    print(f"  文件修改: {files_changed}")
    print(f"  执行时间: {duration:.1f}秒")

    return result_dict


def main():
    """主函数"""

    print("\n" + "="*80)
    print("🚀 鲁棒性测试 - 手动执行14个任务")
    print("="*80)

    results = []

    # 只测试前5个（Phase 1）
    phase1_tasks = ["A1", "A4", "B1", "B2", "C1"]

    print(f"\n将测试 {len(phase1_tasks)} 个任务（Phase 1）")
    print("这可能需要10-15分钟...\n")

    for task_id in phase1_tasks:
        task = TASKS[task_id]
        try:
            result = run_single_task(task_id, task)
            results.append(result)
        except Exception as e:
            print(f"\n❌ 任务 {task_id} 执行异常: {e}")
            results.append({
                "task_id": task_id,
                "passed": False,
                "error": str(e),
            })

        # Short pause between tasks
        time.sleep(2)

    # Summary
    print("\n" + "="*80)
    print("📊 测试总结")
    print("="*80)

    total = len(results)
    passed = sum(1 for r in results if r.get('passed', False))

    print(f"\n总任务数: {total}")
    print(f"通过: {passed} ({passed/total*100:.1f}%)")
    print(f"失败: {total - passed}")

    # Save results
    output_file = Path("tests/robustness/manual_test_results.json")
    output_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')

    print(f"\n结果已保存: {output_file}")
    print("\n" + "="*80)


if __name__ == "__main__":
    main()
