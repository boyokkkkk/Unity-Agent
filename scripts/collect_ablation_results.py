# 消融实验数据收集脚本

import json
from pathlib import Path
import pandas as pd
from datetime import datetime

def collect_ablation_results(artifact_root="artifacts/baselines/state-event-v1"):
    """收集所有消融实验的结果"""
    results = []
    artifact_path = Path(artifact_root)

    if not artifact_path.exists():
        print(f"Artifact directory not found: {artifact_path}")
        return pd.DataFrame()

    for run_dir in artifact_path.iterdir():
        if not run_dir.is_dir():
            continue

        # 只处理ablation实验的结果
        if not run_dir.name.startswith("ablation-group"):
            continue

        try:
            # 解析run_dir名称: ablation-group1-run1-20260801-153000
            parts = run_dir.name.split("-")
            group_num = int(parts[1].replace("group", ""))
            run_num = int(parts[2].replace("run", ""))

            # 读取关键文件
            agent_result_file = run_dir / "agent-result.json"
            baseline_report_file = run_dir / "baseline-report.json"
            stage_metrics_file = run_dir / "stage-metrics.json"
            events_file = run_dir / "events.jsonl"

            if not agent_result_file.exists():
                print(f"Skipping {run_dir.name}: agent-result.json not found")
                continue

            agent_result = json.loads(agent_result_file.read_text(encoding="utf-8"))

            # 基础指标
            result = {
                "group": group_num,
                "run": run_num,
                "run_id": run_dir.name,
                "exit_status": agent_result.get("exit_status", "Unknown"),
                "total_tokens": agent_result.get("total_tokens", 0),
                "input_tokens": agent_result.get("input_tokens", 0),
                "completion_tokens": agent_result.get("token_usage", {}).get("completion_tokens", 0),
            }

            # Baseline report (如果存在)
            if baseline_report_file.exists():
                baseline_report = json.loads(baseline_report_file.read_text(encoding="utf-8"))
                result["experiment_valid"] = baseline_report.get("experiment_valid", False)
                result["verified_success"] = baseline_report.get("verified_success", False)
                result["source_unchanged"] = baseline_report.get("source_project_unchanged", False)
            else:
                result["experiment_valid"] = False
                result["verified_success"] = False
                result["source_unchanged"] = False

            # Stage metrics (如果存在)
            if stage_metrics_file.exists():
                stage_metrics = json.loads(stage_metrics_file.read_text(encoding="utf-8"))
                result["rounds"] = stage_metrics.get("context", {}).get("rounds", 0)
                result["mutation_calls"] = stage_metrics.get("mutation", {}).get("typed_mutation_calls", 0)
                result["escape_hatch_calls"] = stage_metrics.get("mutation", {}).get("escape_hatch_calls", 0)
            else:
                result["rounds"] = 0
                result["mutation_calls"] = 0
                result["escape_hatch_calls"] = 0

            # 从events.jsonl提取更多指标
            if events_file.exists():
                events = []
                for line in events_file.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        events.append(json.loads(line))

                # 统计各阶段
                phases = [e.get("phase") for e in events if "phase" in e]
                result["reached_diagnose"] = "DIAGNOSE" in phases or "diagnose" in phases
                result["reached_edit"] = "EDIT" in phases or "edit" in phases
                result["reached_validate"] = "VALIDATE" in phases or "validate" in phases
                result["reached_review"] = "REVIEW" in phases or "review" in phases
                result["reached_submit"] = "SUBMIT" in phases or "submit" in phases

                # 统计错误
                format_errors = [e for e in events if e.get("error_type") == "FormatError"]
                mutation_failures = [e for e in events if e.get("event") == "tool_end" and
                                    "mutation" in e.get("tool", "") and e.get("returncode", 0) != 0]

                result["format_errors"] = len(format_errors)
                result["mutation_failures"] = len(mutation_failures)
            else:
                result["reached_diagnose"] = False
                result["reached_edit"] = False
                result["reached_validate"] = False
                result["reached_review"] = False
                result["reached_submit"] = False
                result["format_errors"] = 0
                result["mutation_failures"] = 0

            results.append(result)

        except Exception as e:
            print(f"Error processing {run_dir.name}: {e}")
            continue

    if not results:
        print("No ablation results found")
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df = df.sort_values(["group", "run"])
    return df


def analyze_ablation_results(df):
    """分析消融实验结果"""
    if df.empty:
        print("No data to analyze")
        return

    print("=" * 80)
    print("消融实验结果分析")
    print("=" * 80)
    print()

    # 按组汇总
    group_summary = df.groupby("group").agg({
        "verified_success": ["mean", "sum", "count"],
        "total_tokens": ["mean", "std"],
        "rounds": ["mean", "std"],
        "mutation_failures": "mean",
        "format_errors": "mean",
        "reached_edit": "mean",
        "reached_validate": "mean",
    }).round(2)

    print("各组汇总统计:")
    print(group_summary)
    print()

    # 成功率对比
    success_rates = df.groupby("group")["verified_success"].mean() * 100
    print("成功率对比 (%):")
    for group, rate in success_rates.items():
        group_names = {
            1: "完整系统 (baseline)",
            2: "移除P1",
            3: "移除P0+P1",
            4: "移除Dynamic Tool Exposure",
            5: "移除Bounded Search Budget",
            6: "移除Project Graph",
            7: "移除Submission Contract",
            8: "移除Typed Mutations",
            9: "移除Validation",
        }
        print(f"  Group {group} ({group_names.get(group, 'Unknown')}): {rate:.1f}%")
    print()

    # 计算相对baseline的变化
    if 1 in success_rates.index:
        baseline_rate = success_rates[1]
        print("相对Baseline的变化:")
        for group, rate in success_rates.items():
            if group != 1:
                diff = rate - baseline_rate
                print(f"  Group {group}: {diff:+.1f}% (绝对), {diff/baseline_rate*100:+.1f}% (相对)")
    print()

    # Token使用对比
    token_means = df.groupby("group")["total_tokens"].mean()
    print("平均Token使用:")
    for group, tokens in token_means.items():
        print(f"  Group {group}: {tokens:.0f}")
    print()

    # 保存详细结果
    output_file = f"ablation_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    df.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"详细结果已保存到: {output_file}")
    print()

    # 保存汇总结果
    summary_file = f"ablation_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    group_summary.to_csv(summary_file, encoding="utf-8-sig")
    print(f"汇总结果已保存到: {summary_file}")


if __name__ == "__main__":
    print("开始收集消融实验结果...")
    df = collect_ablation_results()

    if not df.empty:
        print(f"找到 {len(df)} 条实验记录")
        analyze_ablation_results(df)
    else:
        print("未找到消融实验结果。请确保:")
        print("  1. 已经运行了消融实验")
        print("  2. run_id以'ablation-group'开头")
        print("  3. artifacts目录路径正确")
