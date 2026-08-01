from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass(slots=True)
class CandidateRef:
    candidate_id: str
    node_id: str
    entity_type: str
    path: str
    symbol: str = ""
    role: str = "source"
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    read_level: str = "unread"
    evidence_ids: list[str] = field(default_factory=list)

    def public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("node_id", None)
        return payload


class CandidateFrontier:
    """Task-local, bounded public aliases for private project-graph nodes."""

    def __init__(self, *, max_size: int = 5, retained_roles: set[str] | None = None) -> None:
        self.max_size = max(1, max_size)
        self.retained_roles = set(retained_roles or set())
        self._by_id: dict[str, CandidateRef] = {}
        self._key_to_id: dict[str, str] = {}
        self._next_id = 1

    def reset(self) -> None:
        self._by_id = {}
        self._key_to_id = {}
        self._next_id = 1

    def add_rows(
        self,
        rows: Iterable[dict[str, Any]],
        *,
        query: str = "",
        source: str = "search",
    ) -> bool:
        before = self.snapshot_key()
        for rank, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            node_id = str(row.get("id", "") or row.get("node_id", ""))
            path = str(row.get("path", "")).replace("\\", "/")
            entity_type = str(row.get("kind", "") or row.get("entity_type", ""))
            name = str(row.get("name", "") or row.get("symbol", ""))
            if not node_id or not path or not _candidate_path(path):
                continue
            score = float(row.get("score", 0.0) or 0.0)
            if score <= 0:
                score = max(0.05, 1.0 - ((rank - 1) * 0.05))
            role = _role(name, path, entity_type)
            reason = f"{source} candidate rank {rank}"
            if query:
                reason += f" for {query!r}"
            self._upsert(
                node_id=node_id,
                entity_type=entity_type,
                path=path,
                symbol=name if entity_type.upper() not in {"CSHARP_FILE", "SCENE", "PREFAB", "ASSET"} else "",
                role=role,
                score=score,
                reason=reason,
            )
        self._bound()
        return before != self.snapshot_key()

    def add_working_set(self, entries: Iterable[Any]) -> bool:
        rows = [
            {
                "id": entry.node_id,
                "kind": entry.kind,
                "name": entry.name,
                "path": entry.path,
                "score": entry.relevance,
            }
            for entry in entries
        ]
        return self.add_rows(rows, source="project graph")

    def get(self, candidate_id: str) -> CandidateRef | None:
        return self._by_id.get(candidate_id.upper())

    def mark_read(self, candidate_id: str, *, level: str, evidence_ids: Iterable[str]) -> bool:
        candidate = self.get(candidate_id)
        if candidate is None:
            return False
        before_level = _read_level(candidate.read_level)
        requested_level = _read_level(level)
        before_evidence = set(candidate.evidence_ids)
        if requested_level > before_level:
            candidate.read_level = level
        candidate.evidence_ids = list(dict.fromkeys([*candidate.evidence_ids, *evidence_ids]))
        return requested_level > before_level or set(candidate.evidence_ids) != before_evidence

    def read_would_advance(self, candidate_id: str, *, level: str) -> bool:
        candidate = self.get(candidate_id)
        return candidate is not None and _read_level(level) > _read_level(candidate.read_level)

    def candidates(self) -> list[CandidateRef]:
        return sorted(self._by_id.values(), key=_sort_key)

    def public_candidates(self) -> list[dict[str, Any]]:
        return [candidate.public_dict() for candidate in self.candidates()]

    def roles(self) -> set[str]:
        return {candidate.role for candidate in self._by_id.values()}

    def snapshot_key(self) -> tuple[tuple[str, str, float], ...]:
        return tuple(
            (candidate.candidate_id, candidate.path.casefold(), round(candidate.score, 6))
            for candidate in self.candidates()
        )

    def __len__(self) -> int:
        return len(self._by_id)

    def _upsert(
        self,
        *,
        node_id: str,
        entity_type: str,
        path: str,
        symbol: str,
        role: str,
        score: float,
        reason: str,
    ) -> None:
        key = _entity_key(path, symbol)
        existing_id = self._key_to_id.get(key)
        if existing_id:
            existing = self._by_id[existing_id]
            if score > existing.score or _prefer_type(entity_type, existing.entity_type):
                existing.node_id = node_id
                existing.entity_type = entity_type
                existing.symbol = symbol
                existing.role = role
                existing.score = max(existing.score, score)
            if reason not in existing.reasons:
                existing.reasons.append(reason)
            return
        candidate_id = f"C{self._next_id}"
        self._next_id += 1
        self._key_to_id[key] = candidate_id
        self._by_id[candidate_id] = CandidateRef(
            candidate_id=candidate_id,
            node_id=node_id,
            entity_type=entity_type,
            path=path,
            symbol=symbol,
            role=role,
            score=score,
            reasons=[reason],
        )

    def _bound(self) -> None:
        ranked = self.candidates()
        keep: list[CandidateRef] = []
        kept_ids: set[str] = set()
        for role in sorted(self.retained_roles):
            candidate = next((item for item in ranked if item.role == role), None)
            if candidate is not None and candidate.candidate_id not in kept_ids:
                keep.append(candidate)
                kept_ids.add(candidate.candidate_id)
        keep.extend(item for item in ranked if item.candidate_id not in kept_ids)
        keep = keep[: self.max_size]
        keep_ids = {candidate.candidate_id for candidate in keep}
        for candidate_id in list(self._by_id):
            if candidate_id in keep_ids:
                continue
            candidate = self._by_id.pop(candidate_id)
            self._key_to_id.pop(_entity_key(candidate.path, candidate.symbol), None)


def _candidate_path(path: str) -> bool:
    return path.casefold().endswith((".cs", ".unity", ".prefab", ".asset"))


def _entity_key(path: str, symbol: str) -> str:
    # Script edits and source evidence are file-scoped. Keeping a separate
    # frontier entry for the file, its type, and each symbol causes the model
    # to reread identical source under different candidate IDs.
    if path.casefold().endswith(".cs"):
        return path.casefold()
    return f"{path.casefold()}::{symbol.casefold()}"


def _prefer_type(candidate: str, existing: str) -> bool:
    priority = {"METHOD": 4, "CLASS": 3, "MONO_BEHAVIOUR": 3, "CSHARP_FILE": 2}
    return priority.get(candidate.upper(), 1) > priority.get(existing.upper(), 1)


def _read_level(value: str) -> int:
    return {
        "unread": 0,
        "outline": 1,
        "preview": 2,
        "window": 3,
        "symbol": 4,
        "full": 5,
    }.get(value.casefold(), 0)


def _sort_key(candidate: CandidateRef) -> tuple[float, str, str]:
    return (-candidate.score, candidate.path.casefold(), candidate.symbol.casefold())


def _role(name: str, path: str, entity_type: str) -> str:
    value = f"{name} {Path(path).stem} {entity_type}".casefold()
    if "test" in value:
        return "test"
    if any(token in value for token in ("manager", "controller", "state", "coordinator")):
        return "controller"
    if any(token in value for token in ("input", "interaction", "event")):
        return "event_source"
    if any(token in value for token in ("ui", "view", "panel", "canvas")):
        return "ui"
    if path.casefold().endswith((".unity", ".prefab", ".asset")):
        return "asset"
    return "source"
