from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from game_agent.baseline_runner import BaselineCase, StateEventBaselineRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the controlled Kitchen Chaos state-event baseline")
    parser.add_argument("--project", required=True, help="Source Unity project; it will not be modified")
    parser.add_argument("--config", default="configs/kitchen_chaos.json")
    parser.add_argument("--editor", required=True)
    parser.add_argument("--output-root", default="artifacts/baselines/state-event-v1")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--variant", choices=("baseline", "innovation"), default="baseline")
    parser.add_argument("--keep-workspace", action="store_true")
    args = parser.parse_args()

    run_id = args.run_id or uuid.uuid4().hex[:12]
    artifact_dir = Path(args.output_root).resolve() / run_id
    report = StateEventBaselineRunner(
        BaselineCase(
            source_project=Path(args.project),
            config_path=Path(args.config),
            artifact_dir=artifact_dir,
            editor_path=Path(args.editor),
            variant=args.variant,
            keep_workspace=args.keep_workspace,
        )
    ).run()
    print(
        json.dumps(
            {
                "run_id": report["run_id"],
                "artifact_dir": str(artifact_dir),
                "experiment_valid": report["experiment_valid"],
                "verified_success": report["verified_success"],
                "agent_exit_status": report["agent"]["exit_status"],
            },
            ensure_ascii=False,
        )
    )
    raise SystemExit(0 if report["experiment_valid"] else 2)


if __name__ == "__main__":
    main()
