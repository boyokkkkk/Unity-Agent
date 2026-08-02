"""
端到端鲁棒性验证脚本
逐个执行14个测试任务，记录详细结果
"""
import json
import sys
import time
from pathlib import Path
from datetime import datetime

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from game_agent_try.agents.coordinator import CoordinatorAgent
from game_agent_try.framework.models.litellm_model import LiteLLMModel


def load_test_tasks():
    """加载测试任务"""
    tasks_file = Path(__file__).parent / "test_tasks_real.json"
    with open(tasks_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def execute_single_task(task_id, task_config, output_dir):
    """
    执行单个测试任务

    Returns:
        dict: 执行结果统计
    """
    print(f"\n{'='*80}")
    print(f"开始任务: {task_id} - {task_config['name']}")
    print(f"类型: {task_config['type']}")
    print(f"复杂度: {task_config.get('expected_complexity', 'unknown')}")
    print(f"优先级: {task_config['priority']}")
    print(f"{'='*80}\n")

    start_time = time.time()

    try:
        # 初始化模型和Agent
        model = LiteLLMModel(
            model_name="gpt-4o",
            temperature=0.0,
            timeout=300
        )

        agent = CoordinatorAgent(
            model=model,
            project_root=str(project_root / "UnityKitchenChaos"),
            max_iterations=10
        )

        # 执行任务
        print(f"执行任务描述: {task_config['description']}\n")
        result = agent.execute(task_config['description'])

        elapsed_time = time.time() - start_time

        # 提取执行结果
        if hasattr(result, 'success'):
            success = result.success
            mutations_applied = result.mutations_applied if hasattr(result, 'mutations_applied') else 0
            total_tokens = result.total_tokens if hasattr(result, 'total_tokens') else 0
            error_message = result.error if hasattr(result, 'error') else None
        elif isinstance(result, dict):
            success = result.get('success', False)
            mutations_applied = result.get('mutations_applied', 0)
            total_tokens = result.get('total_tokens', 0)
            error_message = result.get('error')
        else:
            success = False
            mutations_applied = 0
            total_tokens = 0
            error_message = f"Unknown result type: {type(result)}"

        # 检查成功标准
        criteria = task_config.get('success_criteria', {})
        meets_criteria = True
        criteria_details = {}

        if 'min_mutations' in criteria:
            meets_min_mutations = mutations_applied >= criteria['min_mutations']
            criteria_details['mutations'] = {
                'required': criteria['min_mutations'],
                'actual': mutations_applied,
                'met': meets_min_mutations
            }
            meets_criteria = meets_criteria and meets_min_mutations

        if 'token_budget' in criteria:
            within_token_budget = total_tokens <= criteria['token_budget']
            criteria_details['tokens'] = {
                'budget': criteria['token_budget'],
                'actual': total_tokens,
                'met': within_token_budget
            }
            meets_criteria = meets_criteria and within_token_budget

        if 'time_budget_seconds' in criteria:
            within_time_budget = elapsed_time <= criteria['time_budget_seconds']
            criteria_details['time'] = {
                'budget': criteria['time_budget_seconds'],
                'actual': round(elapsed_time, 2),
                'met': within_time_budget
            }
            meets_criteria = meets_criteria and within_time_budget

        # 构建结果
        task_result = {
            'task_id': task_id,
            'name': task_config['name'],
            'type': task_config['type'],
            'priority': task_config['priority'],
            'complexity': task_config.get('expected_complexity', 'unknown'),
            'success': success,
            'meets_criteria': meets_criteria,
            'execution_time': round(elapsed_time, 2),
            'mutations_applied': mutations_applied,
            'total_tokens': total_tokens,
            'criteria_details': criteria_details,
            'error': error_message
        }

        # 打印结果摘要
        print(f"\n{'-'*80}")
        print(f"任务 {task_id} 完成:")
        print(f"  执行状态: {'✓ 成功' if success else '✗ 失败'}")
        print(f"  满足标准: {'✓ 是' if meets_criteria else '✗ 否'}")
        print(f"  执行时间: {elapsed_time:.2f}s")
        print(f"  Mutations: {mutations_applied}")
        print(f"  Tokens: {total_tokens}")
        if error_message:
            print(f"  错误: {error_message}")
        print(f"{'-'*80}\n")

        return task_result

    except Exception as e:
        elapsed_time = time.time() - start_time
        error_msg = str(e)
        print(f"\n✗ 任务 {task_id} 失败: {error_msg}\n")

        return {
            'task_id': task_id,
            'name': task_config['name'],
            'type': task_config['type'],
            'priority': task_config['priority'],
            'complexity': task_config.get('expected_complexity', 'unknown'),
            'success': False,
            'meets_criteria': False,
            'execution_time': round(elapsed_time, 2),
            'mutations_applied': 0,
            'total_tokens': 0,
            'criteria_details': {},
            'error': error_msg
        }


def main():
    """主函数"""
    print("="*80)
    print("GameAgent 鲁棒性端到端验证")
    print("="*80)

    # 创建输出目录
    output_dir = Path(__file__).parent / "results"
    output_dir.mkdir(exist_ok=True)

    # 加载测试任务
    all_tasks = load_test_tasks()

    print(f"\n加载了 {len(all_tasks)} 个测试任务\n")

    # 询问用户要执行哪些任务
    print("可用任务:")
    for task_id, config in all_tasks.items():
        print(f"  {task_id}: {config['name']} ({config['type']})")

    print("\n选择执行模式:")
    print("  1. 执行所有任务")
    print("  2. 执行特定任务")
    print("  3. 按类型执行")

    choice = input("\n请输入选择 (1/2/3) [默认: 1]: ").strip() or "1"

    tasks_to_run = {}

    if choice == "1":
        tasks_to_run = all_tasks
    elif choice == "2":
        task_ids = input("请输入任务ID (逗号分隔, 如 A1,A2,B1): ").strip().split(',')
        tasks_to_run = {tid.strip(): all_tasks[tid.strip()] for tid in task_ids if tid.strip() in all_tasks}
    elif choice == "3":
        task_type = input("请输入任务类型 (bug_fix/feature_addition/refactoring/performance/edge_case): ").strip()
        tasks_to_run = {tid: cfg for tid, cfg in all_tasks.items() if cfg['type'] == task_type}

    if not tasks_to_run:
        print("没有选择任何任务！")
        return

    print(f"\n将执行 {len(tasks_to_run)} 个任务\n")
    time.sleep(2)

    # 执行任务
    results = []
    for task_id, task_config in tasks_to_run.items():
        result = execute_single_task(task_id, task_config, output_dir)
        results.append(result)

        # 保存中间结果
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        intermediate_file = output_dir / f"results_progress_{timestamp}.json"
        with open(intermediate_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    # 生成最终报告
    generate_report(results, output_dir)


def generate_report(results, output_dir):
    """生成测试报告"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 统计
    total = len(results)
    successful = sum(1 for r in results if r['success'])
    meets_criteria = sum(1 for r in results if r['meets_criteria'])

    by_type = {}
    for r in results:
        task_type = r['type']
        if task_type not in by_type:
            by_type[task_type] = {'total': 0, 'success': 0, 'meets_criteria': 0}
        by_type[task_type]['total'] += 1
        if r['success']:
            by_type[task_type]['success'] += 1
        if r['meets_criteria']:
            by_type[task_type]['meets_criteria'] += 1

    # 生成报告
    report = {
        'timestamp': timestamp,
        'summary': {
            'total_tasks': total,
            'successful': successful,
            'meets_criteria': meets_criteria,
            'success_rate': f"{successful/total*100:.1f}%" if total > 0 else "0%",
            'criteria_rate': f"{meets_criteria/total*100:.1f}%" if total > 0 else "0%"
        },
        'by_type': by_type,
        'detailed_results': results
    }

    # 保存JSON
    report_file = output_dir / f"report_{timestamp}.json"
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # 生成Markdown报告
    md_file = output_dir / f"report_{timestamp}.md"
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write(f"# GameAgent 鲁棒性测试报告\n\n")
        f.write(f"**生成时间:** {timestamp}\n\n")

        f.write("## 总体统计\n\n")
        f.write(f"- **总任务数:** {total}\n")
        f.write(f"- **成功执行:** {successful} ({successful/total*100:.1f}%)\n")
        f.write(f"- **满足标准:** {meets_criteria} ({meets_criteria/total*100:.1f}%)\n\n")

        f.write("## 按类型统计\n\n")
        f.write("| 类型 | 总数 | 成功 | 满足标准 | 成功率 |\n")
        f.write("|------|------|------|----------|--------|\n")
        for task_type, stats in by_type.items():
            success_rate = stats['success'] / stats['total'] * 100 if stats['total'] > 0 else 0
            f.write(f"| {task_type} | {stats['total']} | {stats['success']} | {stats['meets_criteria']} | {success_rate:.1f}% |\n")

        f.write("\n## 详细结果\n\n")
        for r in results:
            status_icon = "✓" if r['success'] else "✗"
            criteria_icon = "✓" if r['meets_criteria'] else "✗"

            f.write(f"### {r['task_id']}: {r['name']}\n\n")
            f.write(f"- **类型:** {r['type']}\n")
            f.write(f"- **优先级:** {r['priority']}\n")
            f.write(f"- **复杂度:** {r['complexity']}\n")
            f.write(f"- **执行状态:** {status_icon} {'成功' if r['success'] else '失败'}\n")
            f.write(f"- **满足标准:** {criteria_icon} {'是' if r['meets_criteria'] else '否'}\n")
            f.write(f"- **执行时间:** {r['execution_time']}s\n")
            f.write(f"- **Mutations:** {r['mutations_applied']}\n")
            f.write(f"- **Tokens:** {r['total_tokens']}\n")

            if r['criteria_details']:
                f.write(f"\n**标准检查:**\n")
                for key, details in r['criteria_details'].items():
                    met_icon = "✓" if details['met'] else "✗"
                    f.write(f"- {met_icon} {key}: {details.get('actual', 'N/A')} / {details.get('budget', details.get('required', 'N/A'))}\n")

            if r.get('error'):
                f.write(f"\n**错误信息:** {r['error']}\n")

            f.write("\n---\n\n")

    print(f"\n{'='*80}")
    print("测试完成！")
    print(f"{'='*80}")
    print(f"\n总结:")
    print(f"  总任务: {total}")
    print(f"  成功: {successful} ({successful/total*100:.1f}%)")
    print(f"  满足标准: {meets_criteria} ({meets_criteria/total*100:.1f}%)")
    print(f"\n报告已保存:")
    print(f"  JSON: {report_file}")
    print(f"  Markdown: {md_file}\n")


if __name__ == "__main__":
    main()
