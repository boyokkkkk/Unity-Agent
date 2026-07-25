"""Observation offloading for SWE-agent under a tight token budget.

This module is the SWE-agent equivalent. It is invoked from
``sweagent/agent/agents.py::DefaultAgent.add_step_to_history`` (patched in at image
build time by ``apply_offload_patch.py``) for any observation that exceeds
``max_observation_length``.

Behaviour:
  * Write the FULL observation to ``/tmp/swe_obs_<n>.txt`` inside the agent's
    container via ``SWEEnv.write_file`` (a runtime call -- it does NOT inject a
    command into the agent's bash session).
  * Return a bounded preview (the first ``max_observation_length`` chars) plus a
    hint telling the model the full output's path and how to read slices of it
    with ``grep`` / ``sed -n``.
  * If the container write fails for any reason, degrade gracefully to plain
    head-truncation with a "narrow your scope" nudge -- never raise, so a run is
    never crashed by the offload path itself.

Returns ``(shown_observation, elided_chars)`` so the caller can keep populating
the existing template kwargs.
"""

from __future__ import annotations

import itertools
from typing import Any

# Per-process counter so each offloaded observation gets a unique container path.
_counter = itertools.count(1)


def offload_observation(env: Any, observation: str, max_observation_length: int) -> tuple[str, int]:
    """Offload an oversized observation to a container file; return preview + hint.

    Args:
        env: the SWEEnv instance (must expose ``write_file(path, content)``).
        observation: the full, untruncated observation text.
        max_observation_length: preview size in characters (also the trigger
            threshold, already checked by the caller).

    Returns:
        ``(shown_observation, elided_chars)`` where ``shown_observation`` is the
        bounded text actually sent to the model.
    """
    full_len = len(observation)
    preview = observation[:max_observation_length]
    elided_chars = full_len - len(preview)
    path = f"/tmp/swe_obs_{next(_counter)}.txt"

    try:
        env.write_file(path, observation)
        hint = (
            f"\n\n[Output truncated -- showing the first {len(preview)} of {full_len} "
            f"characters ({elided_chars} elided). The FULL output is saved in the "
            f"working container at {path}. Read ONLY the part you need, e.g.:\n"
            f'  grep -n "PATTERN" {path}\n'
            f"  sed -n '1,120p' {path}\n"
            f"Prefer grep/find to locate code instead of viewing whole directories.]"
        )
    except Exception:  # noqa: BLE001 - graceful degradation, must never crash the run
        hint = (
            f"\n\n[Output truncated -- showing the first {len(preview)} of {full_len} "
            f"characters ({elided_chars} elided). Re-run with a narrower scope "
            f"(grep/find for a specific symbol, or list a specific subdirectory) "
            f"to see more. Avoid viewing whole directories.]"
        )

    return preview + hint, elided_chars
