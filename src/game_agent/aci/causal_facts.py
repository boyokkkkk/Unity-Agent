from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from game_agent.project_graph.schema import CAUSAL_EDGE_KINDS, EdgeKind, Node, NodeKind, ProjectGraph


STRUCTURED_PREDICATES = {
    "DECLARES_EVENT",
    "SUBSCRIBES_TO",
    "WRITES_STATE",
    "PUBLISHES_EVENT",
    "OBSERVER_EFFECT",
}


@dataclass(frozen=True, slots=True)
class NegativeEvidence:
    scope: str
    edge_kind: str
    graph_revision: str
    observed_matches: int
    complete: bool


@dataclass(frozen=True, slots=True)
class CausalFact:
    fact_id: str
    slot: str
    subject: str
    predicate: str
    object: str
    polarity: str
    locations: list[str] = field(default_factory=list)
    ast_anchor: str = ""
    repair_exemplar: str = ""
    negative_evidence: NegativeEvidence | None = None
    subject_id: str = ""
    object_id: str = ""

    def public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("subject_id", None)
        payload.pop("object_id", None)
        return payload


@dataclass(slots=True)
class CausalFactMatrix:
    graph_revision: str
    scope_paths: list[str]
    facts: list[CausalFact]

    def public_dict(self) -> dict[str, Any]:
        slots = {
            "event_declaration": [],
            "trigger_subscription": [],
            "state_write": [],
            "event_publication": [],
            "observer_subscription": [],
            "observer_effect": [],
        }
        for fact in self.facts:
            slots.setdefault(fact.slot, []).append(fact.public_dict())
        return {
            "graph_revision": self.graph_revision,
            "scope_paths": self.scope_paths,
            "slots": {
                name: {
                    "status": _slot_status(values),
                    "facts": values,
                }
                for name, values in slots.items()
            },
        }

    def by_id(self) -> dict[str, CausalFact]:
        return {fact.fact_id: fact for fact in self.facts}


def build_causal_fact_matrix(
    graph: ProjectGraph,
    *,
    node_ids: Iterable[str] = (),
    paths: Iterable[str] = (),
    causal_edges_enabled: bool = True,
) -> CausalFactMatrix:
    scope_paths = {
        _normalize_path(value)
        for value in paths
        if value
    }
    for node_id in node_ids:
        node = graph.nodes.get(str(node_id))
        if node is not None and node.path:
            scope_paths.add(_normalize_path(node.path))
    revision = str(
        graph.metadata.get("project_revision")
        or graph.metadata.get("git_commit")
        or graph.metadata.get("tree_hash")
        or _graph_digest(graph)
    )

    def in_scope(node: Node | None) -> bool:
        return node is not None and (
            not scope_paths or _normalize_path(node.path) in scope_paths
        )

    facts: list[CausalFact] = []
    events = [
        node for node in graph.nodes.values()
        if node.kind == NodeKind.FIELD
        and bool(node.attributes.get("is_event"))
        and in_scope(node)
    ]
    for event in events:
        owner = str(event.attributes.get("declaring_type", "")).strip()
        facts.append(_fact(
            "event_declaration", owner, "DECLARES_EVENT", _symbol(event), "present",
            subject_id=_type_id(graph, owner), object_id=event.id,
            locations=[_location(event)],
        ))

    writes = []
    publishes: dict[tuple[str, str], dict[str, Any]] = {}
    trigger_subscribers: set[str] = set()
    for edge in graph.edges:
        if not causal_edges_enabled and edge.kind in CAUSAL_EDGE_KINDS:
            continue
        source = graph.nodes.get(edge.source)
        target = graph.nodes.get(edge.target)
        if not in_scope(source):
            continue
        if edge.kind == EdgeKind.SUBSCRIBES_TO and source is not None and target is not None:
            slot = "observer_subscription" if _is_ui_path(source.path) else "trigger_subscription"
            if slot == "trigger_subscription":
                trigger_subscribers.add(source.id)
            facts.append(_edge_fact(slot, source, edge.kind.value, target))
        elif edge.kind == EdgeKind.WRITES_STATE and source is not None and target is not None:
            writes.append((source, target, edge.attributes))
            facts.append(_edge_fact(
                "state_write", source, edge.kind.value, target,
                attributes=edge.attributes,
            ))
        elif edge.kind == EdgeKind.PUBLISHES_EVENT and source is not None and target is not None:
            publishes[(source.id, target.id)] = edge.attributes
        elif (
            edge.kind == EdgeKind.CALLS
            and source is not None and target is not None
            and _is_ui_path(source.path)
            and _is_ui_effect(target)
            and str(source.attributes.get("declaring_type", ""))
            == str(target.attributes.get("declaring_type", ""))
        ):
            facts.append(_edge_fact(
                "observer_effect", source, "OBSERVER_EFFECT", target,
                attributes=edge.attributes,
            ))

    state_events = [
        event for event in events
        if any(token in event.name.casefold() for token in ("state", "change"))
    ]
    for writer, state_field, write_attributes in writes:
        if state_field.name.casefold() != "state":
            continue
        owner = str(writer.attributes.get("declaring_type", ""))
        for event in state_events:
            if str(event.attributes.get("declaring_type", "")) != owner:
                continue
            present = (writer.id, event.id) in publishes
            if not present and writer.id not in trigger_subscribers:
                continue
            negative = None if present else NegativeEvidence(
                scope=_symbol(writer),
                edge_kind=EdgeKind.PUBLISHES_EVENT.value,
                graph_revision=revision,
                observed_matches=0,
                complete=True,
            )
            facts.append(_fact(
                "event_publication",
                _symbol(writer),
                EdgeKind.PUBLISHES_EVENT.value,
                _symbol(event),
                "present" if present else "absent",
                subject_id=writer.id,
                object_id=event.id,
                locations=[_location(writer), _location(event)],
                ast_anchor=str(write_attributes.get("expression", "")),
                repair_exemplar=next(
                    (
                        str(attributes.get("expression", ""))
                        for (publisher_id, event_id), attributes in publishes.items()
                        if event_id == event.id and publisher_id != writer.id
                        and str(attributes.get("expression", ""))
                    ),
                    "",
                ),
                negative_evidence=negative,
            ))

    return CausalFactMatrix(
        graph_revision=revision,
        scope_paths=sorted(scope_paths),
        facts=_deduplicate_facts(facts),
    )


