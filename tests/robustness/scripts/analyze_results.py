"""
收集所有任务结果并生成汇总报告
"""
import json
from pathlib import Path
from collections import defaultdict

results_dir = Path("E:/sysu-course/GameAgent/tests/robustness/results")

# 获取每个任务ID的最新结果
latest_results = {}
for result_file in results_dir.glob("result_*.json"):
    with open(result_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        task_id = data['task_id']
        timestamp = data['timestamp']

        if task_id not in latest_results or timestamp > latest_results[task_id]['timestamp']:
            latest_results[task_id] = data

# 按任务ID排序
sorted_tasks = sorted(latest_results.items(), key=lambda x: x[0])

print("=" * 80)
print("鲁棒性测试汇总报告")
print("=" * 80)
print()

# 统计
total = len(sorted_tasks)
success_count = sum(1 for _, data in sorted_tasks if data['overall_success'])
partial_success = sum(1 for _, data in sorted_tasks if data['success'] and not data['overall_success'])
failed = total - success_count - partial_success

print(f"总任务数: {total}")
print(f"完全成功: {success_count} ({success_count/total*100:.1f}%)")
print(f"部分成功: {partial_success} ({partial_success/total*100:.1f}%)")
print(f"失败: {failed} ({failed/total*100:.1f}%)")
print()

# 按优先级分组
by_priority = defaultdict(list)
for task_id, data in sorted_tasks:
    by_priority[data['priority']].append((task_id, data))

print("按优先级分组:")
for priority in ['P0', 'P1', 'P2']:
    tasks = by_priority[priority]
    if tasks:
        success = sum(1 for _, d in tasks if d['overall_success'])
        print(f"  {priority}: {success}/{len(tasks)} 成功 ({success/len(tasks)*100:.1f}%)")
print()

# 详细结果
print("详细结果:")
print("-" * 80)
print(f"{'任务':<8} {'类型':<15} {'优先级':<6} {'复杂度':<8} {'状态':<6} {'Muts':<5} {'时间(s)':<8}")
print("-" * 80)

for task_id, data in sorted_tasks:
    status = "✓✓✓" if data['overall_success'] else ("✓" if data['success'] else "✗✗✗")
    task_type = data['task_type'].replace('_', ' ')[:14]
    print(f"{task_id:<8} {task_type:<15} {data['priority']:<6} {data['complexity']:<8} "
          f"{status:<6} {data['mutations_applied']:<5} {data['elapsed_time']:<8.2f}")

print("-" * 80)
print()

# 失败任务详情
failed_tasks = [(tid, d) for tid, d in sorted_tasks if not d['overall_success']]
if failed_tasks:
    print(f"失败任务详情 ({len(failed_tasks)}个):")
    print("-" * 80)
    for task_id, data in failed_tasks:
        print(f"\n任务 {task_id}: {data['task_name']}")
        print(f"  原因: {data.get('error', 'Mutations不足或超时')}")
        print(f"  Mutations: {data['mutations_applied']} (需要 >= {data['criteria_check']['min_mutations']['required']})")
        print(f"  时间: {data['elapsed_time']:.2f}s (预算 {data['criteria_check']['time_budget']['budget']}s)")

        # 检查具体失败原因
        criteria = data['criteria_check']
        if not criteria['min_mutations']['met']:
            print(f"    ❌ Mutations不足")
        if not criteria['time_budget']['met']:
            print(f"    ❌ 超时")
print()

print("=" * 80)
