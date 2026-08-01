from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class WorkspaceSnapshot:
    git_tree: str = ""
    git_prefix: str = ""
    files: dict[str, bytes] = field(default_factory=dict, repr=False)


@dataclass(slots=True)
class MutationTransaction:
    transaction_id: str
    operation: str
    authorized_paths: list[str]
    checkpoint_id: str
    checkpoint_manifest: str
    before: WorkspaceSnapshot = field(repr=False)
    actual_changed_paths: list[str] = field(default_factory=list)
    unauthorized_paths: list[str] = field(default_factory=list)
    diff_ref: str = ""
    status: str = "pending"
    rolled_back: bool = False
    created_at: float = field(default_factory=time.time)

    def public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("before", None)
        return payload


class MutationTransactionManager:
    """Capture exact mutation deltas and roll back any transaction that escapes authorization."""

    def __init__(self, project_root: Path, artifact_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.artifact_root = artifact_root.resolve()

    def begin(
        self,
        *,
        operation: str,
        authorized_paths: list[str],
        checkpoint_id: str,
        checkpoint_manifest: str,
    ) -> MutationTransaction:
        return MutationTransaction(
            transaction_id=uuid.uuid4().hex[:12],
            operation=operation,
            authorized_paths=sorted({self._normalize(path) for path in authorized_paths}),
            checkpoint_id=checkpoint_id,
            checkpoint_manifest=checkpoint_manifest,
            before=self._snapshot(),
        )

    def finish(
        self,
        transaction: MutationTransaction,
        *,
        successful: bool = True,
    ) -> MutationTransaction:
        after = self._snapshot()
        paths, patch = self._delta(transaction.before, after)
        transaction.actual_changed_paths = sorted(paths)
        transaction.unauthorized_paths = sorted(
            path for path in paths if not self._authorized(path, transaction.authorized_paths)
        )
        directory = self.artifact_root / "transactions" / transaction.transaction_id
        directory.mkdir(parents=True, exist_ok=False)
        patch_path = directory / "diff.patch"
        patch_path.write_bytes(patch)
        transaction.diff_ref = patch_path.relative_to(self.artifact_root).as_posix()
        if transaction.unauthorized_paths or not successful:
            self.rollback(transaction.before, transaction.actual_changed_paths)
            transaction.status = (
                "rolled_back_unauthorized"
                if transaction.unauthorized_paths else "rolled_back_failed"
            )
            transaction.rolled_back = True
        else:
            transaction.status = "applied"
        (directory / "transaction.json").write_text(
            json.dumps(transaction.public_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return transaction

    def rollback(self, snapshot: WorkspaceSnapshot, paths: list[str]) -> None:
        for relative in paths:
            target = (self.project_root / relative).resolve()
            if target != self.project_root and self.project_root not in target.parents:
                raise RuntimeError(f"Refusing to roll back path outside project: {relative}")
            content = self._snapshot_content(snapshot, relative)
            if content is None:
                if target.is_file():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)

    def _snapshot(self) -> WorkspaceSnapshot:
        prefix = self._git_text(["rev-parse", "--show-prefix"])
        if prefix is not None:
            with tempfile.TemporaryDirectory(prefix="game-agent-transaction-") as directory:
                index_path = Path(directory) / "index"
                env = dict(os.environ)
                env["GIT_INDEX_FILE"] = str(index_path)
                initialized = self._git(["read-tree", "HEAD"], env=env)
                if initialized.returncode != 0:
                    initialized = self._git(["read-tree", "--empty"], env=env)
                if initialized.returncode == 0:
                    pathspecs = ["."]
                    try:
                        artifact_relative = self.artifact_root.relative_to(self.project_root).as_posix()
                    except ValueError:
                        artifact_relative = ""
                    if artifact_relative:
                        pathspecs.extend([
                            f":(exclude){artifact_relative}",
                            f":(exclude){artifact_relative}/**",
                        ])
                    staged = self._git(["add", "-A", "--", *pathspecs], env=env)
                    tree = self._git(["write-tree"], env=env)
                    if staged.returncode == 0 and tree.returncode == 0:
                        return WorkspaceSnapshot(
                            git_tree=tree.stdout.decode("utf-8", errors="replace").strip(),
                            git_prefix=prefix.strip("/"),
                        )
        files: dict[str, bytes] = {}
        for root_name in ("Assets", "Packages", "ProjectSettings"):
            root = self.project_root / root_name
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if path.is_file() and not self._excluded(path):
                    files[path.relative_to(self.project_root).as_posix()] = path.read_bytes()
        return WorkspaceSnapshot(files=files)

    def _delta(
        self,
        before: WorkspaceSnapshot,
        after: WorkspaceSnapshot,
    ) -> tuple[set[str], bytes]:
        if before.git_tree and after.git_tree:
            names = self._git([
                "diff", "--name-only", "-z", before.git_tree, after.git_tree,
            ]).stdout
            raw_paths = [item.decode("utf-8", errors="replace") for item in names.split(b"\0") if item]
            paths = {self._strip_prefix(path, before.git_prefix) for path in raw_paths}
            paths.discard("")
            patch = self._git([
                "diff", "--binary", "--no-ext-diff", before.git_tree, after.git_tree,
            ]).stdout
            return paths, patch
        keys = set(before.files) | set(after.files)
        changed = {path for path in keys if before.files.get(path) != after.files.get(path)}
        summary = {
            "format": "game-agent-non-git-diff-v1",
            "changed_paths": sorted(changed),
            "before_sha256": {
                path: hashlib.sha256(before.files[path]).hexdigest()
                for path in changed if path in before.files
            },
            "after_sha256": {
                path: hashlib.sha256(after.files[path]).hexdigest()
                for path in changed if path in after.files
            },
        }
        return changed, json.dumps(summary, ensure_ascii=False, indent=2).encode("utf-8")

    def _snapshot_content(self, snapshot: WorkspaceSnapshot, relative: str) -> bytes | None:
        if not snapshot.git_tree:
            return snapshot.files.get(relative)
        repository_path = "/".join(filter(None, [snapshot.git_prefix, relative]))
        result = self._git(["show", f"{snapshot.git_tree}:{repository_path}"])
        return result.stdout if result.returncode == 0 else None

    def _git_text(self, args: list[str]) -> str | None:
        result = self._git(args)
        if result.returncode != 0:
            return None
        return result.stdout.decode("utf-8", errors="replace").strip()

    def _git(
        self,
        args: list[str],
        *,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *args], cwd=self.project_root, env=env,
            capture_output=True, timeout=120, check=False,
        )

    def _excluded(self, path: Path) -> bool:
        return path == self.artifact_root or self.artifact_root in path.parents

    @staticmethod
    def _normalize(path: str) -> str:
        return path.replace("\\", "/").lstrip("./")

    @classmethod
    def _authorized(cls, path: str, authorized_paths: list[str]) -> bool:
        normalized = cls._normalize(path).casefold()
        for authorized in authorized_paths:
            candidate = cls._normalize(authorized).casefold()
            if normalized in {candidate, f"{candidate}.meta"}:
                return True
            parent = Path(candidate).parent.as_posix()
            if normalized.endswith(".meta") and parent not in {"", ".", "assets"}:
                if normalized == f"{parent}.meta":
                    return True
        return False

    @staticmethod
    def _strip_prefix(path: str, prefix: str) -> str:
        normalized = path.replace("\\", "/")
        clean_prefix = prefix.replace("\\", "/").strip("/")
        if clean_prefix and normalized.casefold().startswith(f"{clean_prefix.casefold()}/"):
            return normalized[len(clean_prefix) + 1:]
        return normalized
