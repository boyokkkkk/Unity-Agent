from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import networkx as nx

from .schema import CAUSAL_EDGE_KINDS, EdgeKind, Node, NodeKind, ProjectGraph
from .semantic import MultilingualSemanticIndex, SemanticSearchUnavailable


TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]*|[\u4e00-\u9fff]")
CODE_KINDS = {
    NodeKind.CSHARP_FILE,
    NodeKind.CLASS,
    NodeKind.MONO_BEHAVIOUR,
    NodeKind.METHOD,
    NodeKind.FIELD,
}
ASSET_KINDS = {NodeKind.SCENE, NodeKind.PREFAB, NodeKind.ASSET}


def tokenize(text: str) -> list[str]:
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    expanded = expanded.replace("_", " ")
    return [match.group(0).casefold() for match in TOKEN_PATTERN.finditer(expanded)]


def _node_text(node: Node) -> str:
    values = [node.name, node.path]
    for key, value in node.attributes.items():
        if key in {
            "hierarchy_path",
            "type_name",
            "declaring_type",
            "field_type",
            "script_path",
            "bases",
            "attributes",
        }:
            values.append(str(value))
    return " ".join(values)


class TextIndex:
    def __init__(self, documents: dict[str, str]):
        self.documents = documents
        self.term_frequencies = {
            key: Counter(tokenize(value)) for key, value in documents.items()
        }
        self.lengths = {
            key: sum(frequencies.values())
            for key, frequencies in self.term_frequencies.items()
        }
        self.average_length = (
            sum(self.lengths.values()) / len(self.lengths) if self.lengths else 1.0
        )
        document_frequency: Counter[str] = Counter()
        for frequencies in self.term_frequencies.values():
            document_frequency.update(frequencies.keys())
        self.document_frequency = document_frequency

    def score(self, query: str) -> dict[str, float]:
        query_terms = Counter(tokenize(query))
        count = max(len(self.documents), 1)
        scores: dict[str, float] = {}
        for key, frequencies in self.term_frequencies.items():
            score = 0.0
            length = self.lengths[key]
            for term, query_frequency in query_terms.items():
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                df = self.document_frequency.get(term, 0)
                inverse = math.log(1 + (count - df + 0.5) / (df + 0.5))
                denominator = frequency + 1.2 * (
                    1 - 0.75 + 0.75 * length / max(self.average_length, 1.0)
                )
                score += query_frequency * inverse * frequency * 2.2 / denominator
            if score > 0:
                scores[key] = score
        return scores


@dataclass(slots=True)
class LocalizationResult:
    variant: str
    strategy: str
    files: list[dict[str, Any]]
    game_objects: list[dict[str, Any]]
    assets: list[dict[str, Any]]
    ranked_nodes: list[dict[str, Any]]
    dependency_paths: list[dict[str, Any]]
    semantic: dict[str, Any] = field(default_factory=dict)
    treatment: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant": self.variant,
            "strategy": self.strategy,
            "files": self.files,
            "game_objects": self.game_objects,
            "assets": self.assets,
            "ranked_nodes": self.ranked_nodes,
            "dependency_paths": self.dependency_paths,
            "semantic": self.semantic,
            "treatment": self.treatment,
        }


