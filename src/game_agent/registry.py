from __future__ import annotations

import re
import threading
from collections.abc import Callable
from typing import Any


NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")
COMPONENT_KINDS = {"agent", "environment", "model", "benchmark_adapter"}


class ComponentRegistry:
    """Explicit allow-list registry; it never imports user-provided module paths."""

    def __init__(self) -> None:
        self._components: dict[str, dict[str, Callable[..., Any]]] = {
            kind: {} for kind in COMPONENT_KINDS
        }
        self._lock = threading.RLock()

    def register(
        self,
        kind: str,
        name: str,
        factory: Callable[..., Any],
        *,
        replace: bool = False,
    ) -> None:
        if kind not in COMPONENT_KINDS:
            raise ValueError(f"Unknown component kind: {kind}")
        if not NAME_PATTERN.fullmatch(name):
            raise ValueError(f"Invalid component name: {name}")
        if not callable(factory):
            raise TypeError("Component factory must be callable")
        with self._lock:
            if name in self._components[kind] and not replace:
                if self._components[kind][name] is factory:
                    return
                raise ValueError(f"Component already registered: {kind}:{name}")
            self._components[kind][name] = factory

    def resolve(self, kind: str, name: str) -> Callable[..., Any]:
        if kind not in COMPONENT_KINDS:
            raise ValueError(f"Unknown component kind: {kind}")
        with self._lock:
            factory = self._components[kind].get(name)
            available = sorted(self._components[kind])
        if factory is None:
            raise ValueError(f"Unknown {kind} component: {name}. Available: {available}")
        return factory

    def create(self, kind: str, name: str, /, *args: Any, **kwargs: Any) -> Any:
        return self.resolve(kind, name)(*args, **kwargs)

    def names(self, kind: str) -> list[str]:
        if kind not in COMPONENT_KINDS:
            raise ValueError(f"Unknown component kind: {kind}")
        with self._lock:
            return sorted(self._components[kind])

    def snapshot(self) -> dict[str, list[str]]:
        return {kind: self.names(kind) for kind in sorted(COMPONENT_KINDS)}


COMPONENTS = ComponentRegistry()

