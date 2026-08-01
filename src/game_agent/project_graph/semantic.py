from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping


class SemanticSearchUnavailable(RuntimeError):
    """Raised when optional multilingual embedding support cannot be loaded."""


class MultilingualSemanticIndex:
    """Small, file-level multilingual embedding index with an atomic NPZ cache."""

    def __init__(
        self,
        documents: Mapping[str, str],
        *,
        model_name: str,
        cache_path: Path | None = None,
        encoder: Any | None = None,
    ) -> None:
        self.documents = dict(sorted(documents.items()))
        self.model_name = model_name
        self.cache_path = cache_path.resolve() if cache_path else None
        self.encoder = encoder
        self._paths = list(self.documents)
        self._embeddings: Any | None = None
        self.cache_hit = False

    def score(self, query: str) -> dict[str, float]:
        if not query.strip() or not self.documents:
            return {}
        np = self._numpy()
        encoder = self.encoder or self._load_encoder()
        embeddings = self._corpus_embeddings(encoder, np)
        query_embedding = encoder.encode(
            [query],
            batch_size=1,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )[0]
        similarities = embeddings @ query_embedding
        return {
            path: max(0.0, float(score))
            for path, score in zip(self._paths, similarities)
        }

    def metadata(self) -> dict[str, Any]:
        return {
            "status": "enabled",
            "model": self.model_name,
            "documents": len(self.documents),
            "cache_hit": self.cache_hit,
            "cache_path": str(self.cache_path) if self.cache_path else "",
        }

    def _corpus_embeddings(self, encoder: Any, np: Any) -> Any:
        if self._embeddings is not None:
            return self._embeddings
        fingerprint = self._fingerprint()
        if self.cache_path and self.cache_path.is_file():
            try:
                cached = np.load(self.cache_path, allow_pickle=False)
                cached_fingerprint = str(cached["fingerprint"].item())
                cached_paths = [str(value) for value in cached["paths"].tolist()]
                if cached_fingerprint == fingerprint and cached_paths == self._paths:
                    self._embeddings = cached["embeddings"]
                    self.cache_hit = True
                    return self._embeddings
            except (OSError, ValueError, KeyError):
                pass
        self._embeddings = encoder.encode(
            [self.documents[path] for path in self._paths],
            batch_size=32,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
            try:
                with temporary.open("wb") as handle:
                    np.savez_compressed(
                        handle,
                        fingerprint=np.asarray(fingerprint),
                        paths=np.asarray(self._paths),
                        embeddings=self._embeddings,
                    )
                temporary.replace(self.cache_path)
            except OSError:
                temporary.unlink(missing_ok=True)
        return self._embeddings

    def _fingerprint(self) -> str:
        digest = hashlib.sha256(self.model_name.encode("utf-8"))
        for path, document in self.documents.items():
            digest.update(path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(document.encode("utf-8", errors="replace"))
            digest.update(b"\0")
        return digest.hexdigest()

    @staticmethod
    def _numpy() -> Any:
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover - sentence-transformers brings numpy
            raise SemanticSearchUnavailable("numpy is required for semantic search") from exc
        return np

    def _load_encoder(self) -> Any:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise SemanticSearchUnavailable(
                "Install the 'semantic' optional dependency to enable multilingual search."
            ) from exc
        try:
            self.encoder = SentenceTransformer(self.model_name)
        except Exception as exc:  # model loading can fail offline or for an invalid cache
            raise SemanticSearchUnavailable(
                f"Could not load semantic model {self.model_name!r}: {exc}"
            ) from exc
        return self.encoder


def semantic_cache_name(model_name: str) -> str:
    slug = "".join(character if character.isalnum() else "-" for character in model_name)
    return f"semantic-{slug.strip('-').casefold()}.npz"