class LocalizationRetriever:
    def __init__(
        self,
        graph: ProjectGraph,
        project_path: Path,
        *,
        semantic_encoder: Any | None = None,
    ):
        self.graph = graph
        self.project_path = project_path.resolve()
        self.file_documents = self._load_file_documents()
        self.file_index = TextIndex(self.file_documents)
        self.node_index = TextIndex(
            {node.id: _node_text(node) for node in graph.nodes.values()}
        )
        self.semantic_encoder = semantic_encoder
        self._semantic_indexes: dict[tuple[str, str], MultilingualSemanticIndex] = {}
        self.semantic_documents = self._semantic_documents()
        self.one_hop: dict[str, set[str]] = defaultdict(set)
        for edge in graph.edges:
            self.one_hop[edge.source].add(edge.target)
            self.one_hop[edge.target].add(edge.source)

    def retrieve(
        self,
        query: str,
        variant: str,
        *,
        limit: int = 20,
        strategy: str = "relevance",
        max_test_candidates: int = 1,
        mmr_lambda: float = 0.82,
        semantic_model: str = "",
        semantic_weight: float = 0.35,
        semantic_cache_path: Path | None = None,
        graph_retrieval_enabled: bool = True,
        causal_edges_enabled: bool = True,
    ) -> LocalizationResult:
        variant = variant.upper()
        requested_variant = variant
        if not graph_retrieval_enabled:
            variant = "A0"
        if strategy not in {"relevance", "path_collapse", "path_quota", "role_mmr"}:
            raise ValueError(
                "strategy must be relevance, path_collapse, path_quota, or role_mmr"
            )
        semantic_weight = max(0.0, min(1.0, semantic_weight))
        semantic_scores, semantic_metadata = self._semantic_scores(
            query,
            model_name=semantic_model,
            cache_path=semantic_cache_path,
        )
        semantic_metadata["weight"] = semantic_weight if semantic_model else 0.0
        if variant == "A0":
            result = self._a0(
                query,
                limit,
                strategy=strategy,
                max_test_candidates=max_test_candidates,
                mmr_lambda=mmr_lambda,
                semantic_scores=semantic_scores,
                semantic_metadata=semantic_metadata,
                semantic_weight=semantic_weight,
            )
            result.treatment = self._treatment_metadata(
                requested_variant=requested_variant,
                effective_variant=variant,
                graph_retrieval_enabled=graph_retrieval_enabled,
                causal_edges_enabled=causal_edges_enabled,
                result=result,
                semantic_model=semantic_model,
                semantic_scores=semantic_scores,
            )
            return result
        if variant not in {"A1", "A2"}:
            raise ValueError("variant must be A0, A1, or A2")
        result = self._graph_variant(
            query,
            variant,
            limit,
            strategy=strategy,
            max_test_candidates=max_test_candidates,
            mmr_lambda=mmr_lambda,
            semantic_scores=semantic_scores,
            semantic_metadata=semantic_metadata,
            semantic_weight=semantic_weight,
            causal_edges_enabled=causal_edges_enabled,
        )
        result.treatment = self._treatment_metadata(
            requested_variant=requested_variant,
            effective_variant=variant,
            graph_retrieval_enabled=graph_retrieval_enabled,
            causal_edges_enabled=causal_edges_enabled,
            result=result,
            semantic_model=semantic_model,
            semantic_scores=semantic_scores,
        )
        return result

    def _load_file_documents(self) -> dict[str, str]:
        documents: dict[str, str] = {}
        for node in self.graph.iter_nodes({NodeKind.CSHARP_FILE}):
            target = self.project_path / node.path
            text = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
            documents[node.path] = f"{node.path}\n{text}"
        return documents

    def _a0(
        self,
        query: str,
        limit: int,
        *,
        strategy: str,
        max_test_candidates: int,
        mmr_lambda: float,
        semantic_scores: dict[str, float],
        semantic_metadata: dict[str, Any],
        semantic_weight: float,
    ) -> LocalizationResult:
        file_scores = self.file_index.score(query)
        if semantic_scores:
            file_scores = _blend_scores(file_scores, semantic_scores, semantic_weight)
        files = _rank_items(file_scores, limit, key_name="path")
        files = self._diversify_rows(
            files,
            limit=limit,
            strategy="path_quota" if strategy == "role_mmr" else strategy,
            max_test_candidates=max_test_candidates,
            mmr_lambda=mmr_lambda,
        )
        return LocalizationResult(
            variant="A0",
            strategy=strategy,
            files=files,
            game_objects=[],
            assets=[],
            ranked_nodes=[],
            dependency_paths=[],
            semantic=semantic_metadata,
        )

    def _graph_variant(
        self,
        query: str,
        variant: str,
        limit: int,
        *,
        strategy: str,
        max_test_candidates: int,
        mmr_lambda: float,
        semantic_scores: dict[str, float],
        semantic_metadata: dict[str, Any],
        semantic_weight: float,
        causal_edges_enabled: bool,
    ) -> LocalizationResult:
        allowed_nodes = CODE_KINDS if variant == "A1" else set(NodeKind)
        allowed_edges = {
            EdgeKind.CALLS,
            EdgeKind.SUBSCRIBES_TO,
            EdgeKind.PUBLISHES_EVENT,
            EdgeKind.WRITES_STATE,
        } if variant == "A1" else set(EdgeKind)
        if not causal_edges_enabled:
            allowed_edges -= CAUSAL_EDGE_KINDS
        network = nx.DiGraph()
        for node in self.graph.nodes.values():
            if node.kind in allowed_nodes:
                network.add_node(node.id)
        for edge in self.graph.edges:
            if (
                edge.kind in allowed_edges
                and edge.source in network
                and edge.target in network
            ):
                weight = _edge_weight(edge.kind)
                _add_relation(network, edge.source, edge.target, edge.kind.value, weight)
                _add_relation(network, edge.target, edge.source, edge.kind.value, weight * 0.8)
        if variant == "A2":
            self._add_code_component_bridges(network)

        lexical = self.node_index.score(query)
        file_scores = self.file_index.score(query)
        if semantic_scores:
            file_scores = _blend_scores(file_scores, semantic_scores, semantic_weight)
        personalization: dict[str, float] = {}
        for node_id in network:
            node = self.graph.nodes[node_id]
            score = lexical.get(node_id, 0.0)
            if node.path:
                score += file_scores.get(node.path, 0.0)
            if node.kind == NodeKind.CSHARP_FILE:
                score += file_scores.get(node.path, 0.0)
            if score > 0:
                personalization[node_id] = score
        if not personalization:
            personalization = {node_id: 1.0 for node_id in network}
        total = sum(personalization.values()) or 1.0
        personalization = {
            node_id: score / total for node_id, score in personalization.items()
        }
        scores = personalized_rank(
            network,
            personalization,
            alpha=0.72,
            max_iter=200,
        ) if network else {}
        combined = {
            node_id: score + 0.35 * personalization.get(node_id, 0.0)
            for node_id, score in scores.items()
        }
        ranked_node_ids = sorted(
            combined,
            key=lambda node_id: (-combined[node_id], node_id),
        )
        diversified_ids = self._diversify_node_ids(
            ranked_node_ids,
            combined,
            lexical_scores=lexical,
            limit=limit,
            strategy=strategy,
            max_test_candidates=max_test_candidates,
            mmr_lambda=mmr_lambda,
        )
        ranked_nodes = [
            {
                "id": node_id,
                "kind": self.graph.nodes[node_id].kind.value,
                "name": self.graph.nodes[node_id].name,
                "path": self.graph.nodes[node_id].path,
                "score": combined[node_id],
                "role": _path_role(self.graph.nodes[node_id].path),
                "subsystem": _path_subsystem(self.graph.nodes[node_id].path),
            }
            for node_id in diversified_ids
        ]
        files = self._aggregate_files(
            ranked_node_ids,
            combined,
            file_scores,
            max(limit * 4, limit),
        )
        files = self._diversify_rows(
            files,
            limit=limit,
            strategy="path_quota" if strategy == "role_mmr" else strategy,
            max_test_candidates=max_test_candidates,
            mmr_lambda=mmr_lambda,
        )
        game_objects = [
            _node_result(self.graph.nodes[node_id], combined[node_id])
            for node_id in ranked_node_ids
            if self.graph.nodes[node_id].kind == NodeKind.GAME_OBJECT
        ][:limit]
        assets = [
            _node_result(self.graph.nodes[node_id], combined[node_id])
            for node_id in ranked_node_ids
            if (
                self.graph.nodes[node_id].kind in ASSET_KINDS
                and self.graph.nodes[node_id].path.startswith("Assets/")
            )
        ][:limit]
        paths = self._top_dependency_paths(network, ranked_node_ids, personalization, limit=limit)
        return LocalizationResult(
            variant=variant,
            strategy=strategy,
            files=files,
            game_objects=game_objects,
            assets=assets,
            ranked_nodes=ranked_nodes,
            dependency_paths=paths,
            semantic=semantic_metadata,
        )

    def _treatment_metadata(
        self,
        *,
        requested_variant: str,
        effective_variant: str,
        graph_retrieval_enabled: bool,
        causal_edges_enabled: bool,
        result: LocalizationResult,
        semantic_model: str,
        semantic_scores: dict[str, float],
    ) -> dict[str, Any]:
        source_causal_edges = sum(
            1 for edge in self.graph.edges if edge.kind in CAUSAL_EDGE_KINDS
        )
        graph_active = graph_retrieval_enabled and effective_variant in {"A1", "A2"}
        return {
            "retrieval_opportunity": 1,
            "requested_variant": requested_variant,
            "effective_variant": effective_variant,
            "graph_retrieval_enabled": graph_retrieval_enabled,
            "graph_score_contributions": len(result.ranked_nodes) if graph_active else 0,
            "graph_expansions": len(result.dependency_paths) if graph_active else 0,
            "semantic_opportunity": 1,
            "semantic_enabled": bool(semantic_model),
            "semantic_score_contributions": len(semantic_scores) if semantic_model else 0,
            "semantic_status": str(result.semantic.get("status", "disabled")),
            "semantic_reason": str(result.semantic.get("reason", "")),
            "semantic_model": str(result.semantic.get("model", semantic_model)),
            "source_causal_edges": source_causal_edges,
            "returned_causal_edges": source_causal_edges if graph_active and causal_edges_enabled else 0,
            "suppressed_causal_edges": source_causal_edges if graph_active and not causal_edges_enabled else 0,
            "noncausal_graph_candidates": len(result.ranked_nodes) if graph_active else 0,
        }

    def _semantic_scores(
        self,
        query: str,
        *,
        model_name: str,
        cache_path: Path | None,
    ) -> tuple[dict[str, float], dict[str, Any]]:
        if not model_name:
            return {}, {"status": "disabled", "model": ""}
        cache_key = (model_name, str(cache_path.resolve()) if cache_path else "")
        index = self._semantic_indexes.get(cache_key)
        if index is None:
            index = MultilingualSemanticIndex(
                self.semantic_documents,
                model_name=model_name,
                cache_path=cache_path,
                encoder=self.semantic_encoder,
            )
            self._semantic_indexes[cache_key] = index
        try:
            return index.score(query), index.metadata()
        except SemanticSearchUnavailable as exc:
            return {}, {
                "status": "unavailable",
                "model": model_name,
                "reason": str(exc),
            }

    def _semantic_documents(self) -> dict[str, str]:
        summaries: dict[str, list[str]] = defaultdict(list)
        for node in self.graph.nodes.values():
            if not node.path.casefold().endswith(".cs"):
                continue
            attributes = " ".join(
                str(node.attributes.get(key, ""))
                for key in ("declaring_type", "field_type", "return_type", "bases")
            )
            summaries[node.path].append(
                f"{node.kind.value} {node.name} {attributes}".strip()
            )
        relation_phrases = {
            EdgeKind.CALLS: "calls",
            EdgeKind.SUBSCRIBES_TO: "subscribes to event",
            EdgeKind.PUBLISHES_EVENT: "publishes event",
            EdgeKind.WRITES_STATE: "writes state field",
        }
        for edge in self.graph.edges:
            phrase = relation_phrases.get(edge.kind)
            source = self.graph.nodes.get(edge.source)
            target = self.graph.nodes.get(edge.target)
            if not phrase or source is None or target is None:
                continue
            relation = f"{source.name} {phrase} {target.name}"
            if source.path.casefold().endswith(".cs"):
                summaries[source.path].append(relation)
            if target.path.casefold().endswith(".cs") and target.path != source.path:
                summaries[target.path].append(relation)
        documents: dict[str, str] = {}
        for path, source_document in self.file_documents.items():
            structural = "\n".join(dict.fromkeys(summaries.get(path, [])))
            documents[path] = f"{path}\n{structural}\n{source_document}"[:50000]
        return documents

    def _diversify_node_ids(
        self,
        ranked: list[str],
        scores: dict[str, float],
        *,
        lexical_scores: dict[str, float],
        limit: int,
        strategy: str,
        max_test_candidates: int,
        mmr_lambda: float,
    ) -> list[str]:
        if strategy == "relevance":
            return ranked[:limit]
        candidates = ranked[: max(limit * 8, 40)]
        rows = [
            {
                "id": node_id,
                "path": self.graph.nodes[node_id].path,
                "kind": self.graph.nodes[node_id].kind.value,
                "score": scores[node_id],
                "lexical_score": lexical_scores.get(node_id, 0.0),
                "neighbors": sorted(self.one_hop.get(node_id, set())),
            }
            for node_id in candidates
        ]
        return [
            str(row["id"])
            for row in self._diversify_rows(
                rows,
                limit=limit,
                strategy=strategy,
                max_test_candidates=max_test_candidates,
                mmr_lambda=mmr_lambda,
            )
        ]

    @staticmethod
    def _diversify_rows(
        rows: list[dict[str, Any]],
        *,
        limit: int,
        strategy: str,
        max_test_candidates: int,
        mmr_lambda: float,
    ) -> list[dict[str, Any]]:
        enriched = [
            {
                **row,
                "role": _path_role(str(row.get("path", ""))),
                "subsystem": _path_subsystem(str(row.get("path", ""))),
            }
            for row in rows
        ]
        if strategy == "relevance":
            return enriched[:limit]
        collapsed: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for row in enriched:
            path_key = _normalized_candidate_path(row)
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)
            collapsed.append(row)
        if strategy == "path_collapse":
            return collapsed[:limit]
        if strategy == "path_quota":
            return _apply_test_quota(collapsed, limit, max_test_candidates)

        pool = list(collapsed)
        selected: list[dict[str, Any]] = []
        maximum = max((float(row.get("score", 0.0)) for row in pool), default=1.0)
        lexical_maximum = max(
            (float(row.get("lexical_score", 0.0)) for row in pool),
            default=1.0,
        )
        required_implementation = min(
            4,
            limit,
            sum(row["role"] == "implementation" for row in pool),
        )
        while pool and len(selected) < limit:
            eligible = [
                row for row in pool
                if row["role"] != "test"
                or sum(item["role"] == "test" for item in selected) < max_test_candidates
            ]
            selected_implementation = sum(
                item["role"] == "implementation" for item in selected
            )
            if selected_implementation < required_implementation:
                implementation = [
                    row for row in eligible if row["role"] == "implementation"
                ]
                if implementation:
                    eligible = implementation
            if not eligible:
                break
            best = max(
                eligible,
                key=lambda row: (
                    mmr_lambda * float(row.get("score", 0.0)) / max(maximum, 1e-12)
                    - (1.0 - mmr_lambda) * max(
                        (_candidate_similarity(row, chosen) for chosen in selected),
                        default=0.0,
                    )
                    + 0.15 * float(row.get("lexical_score", 0.0))
                    / max(lexical_maximum, 1e-12)
                    + 0.05 * float(any(
                        str(chosen.get("id", "")) in set(row.get("neighbors", []))
                        for chosen in selected
                    )),
                    float(row.get("score", 0.0)),
                    str(row.get("id", row.get("path", ""))),
                ),
            )
            selected.append(best)
            pool.remove(best)
        return selected

    def _add_code_component_bridges(self, network: nx.DiGraph) -> None:
        for node in self.graph.nodes.values():
            if node.kind != NodeKind.COMPONENT:
                continue
            symbol_id = str(node.attributes.get("code_symbol_id", ""))
            if symbol_id in network and node.id in network:
                _add_relation(network, symbol_id, node.id, "CODE_COMPONENT", 1.3)
                _add_relation(network, node.id, symbol_id, "CODE_COMPONENT", 1.3)

    def _aggregate_files(
        self,
        ranked_node_ids: list[str],
        scores: dict[str, float],
        lexical_file_scores: dict[str, float],
        limit: int,
    ) -> list[dict[str, Any]]:
        graph_file_scores: dict[str, float] = defaultdict(float)
        for node_id in ranked_node_ids:
            node = self.graph.nodes[node_id]
            candidates = []
            if node.kind in CODE_KINDS and node.path.endswith(".cs"):
                candidates.append(node.path)
            script = str(node.attributes.get("script_path", ""))
            if script.endswith(".cs"):
                candidates.append(script)
            for path in candidates:
                graph_file_scores[path] = max(graph_file_scores[path], scores[node_id])
        graph_max = max(graph_file_scores.values(), default=1.0)
        lexical_max = max(lexical_file_scores.values(), default=1.0)
        candidates = set(graph_file_scores) | set(lexical_file_scores)
        fused = {
            path: (
                0.65 * lexical_file_scores.get(path, 0.0) / lexical_max
                + 0.35 * graph_file_scores.get(path, 0.0) / graph_max
            )
            for path in candidates
        }
        return _rank_items(fused, limit, key_name="path")

    def _top_dependency_paths(
        self,
        network: nx.DiGraph,
        ranked: list[str],
        personalization: dict[str, float],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        seeds = [
            node_id
            for node_id in sorted(personalization, key=personalization.get, reverse=True)
            if node_id in network
        ][:30]
        targets = [
            node_id for node_id in ranked
            if self.graph.nodes[node_id].kind in {NodeKind.GAME_OBJECT, *ASSET_KINDS}
            and (
                self.graph.nodes[node_id].kind == NodeKind.GAME_OBJECT
                or self.graph.nodes[node_id].path.startswith("Assets/")
            )
        ][:30]
        results: list[tuple[float, dict[str, Any]]] = []
        seen: set[tuple[str, ...]] = set()
        for source in seeds:
            for target in targets:
                if source == target:
                    continue
                try:
                    path = nx.shortest_path(network, source, target)
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    continue
                if len(path) > 6:
                    continue
                signature = tuple(path)
                if signature in seen:
                    continue
                seen.add(signature)
                edge_kinds = [
                    str(network[path[index]][path[index + 1]].get("kind", ""))
                    for index in range(len(path) - 1)
                ]
                target_rank = targets.index(target)
                path_score = (
                    personalization.get(source, 0.0)
                    + 1.0 / (target_rank + 1)
                    + 0.15 / len(path)
                )
                results.append(
                    (path_score, {
                        "node_ids": path,
                        "node_names": [self.graph.nodes[node_id].name for node_id in path],
                        "edge_kinds": edge_kinds,
                    })
                )
        return [
            item
            for _, item in sorted(results, key=lambda pair: -pair[0])[:limit]
        ]


def _edge_weight(kind: EdgeKind) -> float:
    return {
        EdgeKind.CALLS: 1.0,
        EdgeKind.SUBSCRIBES_TO: 1.5,
        EdgeKind.PUBLISHES_EVENT: 1.6,
        EdgeKind.WRITES_STATE: 1.5,
        EdgeKind.ATTACHED_TO: 1.4,
        EdgeKind.CONTAINS: 1.1,
        EdgeKind.PREFAB_SOURCE: 1.3,
        EdgeKind.SERIALIZED_REF: 1.6,
        EdgeKind.UNITY_EVENT_CALL: 1.7,
    }[kind]


RELATION_PRIORITY = {
    "CODE_COMPONENT": 0,
    EdgeKind.SUBSCRIBES_TO.value: 1,
    EdgeKind.PUBLISHES_EVENT.value: 2,
    EdgeKind.WRITES_STATE.value: 3,
    EdgeKind.ATTACHED_TO.value: 4,
    EdgeKind.CONTAINS.value: 5,
    EdgeKind.PREFAB_SOURCE.value: 6,
    EdgeKind.SERIALIZED_REF.value: 7,
    EdgeKind.UNITY_EVENT_CALL.value: 8,
    EdgeKind.CALLS.value: 9,
}


def _add_relation(
    network: nx.DiGraph,
    source: str,
    target: str,
    kind: str,
    weight: float,
) -> None:
    if not network.has_edge(source, target):
        network.add_edge(source, target, weight=weight, kind=kind, kinds=[kind])
        return
    data = network[source][target]
    kinds = list(data.get("kinds", [data.get("kind", "")]))
    if kind not in kinds:
        kinds.append(kind)
    data["kinds"] = kinds
    data["weight"] = max(float(data.get("weight", 1.0)), weight)
    data["kind"] = min(kinds, key=lambda value: RELATION_PRIORITY.get(value, 99))


def personalized_rank(
    network: nx.DiGraph,
    personalization: dict[str, float],
    *,
    alpha: float,
    max_iter: int,
    tolerance: float = 1e-10,
) -> dict[str, float]:
    """Dependency-light weighted personalized PageRank over a NetworkX graph."""
    nodes = list(network)
    if not nodes:
        return {}
    teleport_total = sum(personalization.get(node, 0.0) for node in nodes)
    if teleport_total <= 0:
        teleport = {node: 1.0 / len(nodes) for node in nodes}
    else:
        teleport = {
            node: personalization.get(node, 0.0) / teleport_total
            for node in nodes
        }
    rank = dict(teleport)
    for _ in range(max_iter):
        updated = {node: (1.0 - alpha) * teleport[node] for node in nodes}
        dangling = 0.0
        for source in nodes:
            outgoing = list(network.out_edges(source, data=True))
            total_weight = sum(float(data.get("weight", 1.0)) for _, _, data in outgoing)
            if total_weight <= 0:
                dangling += rank[source]
                continue
            for _, target, data in outgoing:
                updated[target] += (
                    alpha
                    * rank[source]
                    * float(data.get("weight", 1.0))
                    / total_weight
                )
        if dangling:
            for node in nodes:
                updated[node] += alpha * dangling * teleport[node]
        delta = sum(abs(updated[node] - rank.get(node, 0.0)) for node in nodes)
        rank = updated
        if delta < tolerance:
            break
    return rank


def _rank_items(
    scores: dict[str, float],
    limit: int,
    *,
    key_name: str,
) -> list[dict[str, Any]]:
    return [
        {key_name: key, "score": score}
        for key, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _blend_scores(
    lexical_scores: dict[str, float],
    semantic_scores: dict[str, float],
    semantic_weight: float,
) -> dict[str, float]:
    """Blend independently normalized lexical and multilingual similarities."""
    lexical_maximum = max(lexical_scores.values(), default=0.0)
    semantic_maximum = max(semantic_scores.values(), default=0.0)
    keys = set(lexical_scores) | set(semantic_scores)
    return {
        key: (
            (1.0 - semantic_weight)
            * lexical_scores.get(key, 0.0)
            / max(lexical_maximum, 1e-12)
            + semantic_weight
            * semantic_scores.get(key, 0.0)
            / max(semantic_maximum, 1e-12)
        )
        for key in keys
        if lexical_scores.get(key, 0.0) > 0 or semantic_scores.get(key, 0.0) > 0
    }


def _node_result(node: Node, score: float) -> dict[str, Any]:
    return {
        "id": node.id,
        "name": node.name,
        "path": node.path,
        "hierarchy_path": node.attributes.get("hierarchy_path", ""),
        "kind": node.kind.value,
        "score": score,
    }


def _path_role(path: str) -> str:
    normalized = path.replace("\\", "/").casefold()
    if "/tests/" in f"/{normalized}/" or normalized.endswith("tests.cs"):
        return "test"
    if normalized.endswith(".cs"):
        return "implementation"
    if normalized:
        return "asset"
    return "unknown"


def _path_subsystem(path: str) -> str:
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    lowered = [part.casefold() for part in parts]
    if "tests" in lowered:
        index = lowered.index("tests")
        return "/".join(parts[index : index + 2]).casefold()
    if "scripts" in lowered:
        index = lowered.index("scripts")
        following = parts[index + 1 : index + 2]
        return (following[0] if following else "scripts-root").casefold()
    return (parts[1] if len(parts) > 1 else parts[0] if parts else "unknown").casefold()


def _normalized_candidate_path(row: dict[str, Any]) -> str:
    path = str(row.get("path", "")).replace("\\", "/").casefold()
    return path or f"node:{row.get('id', row.get('name', ''))}"


def _candidate_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    if _normalized_candidate_path(left) == _normalized_candidate_path(right):
        return 1.0
    similarity = 0.0
    if left.get("role") == right.get("role"):
        similarity += 0.35
    if left.get("subsystem") == right.get("subsystem"):
        similarity += 0.4
    if left.get("kind") and left.get("kind") == right.get("kind"):
        similarity += 0.15
    return min(1.0, similarity)


def _apply_test_quota(
    rows: list[dict[str, Any]],
    limit: int,
    max_test_candidates: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    tests = 0
    for row in rows:
        if row["role"] == "test":
            if tests >= max_test_candidates:
                continue
            tests += 1
        selected.append(row)
        if len(selected) >= limit:
            break
    return selected
