"""
单个任务执行脚本
参照 test_e2e_coordinator.py 的成功配置
"""
import json
import sys
import time
from pathlib import Path
from datetime import datetime
import os

# 添加项目根目录
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# 加载.env文件
from dotenv import load_dotenv
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"✓ 已加载环境变量: {env_path}\n")

from game_agent_try.agents import CoordinatorAgent
from game_agent_try.context import ContextAssembler, ContextConfig
from game_agent_try.framework.models import get_model


def run_single_task(task_id):
    """执行单个任务"""
    # 加载任务配置
    tasks_file = Path(__file__).parent / "test_tasks_real.json"
    with open(tasks_file, 'r', encoding='utf-8') as f:
        all_tasks = json.load(f)

    if task_id not in all_tasks:
        print(f"错误: 任务 {task_id} 不存在")
        return None

    task = all_tasks[task_id]

    print(f"\n{'='*80}")
    print(f"任务: {task_id} - {task['name']}")
    print(f"类型: {task['type']}")
    print(f"复杂度: {task.get('expected_complexity', 'unknown')}")
    print(f"优先级: {task['priority']}")
    print(f"描述: {task['description']}")
    print(f"{'='*80}\n")

    start_time = time.time()

    try:
        # Unity项目路径
        unity_project_root = Path("E:/Unity_project/Kitchen_Chaos/Kitchen_Chaos")
        if not unity_project_root.exists():
            print(f"✗ Unity项目不存在: {unity_project_root}")
            return None

        # 项目图路径
        graph_path = Path("E:/sysu-course/GameAgent/artifacts/project-graph/kitchen-chaos-full/project-graph.json")
        if not graph_path.exists():
            print(f"✗ 项目图不存在: {graph_path}")
            return None

        print(f"Unity项目: {unity_project_root}")
        print(f"项目图: {graph_path}\n")

        # 初始化模型 (使用.env中的配置)
        print("初始化模型...")
        model_config = {
            "model_class": "litellm",
            "cost_tracking": "ignore_errors",
            "model_kwargs": {
                "drop_params": True,
                "api_base": os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                "temperature": 0.0,
                "max_tokens": 8192,
            },
        }

        model = get_model("openai/qwen-plus", model_config)
        print("✓ 模型初始化成功\n")

        # 初始化上下文
        print("初始化上下文...")
        context_config = ContextConfig(
            enabled=True,
            graph_path=str(graph_path),
        )

        context = ContextAssembler(
            context_config,
            project_root=unity_project_root,
        )
        print("✓ 上下文初始化成功\n")

        # 初始化Coordinator
        print("初始化 CoordinatorAgent...")
        coordinator = CoordinatorAgent(
            model=model,
            context=context,
            project_root=unity_project_root,
        )
        print("✓ Coordinator初始化成功\n")

        # 执行任务
        print(f"开始执行任务...\n")
        print("-" * 80)

        result = coordinator.run_task(task['description'])

        print("-" * 80)
        elapsed = time.time() - start_time

        # 解析结果
        if hasattr(result, '__dict__'):
            result_dict = vars(result)
        elif isinstance(result, dict):
            result_dict = result
        else:
            result_dict = {'raw_result': str(result)}

        success = result_dict.get('success', False)
        mutations = result_dict.get('mutations_applied', 0)
        tokens = result_dict.get('total_tokens', 0)
        error = result_dict.get('error')

        # 打印结果
        print(f"\n{'='*80}")
        print(f"任务 {task_id} 完成")
        print(f"{'='*80}")
        print(f"状态: {'✓ 成功' if success else '✗ 失败'}")
        print(f"用时: {elapsed:.2f}s")
        print(f"Mutations: {mutations}")
        print(f"Tokens: {tokens}")

        if error:
            print(f"错误: {error}")

        # 检查成功标准
        criteria = task.get('success_criteria', {})
        print(f"\n标准检查:")

        meets_all = True

        if 'min_mutations' in criteria:
            met = mutations >= criteria['min_mutations']
            meets_all = meets_all and met
            print(f"  {'✓' if met else '✗'} Mutations: {mutations} >= {criteria['min_mutations']}")

        if 'token_budget' in criteria:
            met = tokens <= criteria['token_budget']
            meets_all = meets_all and met
            print(f"  {'✓' if met else '✗'} Tokens: {tokens} <= {criteria['token_budget']}")

        if 'time_budget_seconds' in criteria:
            met = elapsed <= criteria['time_budget_seconds']
            meets_all = meets_all and met
            print(f"  {'✓' if met else '✗'} Time: {elapsed:.2f}s <= {criteria['time_budget_seconds']}s")

        overall_success = success and meets_all

        print(f"\n{'='*80}")
        print(f"整体结果: {'✓✓✓ 成功通过' if overall_success else '✗✗✗ 未通过'}")
        print(f"{'='*80}\n")

        # 保存结果
        results_dir = Path(__file__).parent / "results"
        results_dir.mkdir(exist_ok=True)

        result_data = {
            'task_id': task_id,
            'task_name': task['name'],
            'task_type': task['type'],
            'priority': task['priority'],
            'complexity': task.get('expected_complexity', 'unknown'),
            'timestamp': datetime.now().isoformat(),
            'success': success,
            'meets_all_criteria': meets_all,
            'overall_success': overall_success,
            'elapsed_time': elapsed,
            'mutations_applied': mutations,
            'total_tokens': tokens,
            'error': error,
            'criteria_check': {
                'min_mutations': {
                    'required': criteria.get('min_mutations'),
                    'actual': mutations,
                    'met': mutations >= criteria['min_mutations'] if 'min_mutations' in criteria else None
                },
                'token_budget': {
                    'budget': criteria.get('token_budget'),
                    'actual': tokens,
                    'met': tokens <= criteria['token_budget'] if 'token_budget' in criteria else None
                },
                'time_budget': {
                    'budget': criteria.get('time_budget_seconds'),
                    'actual': elapsed,
                    'met': elapsed <= criteria['time_budget_seconds'] if 'time_budget_seconds' in criteria else None
                }
            }
        }

        result_file = results_dir / f"result_{task_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result_data, f, indent=2, ensure_ascii=False)

        print(f"结果已保存: {result_file}\n")

        return result_data

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n{'='*80}")
        print(f"✗✗✗ 执行失败")
        print(f"{'='*80}")
        print(f"错误: {str(e)}\n")
        import traceback
        traceback.print_exc()

        return {
            'task_id': task_id,
            'task_name': task['name'],
            'timestamp': datetime.now().isoformat(),
            'success': False,
            'meets_all_criteria': False,
            'overall_success': False,
            'elapsed_time': elapsed,
            'mutations_applied': 0,
            'total_tokens': 0,
            'error': str(e)
        }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python run_task.py <task_id>")
        print("\n可用任务:")

        tasks_file = Path(__file__).parent / "test_tasks_real.json"
        with open(tasks_file, 'r', encoding='utf-8') as f:
            all_tasks = json.load(f)

        for tid, task in all_tasks.items():
            print(f"  {tid}: {task['name']} ({task['type']})")

        sys.exit(1)

    task_id = sys.argv[1]
    run_single_task(task_id)
