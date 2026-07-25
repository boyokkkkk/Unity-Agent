#!/usr/bin/env python3
"""Build-time patch: route oversized SWE-agent observations through offloading.

Run inside the image after SWE-agent is installed. It rewrites the truncation
branch of ``DefaultAgent.add_step_to_history`` so that, instead of silently
head-clipping a too-large observation, SWE-agent offloads the full text to a
container file and shows the model a bounded preview + a grep/sed retrieval hint
(see ``_obs_offload.py``).

Anchored, exact-text replacement against SWE-agent v1.1.0. Fails loudly (non-zero
exit) if the anchor is missing -- so a SWE-agent version bump can't silently skip
the patch. Idempotent: re-running is a no-op.
"""

from __future__ import annotations

import sys
from pathlib import Path

AGENTS_PY = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/SWE-agent/sweagent/agent/agents.py")

ANCHOR = (
    "        elif len(step.observation) > self.templates.max_observation_length:\n"
    "            templates = [self.templates.next_step_truncated_observation_template]\n"
    "            elided_chars = len(step.observation) - self.templates.max_observation_length\n"
    "            step.observation = step.observation[: self.templates.max_observation_length]\n"
)

REPLACEMENT = (
    "        elif len(step.observation) > self.templates.max_observation_length:\n"
    "            # PATCHED: offload oversized observation to a container file +\n"
    "            # show a bounded preview with a grep/sed retrieval hint.\n"
    "            from sweagent._obs_offload import offload_observation\n"
    "            templates = [self.templates.next_step_template]\n"
    "            step.observation, elided_chars = offload_observation(\n"
    "                self._env, step.observation, self.templates.max_observation_length\n"
    "            )\n"
)

MARKER = "from sweagent._obs_offload import offload_observation"


def main() -> int:
    if not AGENTS_PY.is_file():
        print(f"[offload-patch] ERROR: {AGENTS_PY} not found", file=sys.stderr)
        return 1

    src = AGENTS_PY.read_text(encoding="utf-8")

    if MARKER in src:
        print("[offload-patch] already applied; skipping")
        return 0

    if ANCHOR not in src:
        print(
            "[offload-patch] ERROR: anchor not found in agents.py -- SWE-agent "
            "source changed. Re-derive the anchor against the installed version.",
            file=sys.stderr,
        )
        return 2

    AGENTS_PY.write_text(src.replace(ANCHOR, REPLACEMENT, 1), encoding="utf-8")
    print(f"[offload-patch] applied to {AGENTS_PY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
