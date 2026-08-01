from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable


class EvidenceStatus(str, Enum):
    SUGGESTED = "suggested"
    OBSERVED = "observed"
    SOURCE_VERIFIED = "source_verified"
    RUNTIME_VERIFIED = "runtime_verified"
    REJECTED = "rejected"


@dataclass(slots=True)
class Evidence:
    id: str
    claim: str
    status: EvidenceStatus
    sources: list[str] = field(default_factory=list)
    node_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    repository_revision: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    artifact_path: str | None = None
    artifact_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Full serialization for storage/debugging."""
        data = asdict(self)
        data["status"] = self.status.value
        return data

    def to_context_dict(self) -> dict[str, Any]:
        """Minimal serialization for agent context."""
        return {
            "id": self.id,
            "claim": self.claim,
            "status": self.status.value,
            "sources": self.sources,
            "node_ids": self.node_ids,
        }


class EvidenceLedger:
    """Persistent, structured claims that survive detail and message eviction."""

    def __init__(self) -> None:
        self.items: dict[str, Evidence] = {}

    @staticmethod
    def id_for(claim: str, sources: Iterable[str]) -> str:
        """Return the stable identifier used when the evidence is recorded."""
        payload = claim.strip() + "\x1f" + "\x1f".join(sorted(set(sources)))
        return "evidence:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def add(
        self,
        claim: str,
        *,
        status: EvidenceStatus = EvidenceStatus.SUGGESTED,
        sources: Iterable[str] = (),
        node_ids: Iterable[str] = (),
        confidence: float = 0.0,
        repository_revision: str = "",
        artifact_path: str | None = None,
        artifact_sha256: str | None = None,
    ) -> Evidence:
        normalized_sources = sorted(set(str(value) for value in sources if value))
        evidence_id = self.id_for(claim, normalized_sources)
        existing = self.items.get(evidence_id)
        if existing is not None:
            if _status_rank(status) > _status_rank(existing.status):
                existing.status = status
            existing.node_ids = sorted(set(existing.node_ids) | set(node_ids))
            existing.confidence = max(existing.confidence, confidence)
            if repository_revision:
                existing.repository_revision = repository_revision
            if artifact_path:
                existing.artifact_path = artifact_path
            if artifact_sha256:
                existing.artifact_sha256 = artifact_sha256
            existing.updated_at = time.time()
            return existing
        item = Evidence(
            id=evidence_id,
            claim=claim.strip(),
            status=status,
            sources=normalized_sources,
            node_ids=sorted(set(node_ids)),
            confidence=max(0.0, min(1.0, confidence)),
            repository_revision=repository_revision,
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha256,
        )
        self.items[item.id] = item
        return item

    def update_status(self, evidence_id: str, status: EvidenceStatus) -> None:
        item = self.items[evidence_id]
        item.status = status
        item.updated_at = time.time()

    def active(self) -> list[Evidence]:
        return [item for item in self.items.values() if item.status != EvidenceStatus.REJECTED]

    def verified(self) -> list[Evidence]:
        return [
            item for item in self.items.values()
            if item.status in {EvidenceStatus.SOURCE_VERIFIED, EvidenceStatus.RUNTIME_VERIFIED}
        ]

    def rejected(self) -> list[Evidence]:
        return [item for item in self.items.values() if item.status == EvidenceStatus.REJECTED]

    def to_dict(self) -> dict[str, Any]:
        return {"items": [item.to_dict() for item in sorted(self.items.values(), key=lambda value: value.created_at)]}


def _status_rank(status: EvidenceStatus) -> int:
    return {
        EvidenceStatus.SUGGESTED: 0,
        EvidenceStatus.OBSERVED: 1,
        EvidenceStatus.SOURCE_VERIFIED: 2,
        EvidenceStatus.RUNTIME_VERIFIED: 3,
        EvidenceStatus.REJECTED: 4,
    }[status]


@dataclass(slots=True)
class WorkingSetEntry:
    node_id: str
    kind: str
    name: str
    path: str
    relevance: float = 0.0
    status: str = "recommended"
    detail: dict[str, Any] | None = None
    evidence_ids: list[str] = field(default_factory=list)
    relevance_label: bool | None = None
    accesses: int = 0
    last_accessed_at: float = 0.0
    stale_reason: str = ""

    def touch(self) -> None:
        self.accesses += 1
        self.last_accessed_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TaskWorkingSet:
    """Task-local graph working set with paging and evidence-preserving eviction."""

    def __init__(self, task_id: str, *, max_entries: int = 24) -> None:
        self.task_id = task_id
        self.max_entries = max_entries
        self.entries: dict[str, WorkingSetEntry] = {}
        self.context_hits = 0
        self.context_misses = 0
        self.evictions = 0
        self.remaps = 0

    def add(self, entry: WorkingSetEntry) -> WorkingSetEntry:
        existing = self.entries.get(entry.node_id)
        if existing is not None:
            existing.relevance = max(existing.relevance, entry.relevance)
            if existing.status == "stale" and entry.status != "stale":
                existing.status = entry.status
                existing.stale_reason = ""
            # Merge evidence_ids
            if entry.evidence_ids:
                existing.evidence_ids = sorted(set(existing.evidence_ids) | set(entry.evidence_ids))
                # Auto-judge as relevant if has evidence
                if existing.relevance_label is None:
                    existing.relevance_label = True
            return existing
        self.entries[entry.node_id] = entry
        self._bound_entries()
        return entry

    def record_access(self, node_id: str, *, hit: bool) -> None:
        entry = self.entries[node_id]
        entry.touch()
        if hit:
            self.context_hits += 1
        else:
            self.context_misses += 1

    def mark_stale(self, node_ids: Iterable[str], reason: str) -> None:
        for node_id in node_ids:
            if node_id not in self.entries:
                continue
            entry = self.entries[node_id]
            entry.status = "stale"
            entry.stale_reason = reason
            entry.detail = None

    def label(self, node_id: str, relevant: bool, *, evidence_id: str = "") -> None:
        if node_id not in self.entries:
            return
        entry = self.entries[node_id]
        entry.relevance_label = relevant
        if relevant and evidence_id:
            if evidence_id not in entry.evidence_ids:
                entry.evidence_ids.append(evidence_id)
        entry.status = "verified" if relevant else "rejected"
        if evidence_id and evidence_id not in entry.evidence_ids:
            entry.evidence_ids.append(evidence_id)

    def evict_details(self, *, keep: int) -> list[str]:
        detailed = [entry for entry in self.entries.values() if entry.detail is not None]
        detailed.sort(
            key=lambda entry: (
                bool(entry.evidence_ids),
                entry.status == "verified",
                entry.last_accessed_at,
                entry.relevance,
            ),
            reverse=True,
        )
        evicted: list[str] = []
        for entry in detailed[max(0, keep):]:
            entry.detail = None
            evicted.append(entry.node_id)
        self.evictions += len(evicted)
        return evicted

    def metrics(self) -> dict[str, Any]:
        accesses = self.context_hits + self.context_misses
        active = [entry for entry in self.entries.values() if entry.status != "stale"]
        judged = [entry for entry in active if entry.relevance_label is not None]
        relevant = [entry for entry in judged if entry.relevance_label]
        return {
            "context_hits": self.context_hits,
            "context_misses": self.context_misses,
            "context_hit_rate": self.context_hits / accesses if accesses else 0.0,
            "context_miss_rate": self.context_misses / accesses if accesses else 0.0,
            "working_set_size": len(active),
            "working_set_precision": len(relevant) / len(active) if active else 0.0,
            "working_set_judged_precision": len(relevant) / len(judged) if judged else None,
            "working_set_judgment_coverage": len(judged) / len(active) if active else 0.0,
            "judged_nodes": len(judged),
            "evictions": self.evictions,
            "remaps": self.remaps,
        }

    def _bound_entries(self) -> None:
        if len(self.entries) <= self.max_entries:
            return
        removable = sorted(
            self.entries.values(),
            key=lambda entry: (bool(entry.evidence_ids), entry.status == "verified", entry.relevance, entry.last_accessed_at),
        )
        while len(self.entries) > self.max_entries and removable:
            entry = removable.pop(0)
            self.entries.pop(entry.node_id, None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "max_entries": self.max_entries,
            "entries": [entry.to_dict() for entry in self.entries.values()],
            "metrics": self.metrics(),
        }


@dataclass(slots=True)
class ToolObservation:
    summary: str
    artifact_ref: str = ""
    important_ranges: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    command: str = ""
    category: str = "other"
    success: bool = True
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ContextMemory:
    decisions: list[str] = field(default_factory=list)
    verified_facts: list[str] = field(default_factory=list)
    rejected_hypotheses: list[str] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    pending_validations: list[str] = field(default_factory=list)
    last_failure: dict[str, Any] | None = None
    artifact_references: list[str] = field(default_factory=list)
    conversation_summary: str = ""

    def add_unique(self, field_name: str, value: str) -> None:
        if not value:
            return
        collection = getattr(self, field_name)
        if value not in collection:
            collection.append(value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