class CausalClaimVerifier:
    def __init__(self, graph: ProjectGraph, matrix: CausalFactMatrix):
        self.graph = graph
        self.matrix = matrix
        self.facts = matrix.by_id()
        self.symbols = _symbol_index(graph)

    def verify(self, claim: Any, *, claim_index: int) -> list[str]:
        label = f"causal claim {claim_index}"
        gaps: list[str] = []
        predicate = str(getattr(claim, "predicate", "")).upper()
        polarity = str(getattr(claim, "polarity", "")).casefold()
        subject = str(getattr(claim, "subject", "")).strip()
        object_name = str(getattr(claim, "object", "")).strip()
        fact_ids = list(getattr(claim, "fact_ids", []) or [])
        if predicate not in STRUCTURED_PREDICATES:
            gaps.append(f"{label} predicate is unsupported: {predicate or '<empty>'}")
        if polarity not in {"present", "absent", "unknown"}:
            gaps.append(f"{label} polarity must be present, absent, or unknown")
        subject_ids, subject_error = self._resolve(subject)
        object_ids, object_error = self._resolve(object_name)
        if subject_error:
            gaps.append(f"{label} subject {subject_error}: {subject or '<empty>'}")
        if object_error:
            gaps.append(f"{label} object {object_error}: {object_name or '<empty>'}")
        cited = [self.facts.get(fact_id) for fact_id in fact_ids]
        missing_fact_ids = [fact_id for fact_id, fact in zip(fact_ids, cited) if fact is None]
        if missing_fact_ids:
            gaps.append(f"{label} references unknown causal fact(s): {', '.join(missing_fact_ids)}")
        matching = [
            fact for fact in cited
            if fact is not None
            and fact.predicate == predicate
            and fact.polarity == polarity
            and fact.subject == subject
            and fact.object == object_name
        ]
        if not matching:
            gaps.append(f"{label} is not supported by a matching causal fact")
        relation_present = (
            self._relation_present(predicate, subject_ids, object_ids)
            if predicate in STRUCTURED_PREDICATES else False
        )
        if polarity == "absent":
            if relation_present:
                gaps.append(f"{label} contradicts the Roslyn graph: the relation is present")
            proof = next((fact.negative_evidence for fact in matching if fact.negative_evidence), None)
            supplied = getattr(claim, "negative_evidence", None)
            if proof is None or not proof.complete or proof.observed_matches != 0:
                gaps.append(f"{label} has no complete bounded negative evidence")
            elif not _negative_evidence_matches(supplied, proof):
                gaps.append(f"{label} negative evidence does not match the controller-generated proof")
        elif polarity == "present" and not relation_present:
            gaps.append(f"{label} contradicts the Roslyn graph: the relation is absent")
        return gaps

    def _resolve(self, value: str) -> tuple[set[str], str]:
        ids = self.symbols.get(value.casefold(), set()) if value else set()
        if not ids:
            return set(), "does not exist in the symbol table"
        if len(ids) > 1:
            return ids, "is ambiguous in the symbol table"
        return ids, ""

    def _relation_present(
        self, predicate: str, subject_ids: set[str], object_ids: set[str]
    ) -> bool:
        if not subject_ids or not object_ids:
            return False
        if predicate == "DECLARES_EVENT":
            return any(
                (node := self.graph.nodes.get(object_id)) is not None
                and node.kind == NodeKind.FIELD
                and bool(node.attributes.get("is_event"))
                and str(node.attributes.get("declaring_type", "")).casefold()
                in {
                    self.graph.nodes[subject_id].name.casefold()
                    for subject_id in subject_ids if subject_id in self.graph.nodes
                }
                for object_id in object_ids
            )
        kind = EdgeKind.CALLS if predicate == "OBSERVER_EFFECT" else EdgeKind(predicate)
        return any(
            edge.kind == kind and edge.source in subject_ids and edge.target in object_ids
            for edge in self.graph.edges
        )


