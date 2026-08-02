"""
批量运行所有14个任务并收集详细的metrics数据
包括token消耗、成功率、各阶段性能等
"""
import subprocess
import time
import json
from pathlib import Path
from collections import defaultdict

# 任务列表
TASKS = [
    "A1", "A2", "A3", "A4",  # P0 Bug修复
    "B1", "B2", "B3",         # P0/P1 功能添加
    "C1", "C2", "C3",         # P1/P2 重构
    "D1", "D2", "D3",         # P2 复杂功能/边界情况
    "E1"                      # P2 性能优化
]

results_dir = Path("E:/sysu-course/GameAgent/tests/robustness/results")
script_path = Path("E:/sysu-course/GameAgent/tests/robustness/run_task.py")

print("=" * 80)
print("开始运行所有14个任务并收集metrics")
print("=" * 80)
print()

start_time = time.time()
completed = 0
failed = 0

for task_id in TASKS:
    print(f"\n{'='*80}")
    print(f"运行任务 {task_id} ({TASKS.index(task_id) + 1}/{len(TASKS)})")
    print(f"{'='*80}\n")

    try:
        # 运行任务
        result = subprocess.run(
            ["python", str(script_path), task_id],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=180,  # 3分钟超时
        )

        if result.returncode == 0:
            completed += 1
            print(f"✓ 任务 {task_id} 完成")
        else:
            failed += 1
            print(f"✗ 任务 {task_id} 失败")
            print(f"错误: {result.stderr[:200]}")

    except subprocess.TimeoutExpired:
        failed += 1
        print(f"✗ 任务 {task_id} 超时")
    except Exception as e:
        failed += 1
        print(f"✗ 任务 {task_id} 异常: {e}")

    # 短暂延迟避免资源竞争
    time.sleep(2)

elapsed = time.time() - start_time

print(f"\n{'='*80}")
print(f"批量运行完成")
print(f"{'='*80}")
print(f"总任务数: {len(TASKS)}")
print(f"已完成: {completed}")
print(f"失败: {failed}")
print(f"总用时: {elapsed:.1f}秒 ({elapsed/60:.1f}分钟)")
print()

# 收集所有最新结果
print("收集结果和metrics...")
print()

latest_results = {}
for task_id in TASKS:
    # 找到该任务的最新结果文件
    task_results = sorted(results_dir.glob(f"result_{task_id}_*.json"))
    if task_results:
        latest_file = task_results[-1]
        with open(latest_file, 'r', encoding='utf-8') as f:
            latest_results[task_id] = json.load(f)

# 统计分析
print(f"\n{'='*80}")
print("Metrics分析")
print(f"{'='*80}\n")

# 按优先级分组
by_priority = defaultdict(list)
by_complexity = defaultdict(list)

for task_id, data in latest_results.items():
    by_priority[data['priority']].append((task_id, data))
    by_complexity[data.get('complexity', 'unknown')].append((task_id, data))

# 成功率统计
total = len(latest_results)
success = sum(1 for d in latest_results.values() if d['overall_success'])
print(f"总体成功率: {success}/{total} ({success/total*100:.1f}%)")
print()

# 按优先级统计
print("按优先级分组:")
for priority in ['P0', 'P1', 'P2']:
    tasks = by_priority.get(priority, [])
    if tasks:
        success_count = sum(1 for _, d in tasks if d['overall_success'])
        avg_time = sum(d['elapsed_time'] for _, d in tasks) / len(tasks)
        avg_tokens = sum(d['total_tokens'] for _, d in tasks) / len(tasks)
        print(f"  {priority}: {success_count}/{len(tasks)} 成功 ({success_count/len(tasks)*100:.1f}%)")
        print(f"    平均时间: {avg_time:.1f}秒")
        print(f"    平均tokens: {avg_tokens:,.0f}")
print()

# 按复杂度统计
print("按复杂度分组:")
for complexity in ['simple', 'medium', 'complex', 'unknown']:
    tasks = by_complexity.get(complexity, [])
    if tasks:
        success_count = sum(1 for _, d in tasks if d['overall_success'])
        avg_time = sum(d['elapsed_time'] for _, d in tasks) / len(tasks)
        avg_tokens = sum(d['total_tokens'] for _, d in tasks) / len(tasks)
        print(f"  {complexity.capitalize()}: {success_count}/{len(tasks)} 成功")
        print(f"    平均时间: {avg_time:.1f}秒")
        print(f"    平均tokens: {avg_tokens:,.0f}")
print()

# Token消耗详细分析
print(f"{'='*80}")
print("Token消耗详细分析")
print(f"{'='*80}\n")

print(f"{'任务':<8} {'类型':<15} {'优先级':<6} {'复杂度':<8} {'Tokens':<10} {'时间(s)':<8} {'状态':<6}")
print("-" * 80)

