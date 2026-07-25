from __future__ import annotations

import argparse
import json
from pathlib import Path

from .mini import run as run_mini
from .runner import BaselineRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="SkillGameAgent mini-SWE-agent compatible runner")
    parser.add_argument("--mode", choices=["mini", "fixture"], default="mini")
    parser.add_argument("--config", default="configs/kitchen_chaos.json")
    parser.add_argument("--task", help="Natural-language task for mini mode")
    args = parser.parse_args()
    root = Path.cwd()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path
    if args.mode == "mini":
        if not args.task:
            parser.error("--task is required in mini mode")
        result = run_mini(args.task, config_path)
        raise SystemExit(0 if result.get("exit_status") == "Submitted" else 1)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    runner = BaselineRunner(root, config)
    raise SystemExit(runner.task(args.task) is False if args.task else runner.run_all())
