"""Analyzer interface: what the engine needs from any static analysis tool.

An analyzer gets an `AnalyzerContext` (repository root, a neutral working
directory, the eligible files, the resolved config and the process runner) and
returns an `AnalyzerOutcome`: findings in the canonical vocabulary, optional raw
metrics, the tool version, the execution metadata and a status. It never raises
for a tool-side failure — it degrades.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from app.analysis.config import AnalysisConfig
from app.analysis.errors import ErrorCategory

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.analysis.runner import AnalyzerRunner


class AnalyzerStatus(str, Enum):
    """How one analyzer invocation ended."""

    OK = "ok"
    FINDINGS = "findings"
    NOT_APPLICABLE = "not_applicable"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"
    TIMEOUT = "timeout"
    OUTPUT_LIMIT = "output_limit"
    EXECUTION_ERROR = "execution_error"
    INVALID_OUTPUT = "invalid_output"
    INVALID_CONFIG = "invalid_config"

    @property
    def succeeded(self) -> bool:
        return self in (AnalyzerStatus.OK, AnalyzerStatus.FINDINGS)

    @property
    def failed(self) -> bool:
        return not self.succeeded and self is not AnalyzerStatus.NOT_APPLICABLE

    @property
    def error_category(self) -> Optional[ErrorCategory]:
        return {
            AnalyzerStatus.UNAVAILABLE: ErrorCategory.ANALYZER_UNAVAILABLE,
            AnalyzerStatus.DISABLED: ErrorCategory.CONFIGURATION,
            AnalyzerStatus.TIMEOUT: ErrorCategory.ANALYZER_TIMEOUT,
            AnalyzerStatus.OUTPUT_LIMIT: ErrorCategory.RESOURCE_LIMIT,
            AnalyzerStatus.INVALID_OUTPUT: ErrorCategory.OUTPUT_PARSING,
            AnalyzerStatus.INVALID_CONFIG: ErrorCategory.CONFIGURATION,
            AnalyzerStatus.EXECUTION_ERROR: ErrorCategory.ANALYZER_EXECUTION,
        }.get(self)


@dataclass(frozen=True)
class RawFinding:
    """A finding exactly as one analyzer reported it, before normalisation."""

    tool: str
    rule_id: Optional[str]
    category: str
    severity: str
    title: str
    description: Optional[str] = None
    confidence: Optional[str] = None
    file_path: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    column_start: Optional[int] = None
    column_end: Optional[int] = None
    references: Optional[dict[str, Any]] = None
    metadata: Optional[dict[str, Any]] = None
    # Optional rule-specific identity used to make fingerprints stable
    # (e.g. the function name for a complexity finding).
    identity: Optional[str] = None


@dataclass
class AnalyzerOutcome:
    """Everything one analyzer invocation produced."""

    analyzer: str
    status: AnalyzerStatus
    findings: list[RawFinding] = field(default_factory=list)
    metrics: Optional[dict[str, Any]] = None
    version: Optional[str] = None
    duration_seconds: float = 0.0
    exit_code: Optional[int] = None
    message: Optional[str] = None
    truncated: bool = False

    @property
    def succeeded(self) -> bool:
        return self.status.succeeded


@dataclass(frozen=True)
class AnalyzerContext:
    """Inputs available to one analyzer."""

    root: Path
    cwd: Path
    paths: tuple[str, ...]
    config: AnalysisConfig
    runner: "AnalyzerRunner"
    language: str = "python"

    def absolute(self, relative_path: str) -> str:
        return str((self.root / relative_path).resolve())


@runtime_checkable
class Analyzer(Protocol):
    name: str

    def analyze(self, context: AnalyzerContext) -> AnalyzerOutcome:
        """Run the tool over `context.paths` and return its normalised outcome."""
        ...
