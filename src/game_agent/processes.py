from __future__ import annotations

import os
import subprocess
import signal


def terminate_process_tree(pid: int, *, force: bool = True) -> None:
    """Terminate a process and its descendants without raising for an already-exited pid."""
    if pid <= 0:
        return
    if os.name == "nt":
        command = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            command.append("/F")
        subprocess.run(command, capture_output=True, check=False)
        return
    listed = subprocess.run(
        ["ps", "-eo", "pid=,ppid="], capture_output=True, text=True, check=False
    )
    children: dict[int, list[int]] = {}
    if listed.returncode == 0:
        for line in listed.stdout.splitlines():
            try:
                child, parent = (int(value) for value in line.split())
            except (ValueError, TypeError):
                continue
            children.setdefault(parent, []).append(child)

    descendants: list[int] = []

    def collect(parent: int) -> None:
        for child in children.get(parent, []):
            collect(child)
            descendants.append(child)

    collect(pid)
    for process_id in [*descendants, pid]:
        try:
            os.kill(process_id, signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:
            continue
