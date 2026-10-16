"""Analyzer registry: the single place that knows which tools exist.

Adding a language or a tool means registering one `AnalyzerSpec` here (see
`build_default_registry`); the orchestrator, the file inventory and the API all
read applicability from the registry instead of hard-coding tool names.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Iterable, Optional

from app.analysis.analyzers.base import Analyzer, AnalyzerContext


@dataclass(frozen=True)
class AnalyzerSpec:
    """What an analyzer is, and what it can do."""

    name: str
    languages: frozenset[str]
    # "lint" | "security" | "metrics" — used by the risk evaluator to tell a
    # security signal from a code-quality one.
    category: str
    capabilities: frozenset[str]
    executable: str

    def applies_to(self, language: str) -> bool:
        return language in self.languages


@dataclass(frozen=True)
class RegisteredAnalyzer:
    spec: AnalyzerSpec
    factory: Callable[[AnalyzerContext], Analyzer]


class AnalyzerRegistry:
    """Deterministic, ordered registry of analyzers."""

    def __init__(self) -> None:
        self._entries: dict[str, RegisteredAnalyzer] = {}

    def register(self, spec: AnalyzerSpec, factory: Callable[[AnalyzerContext], Analyzer]) -> None:
        if spec.name in self._entries:
            raise ValueError(f"analyzer already registered: {spec.name}")
        self._entries[spec.name] = RegisteredAnalyzer(spec=spec, factory=factory)

    def get(self, name: str) -> RegisteredAnalyzer:
        try:
            return self._entries[name]
        except KeyError as exc:
            raise KeyError(f"unknown analyzer: {name}") from exc

    def __contains__(self, name: object) -> bool:
        return name in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def names(self) -> tuple[str, ...]:
        return tuple(self._entries)

    def specs(self) -> tuple[AnalyzerSpec, ...]:
        return tuple(entry.spec for entry in self._entries.values())

    def spec(self, name: str) -> AnalyzerSpec:
        return self.get(name).spec

    def languages(self) -> frozenset[str]:
        return frozenset(
            language for entry in self._entries.values() for language in entry.spec.languages
        )

    def applicable(self, language: str, *, enabled: Optional[Iterable[str]] = None) -> tuple[str, ...]:
        """Analyzer names that handle `language` and are enabled, in registry order."""
        allowed = set(enabled) if enabled is not None else set(self._entries)
        return tuple(
            name
            for name, entry in self._entries.items()
            if name in allowed and entry.spec.applies_to(language)
        )

    def security_analyzers(self, *, enabled: Optional[Iterable[str]] = None) -> tuple[str, ...]:
        allowed = set(enabled) if enabled is not None else set(self._entries)
        return tuple(
            name
            for name, entry in self._entries.items()
            if name in allowed and entry.spec.category == "security"
        )


def build_default_registry() -> AnalyzerRegistry:
    """The analyzers that ship with this engine."""
    from app.analysis.analyzers import bandit as bandit_analyzer
    from app.analysis.analyzers import radon as radon_analyzer
    from app.analysis.analyzers import ruff as ruff_analyzer

    registry = AnalyzerRegistry()
    registry.register(ruff_analyzer.SPEC, ruff_analyzer.build)
    registry.register(bandit_analyzer.SPEC, bandit_analyzer.build)
    registry.register(radon_analyzer.SPEC, radon_analyzer.build)
    return registry


@lru_cache(maxsize=1)
def default_registry() -> AnalyzerRegistry:
    """Process-wide registry, for callers that only need the specs (e.g. the API)."""
    return build_default_registry()