def _fact(
    slot: str,
    subject: str,
    predicate: str,
    object_name: str,
    polarity: str,
    *,
    subject_id: str = "",
    object_id: str = "",
    locations: list[str] | None = None,
    negative_evidence: NegativeEvidence | None = None,
    ast_anchor: str = "",
    repair_exemplar: str = "",
) -> CausalFact:
    key = "\x1f".join((slot, subject, predicate, object_name, polarity))
    fact_id = "fact:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return CausalFact(
        fact_id=fact_id,
        slot=slot,
        subject=subject,
        predicate=predicate,
        object=object_name,
        polarity=polarity,
        locations=list(locations or []),
        negative_evidence=negative_evidence,
        ast_anchor=ast_anchor,
        repair_exemplar=repair_exemplar,
        subject_id=subject_id,
        object_id=object_id,
    )


def _edge_fact(
    slot: str,
    source: Node,
    predicate: str,
    target: Node,
    *,
    attributes: dict[str, Any] | None = None,
) -> CausalFact:
    return _fact(
        slot, _symbol(source), predicate, _symbol(target), "present",
        subject_id=source.id, object_id=target.id,
        locations=[_location(source), _location(target)],
        ast_anchor=str((attributes or {}).get("expression", "")),
    )


def _symbol(node: Node) -> str:
    declaring = str(node.attributes.get("declaring_type", "")).strip()
    return f"{declaring}.{node.name}" if declaring else node.name


def _location(node: Node) -> str:
    line = int(node.attributes.get("line", 0) or 0)
    return f"{node.path}:{line}" if line else node.path


def _type_id(graph: ProjectGraph, name: str) -> str:
    return next(
        (
            node.id for node in graph.nodes.values()
            if node.kind in {NodeKind.CLASS, NodeKind.MONO_BEHAVIOUR} and node.name == name
        ),
        "",
    )


def _symbol_index(graph: ProjectGraph) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for node in graph.nodes.values():
        for value in (node.id, node.name, _symbol(node)):
            if value:
                index.setdefault(value.casefold(), set()).add(node.id)
    return index


def _is_ui_path(path: str) -> bool:
    value = path.replace("\\", "/").casefold()
    return "/ui/" in value or value.rsplit("/", 1)[-1].endswith("ui.cs")


def _is_ui_effect(node: Node) -> bool:
    return _is_ui_path(node.path) and any(
        token in node.name.casefold() for token in ("show", "hide", "update", "refresh")
    )


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").lstrip("./").casefold()


def _slot_status(values: list[dict[str, Any]]) -> str:
    polarities = {str(value.get("polarity", "")) for value in values}
    if "absent" in polarities:
        return "absent"
    if "present" in polarities:
        return "present"
    return "unknown"


def _deduplicate_facts(facts: list[CausalFact]) -> list[CausalFact]:
    return list({fact.fact_id: fact for fact in facts}.values())


def _negative_evidence_matches(supplied: Any, expected: NegativeEvidence) -> bool:
    if supplied is None:
        return False
    return all(
        getattr(supplied, key, None) == value
        for key, value in asdict(expected).items()
    )


def _graph_digest(graph: ProjectGraph) -> str:
    parts = [
        *(f"n:{node.id}" for node in graph.nodes.values()),
        *(
            f"e:{edge.source}:{edge.kind.value}:{edge.target}"
            for edge in graph.edges
        ),
    ]
    return "graph:" + hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()[:16]