for task_id in TASKS:
    if task_id in latest_results:
        data = latest_results[task_id]
        task_type = data['task_type'].replace('_', ' ')[:14]
        tokens = data['total_tokens']
        elapsed = data['elapsed_time']
        status = "✓✓✓" if data['overall_success'] else "✓" if data['success'] else "✗✗✗"

        print(f"{task_id:<8} {task_type:<15} {data['priority']:<6} "
              f"{data.get('complexity', 'N/A'):<8} {tokens:<10,} {elapsed:<8.2f} {status:<6}")

print("-" * 80)
print()

# Token消耗统计
all_tokens = [d['total_tokens'] for d in latest_results.values()]
if all_tokens:
    print("Token消耗统计:")
    print(f"  总计: {sum(all_tokens):,} tokens")
    print(f"  平均: {sum(all_tokens)/len(all_tokens):,.0f} tokens/task")
    print(f"  最小: {min(all_tokens):,} tokens")
    print(f"  最大: {max(all_tokens):,} tokens")
    print(f"  中位数: {sorted(all_tokens)[len(all_tokens)//2]:,} tokens")
print()

# 时间消耗统计
all_times = [d['elapsed_time'] for d in latest_results.values()]
if all_times:
    print("时间消耗统计:")
    print(f"  总计: {sum(all_times):.1f}秒 ({sum(all_times)/60:.1f}分钟)")
    print(f"  平均: {sum(all_times)/len(all_times):.1f}秒/task")
    print(f"  最小: {min(all_times):.1f}秒")
    print(f"  最大: {max(all_times):.1f}秒")
print()

# 失败任务分析
failed_tasks = [(tid, d) for tid, d in latest_results.items() if not d['overall_success']]
if failed_tasks:
    print(f"{'='*80}")
    print(f"失败任务详情 ({len(failed_tasks)}个)")
    print(f"{'='*80}\n")

    for task_id, data in failed_tasks:
        print(f"任务 {task_id}: {data['task_name']}")
        print(f"  Tokens: {data['total_tokens']:,} (预算: {data['criteria_check']['token_budget']['budget']:,})")
        print(f"  时间: {data['elapsed_time']:.2f}秒 (预算: {data['criteria_check']['time_budget']['budget']}秒)")
        print(f"  Mutations: {data['mutations_applied']} (需要: {data['criteria_check']['min_mutations']['required']})")

        criteria = data['criteria_check']
        if not criteria['min_mutations']['met']:
            print(f"    ❌ Mutations不足")
        if not criteria['token_budget']['met']:
            print(f"    ❌ Token超出预算")
        if not criteria['time_budget']['met']:
            print(f"    ❌ 超时")
        print()

print(f"{'='*80}")
print("所有任务执行完成！")
print(f"{'='*80}\n")

# 保存汇总数据
summary_file = results_dir / "metrics_summary.json"
summary = {
    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    "total_tasks": len(TASKS),
    "completed": completed,
    "failed": failed,
    "total_elapsed": elapsed,
    "success_rate": success / total if total > 0 else 0,
    "token_stats": {
        "total": sum(all_tokens) if all_tokens else 0,
        "average": sum(all_tokens) / len(all_tokens) if all_tokens else 0,
        "min": min(all_tokens) if all_tokens else 0,
        "max": max(all_tokens) if all_tokens else 0,
        "median": sorted(all_tokens)[len(all_tokens)//2] if all_tokens else 0,
    },
    "time_stats": {
        "total": sum(all_times) if all_times else 0,
        "average": sum(all_times) / len(all_times) if all_times else 0,
        "min": min(all_times) if all_times else 0,
        "max": max(all_times) if all_times else 0,
    },
    "by_priority": {
        priority: {
            "total": len(tasks),
            "success": sum(1 for _, d in tasks if d['overall_success']),
            "avg_tokens": sum(d['total_tokens'] for _, d in tasks) / len(tasks) if tasks else 0,
            "avg_time": sum(d['elapsed_time'] for _, d in tasks) / len(tasks) if tasks else 0,
        }
        for priority, tasks in by_priority.items()
    },
    "by_complexity": {
        complexity: {
            "total": len(tasks),
            "success": sum(1 for _, d in tasks if d['overall_success']),
            "avg_tokens": sum(d['total_tokens'] for _, d in tasks) / len(tasks) if tasks else 0,
            "avg_time": sum(d['elapsed_time'] for _, d in tasks) / len(tasks) if tasks else 0,
        }
        for complexity, tasks in by_complexity.items()
    },
}

with open(summary_file, 'w', encoding='utf-8') as f:
    json.dump(summary, f, indent=2, ensure_ascii=False)

print(f"Metrics汇总已保存到: {summary_file}")
