from __future__ import annotations

import argparse
import json
from pathlib import Path

from game_agent.registry import COMPONENTS
from game_agent.framework.agents import register_builtin_agents
from game_agent.framework.environments import register_builtin_environments
from game_agent.framework.models import register_builtin_models

from .adapter import register_builtin_adapters
from .runner import BenchmarkRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Run reproducible Unity Agent benchmark matrices")
    parser.add_argument("--manifest", help="Benchmark manifest JSON")
    parser.add_argument("--output", help="Override benchmark output directory")
    parser.add_argument("--max-workers", type=int, help="Override maximum parallel cases")
    parser.add_argument("--no-resume", action="store_true", help="Ignore progress.json and rerun all cases")
    parser.add_argument("--dry-run", action="store_true", help="Expand and print cases without executing")
    parser.add_argument("--list-components", action="store_true", help="Print registered controlled components")
    args = parser.parse_args()
    register_builtin_adapters()
    register_builtin_agents()
    register_builtin_environments()
    register_builtin_models()
    if args.list_components:
        print(json.dumps(COMPONENTS.snapshot(), ensure_ascii=False, indent=2))
        return
    if not args.manifest:
        parser.error("--manifest is required unless --list-components is used")
    manifest_path = Path(args.manifest).resolve()
    runner = BenchmarkRunner.from_path(
        manifest_path, output_dir=Path(args.output).resolve() if args.output else None
    )
    if args.dry_run:
        print(json.dumps(runner.expand_cases(), ensure_ascii=False, indent=2))
        return
    result = runner.run(
        resume=False if args.no_resume else None,
        max_workers=args.max_workers,
    )
    print(json.dumps(result["metrics"]["overall"], ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["metrics"]["overall"]["successes"] == result["planned_cases"] else 1)


if __name__ == "__main__":
    main()
