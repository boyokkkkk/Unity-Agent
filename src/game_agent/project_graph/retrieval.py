from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import networkx as nx

from .schema import EdgeKind, Node, NodeKind, ProjectGraph


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant": self.variant,
            "strategy": self.strategy,
            "files": self.files,
            "game_objects": self.game_objects,
            "assets": self.assets,
            "ranked_nodes": self.ranked_nodes,
            "dependency_paths": self.dependency_paths,
        }


class LocalizationRetriever:
    def __init__(self, graph: ProjectGraph, project_path: Path):
        self.graph = graph
        self.project_path = project_path.resolve()
        self.file_documents = self._load_file_documents()
        self.file_index = TextIndex(self.file_documents)
        self.node_index = TextIndex(
            {node.id: _node_text(node) for node in graph.nodes.values()}
        )
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
    ) -> LocalizationResult:
        variant = variant.upper()
        if strategy not in {"relevance", "path_collapse", "path_quota", "role_mmr"}:
            raise ValueError(
                "strategy must be relevance, path_collapse, path_quota, or role_mmr"
            )
        if variant == "A0":
            return self._a0(
                query,
                limit,
                strategy=strategy,
                max_test_candidates=max_test_candidates,
                mmr_lambda=mmr_lambda,
            )
        if variant not in {"A1", "A2"}:
            raise ValueError("variant must be A0, A1, or A2")
        return self._graph_variant(
            query,
            variant,
            limit,
            strategy=strategy,
            max_test_candidates=max_test_candidates,
            mmr_lambda=mmr_lambda,
        )

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
    ) -> LocalizationResult:
        file_scores = self.file_index.score(query)
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
    ) -> LocalizationResult:
        allowed_nodes = CODE_KINDS if variant == "A1" else set(NodeKind)
        allowed_edges = {EdgeKind.CALLS} if variant == "A1" else set(EdgeKind)
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
        )

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
        EdgeKind.ATTACHED_TO: 1.4,
        EdgeKind.CONTAINS: 1.1,
        EdgeKind.PREFAB_SOURCE: 1.3,
        EdgeKind.SERIALIZED_REF: 1.6,
        EdgeKind.UNITY_EVENT_CALL: 1.7,
    }[kind]


RELATION_PRIORITY = {
    "CODE_COMPONENT": 0,
    EdgeKind.ATTACHED_TO.value: 1,
    EdgeKind.CONTAINS.value: 2,
    EdgeKind.PREFAB_SOURCE.value: 3,
    EdgeKind.SERIALIZED_REF.value: 4,
    EdgeKind.UNITY_EVENT_CALL.value: 5,
    EdgeKind.CALLS.value: 6,
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
