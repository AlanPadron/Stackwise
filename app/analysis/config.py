"""Effective analysis configuration: platform defaults + validated project overrides.

Everything an analysis run is allowed to do is decided here, once:

* `AnalysisConfigOverrides` is what a client may send (`analysis_config` in the
  `POST /projects/from-repo` body, or `PATCH /projects/{id}`) — a deliberately
  small, validated surface.
* `resolve_config()` merges those overrides onto the platform ceiling in
  `app.core.config.Settings` and **refuses** (never silently widens) anything
  that would escape a resource limit, disable a security protection or touch the
  host.

The resolved config is hashed into `AnalysisRun.config_hash`, so a run is
reproducible: the same source with the same config hash yields the same findings
and the same risk index.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.analysis.errors import AnalysisConfigError
from app.core.config import Settings, settings

# Engine version: bump when the pipeline or the normalisation rules change in a
# way that alters stored results (not for a pure refactor).
ENGINE_VERSION = "1.0.0"

# Config version: bump when the *meaning* of a setting changes, so a stored
# config_hash never silently means something else.
CONFIG_VERSION = "1"

# Ruff rule selectors a project may choose from. Deliberately a curated list of
# stable rule families rather than "any string ruff accepts": an unknown or
# plugin-provided selector would otherwise change engine behaviour per project.
RUFF_ALLOWED_SELECTS = frozenset(
    {
        "E4", "E7", "E9", "F", "B", "C4", "SIM", "I", "UP", "RUF", "N", "PGH",
        "PERF", "ARG", "PIE", "RET", "TID", "TRY", "S", "BLE", "A", "T20",
        "DTZ", "LOG", "G", "ERA", "PTH", "PT", "Q", "EM", "FA", "T10", "TD",
        "ANN", "COM", "INP", "INT", "PD", "SLF", "SLOT", "RSE", "FIX", "FLY",
        "ISC", "ICN", "EXE", "FURB", "PL", "D", "CPY", "PYI", "TCH", "S102",
        "S602", "S301", "S506", "B602", "F821", "F401",
    }
)

# Patterns that would exclude everything; rejected instead of silently analysed
# nothing.
_FORBIDDEN_EXCLUDE_PATTERNS = frozenset({"", ".", "..", "/", "*", "**", "**/*", "*/", "/*", "\\"})

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class AnalysisConfigOverrides(BaseModel):
    """The only analysis settings a client may influence."""

    model_config = ConfigDict(extra="forbid")

    excluded_paths: list[str] = Field(
        default_factory=list,
        max_length=50,
        description=(
            "Glob patterns (matched against the repository-relative path and each "
            "of its directory segments) to skip, added to the fixed exclusion policy."
        ),
    )
    enabled_analyzers: Optional[list[str]] = Field(
        default=None,
        max_length=8,
        description="Subset of the platform's enabled analyzers.",
    )
    ruff_select: Optional[list[str]] = Field(
        default=None,
        max_length=32,
        description="Subset of the allowed ruff rule families.",
    )
    complexity_threshold: Optional[int] = Field(
        default=None, ge=2, le=100, description="Cyclomatic complexity that becomes a finding."
    )
    maintainability_rank: Optional[str] = Field(
        default=None, description="Lowest radon maintainability rank to report ('A', 'B' or 'C')."
    )
    max_findings_per_run: Optional[int] = Field(
        default=None, ge=1, le=100_000, description="Cap applied to the findings kept per run."
    )
    analyzer_timeout_seconds: Optional[float] = Field(
        default=None, ge=1, le=3600, description="Per-analyzer process timeout."
    )

    @field_validator("excluded_paths")
    @classmethod
    def _validate_excludes(cls, value: Sequence[str]) -> list[str]:
        cleaned: list[str] = []
        for pattern in value:
            pattern = pattern.strip()
            if pattern in _FORBIDDEN_EXCLUDE_PATTERNS:
                raise AnalysisConfigError(
                    f"excluded_paths entry {pattern!r} would exclude every file"
                )
            if len(pattern) > 200:
                raise AnalysisConfigError("excluded_paths entry is longer than 200 characters")
            if _CONTROL_CHARS.search(pattern):
                raise AnalysisConfigError("excluded_paths entry contains control characters")
            if pattern.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", pattern):
                raise AnalysisConfigError("excluded_paths entries must be repository-relative")
            parts = [part for part in re.split(r"[\\/]+", pattern) if part]
            if any(part == ".." for part in parts):
                raise AnalysisConfigError("excluded_paths entries must not traverse upwards")
            if not any(char not in "*?[]" for char in pattern):
                raise AnalysisConfigError(
                    f"excluded_paths entry {pattern!r} would exclude every file"
                )
            cleaned.append(pattern)
        return cleaned

    @field_validator("maintainability_rank")
    @classmethod
    def _validate_rank(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip().upper()
        if value not in {"A", "B", "C"}:
            raise AnalysisConfigError("maintainability_rank must be one of A, B, C")
        return value


@dataclass(frozen=True)
class AnalysisConfig:
    """The resolved, immutable limits and toggles of one analysis run."""

    engine_version: str = ENGINE_VERSION
    config_version: str = CONFIG_VERSION

    enabled_analyzers: tuple[str, ...] = ("ruff", "bandit", "radon")
    ruff_select: str = "E4,E7,E9,F,B"
    complexity_threshold: int = 11
    complexity_high_threshold: int = 21
    maintainability_min_rank: str = "B"
    excluded_paths: tuple[str, ...] = ()

    max_archive_bytes: int = 10 * 1024 * 1024
    max_extracted_bytes: int = 50 * 1024 * 1024
    max_file_count: int = 500
    max_file_bytes: int = 1024 * 1024
    max_workspace_depth: int = 12
    max_compression_ratio: int = 200

    max_analysis_duration_seconds: int = 300
    max_findings_per_run: int = 2000
    max_analyzer_output_bytes: int = 2_000_000
    analyzer_timeout_seconds: float = 60.0
    analyzer_memory_mb: int = 1024
    analyzer_cpu_seconds: int = 120

    overridden: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["excluded_paths"] = list(self.excluded_paths)
        data["enabled_analyzers"] = list(self.enabled_analyzers)
        data["overridden"] = list(self.overridden)
        return data

    def hash(self) -> str:
        """Stable sha256 over the effective configuration."""
        payload = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def excluded_patterns(self) -> tuple[str, ...]:
        return self.excluded_paths


def resolve_config(
    overrides: Optional[AnalysisConfigOverrides] = None,
    *,
    platform: Settings = settings,
) -> AnalysisConfig:
    """Merge client overrides onto the platform ceiling.

    Raises `AnalysisConfigError` (surfaced as 422) for anything that would widen
    a limit, disable every analyzer, or select a rule family outside the
    allowlist. Requested timeouts/finding caps above the ceiling are refused
    rather than silently clamped, so the stored config hash always describes
    what actually ran.
    """
    overrides = overrides or AnalysisConfigOverrides()
    overridden: list[str] = []

    enabled = tuple(platform.ANALYSIS_ENABLED_ANALYZERS)
    if overrides.enabled_analyzers is not None:
        requested = tuple(dict.fromkeys(overrides.enabled_analyzers))
        if not requested:
            raise AnalysisConfigError("enabled_analyzers must not be empty")
        unsupported = [name for name in requested if name not in enabled]
        if unsupported:
            raise AnalysisConfigError(
                "analyzers not enabled on this platform: " + ", ".join(sorted(unsupported))
            )
        enabled = requested
        overridden.append("enabled_analyzers")

    ruff_select = platform.ANALYSIS_RUFF_SELECT
    if overrides.ruff_select is not None:
        requested = [code.strip().upper() for code in overrides.ruff_select]
        if not requested:
            raise AnalysisConfigError("ruff_select must not be empty")
        unknown = [code for code in requested if code not in RUFF_ALLOWED_SELECTS]
        if unknown:
            raise AnalysisConfigError(
                "ruff_select entries outside the allowlist: " + ", ".join(sorted(unknown))
            )
        ruff_select = ",".join(dict.fromkeys(requested))
        overridden.append("ruff_select")

    timeout = platform.ANALYSIS_RUFF_TIMEOUT_SECONDS
    if overrides.analyzer_timeout_seconds is not None:
        if overrides.analyzer_timeout_seconds > platform.ANALYSIS_MAX_ANALYZER_TIMEOUT_SECONDS:
            raise AnalysisConfigError(
                "analyzer_timeout_seconds exceeds the platform maximum of "
                f"{platform.ANALYSIS_MAX_ANALYZER_TIMEOUT_SECONDS}"
            )
        timeout = float(overrides.analyzer_timeout_seconds)
        overridden.append("analyzer_timeout_seconds")

    max_findings = platform.ANALYSIS_MAX_FINDINGS_PER_RUN
    if overrides.max_findings_per_run is not None:
        if overrides.max_findings_per_run > platform.ANALYSIS_MAX_FINDINGS_PER_RUN:
            raise AnalysisConfigError(
                "max_findings_per_run exceeds the platform maximum of "
                f"{platform.ANALYSIS_MAX_FINDINGS_PER_RUN}"
            )
        max_findings = overrides.max_findings_per_run
        overridden.append("max_findings_per_run")

    maintainability_rank = platform.ANALYSIS_MAINTAINABILITY_MIN_RANK.upper()
    if overrides.maintainability_rank is not None:
        maintainability_rank = overrides.maintainability_rank
        overridden.append("maintainability_rank")

    complexity_threshold = platform.ANALYSIS_COMPLEXITY_FINDING_THRESHOLD
    if overrides.complexity_threshold is not None:
        complexity_threshold = overrides.complexity_threshold
        overridden.append("complexity_threshold")

    if overrides.excluded_paths:
        overridden.append("excluded_paths")

    return AnalysisConfig(
        engine_version=ENGINE_VERSION,
        config_version=CONFIG_VERSION,
        enabled_analyzers=enabled,
        ruff_select=ruff_select,
        complexity_threshold=complexity_threshold,
        complexity_high_threshold=max(
            complexity_threshold + 1, platform.ANALYSIS_COMPLEXITY_HIGH_THRESHOLD
        ),
        maintainability_min_rank=maintainability_rank,
        excluded_paths=tuple(overrides.excluded_paths),
        max_archive_bytes=platform.ANALYSIS_MAX_ARCHIVE_SIZE_MB * 1024 * 1024,
        max_extracted_bytes=platform.ANALYSIS_MAX_EXTRACTED_SIZE_MB * 1024 * 1024,
        max_file_count=platform.ANALYSIS_MAX_FILE_COUNT,
        max_file_bytes=platform.ANALYSIS_MAX_FILE_SIZE_KB * 1024,
        max_workspace_depth=platform.ANALYSIS_MAX_WORKSPACE_DEPTH,
        max_compression_ratio=platform.ANALYSIS_MAX_COMPRESSION_RATIO,
        max_analysis_duration_seconds=platform.ANALYSIS_MAX_ANALYSIS_DURATION_SECONDS,
        max_findings_per_run=max_findings,
        max_analyzer_output_bytes=platform.ANALYSIS_MAX_ANALYZER_OUTPUT_BYTES,
        analyzer_timeout_seconds=timeout,
        analyzer_memory_mb=platform.ANALYSIS_ANALYZER_MEMORY_MB,
        analyzer_cpu_seconds=platform.ANALYSIS_ANALYZER_CPU_SECONDS,
        overridden=tuple(sorted(overridden)),
    )


def config_from_stored(block: Optional[dict[str, Any]], *, platform: Settings = settings) -> AnalysisConfig:
    """Rebuild the config of a stored project (`projects.analysis_config`).

    Stored overrides were validated when they were written; if the platform
    ceiling has since dropped below them (someone lowered a limit in the
    environment), `AnalysisConfigError` is raised and the run fails loudly
    instead of running with limits nobody approved.
    """
    if not block:
        return resolve_config(None, platform=platform)
    return resolve_config(AnalysisConfigOverrides(**block), platform=platform)


def overrides_for_storage(raw: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Validate and normalise an override block for `projects.analysis_config`."""
    if raw is None:
        return None
    parsed = AnalysisConfigOverrides(**raw)
    stored = parsed.model_dump(exclude_none=True)
    # Resolve once: an override that cannot be satisfied is rejected at write
    # time rather than at analysis time.
    resolve_config(parsed)
    return stored

