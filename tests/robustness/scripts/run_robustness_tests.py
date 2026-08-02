"""
Robustness Test Suite Runner

运行多样化任务测试系统鲁棒性。
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

# Add project to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

from dotenv import load_dotenv
load_dotenv()

from game_agent_try.agents.coordinator import CoordinatorAgent
from game_agent_try.context import ContextAssembler
from game_agent_try.framework.models.litellm_model import LitellmModel

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('robustness_test.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class RobustnessTestRunner:
    """运行鲁棒性测试套件"""

    def __init__(self, unity_project_root: str = r"E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos"):
        self.unity_project_root = Path(unity_project_root)
        self.results = []
        self.tasks = self._load_tasks()

        # Initialize model and context once
        self.model = LitellmModel(
            model_name="openai/deepseek-v3",
            temperature=0.3,
            cost_tracking="ignore_errors",
            api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
            drop_params=True,
        )

        # Initialize context
        graph_path = Path("E:/sysu-course/GameAgent/artifacts/project-graph/kitchen-chaos-causal-full/project-graph.json")
        if graph_path.exists():
            self.context = ContextAssembler(
                project_root=self.unity_project_root,
                config={"enabled": True, "graph_path": str(graph_path)},
            )
        else:
            self.context = ContextAssembler(
                project_root=self.unity_project_root,
                config={"enabled": False},
            )

    def _load_tasks(self) -> Dict[str, Dict]:
        """加载测试任务配置"""
        tasks_file = Path(__file__).parent / "test_tasks_real.json"
        with open(tasks_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def run_single_test(self, task_id: str) -> Dict[str, Any]:
        """运行单个测试任务"""
        task = self.tasks[task_id]

        logger.info(f"\n{'='*80}")
        logger.info(f"Testing: {task_id} - {task['name']}")
        logger.info(f"Type: {task['type']} | Complexity: {task['expected_complexity']}")
        logger.info(f"{'='*80}\n")

        start_time = datetime.now()

        try:
            # Create coordinator
            coordinator = CoordinatorAgent(
                model=self.model,
                context=self.context,
                project_root=self.unity_project_root,
                artifact_root=self.unity_project_root / ".game-agent-artifacts",
            )

            # Execute task
            result = coordinator.run_task(task['description'])

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            # Convert ExecutionMetrics to dict for easier handling
            result_dict = {
                "success": result.success,
                "exploration_tokens": result.exploration_tokens,
                "total_tokens": result.total_tokens,
                "complexity_level": result.complexity_level.value if hasattr(result.complexity_level, 'value') else str(result.complexity_level),
                "execution_path": result.execution_path,
                "exit_status": result.exit_status,
                "duration_seconds": result.duration_seconds,
                "changed_paths": [],  # Need to extract from coordinator if available
                "mutations_applied": 0,  # Need to extract from coordinator if available
            }

            # Validate result
            validation = self._validate_result(task_id, task, result_dict, duration)

            return {
                "task_id": task_id,
                "success": validation["passed"],
                "result": result_dict,
                "validation": validation,
                "duration_seconds": duration,
                "timestamp": start_time.isoformat(),
            }

        except Exception as e:
            logger.error(f"Task {task_id} failed with exception: {e}")
            return {
                "task_id": task_id,
                "success": False,
                "error": str(e),
                "duration_seconds": (datetime.now() - start_time).total_seconds(),
                "timestamp": start_time.isoformat(),
            }

    def _validate_result(self, task_id: str, task: Dict, result: Dict, duration: float) -> Dict:
        """验证测试结果"""
        validation = {
            "passed": True,
            "checks": {},
            "issues": []
        }

        criteria = task.get("success_criteria", {})

        # Check complexity assessment
        expected_complexity = task.get("expected_complexity")
        actual_complexity = result.get("metrics", {}).get("complexity_level")
        complexity_match = str(actual_complexity).lower() == expected_complexity.lower()
        validation["checks"]["complexity_assessment"] = complexity_match
        if not complexity_match:
            validation["issues"].append(
                f"Complexity mismatch: expected {expected_complexity}, got {actual_complexity}"
            )

        # Check token budget
        token_budget = criteria.get("token_budget")
        if token_budget:
            actual_tokens = result.get("exploration_tokens", 0)
            within_budget = actual_tokens <= token_budget
            validation["checks"]["token_budget"] = within_budget
            if not within_budget:
                validation["issues"].append(
                    f"Token budget exceeded: {actual_tokens} > {token_budget}"
                )

        # Check execution time
        time_budget = criteria.get("time_budget_seconds")
        if time_budget:
            within_time = duration <= time_budget
            validation["checks"]["time_budget"] = within_time
            if not within_time:
                validation["issues"].append(
                    f"Time budget exceeded: {duration}s > {time_budget}s"
                )

        # Check files changed
        expected_files = criteria.get("files_changed")
        if expected_files:
            actual_files = len(result.get("changed_paths", []))
            files_match = actual_files == expected_files
            validation["checks"]["files_changed"] = files_match
            if not files_match:
                validation["issues"].append(
                    f"Files changed mismatch: expected {expected_files}, got {actual_files}"
                )

        # Check mutations applied
        min_mutations = criteria.get("min_mutations", 0)
        actual_mutations = result.get("mutations_applied", 0)
        mutations_ok = actual_mutations >= min_mutations
        validation["checks"]["mutations_applied"] = mutations_ok
        if not mutations_ok:
            validation["issues"].append(
                f"Insufficient mutations: {actual_mutations} < {min_mutations}"
            )

        # Overall pass/fail
        validation["passed"] = result.get("success", False) and len(validation["issues"]) == 0

        return validation

    def run_phase(self, phase: str) -> List[Dict]:
        """运行指定阶段的测试"""
        phase_tasks = {
            "phase1": ["A1", "A4", "B1", "B2", "C1"],  # P0 - 基础验证
            "phase2": ["A2", "A3", "C2", "C3", "B3"],  # P1 - 进阶验证
            "phase3": ["D1", "D2", "D3", "E1"],        # P2 - 压力测试和边界情况
        }

        task_ids = phase_tasks.get(phase, [])
        results = []

        logger.info(f"\n{'#'*80}")
        logger.info(f"Running {phase.upper()}: {len(task_ids)} tasks")
        logger.info(f"{'#'*80}\n")

        for task_id in task_ids:
            result = self.run_single_test(task_id)
            results.append(result)

            # Print immediate result
            status = "✅ PASS" if result["success"] else "❌ FAIL"
            logger.info(f"{status} - {task_id}: {result.get('duration_seconds', 0):.1f}s")

            if not result["success"] and "validation" in result:
                for issue in result["validation"].get("issues", []):
                    logger.warning(f"  ⚠️  {issue}")

        return results

    def run_all(self) -> Dict[str, Any]:
        """运行所有测试"""
        all_results = {
            "start_time": datetime.now().isoformat(),
            "phases": {},
            "summary": {}
        }

        for phase in ["phase1", "phase2", "phase3"]:
            phase_results = self.run_phase(phase)
            all_results["phases"][phase] = phase_results

        # Generate summary
        all_results["end_time"] = datetime.now().isoformat()
        all_results["summary"] = self._generate_summary(all_results["phases"])

        return all_results

    def _generate_summary(self, phases: Dict) -> Dict:
        """生成测试摘要"""
        all_results = []
        for phase_results in phases.values():
            all_results.extend(phase_results)

        total = len(all_results)
        passed = sum(1 for r in all_results if r["success"])
        failed = total - passed

        # By complexity
        by_complexity = {}
        for r in all_results:
            task_id = r["task_id"]
            if task_id in self.tasks:
                complexity = self.tasks[task_id].get("expected_complexity", "unknown")
                if complexity not in by_complexity:
                    by_complexity[complexity] = {"total": 0, "passed": 0}
                by_complexity[complexity]["total"] += 1
                if r["success"]:
                    by_complexity[complexity]["passed"] += 1

        # Average metrics
        durations = [r["duration_seconds"] for r in all_results if "duration_seconds" in r]
        tokens = [r.get("result", {}).get("exploration_tokens", 0) for r in all_results]

        return {
            "total_tasks": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / total if total > 0 else 0,
            "by_complexity": by_complexity,
            "avg_duration_seconds": sum(durations) / len(durations) if durations else 0,
            "avg_tokens": sum(tokens) / len(tokens) if tokens else 0,
            "failed_tasks": [r["task_id"] for r in all_results if not r["success"]],
        }


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="Run robustness tests")
    parser.add_argument("--phase", choices=["phase1", "phase2", "phase3", "all"],
                       default="phase1", help="Which phase to run")
    parser.add_argument("--task", type=str, help="Run single task by ID")
    parser.add_argument("--output", type=str, default="robustness_results.json",
                       help="Output file for results")

    args = parser.parse_args()

    runner = RobustnessTestRunner()

    if args.task:
        # Run single task
        result = runner.run_single_test(args.task)
        results = {"tasks": [result], "summary": runner._generate_summary({"single": [result]})}
    elif args.phase == "all":
        # Run all phases
        results = runner.run_all()
    else:
        # Run specific phase
        phase_results = runner.run_phase(args.phase)
        results = {"tasks": phase_results, "summary": runner._generate_summary({args.phase: phase_results})}

    # Save results
    output_path = Path(__file__).parent / args.output
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Print summary
    print(f"\n{'='*80}")
    print("TEST SUMMARY")
    print(f"{'='*80}")
    summary = results["summary"]
    print(f"Total Tasks:     {summary['total_tasks']}")
    print(f"Passed:          {summary['passed']} ({summary['pass_rate']*100:.1f}%)")
    print(f"Failed:          {summary['failed']}")
    print(f"Avg Duration:    {summary['avg_duration_seconds']:.1f}s")
    print(f"Avg Tokens:      {summary['avg_tokens']:.0f}")

    if summary['failed_tasks']:
        print(f"\nFailed Tasks: {', '.join(summary['failed_tasks'])}")

    print(f"\nResults saved to: {output_path}")
    print(f"{'='*80}\n")

    # Exit code
    sys.exit(0 if summary['failed'] == 0 else 1)


if __name__ == "__main__":
    main()
