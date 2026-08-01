from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CausalClaim:
    statement: str
    evidence_ids: list[str]


@dataclass(frozen=True, slots=True)
class ProposedMutation:
    target: str
    operation: str
    target_paths: list[str] = field(default_factory=list)
    evidence_id: str = ""
    old_text: str = ""
    new_text: str = ""


@dataclass(frozen=True, slots=True)
class DiagnosisRecord:
    version: int
    symptom: str
    root_targets: list[str]
    causal_chain: list[CausalClaim]
    proposed_mutations: list[ProposedMutation]
    validation_plan: list[str]
    remaining_uncertainty: list[str]
    repository_revision: str
    status: str
    gaps: list[str] = field(default_factory=list)
    evidence_artifacts: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_arguments(
        cls,
        arguments: dict[str, Any],
        *,
        version: int,
        repository_revision: str,
        status: str = "proposed",
        gaps: list[str] | None = None,
        evidence_ledger: Any = None,
    ) -> "DiagnosisRecord":
        causal_chain = [
            CausalClaim(
                statement=str(item.get("statement", "")).strip(),
                evidence_ids=[str(value) for value in item.get("evidence_ids", []) if value],
            )
            for item in arguments.get("causal_chain", [])
            if isinstance(item, dict)
        ]
        proposed_mutations = [
            ProposedMutation(
                target=str(item.get("target", "")).upper(),
                operation=str(item.get("operation", "")).strip(),
                target_paths=[str(value).replace("\\", "/") for value in item.get("target_paths", []) if value],
                evidence_id=str(item.get("evidence_id", "")).strip(),
                old_text=str(item.get("old_text", "")),
                new_text=str(item.get("new_text", "")),
            )
            for item in arguments.get("proposed_mutations", [])
            if isinstance(item, dict)
        ]

        # Collect evidence artifacts from the ledger
        evidence_artifacts: dict[str, str] = {}
        if evidence_ledger is not None:
            all_evidence_ids = []
            for claim in causal_chain:
                all_evidence_ids.extend(claim.evidence_ids)
            for evidence_id in all_evidence_ids:
                if hasattr(evidence_ledger, 'items') and evidence_id in evidence_ledger.items:
                    evidence = evidence_ledger.items[evidence_id]
                    if evidence.artifact_path:
                        evidence_artifacts[evidence_id] = evidence.artifact_path

        return cls(
            version=version,
            symptom=str(arguments.get("symptom", "")).strip(),
            root_targets=list(dict.fromkeys(
                str(value).upper() for value in arguments.get("root_targets", []) if value
            )),
            causal_chain=causal_chain,
            proposed_mutations=proposed_mutations,
            validation_plan=list(dict.fromkeys(
                str(value).casefold() for value in arguments.get("validation_plan", []) if value
            )),
            remaining_uncertainty=[
                str(value).strip() for value in arguments.get("remaining_uncertainty", []) if str(value).strip()
            ],
            repository_revision=repository_revision,
            status=status,
            gaps=list(gaps or []),
            evidence_artifacts=evidence_artifacts,
        )

    def with_decision(self, *, status: str, gaps: list[str]) -> "DiagnosisRecord":
        payload = asdict(self)
        payload.update(status=status, gaps=list(gaps))
        payload["causal_chain"] = [CausalClaim(**item) for item in payload["causal_chain"]]
        payload["proposed_mutations"] = [ProposedMutation(**item) for item in payload["proposed_mutations"]]
        return DiagnosisRecord(**payload)

    def evidence_ids(self) -> list[str]:
        return list(dict.fromkeys(
            evidence_id
            for claim in self.causal_chain
            for evidence_id in claim.evidence_ids
        ))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
