from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from .agent_audit import run_agent_graph_audit
from .builder import ProjectGraphBuilder
from .evaluation import LocalizationEvaluator, save_evaluation
from .retrieval import LocalizationRetriever
from .schema import ProjectGraph


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and evaluate the Unity typed project graph")
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="Build Roslyn and Unity Editor project graph")
    build.add_argument("--project", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--editor", type=Path)
    build.add_argument("--code-only", action="store_true")
    build.add_argument("--keep-unity-workspace", action="store_true")
    build.add_argument("--unity-timeout-seconds", type=int, default=1200)

    evaluate = commands.add_parser("evaluate", help="Evaluate A0/A1/A2 localization")
    evaluate.add_argument("--graph", type=Path, required=True)
    evaluate.add_argument("--tasks", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--bootstrap-resamples", type=int, default=10_000)
    evaluate.add_argument("--bootstrap-seed", type=int, default=42)
    evaluate.add_argument(
        "--diversity-study",
        action="store_true",
        help="Compare relevance, path collapse, test quota, and role-aware MMR on A2",
    )

    query = commands.add_parser("query", help="Query A0/A1/A2 localization context")
    query.add_argument("--graph", type=Path, required=True)
    query.add_argument("--project", type=Path, required=True)
    query.add_argument("--query", required=True)
    query.add_argument("--variant", choices=["A0", "A1", "A2"], default="A2")
    query.add_argument(
        "--strategy",
        choices=["relevance", "path_collapse", "path_quota", "role_mmr"],
        default="role_mmr",
    )
    query.add_argument("--limit", type=int, default=10)
    query.add_argument("--output", type=Path)

    audit = commands.add_parser("audit-agent", help="Run a real Agent graph-adoption audit")
    audit.add_argument("--project", type=Path, required=True)
    audit.add_argument("--graph", type=Path, required=True)
    audit.add_argument("--tasks", type=Path, required=True)
    audit.add_argument("--task-id", required=True)
    audit.add_argument("--config", type=Path, default=Path("configs/kitchen_chaos.json"))
    audit.add_argument("--output-root", type=Path, default=Path("artifacts/project-graph/agent-audits"))
    audit.add_argument("--run-id", default="")
    audit.add_argument("--env-file", type=Path, default=Path(".env"))
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "build":
        _, report = ProjectGraphBuilder(
            project_path=args.project,
            output_dir=args.output,
            editor_path=args.editor,
        ).build(
            code_only=args.code_only,
            keep_unity_workspace=args.keep_unity_workspace,
            unity_timeout_seconds=args.unity_timeout_seconds,
        )
        print(json.dumps(report, ensure_ascii=False))
        return
    if args.command == "evaluate":
        evaluator = LocalizationEvaluator.from_paths(args.graph, args.tasks)
        runner = evaluator.run_diversity if args.diversity_study else evaluator.run
        result = runner(
            bootstrap_resamples=args.bootstrap_resamples,
            bootstrap_seed=args.bootstrap_seed,
        )
        save_evaluation(result, args.output)
        print(json.dumps(
            {
                "schema_version": result["schema_version"],
                "task_count": result["task_count"],
                "aggregate": result["aggregate"],
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
        ))
        return
    if args.command == "audit-agent":
        run_id = args.run_id or uuid.uuid4().hex[:12]
        report = run_agent_graph_audit(
            source_project=args.project,
            graph_path=args.graph,
            tasks_path=args.tasks,
            task_id=args.task_id,
            config_path=args.config,
            artifact_dir=args.output_root.resolve() / run_id,
            env_file=args.env_file,
        )
        print(json.dumps(
            {
                "run_id": report["run_id"],
                "task_id": report["task_id"],
                "exit_status": report["agent"]["exit_status"],
                "correctly_applied": report["audit"]["correctly_applied"],
                "metrics": report["audit"]["metrics"],
            },
            ensure_ascii=False,
        ))
        return
    graph = ProjectGraph.load(args.graph)
    result = LocalizationRetriever(graph, args.project).retrieve(
        args.query,
        args.variant,
        limit=args.limit,
        strategy=args.strategy,
    ).to_dict()
    payload = {
        "schema_version": "game-agent-project-graph-query-v1",
        "query": args.query,
        "variant": args.variant,
        "strategy": args.strategy,
        "limit": args.limit,
        "result": result,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
